# ruff: noqa: F811
"""Account lifecycle on SYNTHETIC users: deletion requests, export, erasure (slice 3)."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from tests.helpers import SEED_QUESTIONS_FR, SEED_QUESTIONS_HT, SEED_REV_FR, answer_op, completed_op
from tests.staff_fixtures import make_staff, staff_url, worker_url  # noqa: F401

if TYPE_CHECKING:
    from tests.account_fixtures import SyntheticLearner

pytestmark = pytest.mark.integration
#: Registers the lane's fixtures (account_app, account_client, learners, ...).
pytest_plugins = ["tests.account_fixtures"]

ROUTES = (
    ("GET", "/v1/me/account-requests"),
    ("POST", "/v1/me/deletion-request"),
    ("DELETE", "/v1/me/deletion-request"),
    ("POST", "/v1/me/export"),
)
LEARNER_ROWS = (
    "SELECT (SELECT count(*) FROM app.learner_profiles WHERE user_id = $1), "
    "(SELECT count(*) FROM app.practice_attempts WHERE learner_id = $1), "
    "(SELECT count(*) FROM app.sync_receipts WHERE learner_id = $1), "
    "(SELECT count(*) FROM app.account_change_feed WHERE learner_id = $1), "
    "(SELECT count(*) FROM app.lesson_progress WHERE learner_id = $1), "
    "(SELECT count(*) FROM app.account_sync_state WHERE learner_id = $1), "
    "(SELECT count(*) FROM account.onboarding_state WHERE user_id = $1), "
    "(SELECT count(*) FROM account.deletion_requests WHERE user_id = $1), "
    "(SELECT count(*) FROM account.export_requests WHERE user_id = $1)"
)


async def study(
    client: httpx.AsyncClient, learner: SyntheticLearner, *, creole: bool = False
) -> None:
    """Two answers and a completed lesson, through the real sync endpoint."""
    questions = SEED_QUESTIONS_HT if creole else SEED_QUESTIONS_FR
    ops = [answer_op(questions[0][0], questions[0][1]), answer_op(questions[1][0], "d")]
    if not creole:
        ops.append(completed_op(SEED_REV_FR))
    response = await client.post("/v1/sync/push", json={"ops": ops}, headers=learner.headers)
    assert response.status_code == 200, response.text
    assert {result["status"] for result in response.json()["results"]} == {"accepted"}


async def snapshot(admin: asyncpg.Pool, user_id: uuid.UUID) -> dict[str, list[Any]]:
    """Every row a learner owns, in full, for byte-for-byte comparison."""
    queries = {
        "profile": "SELECT * FROM app.learner_profiles WHERE user_id = $1",
        "attempts": "SELECT * FROM app.practice_attempts WHERE learner_id = $1 ORDER BY id",
        "receipts": "SELECT * FROM app.sync_receipts WHERE learner_id = $1 ORDER BY op_id",
        "feed": "SELECT * FROM app.account_change_feed WHERE learner_id = $1 ORDER BY version",
        "progress": "SELECT * FROM app.lesson_progress WHERE learner_id = $1 ORDER BY lesson_id",
        "state": "SELECT * FROM app.account_sync_state WHERE learner_id = $1",
        "onboarding": "SELECT * FROM account.onboarding_state WHERE user_id = $1",
        "deletion": "SELECT * FROM account.deletion_requests WHERE user_id = $1 ORDER BY id",
        "exports": "SELECT * FROM account.export_requests WHERE user_id = $1 ORDER BY id",
    }
    return {name: await admin.fetch(sql, user_id) for name, sql in queries.items()}


# ------------------------------------------------------------- feature flag
async def test_with_the_flag_off_lifecycle_routes_answer_the_standard_404(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    before = await admin.fetchval(
        "SELECT (SELECT count(*) FROM account.deletion_requests) + "
        "(SELECT count(*) FROM account.export_requests)"
    )
    for headers in ({"Authorization": f"Bearer {tokens['student_a']}"}, {}):
        for method, path in ROUTES:
            response = await client.request(method, path, headers=headers)
            assert response.status_code == 404, (method, path)
            assert response.json()["error"]["code"] == "not_found"
    after = await admin.fetchval(
        "SELECT (SELECT count(*) FROM account.deletion_requests) + "
        "(SELECT count(*) FROM account.export_requests)"
    )
    assert after == before


async def test_lifecycle_routes_require_a_token(account_client: httpx.AsyncClient) -> None:
    for method, path in ROUTES:
        response = await account_client.request(method, path)
        assert response.status_code == 401, (method, path)
        assert response.json()["error"]["code"] == "unauthenticated"


# -------------------------------------------------------- deletion requests
async def test_deletion_request_is_idempotent_cancellable_and_deletes_nothing(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    x = learners["x"]
    await study(account_client, x)
    before = await admin.fetchrow(LEARNER_ROWS, x.user_id)

    empty = await account_client.get("/v1/me/account-requests", headers=x.headers)
    assert empty.status_code == 200
    assert empty.json() == {"deletion_request": None, "last_export": None}
    nothing = await account_client.delete("/v1/me/deletion-request", headers=x.headers)
    assert nothing.status_code == 200 and nothing.json() == {"deletion_request": None}

    first = await account_client.post("/v1/me/deletion-request", headers=x.headers)
    again = await account_client.post("/v1/me/deletion-request", headers=x.headers)
    assert first.status_code == again.status_code == 200
    request = first.json()["deletion_request"]
    assert set(request) == {"id", "status", "requested_at", "cancelled_at"}
    assert request["status"] == "requested" and request["cancelled_at"] is None
    assert again.json() == first.json(), "asking twice is the same request"
    seen = await account_client.get("/v1/me/account-requests", headers=x.headers)
    assert seen.json()["deletion_request"] == request

    # Nothing was deleted, and the learner can keep studying.
    after = await admin.fetchrow(LEARNER_ROWS, x.user_id)
    assert tuple(after)[:7] == tuple(before)[:7]
    assert (await account_client.get("/v1/me", headers=x.headers)).status_code == 200
    assert (
        len((await account_client.get("/v1/sync/pull", headers=x.headers)).json()["changes"]) == 3
    )

    cancelled = await account_client.delete("/v1/me/deletion-request", headers=x.headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["deletion_request"]["id"] == request["id"]
    assert cancelled.json()["deletion_request"]["status"] == "cancelled"
    assert cancelled.json()["deletion_request"]["cancelled_at"] is not None
    twice = await account_client.delete("/v1/me/deletion-request", headers=x.headers)
    assert twice.json() == cancelled.json()

    new = await account_client.post("/v1/me/deletion-request", headers=x.headers)
    assert new.json()["deletion_request"]["id"] != request["id"]
    assert new.json()["deletion_request"]["status"] == "requested"
    assert await admin.fetchval(
        "SELECT array_agg(status ORDER BY status) FROM account.deletion_requests WHERE user_id = $1",
        x.user_id,
    ) == ["cancelled", "requested"]


async def test_requests_are_isolated_between_accounts(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    x, y = learners["x"], learners["y"]
    mine = await account_client.post("/v1/me/deletion-request", headers=x.headers)
    await account_client.post("/v1/me/export", headers=x.headers)

    # Same client, next request is another account.
    theirs = await account_client.get("/v1/me/account-requests", headers=y.headers)
    assert theirs.json() == {"deletion_request": None, "last_export": None}
    # Y "cancels" — with X named everywhere a client could try to name them.
    attempt = await account_client.request(
        "DELETE",
        "/v1/me/deletion-request",
        params={"user_id": str(x.user_id), "id": mine.json()["deletion_request"]["id"]},
        headers={**y.headers, "X-User-Id": str(x.user_id)},
    )
    assert attempt.status_code == 200 and attempt.json() == {"deletion_request": None}
    assert (
        await admin.fetchval(
            "SELECT status FROM account.deletion_requests WHERE user_id = $1", x.user_id
        )
        == "requested"
    )
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM account.deletion_requests WHERE user_id = $1", y.user_id
        )
        == 0
    )


# ------------------------------------------------------------------- export
async def test_export_contains_the_callers_data_and_nobody_elses(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    x, y = learners["x"], learners["y"]
    await account_client.patch(
        "/v1/me", json={"grade_code": "9AF", "display_name": "Export X"}, headers=x.headers
    )
    await account_client.patch(
        "/v1/me", json={"preferred_locale": "ht", "display_name": "Lot elev Y"}, headers=y.headers
    )
    await study(account_client, x)
    await study(account_client, y, creole=True)
    await account_client.put(
        "/v1/me/onboarding", json={"state": "ready", "onboarding_version": 1}, headers=x.headers
    )

    response = await account_client.post("/v1/me/export", headers=x.headers)
    assert response.status_code == 200, response.text
    export = response.json()
    assert set(export) == {
        "format",
        "export_id",
        "generated_at",
        "user_id",
        "profile",
        "onboarding",
        "lesson_progress",
        "practice_attempts",
        "counts",
        "limits",
        "truncated",
    }
    assert export["format"] == "mep-account-export-1"
    assert export["user_id"] == str(x.user_id)
    assert export["profile"]["display_name"] == "Export X"
    assert export["profile"]["grade_code"] == "9AF"
    assert export["onboarding"]["state"] == "ready"
    assert export["counts"] == {"lesson_progress": 1, "practice_attempts": 2}
    assert export["truncated"] == {"lesson_progress": False, "practice_attempts": False}
    assert [attempt["score"] for attempt in export["practice_attempts"]].count(1.0) == 1

    own_attempts = {
        str(row["id"])
        for row in await admin.fetch(
            "SELECT id FROM app.practice_attempts WHERE learner_id = $1", x.user_id
        )
    }
    assert {attempt["id"] for attempt in export["practice_attempts"]} == own_attempts
    y_markers = [str(y.user_id), "Lot elev Y", str(SEED_QUESTIONS_HT[0][0])] + [
        str(row["id"])
        for row in await admin.fetch(
            "SELECT id FROM app.practice_attempts WHERE learner_id = $1", y.user_id
        )
    ]
    for marker in y_markers:
        assert marker not in response.text

    y_export = (await account_client.post("/v1/me/export", headers=y.headers)).json()
    assert y_export["user_id"] == str(y.user_id)
    assert y_export["onboarding"] is None
    assert y_export["counts"] == {"lesson_progress": 0, "practice_attempts": 2}
    assert str(x.user_id) not in str(y_export) and "Export X" not in str(y_export)

    recorded = await account_client.get("/v1/me/account-requests", headers=x.headers)
    assert recorded.json()["last_export"]["id"] == export["export_id"]
    assert recorded.json()["last_export"]["status"] == "processed"


# ------------------------------------------------------------------ erasure
async def test_api_role_cannot_run_or_approach_the_erasure(
    account_app: FastAPI, learners: dict[str, SyntheticLearner]
) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    x, y = learners["x"], learners["y"]
    db = account_app.state.db
    for statement in (
        f"SELECT account.erase_learner('{y.user_id}')",
        f"SELECT account.erase_learner('{x.user_id}')",
        f"SELECT account.find_learner_references('{y.user_id}')",
        "SELECT count(*) FROM account.erasure_hooks",
        "INSERT INTO account.erasure_hooks (schema_name, position) VALUES ('public', 1)",
        "SET LOCAL session_replication_role = replica",
        f"INSERT INTO account.deletion_requests (user_id) VALUES ('{y.user_id}')",
        "UPDATE account.deletion_requests SET status = 'cancelled', cancelled_at = now()",
        "DELETE FROM account.export_requests",
    ):
        with pytest.raises(DBAPIError) as caught:
            async with db.transaction(x.user_id) as conn:
                await conn.execute(text(statement))
        assert getattr(caught.value.orig, "sqlstate", None) == "42501", statement


async def test_suspending_triggers_in_one_session_does_not_affect_another(
    admin: asyncpg.Pool,
    account_client: httpx.AsyncClient,
    learners: dict[str, SyntheticLearner],
) -> None:
    """The erasure relies on `session_replication_role` being local to one
    session and one transaction. While session 1 has it set to `replica`,
    session 2 — even as the table owner — is still refused."""
    y = learners["y"]
    await study(account_client, y)
    async with admin.acquire() as one, admin.acquire() as two:
        transaction = one.transaction()
        await transaction.start()
        try:
            await one.execute("SET LOCAL session_replication_role = replica")
            assert await one.fetchval("SHOW session_replication_role") == "replica"
            assert await two.fetchval("SHOW session_replication_role") == "origin"
            with pytest.raises(asyncpg.PostgresError, match="Append-only records"):
                await two.execute(
                    "DELETE FROM app.practice_attempts WHERE learner_id = $1", y.user_id
                )
            with pytest.raises(asyncpg.PostgresError, match="Append-only records"):
                await two.execute(
                    "UPDATE app.practice_attempts SET score = 1 WHERE learner_id = $1", y.user_id
                )
        finally:
            await transaction.rollback()
        assert await one.fetchval("SHOW session_replication_role") == "origin"
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.practice_attempts WHERE learner_id = $1", y.user_id
        )
        == 2
    )


async def test_a_synthetic_learner_is_fully_erased_and_another_is_untouched(
    account_client: httpx.AsyncClient,
    learners: dict[str, SyntheticLearner],
    admin: asyncpg.Pool,
    local_env: dict[str, str],
) -> None:
    from tests.account_fixtures import create_synthetic_learner, delete_auth_user

    z = create_synthetic_learner(local_env)  # a brand-new account, erased by this test
    y = learners["y"]

    # Both learners use the product: profile, onboarding, study, requests, export.
    for learner, name in ((z, "Synthetic learner Z"), (y, "Synthetic learner Y")):
        patched = await account_client.patch(
            "/v1/me", json={"grade_code": "9AF", "display_name": name}, headers=learner.headers
        )
        assert patched.status_code == 200
        await account_client.put(
            "/v1/me/onboarding",
            json={"state": "ready", "onboarding_version": 1, "tour_dismissed": True},
            headers=learner.headers,
        )
        await account_client.post("/v1/me/deletion-request", headers=learner.headers)
        await account_client.post("/v1/me/export", headers=learner.headers)
    await study(account_client, z)
    await study(account_client, y, creole=True)
    await account_client.delete("/v1/me/deletion-request", headers=z.headers)
    await account_client.post("/v1/me/deletion-request", headers=z.headers)

    assert tuple(await admin.fetchrow(LEARNER_ROWS, z.user_id)) == (1, 2, 3, 3, 1, 1, 1, 2, 1)
    y_before = await snapshot(admin, y.user_id)
    assert len(y_before["attempts"]) == 2 and len(y_before["deletion"]) == 1
    triggers_before = await admin.fetch(
        "SELECT t.oid, t.tgname, t.tgenabled, pg_get_triggerdef(t.oid) FROM pg_trigger t "
        "JOIN pg_class c ON c.oid = t.tgrelid WHERE c.relnamespace = 'app'::regnamespace "
        "AND NOT t.tgisinternal ORDER BY t.oid"
    )
    processed_before = await admin.fetchval(
        "SELECT count(*) FROM account.deletion_requests WHERE status = 'processed'"
    )

    # Before the erasure, Auth cannot delete the account: our foreign keys refuse.
    refused = delete_auth_user(local_env, z.user_id)
    assert refused.status_code >= 400
    assert await admin.fetchval("SELECT count(*) FROM auth.users WHERE id = $1", z.user_id) == 1

    # The erasure, run over a real connection of the WORKER login role
    # (edu_worker_login): the only thing that role can do in this schema.
    worker = await asyncpg.connect(worker_url(local_env))
    try:
        assert await worker.fetchval("SELECT session_user::text") == "edu_worker_login"
        for forbidden in (
            "SELECT count(*) FROM app.practice_attempts",
            "DELETE FROM app.practice_attempts",
            "SET session_replication_role = replica",
            "SELECT account.find_learner_references(gen_random_uuid())",
            "SELECT account.staff_erase_learner(gen_random_uuid())",
            "SELECT account.export_own_data()",
            # Review M-2: the worker cannot name a user, only an open request.
            f"SELECT account.erase_learner('{z.user_id}')",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await worker.execute(forbidden)
        with pytest.raises(asyncpg.PostgresError, match="No open deletion request"):
            await worker.execute("SELECT account.worker_process_deletion($1)", uuid.uuid4())
        with pytest.raises(asyncpg.PostgresError, match="No open deletion request"):
            await worker.execute("SELECT account.worker_process_deletion($1)", z.user_id)
        request_id = await admin.fetchval(
            "SELECT id FROM account.deletion_requests WHERE user_id = $1 AND status = 'requested'",
            z.user_id,
        )
        async with worker.transaction():
            report = await worker.fetchval(
                "SELECT account.worker_process_deletion($1)::text", request_id
            )
            # Still inside the worker's own transaction: protections are back.
            assert await worker.fetchval("SHOW session_replication_role") == "origin"
        assert await worker.fetchval("SHOW session_replication_role") == "origin"
    finally:
        await worker.close()
    assert str(z.user_id) not in report
    erased_event = await admin.fetchrow(
        "SELECT actor_id, actor_kind, target_id, details FROM app.audit_events "
        "WHERE action = 'account.learner_erased' ORDER BY created_at DESC LIMIT 1"
    )
    assert (erased_event["actor_id"], erased_event["actor_kind"]) == (None, "worker")
    assert erased_event["target_id"] is None and str(z.user_id) not in erased_event["details"]
    assert '"practice_attempts": 2' in erased_event["details"]

    # No row in any application schema references the id.
    assert tuple(await admin.fetchrow(LEARNER_ROWS, z.user_id)) == (0,) * 9
    assert await admin.fetchval("SELECT account.find_learner_references($1)", z.user_id) == []
    text_columns = await admin.fetch(
        "SELECT n.nspname, c.relname, a.attname FROM pg_attribute a "
        "JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname IN ('app', 'account', 'ops', 'staff', 'public') AND c.relkind = 'r' AND a.attnum > 0 "
        "AND NOT a.attisdropped AND a.atttypid IN ('uuid'::regtype, 'text'::regtype, "
        "'jsonb'::regtype, 'json'::regtype)"
    )
    assert len(text_columns) > 60
    for column in text_columns:
        found = await admin.fetchval(
            f'SELECT count(*) FROM "{column["nspname"]}"."{column["relname"]}" '
            f'WHERE position($1 IN "{column["attname"]}"::text) > 0',
            str(z.user_id),
        )
        assert found == 0, f"{column['nspname']}.{column['relname']}.{column['attname']}"
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM account.deletion_requests WHERE status = 'processed' "
            "AND user_id IS NULL"
        )
        == processed_before + 1
    ), "the carried-out request remains, without the user id"

    # The other learner is byte-identical and keeps working.
    assert await snapshot(admin, y.user_id) == y_before
    more = await account_client.post(
        "/v1/sync/push",
        json={"ops": [answer_op(SEED_QUESTIONS_HT[2][0], SEED_QUESTIONS_HT[2][1])]},
        headers=y.headers,
    )
    assert more.json()["results"][0]["status"] == "accepted"
    assert more.json()["results"][0]["result"]["change_version"] == 3
    y_requests = await account_client.get("/v1/me/account-requests", headers=y.headers)
    assert y_requests.json()["deletion_request"]["status"] == "requested"

    # The protections are the same catalog rows as before, and still bite.
    assert (
        await admin.fetch(
            "SELECT t.oid, t.tgname, t.tgenabled, pg_get_triggerdef(t.oid) FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid WHERE c.relnamespace = 'app'::regnamespace "
            "AND NOT t.tgisinternal ORDER BY t.oid"
        )
        == triggers_before
    )
    assert {row["tgenabled"] for row in triggers_before} == {b"O"}
    with pytest.raises(asyncpg.PostgresError, match="Append-only records"):
        await admin.execute("DELETE FROM app.practice_attempts WHERE learner_id = $1", y.user_id)

    # A still-valid token of the erased learner gets a fresh, EMPTY account:
    # none of the old data comes back. (Documented gap: disable the Auth
    # account first, or delete it right after — which now works.)
    pull = await account_client.get("/v1/sync/pull", headers=z.headers)
    assert pull.status_code == 200 and pull.json()["changes"] == []
    fresh = await account_client.get("/v1/me", headers=z.headers)
    assert fresh.status_code == 200
    assert fresh.json()["display_name"] is None and fresh.json()["grade"] is None
    onboarding = await account_client.get("/v1/me/onboarding", headers=z.headers)
    assert onboarding.json()["state"] == "new"

    # Erase that empty shell again, then Auth deletes the account itself.
    again = await admin.fetchval("SELECT account.erase_learner($1)", z.user_id)
    assert '"app.learner_profiles": 1' in again and '"app.practice_attempts": 0' in again
    deleted = delete_auth_user(local_env, z.user_id)
    assert deleted.status_code == 200, deleted.text
    assert await admin.fetchval("SELECT count(*) FROM auth.users WHERE id = $1", z.user_id) == 0

    # The token outlives the account for up to an hour, but it now reaches nothing.
    gone = await account_client.get("/v1/me", headers=z.headers)
    assert gone.status_code != 200
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.learner_profiles WHERE user_id = $1", z.user_id
        )
        == 0
    )
    assert await snapshot(admin, y.user_id) != y_before  # (Y studied once more, above)
    assert len((await snapshot(admin, y.user_id))["attempts"]) == 3


# ------------------------------------------------------- who may run erasure
async def test_only_the_worker_and_a_staff_administrator_can_erase(
    account_client: httpx.AsyncClient,
    learners: dict[str, SyntheticLearner],
    admin: asyncpg.Pool,
    local_env: dict[str, str],
    make_staff,  # type: ignore[no-untyped-def]
) -> None:
    from tests.account_fixtures import create_synthetic_learner
    from tests.helpers import EDITOR, REVIEWER

    y = learners["y"]
    target = create_synthetic_learner(local_env)
    await study(account_client, target)
    await study(account_client, y, creole=True)
    administrator = await make_staff("admin")
    y_before = await snapshot(admin, y.user_id)

    staff = await asyncpg.connect(staff_url(local_env))
    try:
        assert await staff.fetchval("SELECT session_user::text") == "edu_staff_login"

        async def as_actor(actor: uuid.UUID | None, user_id: uuid.UUID) -> str:
            async with staff.transaction():
                if actor is not None:
                    await staff.execute("SELECT set_config('edu.actor_id', $1, true)", str(actor))
                return str(
                    await staff.fetchval("SELECT account.staff_erase_learner($1)::text", user_id)
                )

        # editor, reviewer, a learner's id, another learner, and no actor at all
        for actor in (EDITOR, REVIEWER, target.user_id, y.user_id, None):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await as_actor(actor, target.user_id)
        # staff cannot reach the orchestrator around the role check
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await staff.execute("SELECT account.erase_learner($1)", target.user_id)
        # an administrator cannot erase staff accounts (including their own)
        for staff_account in (EDITOR, administrator.user_id):
            with pytest.raises(asyncpg.PostgresError, match="staff records|No learner with this id"):
                await as_actor(administrator.user_id, staff_account)
        assert tuple(await admin.fetchrow(LEARNER_ROWS, target.user_id))[:6] == (1, 2, 3, 3, 1, 1)

        report = await as_actor(administrator.user_id, target.user_id)
        assert '"erased": true' in report and str(target.user_id) not in report
    finally:
        await staff.close()

    assert tuple(await admin.fetchrow(LEARNER_ROWS, target.user_id)) == (0,) * 9
    assert await admin.fetchval("SELECT account.find_learner_references($1)", target.user_id) == []
    assert await snapshot(admin, y.user_id) == y_before
    event = await admin.fetchrow(
        "SELECT actor_id, actor_kind, target_id FROM app.audit_events "
        "WHERE action = 'account.learner_erased' AND actor_id = $1",
        administrator.user_id,
    )
    assert event is not None and event["actor_kind"] == "staff" and event["target_id"] is None
    # (The erased account's Auth row is left for `make db-reset`; no token of it is used again.)


# ------------------------------------------- concurrency: nothing interleaves
async def test_a_push_in_flight_makes_the_erasure_wait_and_is_then_erased_too(
    account_client: httpx.AsyncClient,
    learners: dict[str, SyntheticLearner],
    admin: asyncpg.Pool,
) -> None:
    """Connection 1 is in the middle of a sync for the learner (it holds the
    learner's sync-row lock, like the API does until COMMIT). The erasure on
    connection 2 must wait, then remove that operation's rows as well."""
    x, y = learners["x"], learners["y"]
    await study(account_client, x)
    await study(account_client, y, creole=True)
    y_before = await snapshot(admin, y.user_id)
    async with admin.acquire() as one, admin.acquire() as two:
        push = one.transaction()
        await push.start()
        await one.execute("SELECT set_config('edu.actor_id', $1, true)", str(x.user_id))
        status = await one.fetchval(
            "SELECT app.sync_apply_operation($1, 'practice_answer', $2::jsonb, sha256('p'), "
            "'mep-canon-1') ->> 'status'",
            uuid.uuid4(),
            f'{{"question_revision_id":"{SEED_QUESTIONS_FR[2][0]}","response":{{"choice_id":"c"}}}}',
        )
        assert status == "accepted"

        erasure = asyncio.ensure_future(
            two.fetchval("SELECT account.erase_learner($1)::text", x.user_id)
        )
        await asyncio.sleep(0.7)
        assert not erasure.done(), "the erasure must wait for the sync in flight"
        # Meanwhile nothing of the learner has been touched (as seen by a third session).
        assert tuple(await admin.fetchrow(LEARNER_ROWS, x.user_id))[:6] == (1, 2, 3, 3, 1, 1)

        await push.commit()
        report = await asyncio.wait_for(erasure, timeout=10)
    assert '"app.practice_attempts": 3' in report, "the just-committed attempt was erased too"
    assert tuple(await admin.fetchrow(LEARNER_ROWS, x.user_id)) == (0,) * 9
    assert await snapshot(admin, y.user_id) == y_before


async def test_a_push_arriving_during_the_erasure_waits_and_never_mixes_with_old_data(
    account_client: httpx.AsyncClient,
    learners: dict[str, SyntheticLearner],
    admin: asyncpg.Pool,
) -> None:
    """Connection 1 has run the erasure but not committed. A push by the same
    learner through the real API must wait; once the erasure commits, the push
    either fails or starts a brand-new, complete account — it never lands
    inside the erased history. (Why the Auth account must be disabled first.)"""
    x, y = learners["x"], learners["y"]
    await study(account_client, x)
    await study(account_client, y, creole=True)
    y_before = await snapshot(admin, y.user_id)
    old_attempts = {
        row["id"]
        for row in await admin.fetch(
            "SELECT id FROM app.practice_attempts WHERE learner_id = $1", x.user_id
        )
    }
    async with admin.acquire() as one:
        erasure = one.transaction()
        await erasure.start()
        await one.fetchval("SELECT account.erase_learner($1)", x.user_id)

        push = asyncio.ensure_future(
            account_client.post(
                "/v1/sync/push",
                json={"ops": [answer_op(SEED_QUESTIONS_FR[3][0], SEED_QUESTIONS_FR[3][1])]},
                headers=x.headers,
            )
        )
        await asyncio.sleep(0.7)
        assert not push.done(), "the push must wait for the erasure in flight"
        await erasure.commit()
        response = await asyncio.wait_for(push, timeout=15)

    rows = tuple(await admin.fetchrow(LEARNER_ROWS, x.user_id))
    if response.status_code == 200:
        # A fresh account: exactly this one operation, version 1, nothing older.
        assert response.json()["results"][0]["status"] == "accepted"
        assert response.json()["results"][0]["result"]["change_version"] == 1
        assert rows[:6] == (1, 1, 1, 1, 0, 1)
    else:
        assert response.status_code >= 500 and rows[:6] == (0, 0, 0, 0, 0, 0)
    remaining = {
        row["id"]
        for row in await admin.fetch(
            "SELECT id FROM app.practice_attempts WHERE learner_id = $1", x.user_id
        )
    }
    assert not remaining & old_attempts, "none of the erased attempts came back"
    assert await snapshot(admin, y.user_id) == y_before


async def test_onboarding_and_export_racing_an_erasure_wait_and_are_refused(
    account_app: FastAPI,
    account_client: httpx.AsyncClient,
    learners: dict[str, SyntheticLearner],
    admin: asyncpg.Pool,
) -> None:
    """Review finding H-1. With the erasure of X in flight on one connection,
    X's onboarding update and export (run as the API role on other
    connections) must queue behind it and then be refused — not commit rows
    for an erased learner after the erasure has reported success."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    x = learners["x"]
    await study(account_client, x)
    db = account_app.state.db

    async def as_learner(statement: str) -> str:
        try:
            async with db.transaction(x.user_id) as conn:
                await conn.execute(text(statement))
        except DBAPIError as exc:
            return str(getattr(exc.orig, "sqlstate", None))
        return "committed"

    async with admin.acquire() as one:
        erasure = one.transaction()
        await erasure.start()
        await one.fetchval("SELECT account.erase_learner($1)", x.user_id)
        calls = [
            asyncio.ensure_future(as_learner("SELECT account.advance_onboarding('ready', 1)")),
            asyncio.ensure_future(as_learner("SELECT account.export_own_data()")),
        ]
        await asyncio.sleep(0.7)
        assert not any(call.done() for call in calls), "both must wait for the erasure"
        await erasure.commit()
        outcomes = await asyncio.wait_for(asyncio.gather(*calls), timeout=10)

    assert outcomes == ["42501", "42501"]
    assert tuple(await admin.fetchrow(LEARNER_ROWS, x.user_id)) == (0,) * 9
    assert await admin.fetchval("SELECT account.find_learner_references($1)", x.user_id) == []
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.audit_events WHERE actor_id = $1 OR target_id = $1",
            x.user_id,
        )
        == 0
    )
