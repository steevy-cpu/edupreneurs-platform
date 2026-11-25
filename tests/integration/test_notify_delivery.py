"""The delivery pass end to end against the real database functions, with the dummy
adapter. NOTHING IS SENT: the adapter appends to an in-memory list.

The worker code logs in as the real ``edu_worker_login`` role (``worker_engine``).
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import asyncpg
import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from edu_api.notify.adapter import DeliveryResult, DummyLocalAdapter, assert_content_free
from edu_api.notify.worker import SqlOutboxPort, deliver_due
from tests.helpers import STUDENT_A, STUDENT_B, bearer

if TYPE_CHECKING:
    from tests.notify_fixtures import Enqueue

pytest_plugins = ("tests.notify_fixtures",)

PREFS = "/v1/me/notification-preferences"
WORD = "f0000000-0000-4000-8000-000000000001"


async def _opt_in(
    http: httpx.AsyncClient, token: str, *, muted: tuple[str, ...] = (), push: bool = True
) -> None:
    response = await http.put(
        PREFS,
        headers=bearer(token),
        json={"push_enabled": push, "muted_categories": list(muted), "quiet_hours": None},
    )
    assert response.status_code == 200, response.text


async def _states(admin: asyncpg.Pool) -> dict[str, str]:
    rows = await admin.fetch(
        "SELECT o.kind, d.state || '/' || d.attempt_count || '/' || COALESCE(d.last_error_code, '-') AS s "
        "FROM notify.deliveries d JOIN notify.outbox o ON o.id = d.outbox_id"
    )
    return {row["kind"]: row["s"] for row in rows}


async def test_dummy_delivery_respects_opt_in_and_carries_no_content(
    notify_client: httpx.AsyncClient,
    tokens: dict[str, str],
    enqueue: Enqueue,
    worker_engine: AsyncEngine,
    outside_quiet_hours: None,
    admin: asyncpg.Pool,
) -> None:
    # A opted in through the API; B never did (no row = not granted).
    await _opt_in(notify_client, tokens["student_a"], muted=("reminders",))
    event = await enqueue(
        STUDENT_A,
        "daily_word_available",
        json.dumps({"word_id": WORD}),
        channels=("push", "in_app"),
    )
    await enqueue(STUDENT_A, "sync_reminder", channels=("push",))  # muted category
    await enqueue(STUDENT_B, "entitlement_expiring", channels=("push", "in_app"))  # not opted in

    adapter = DummyLocalAdapter()
    summary = await deliver_due(SqlOutboxPort(worker_engine), adapter)
    assert (summary.claimed, summary.delivered, summary.retried, summary.failed) == (1, 1, 0, 0)

    (record,) = adapter.records
    assert record.recipient_id == STUDENT_A and record.channel == "push"
    assert record.payload == {
        "v": 1,
        "id": str(event),
        "kind": "daily_word_available",
        "refs": {"word_id": WORD},
    }
    assert_content_free(record.payload)
    assert await _states(admin) == {
        "daily_word_available": "delivered/1/-",
        "sync_reminder": "suppressed/0/category_muted",
        "entitlement_expiring": "suppressed/0/push_not_enabled",
    }
    assert await admin.fetchval("SELECT count(*) FROM notify.outbox WHERE state <> 'settled'") == 0
    # Nothing is left to do: a second pass claims nothing and "sends" nothing.
    assert (await deliver_due(SqlOutboxPort(worker_engine), adapter)).claimed == 0
    assert len(adapter.records) == 1
    # B still finds the event in the in-app list although the push was suppressed.
    listed = await notify_client.get("/v1/notifications", headers=bearer(tokens["student_b"]))
    assert [item["kind"] for item in listed.json()["items"]] == ["entitlement_expiring"]


async def test_opting_out_again_stops_delivery_of_already_queued_events(
    notify_client: httpx.AsyncClient,
    tokens: dict[str, str],
    enqueue: Enqueue,
    worker_engine: AsyncEngine,
    outside_quiet_hours: None,
    admin: asyncpg.Pool,
) -> None:
    await _opt_in(notify_client, tokens["student_a"])
    await enqueue(STUDENT_A, "sync_reminder", channels=("push",))
    await _opt_in(notify_client, tokens["student_a"], push=False)  # changed mind before delivery
    adapter = DummyLocalAdapter()
    assert (await deliver_due(SqlOutboxPort(worker_engine), adapter)).claimed == 0
    assert len(adapter.records) == 0
    assert await _states(admin) == {"sync_reminder": "suppressed/0/push_not_enabled"}


async def test_quiet_hours_defer_delivery_on_the_real_clock(
    notify_client: httpx.AsyncClient,
    tokens: dict[str, str],
    enqueue: Enqueue,
    worker_engine: AsyncEngine,
    admin: asyncpg.Pool,
) -> None:
    """Make "now" quiet (a platform window around the present Haiti time) and check
    that the real ``notify.claim_due`` hands out nothing and spends no attempt."""
    await _opt_in(notify_client, tokens["student_a"])
    await admin.execute(
        "UPDATE notify.policy SET "
        "quiet_start = ((now() AT TIME ZONE 'America/Port-au-Prince') - interval '1 hour')::time, "
        "quiet_end = ((now() AT TIME ZONE 'America/Port-au-Prince') + interval '2 hours')::time"
    )
    await enqueue(STUDENT_A, "sync_reminder", channels=("push",))
    adapter = DummyLocalAdapter()
    assert (await deliver_due(SqlOutboxPort(worker_engine), adapter)).claimed == 0
    assert len(adapter.records) == 0
    row = await admin.fetchrow(
        "SELECT state, attempt_count, next_attempt_at - now() AS wait FROM notify.deliveries"
    )
    assert (row["state"], row["attempt_count"]) == ("pending", 0)
    assert 3600 < row["wait"].total_seconds() <= 2 * 3600 + 5, "put off to the end of the window"


async def test_retries_then_terminal_failure_with_the_real_functions(
    notify_client: httpx.AsyncClient,
    tokens: dict[str, str],
    enqueue: Enqueue,
    worker_engine: AsyncEngine,
    outside_quiet_hours: None,
    admin: asyncpg.Pool,
) -> None:
    await _opt_in(notify_client, tokens["student_a"])
    await admin.execute("UPDATE notify.policy SET max_attempts = 3")
    await enqueue(STUDENT_A, "sync_reminder", channels=("push",))
    port = SqlOutboxPort(worker_engine)
    adapter = DummyLocalAdapter(script=[DeliveryResult("retry", "provider_unavailable")] * 5)

    waits = []
    for expected_state in ("pending", "pending", "failed"):
        summary = await deliver_due(port, adapter)
        assert summary.claimed == 1
        row = await admin.fetchrow(
            "SELECT state, attempt_count, next_attempt_at - now() AS wait FROM notify.deliveries"
        )
        assert row["state"] == expected_state
        if row["wait"] is not None:
            waits.append(round(row["wait"].total_seconds() / 60))
            # Backoff has not passed yet: a pass right now claims nothing.
            assert (await deliver_due(port, adapter)).claimed == 0
            await admin.execute("UPDATE notify.deliveries SET next_attempt_at = now()")
    assert waits == [1, 2], "60 s then 120 s"
    assert await _states(admin) == {"sync_reminder": "failed/3/max_attempts"}
    assert len(adapter.records) == 0, "nothing was ever recorded as delivered"
    log = await admin.fetch(
        "SELECT attempt_no, outcome, error_code FROM notify.delivery_attempts ORDER BY attempt_no"
    )
    assert [tuple(row) for row in log] == [
        (1, "retry", "provider_unavailable"),
        (2, "retry", "provider_unavailable"),
        (3, "failed", "provider_unavailable"),
    ]
    assert (await deliver_due(port, adapter)).claimed == 0, "terminal means terminal"


async def test_concurrent_workers_never_deliver_the_same_event_twice(
    notify_client: httpx.AsyncClient,
    tokens: dict[str, str],
    enqueue: Enqueue,
    worker_engine: AsyncEngine,
    outside_quiet_hours: None,
    admin: asyncpg.Pool,
) -> None:
    await _opt_in(notify_client, tokens["student_a"])
    await _opt_in(notify_client, tokens["student_b"])
    for index in range(12):
        await enqueue(STUDENT_A if index % 2 else STUDENT_B, "sync_reminder", channels=("push",))
    adapters = [DummyLocalAdapter() for _ in range(4)]
    port = SqlOutboxPort(worker_engine)
    summaries = await asyncio.gather(
        *(deliver_due(port, adapter, limit=5) for adapter in adapters),
        *(deliver_due(port, adapter, limit=5) for adapter in adapters),
    )
    delivered = [record.payload["id"] for adapter in adapters for record in adapter.records]
    assert sum(summary.claimed for summary in summaries) == 12
    assert len(delivered) == 12 and len(set(delivered)) == 12, "each event exactly once"
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM notify.deliveries WHERE state = 'delivered' AND attempt_count = 1"
        )
        == 12
    )


async def test_the_same_event_enqueued_twice_is_delivered_once(
    notify_client: httpx.AsyncClient,
    tokens: dict[str, str],
    enqueue: Enqueue,
    worker_engine: AsyncEngine,
    outside_quiet_hours: None,
    admin: asyncpg.Pool,
) -> None:
    await _opt_in(notify_client, tokens["student_a"])
    refs = json.dumps({"word_id": WORD})
    ids = await asyncio.gather(
        *(
            enqueue(STUDENT_A, "daily_word_available", refs, "word:2026-11-24", ("push", "in_app"))
            for _ in range(8)
        )
    )
    assert len(set(ids)) == 1, "eight concurrent producers, one event"
    adapter = DummyLocalAdapter()
    assert (await deliver_due(SqlOutboxPort(worker_engine), adapter)).delivered == 1
    assert len(adapter.records) == 1
    listed = await notify_client.get("/v1/notifications", headers=bearer(tokens["student_a"]))
    assert len(listed.json()["items"]) == 1


async def test_erase_learner_removes_everything_the_api_could_show(
    notify_client: httpx.AsyncClient,
    tokens: dict[str, str],
    enqueue: Enqueue,
    admin: asyncpg.Pool,
) -> None:
    await _opt_in(notify_client, tokens["student_a"], muted=("learning",))
    await _opt_in(notify_client, tokens["student_b"])
    await enqueue(STUDENT_A, "sync_reminder", channels=("push", "in_app"))
    await enqueue(STUDENT_B, "sync_reminder")
    report = json.loads(await admin.fetchval("SELECT notify.erase_learner($1)::text", STUDENT_A))
    assert report == {
        "schema": "notify",
        "outbox": 1,
        "deliveries": 1,
        "delivery_attempts": 0,
        "preferences": 1,
    }
    after = await notify_client.get(PREFS, headers=bearer(tokens["student_a"]))
    assert after.json()["push_enabled"] is False and after.json()["updated_at"] is None
    listed = await notify_client.get("/v1/notifications", headers=bearer(tokens["student_a"]))
    assert listed.json() == {"items": [], "next_cursor": None}
    other = await notify_client.get("/v1/notifications", headers=bearer(tokens["student_b"]))
    assert len(other.json()["items"]) == 1
