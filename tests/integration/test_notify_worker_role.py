"""The worker role against the real database: a real ``edu_worker_login`` connection
can claim, report and enqueue; ``edu_api_login`` and ``edu_staff_login`` cannot.
Also: who the audit trail says changed a learner's preferences."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import asyncpg
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from edu_api.notify.adapter import DummyLocalAdapter
from edu_api.notify.worker import SqlOutboxPort, deliver_due
from tests.helpers import STUDENT_A, STUDENT_B, bearer
from tests.staff_fixtures import staff_url, worker_url

if TYPE_CHECKING:
    from tests.notify_fixtures import Enqueue

pytest_plugins = ("tests.notify_fixtures",)

PREFS = "/v1/me/notification-preferences"
ENQUEUE = "SELECT notify.enqueue($1, 'sync_reminder', '{}'::jsonb, $2, $3::text[])"


@pytest.fixture
async def worker(local_env: dict[str, str]) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(worker_url(local_env), timeout=10)
    yield conn
    await conn.close()


async def _opt_in(http: httpx.AsyncClient, token: str) -> None:
    body = {"push_enabled": True, "muted_categories": [], "quiet_hours": None}
    assert (await http.put(PREFS, headers=bearer(token), json=body)).status_code == 200


async def test_the_worker_login_is_only_the_worker(worker: asyncpg.Connection) -> None:
    row = await worker.fetchrow(
        "SELECT current_user AS u, session_user AS s, "
        "(SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user) AS power"
    )
    assert (row["u"], row["s"], row["power"]) == ("edu_worker_login", "edu_worker_login", False)


async def test_a_real_worker_connection_claims_reports_and_enqueues(
    notify_client: httpx.AsyncClient,
    tokens: dict[str, str],
    worker: asyncpg.Connection,
    outside_quiet_hours: None,
    admin: asyncpg.Pool,
) -> None:
    await _opt_in(notify_client, tokens["student_a"])
    event = await worker.fetchval(ENQUEUE, STUDENT_A, "job-1", ["push", "in_app"])
    assert isinstance(event, uuid.UUID)
    assert await worker.fetchval(ENQUEUE, STUDENT_A, "job-1", ["push", "in_app"]) == event
    await worker.fetchval(ENQUEUE, STUDENT_B, "job-2", ["push"])  # B never opted in

    claimed = await worker.fetch("SELECT * FROM notify.claim_due('push', 20, 60)")
    assert [(row["outbox_id"], row["recipient_id"], row["attempt_no"]) for row in claimed] == [
        (event, STUDENT_A, 1)
    ], "only the opted-in learner's delivery is handed to the worker"
    assert json.loads(claimed[0]["refs"]) == {}
    state = await worker.fetchval(
        "SELECT notify.record_attempt($1, 'push', $2, 'delivered')",
        event,
        claimed[0]["lease_token"],
    )
    assert state == "delivered"
    stale = await worker.fetchval(
        "SELECT notify.record_attempt($1, 'push', $2, 'delivered')",
        event,
        claimed[0]["lease_token"],
    )
    assert stale == "stale", "a lease can be reported once"
    rows = await admin.fetch(
        "SELECT o.recipient_id, d.state FROM notify.deliveries d JOIN notify.outbox o ON o.id = d.outbox_id"
    )
    assert {(row["recipient_id"], row["state"]) for row in rows} == {
        (STUDENT_A, "delivered"),
        (STUDENT_B, "suppressed"),
    }


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT count(*) FROM notify.outbox",
        "SELECT count(*) FROM notify.deliveries",
        "SELECT count(*) FROM notify.delivery_attempts",
        "SELECT count(*) FROM notify.preferences",
        "UPDATE notify.policy SET quiet_start = '00:00', quiet_end = '00:01'",
        "UPDATE notify.deliveries SET state = 'delivered'",
        "INSERT INTO notify.kinds (kind, category) VALUES ('marketing_blast', 'learning')",
        "SELECT * FROM notify._claim_due_at('push', 20, 60, now() + interval '12 hours')",
        "SELECT notify._record_attempt_at(gen_random_uuid(), 'push', gen_random_uuid(), 'delivered', NULL, now())",
        "SELECT notify._settle(gen_random_uuid())",
        f"SELECT notify.erase_learner('{STUDENT_A}')",
        "SELECT notify.set_preferences(true, '{}', NULL, NULL)",
        f"SELECT notify.quiet_until(now(), '{STUDENT_A}')",
        "SELECT count(*) FROM app.learner_profiles",
        "CREATE TABLE notify.x (id int)",
    ],
)
async def test_the_worker_login_reaches_nothing_else_in_notify(
    worker: asyncpg.Connection, clean_notify_state: None, statement: str
) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await worker.execute(statement)


async def test_the_worker_cannot_choose_the_time_to_get_around_quiet_hours(
    notify_client: httpx.AsyncClient,
    tokens: dict[str, str],
    worker: asyncpg.Connection,
    admin: asyncpg.Pool,
) -> None:
    await _opt_in(notify_client, tokens["student_a"])
    await admin.execute(
        "UPDATE notify.policy SET "
        "quiet_start = ((now() AT TIME ZONE 'America/Port-au-Prince') - interval '1 hour')::time, "
        "quiet_end = ((now() AT TIME ZONE 'America/Port-au-Prince') + interval '2 hours')::time"
    )
    await worker.fetchval(ENQUEUE, STUDENT_A, "night", ["push"])
    for _ in range(3):
        assert await worker.fetch("SELECT * FROM notify.claim_due('push')") == []
    # Session tricks do not move the database clock used inside the function.
    await worker.execute("SET TIME ZONE 'Asia/Tokyo'")
    assert await worker.fetch("SELECT * FROM notify.claim_due('push')") == []
    assert await admin.fetchval("SELECT attempt_count FROM notify.deliveries") == 0


async def test_api_and_staff_logins_cannot_enqueue_claim_or_report(
    notify_app: object,
    clean_notify_state: None,
    local_env: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    api_url = local_env["EDU_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    statements = [
        f"SELECT notify.enqueue('{STUDENT_A}', 'sync_reminder', '{{}}', 'forged')",
        f"SELECT notify.enqueue('{STUDENT_B}', 'sync_reminder', '{{}}', 'forged', ARRAY['push'])",
        "SELECT * FROM notify.claim_due('push')",
        "SELECT notify.record_attempt(gen_random_uuid(), 'push', gen_random_uuid(), 'delivered')",
        f"SELECT notify.erase_learner('{STUDENT_A}')",
    ]
    for label, url in (("edu_api_login", api_url), ("edu_staff_login", staff_url(local_env))):
        conn = await asyncpg.connect(url, timeout=10)
        try:
            assert await conn.fetchval("SELECT session_user") == label
            for actor in (None, STUDENT_A):
                for statement in statements:
                    async with conn.transaction():
                        if actor is not None:
                            await conn.execute(
                                "SELECT set_config('edu.actor_id', $1, true)", str(actor)
                            )
                        with pytest.raises(asyncpg.InsufficientPrivilegeError):
                            async with conn.transaction():
                                await conn.execute(statement)
        finally:
            await conn.close()
    assert await admin.fetchval("SELECT count(*) FROM notify.outbox") == 0


async def test_two_real_workers_never_claim_the_same_delivery(
    notify_client: httpx.AsyncClient,
    tokens: dict[str, str],
    enqueue: Enqueue,
    local_env: dict[str, str],
    worker_engine: AsyncEngine,
    outside_quiet_hours: None,
    admin: asyncpg.Pool,
) -> None:
    await _opt_in(notify_client, tokens["student_a"])
    await _opt_in(notify_client, tokens["student_b"])
    for index in range(30):
        await enqueue(STUDENT_A if index % 2 else STUDENT_B, "sync_reminder", channels=("push",))

    # (1) Two separate worker sessions, raw SQL, racing in small batches.
    first = await asyncpg.connect(worker_url(local_env), timeout=10)
    second = await asyncpg.connect(worker_url(local_env), timeout=10)
    try:
        assert await first.fetchval("SELECT pg_backend_pid()") != await second.fetchval(
            "SELECT pg_backend_pid()"
        )

        async def drain(conn: asyncpg.Connection, rounds: int) -> list[uuid.UUID]:
            mine: list[uuid.UUID] = []
            for _ in range(rounds):
                rows = await conn.fetch("SELECT outbox_id FROM notify.claim_due('push', 3, 60)")
                mine += [row["outbox_id"] for row in rows]
            return mine

        claimed_first, claimed_second = await asyncio.gather(drain(first, 3), drain(second, 3))
    finally:
        await first.close()
        await second.close()
    assert len(claimed_first) + len(claimed_second) == 18
    assert not set(claimed_first) & set(claimed_second), "no delivery was leased twice"
    assert len(set(claimed_first + claimed_second)) == 18

    # (2) The worker code itself, several passes at once, takes the remaining 12.
    adapters = [DummyLocalAdapter() for _ in range(4)]
    port = SqlOutboxPort(worker_engine)
    summaries = await asyncio.gather(*(deliver_due(port, adapter, limit=5) for adapter in adapters))
    delivered = [record.payload["id"] for adapter in adapters for record in adapter.records]
    assert sum(summary.claimed for summary in summaries) == 12
    assert len(delivered) == len(set(delivered)) == 12
    assert not {uuid.UUID(str(ident)) for ident in delivered} & set(claimed_first + claimed_second)
    assert await admin.fetchval("SELECT max(attempt_count) FROM notify.deliveries") == 1


async def test_preference_changes_and_erasure_are_audited_with_codes_only(
    notify_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    started = await admin.fetchval("SELECT clock_timestamp()")
    body = {
        "push_enabled": True,
        "muted_categories": ["learning", "reminders"],
        "quiet_hours": {"start": "19:45", "end": "07:15"},
    }
    saved = await notify_client.put(PREFS, headers=bearer(tokens["student_a"]), json=body)
    assert saved.status_code == 200
    rejected = await notify_client.put(
        PREFS, headers=bearer(tokens["student_a"]), json={**body, "muted_categories": ["x"]}
    )
    assert rejected.status_code == 422
    await notify_client.get(PREFS, headers=bearer(tokens["student_a"]))  # reads are not audited
    await admin.fetchval("SELECT notify.erase_learner($1)", STUDENT_A)

    rows = await admin.fetch(
        "SELECT action, actor_id, actor_kind, target_kind, target_id, outcome, details::text AS details "
        "FROM app.audit_events WHERE created_at >= $1 AND action LIKE 'notify%' ORDER BY created_at",
        started,
    )
    assert [
        (r["action"], r["actor_id"], r["actor_kind"], r["target_id"], r["outcome"]) for r in rows
    ] == [
        ("notify_preferences.update", STUDENT_A, "user", STUDENT_A, "allowed"),
        ("notify_learner.erase", None, "system", STUDENT_A, "allowed"),
    ]
    assert json.loads(rows[0]["details"]) == {
        "push_enabled": True,
        "muted_count": 2,
        "own_quiet_hours": True,
    }
    assert json.loads(rows[1]["details"]) == {
        "outbox": 0,
        "deliveries": 0,
        "delivery_attempts": 0,
        "preferences": 1,
    }
    text = " ".join(r["details"] for r in rows)
    for forbidden in ("19:45", "07:15", "learning", "reminders"):
        assert forbidden not in text, "the audit trail holds flags and counts, not the choices"
