"""Learner rewards API: flag behaviour, contract, paging, isolation, exposure."""

# ruff: noqa: F811 — fixtures are imported from tests/rewards_fixtures.py and requested by
# parameter name, which pyflakes reads as a redefinition.

from __future__ import annotations

import base64
import datetime as dt
import json
import uuid
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from edu_api.rewards.cursor import encode_ledger_cursor
from tests.conftest import publish_new_lesson
from tests.helpers import (
    SEED_LESSON,
    SEED_QUESTIONS_FR,
    SEED_REV_FR,
    STUDENT_A,
    STUDENT_B,
    answer_op,
    bearer,
    completed_op,
)
from tests.rewards_fixtures import (  # noqa: F401  (fixtures are used by name)
    assert_balance_matches_ledger,
    clean_rewards,
    ledger_total,
    off,
    on,
    push,
    rewards_app,
    rewards_off_app,
    summary,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_rewards")]

Q1, Q1_CORRECT = SEED_QUESTIONS_FR[0]
Q2, Q2_CORRECT = SEED_QUESTIONS_FR[1]
PATHS = ("/v1/rewards/summary", "/v1/rewards/ledger")


# ---------------------------------------------------------------- flag behaviour
@pytest.mark.parametrize("path", PATHS)
async def test_flag_off_the_routes_do_not_exist(
    off: httpx.AsyncClient, tokens: dict[str, str], path: str
) -> None:
    unknown = await off.get("/v1/definitely-not-a-route")
    for headers in ({}, bearer(tokens["student_a"])):
        response = await off.get(path, headers=headers)
        assert response.status_code == 404
        body = response.json()
        assert set(body) == {"error"}
        assert body["error"]["code"] == "not_found"
        assert body["error"]["request_id"] == response.headers["x-request-id"]
        # Indistinguishable from any path the API has never heard of.
        assert body["error"]["message"] == unknown.json()["error"]["message"]
        assert "www-authenticate" not in response.headers


async def test_flag_off_push_never_touches_the_rewards_schema(
    off: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    response = await push(
        off, tokens["student_a"], [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)]
    )
    assert response.status_code == 200
    for table in ("ledger", "balances", "processed_operations", "activity_days", "streak_state"):
        assert (
            await admin.fetchval(
                f"SELECT count(*) FROM rewards.{table} WHERE learner_id = $1", STUDENT_A
            )
            == 0
        ), table


def test_the_flag_defaults_to_off(
    local_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import build_settings

    monkeypatch.delenv("EDU_REWARDS_ENABLED", raising=False)
    assert build_settings(local_env).rewards_enabled is False


async def test_routes_are_not_yet_in_the_generated_contract(on: httpx.AsyncClient) -> None:
    """Deliberate (see routers/rewards.py): the verified contract test pins the
    documented path set, so these routes are served (next test) but stay out of
    openapi.json until the integrator updates that pin."""
    documented = (await on.get("/openapi.json")).json()["paths"]
    assert not any(path.startswith("/v1/rewards") for path in documented)


def test_with_the_schema_constant_on_the_contract_is_bearer_only_and_one_error_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling R-01: what the generated contract will contain once the integrator
    flips INCLUDE_IN_SCHEMA — every rewards operation needs the bearer token and
    documents nothing but the standard error shape for non-200 answers."""
    from fastapi.openapi.utils import get_openapi

    from edu_api.routers import rewards as rewards_router

    assert rewards_router.INCLUDE_IN_SCHEMA is False, "the integrator flips this, not a lane"
    for route in rewards_router.router.routes:
        monkeypatch.setattr(route, "include_in_schema", True)
    spec = get_openapi(title="rewards", version="0", routes=rewards_router.router.routes)

    assert set(spec["paths"]) == set(PATHS)
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for path, operations in spec["paths"].items():
        assert set(operations) == {"get"}, path
        operation = operations["get"]
        assert operation["security"] == [{"HTTPBearer": []}], path
        assert {"200", "401", "404", "503"} <= set(operation["responses"]), path
        for status, response in operation["responses"].items():
            if status != "200":
                assert response["content"]["application/json"]["schema"] == error_ref, (
                    path,
                    status,
                )
        assert "requestBody" not in operation, "read-only: nothing can be sent"
    schemas = spec["components"]["schemas"]
    assert "HTTPValidationError" not in schemas, "one error shape only"
    assert {"RewardsSummary", "LedgerPage", "LedgerEntry", "ErrorResponse"} <= set(schemas)
    assert spec["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


@pytest.mark.parametrize("path", PATHS)
async def test_flag_on_a_token_is_required(on: httpx.AsyncClient, path: str) -> None:
    response = await on.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
async def test_there_is_no_way_to_write_gold_through_the_api(
    on: httpx.AsyncClient, tokens: dict[str, str], path: str, method: str
) -> None:
    response = await on.request(
        method, path, headers=bearer(tokens["student_a"]), json={"amount": 1000, "balance": 1000}
    )
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


# ------------------------------------------------------------------- summary
async def test_summary_of_a_learner_with_no_activity(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    body = await summary(on, tokens["student_a"])
    today = await admin.fetchval("SELECT rewards.haiti_day(now())")
    assert body == {
        "balance": 0,
        "lifetime_earned": 0,
        "streak": {
            "current_days": 0,
            "longest_days": 0,
            "last_active_day": None,
            "active_today": False,
        },
        "achievements": [],
        "recent": [],
        "today": today.isoformat(),
        "up_to_date": True,
        "rules_status": "provisional",
    }
    assert await ledger_total(admin, STUDENT_A) == (0, 0), "reading creates nothing"


async def test_summary_contract_after_activity(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    ops = [answer_op(Q1, Q1_CORRECT), answer_op(Q2, "d"), completed_op(SEED_REV_FR)]
    await push(on, tokens["student_a"], ops)
    body = await summary(on, tokens["student_a"])
    today = (await admin.fetchval("SELECT rewards.haiti_day(now())")).isoformat()

    assert set(body) == {
        "balance",
        "lifetime_earned",
        "streak",
        "achievements",
        "recent",
        "today",
        "up_to_date",
        "rules_status",
    }
    assert (body["balance"], body["lifetime_earned"], body["up_to_date"]) == (35, 35, True)
    assert body["streak"] == {
        "current_days": 1,
        "longest_days": 1,
        "last_active_day": today,
        "active_today": True,
    }
    assert [(a["code"], a["gold"]) for a in body["achievements"]] == [
        ("first_correct_answer", 0),
        ("first_lesson_completed", 10),
    ]
    assert all(set(a) == {"code", "titles", "earned_at", "gold"} for a in body["achievements"])
    assert set(body["achievements"][0]["titles"]) == {"fr", "ht"}

    recent = body["recent"]
    assert [e["source"] for e in recent] == [
        "achievement",
        "lesson_first_completed",
        "question_first_correct",
    ], "newest first"
    assert set(recent[0]) == {
        "id",
        "kind",
        "amount",
        "source",
        "lesson_id",
        "question_key",
        "achievement_code",
        "op_id",
        "day",
        "created_at",
    }
    assert recent[2] == {
        "id": recent[2]["id"],
        "kind": "award",
        "amount": 5,
        "source": "question_first_correct",
        "lesson_id": str(SEED_LESSON),
        "question_key": "addition",
        "achievement_code": None,
        "op_id": ops[0]["op_id"],
        "day": today,
        "created_at": recent[2]["created_at"],
    }
    assert recent[0]["achievement_code"] == "first_lesson_completed"
    assert recent[0]["op_id"] == ops[2]["op_id"]
    assert sum(e["amount"] for e in recent) == body["balance"]
    # Internal bookkeeping never leaves the server.
    assert (
        "learner_id" not in str(body) and "source_key" not in str(body) and "seq" not in str(body)
    )


async def test_an_old_run_is_reported_without_a_lost_streak_state(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    """Three active days that ended a week ago: current is 0, longest is 3,
    nothing is taken away and no 'lost' field exists."""
    today: dt.date = await admin.fetchval("SELECT rewards.haiti_day(now())")
    for days_ago in (9, 8, 7):
        instant = dt.datetime.combine(
            today - dt.timedelta(days=days_ago), dt.time(17, 0), tzinfo=dt.UTC
        )
        await admin.execute(
            "INSERT INTO app.sync_receipts (learner_id, op_id, op_kind, canon_version, payload_sha256, "
            "result_code, result, created_at) VALUES ($1, gen_random_uuid(), 'practice_answer', "
            "'mep-canon-1', sha256(gen_random_uuid()::text::bytea), 'accepted', '{}', $2)",
            STUDENT_A,
            instant,
        )
    body = await summary(on, tokens["student_a"])
    assert body["streak"] == {
        "current_days": 0,
        "longest_days": 3,
        "last_active_day": (today - dt.timedelta(days=7)).isoformat(),
        "active_today": False,
    }
    assert body["balance"] == 0
    assert [a["code"] for a in body["achievements"]] == ["three_day_streak"]
    assert not any(word in str(body).lower() for word in ("lost", "broken", "missed", "penalty"))

    # Studying again today starts a new run; the old best is kept.
    await push(on, tokens["student_a"], [answer_op(Q1, "a")])
    again = (await summary(on, tokens["student_a"]))["streak"]
    assert (again["current_days"], again["longest_days"], again["active_today"]) == (1, 3, True)


# -------------------------------------------------------------------- ledger
async def test_ledger_pages_newest_first_with_an_opaque_cursor(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    lesson = await publish_new_lesson(admin, questions=(("mcq", "b"),) * 7)
    await push(on, tokens["student_a"], [answer_op(q, "b") for q in lesson["question_ids"]])

    async def page(**params: Any) -> dict[str, Any]:
        response = await on.get(
            "/v1/rewards/ledger", params=params, headers=bearer(tokens["student_a"])
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    first = await page(limit=3)
    assert set(first) == {"entries", "next_cursor", "has_more", "balance"}
    assert (len(first["entries"]), first["has_more"], first["balance"]) == (3, True, 35)
    assert [e["question_key"] for e in first["entries"]] == ["q7", "q6", "q5"]
    second = await page(limit=3, cursor=first["next_cursor"])
    assert [e["question_key"] for e in second["entries"]] == ["q4", "q3", "q2"]
    third = await page(limit=3, cursor=second["next_cursor"])
    assert [e["question_key"] for e in third["entries"]] == ["q1"]
    assert (third["has_more"], third["next_cursor"]) == (False, None)

    everything = await page()
    assert len(everything["entries"]) == 7 and everything["has_more"] is False
    ids = [e["id"] for e in first["entries"] + second["entries"] + third["entries"]]
    assert ids == [e["id"] for e in everything["entries"]], "pages do not overlap or skip"
    assert sum(e["amount"] for e in everything["entries"]) == everything["balance"]

    # Security review L3: the cursor names one of the caller's OWN entries and
    # nothing global — no table-wide sequence number to watch grow.
    raw = first["next_cursor"]
    document = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    assert set(document) == {"v", "a", "t", "i"}
    assert document["i"] == first["entries"][-1]["id"]
    global_seq = await admin.fetchval("SELECT max(seq) FROM rewards.ledger")
    assert global_seq not in document.values()

    # New entries do not disturb a walk that is already in progress.
    await push(on, tokens["student_a"], [completed_op(lesson["revision_id"])])
    assert (await page(limit=3, cursor=first["next_cursor"]))["entries"] == second["entries"]


async def test_ledger_cursor_and_limit_validation(
    on: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    await push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT)])

    async def get(token: str, **params: Any) -> httpx.Response:
        return await on.get("/v1/rewards/ledger", params=params, headers=bearer(token))

    now = dt.datetime.now(dt.UTC)
    some_id = uuid.uuid4()
    for bad in ("garbage", "e30", encode_ledger_cursor(STUDENT_B, now, some_id), "x" * 150):
        response = await get(tokens["student_a"], cursor=bad)
        assert response.status_code == 422, bad
        assert response.json()["error"]["code"] == "invalid_cursor"
    # A cursor is bound to its account: A's cursor is useless to B.
    assert (
        await get(tokens["student_b"], cursor=encode_ledger_cursor(STUDENT_A, now, some_id))
    ).json()["error"]["code"] == "invalid_cursor"

    for params in ({"limit": 0}, {"limit": 101}, {"limit": "many"}, {"cursor": "x" * 201}):
        response = await get(tokens["student_a"], **params)
        assert response.status_code == 422, params
        assert response.json()["error"]["code"] == "validation_error"
    assert (await get(tokens["student_a"], limit=100)).status_code == 200
    # A well-formed cursor pointing past the oldest entry is simply an empty page.
    long_ago = dt.datetime(2000, 1, 1, tzinfo=dt.UTC)
    empty = (
        await get(tokens["student_a"], cursor=encode_ledger_cursor(STUDENT_A, long_ago, some_id))
    ).json()
    assert (empty["entries"], empty["has_more"], empty["next_cursor"]) == ([], False, None)


# ------------------------------------------------------------ cross-account
async def test_cross_account_isolation(
    on: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    op = answer_op(Q1, Q1_CORRECT)
    await push(on, tokens["student_a"], [op, completed_op(SEED_REV_FR)])
    await push(on, tokens["student_b"], [answer_op(Q2, Q2_CORRECT)])

    a = await summary(on, tokens["student_a"])
    b = await summary(on, tokens["student_b"])
    assert (a["balance"], b["balance"]) == (35, 5)
    a_ids = {e["id"] for e in a["recent"]}
    b_ledger = (await on.get("/v1/rewards/ledger", headers=bearer(tokens["student_b"]))).json()
    assert a_ids.isdisjoint(e["id"] for e in b_ledger["entries"])
    assert [e["question_key"] for e in b_ledger["entries"]] == ["multiplication"]
    assert [x["code"] for x in b["achievements"]] == ["first_correct_answer"]

    # B replays A's op id: for B it is a brand-new operation of B's own.
    replayed_by_b = (await push(on, tokens["student_b"], [op])).json()["results"][0]
    assert (replayed_by_b["status"], replayed_by_b["replayed"]) == ("accepted", False)
    assert await assert_balance_matches_ledger(admin, STUDENT_A) == 35
    assert await assert_balance_matches_ledger(admin, STUDENT_B) == 10

    # A staff account is just another caller of the student API: it sees nothing of A or B.
    editor = await summary(on, tokens["editor"])
    assert (editor["balance"], editor["recent"], editor["achievements"]) == (0, [], [])


async def test_award_function_never_reveals_other_learners_operations(
    on: httpx.AsyncClient, rewards_app: FastAPI, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    op = answer_op(Q2, Q2_CORRECT)
    await push(on, tokens["student_a"], [op])
    call = text("SELECT rewards.award_for_operation(:op_id) AS o")
    async with rewards_app.state.db.transaction(STUDENT_B) as conn:
        theirs = (await conn.execute(call, {"op_id": uuid.UUID(op["op_id"])})).scalar_one()
        unknown = (await conn.execute(call, {"op_id": uuid.uuid4()})).scalar_one()
    assert (
        theirs
        == unknown
        == {"status": "no_award", "replayed": False, "gold": 0, "achievements": []}
    )
    assert await ledger_total(admin, STUDENT_B) == (0, 0)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO rewards.ledger (learner_id, entry_kind, amount, rule_code, rule_version, source_kind, "
        "source_op_id, lesson_id, question_key, accepted_at, accepted_day) VALUES "
        "('a0000000-0000-4000-8000-000000000001', 'award', 5, 'question_first_correct', 1, "
        "'question_first_correct', gen_random_uuid(), 'b0000000-0000-4000-8000-000000000005', 'addition', now(), current_date)",
        "UPDATE rewards.ledger SET amount = 1000",
        "DELETE FROM rewards.ledger",
        "UPDATE rewards.balances SET balance = 1000000",
        "INSERT INTO rewards.balances (learner_id, balance, lifetime_earned) "
        "VALUES ('a0000000-0000-4000-8000-000000000001', 1000, 1000)",
        "UPDATE rewards.streak_state SET longest_run_days = 365",
        "INSERT INTO rewards.achievement_awards (learner_id, achievement_code, source_op_id, awarded_at, awarded_day) "
        "VALUES ('a0000000-0000-4000-8000-000000000001', 'three_day_streak', gen_random_uuid(), now(), current_date)",
        "UPDATE rewards.rules SET is_active = false",
        "INSERT INTO rewards.rules (code, version, event_kind, amount) VALUES ('question_first_correct', 9, 'question_first_correct', 1000)",
        "SELECT * FROM rewards.rules",
        "SELECT * FROM rewards.processed_operations",
        "SELECT * FROM rewards.activity_days",
        "SELECT rewards.rebuild_balance('a0000000-0000-4000-8000-000000000002')",
        "SELECT rewards.rebuild_balance('a0000000-0000-4000-8000-000000000001')",
        "SELECT rewards.apply_operation('a0000000-0000-4000-8000-000000000002', gen_random_uuid())",
        "SELECT rewards.reconcile_learner_internal('a0000000-0000-4000-8000-000000000002', 10)",
        "SELECT rewards.reconcile_batch(10, 10)",
        "SELECT rewards.reverse_entry(gen_random_uuid(), 'test_correction')",
        "SELECT rewards.staff_reverse_entry(gen_random_uuid(), 'test_correction')",
        "SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 100, 'support_goodwill', gen_random_uuid())",
        "SELECT rewards.is_correction_reason('test_correction')",
        "SELECT ops.audit_write('rewards_ledger.adjust', 'rewards_ledger', gen_random_uuid(), 'allowed')",
        "SELECT staff.require_role('admin')",
        "SELECT rewards.erase_learner('a0000000-0000-4000-8000-000000000002')",
        "SELECT rewards.rebuild_streak('a0000000-0000-4000-8000-000000000001')",
        "SELECT rewards.lock_learner('a0000000-0000-4000-8000-000000000002')",
        "TRUNCATE rewards.ledger",
        "ALTER TABLE rewards.ledger DISABLE TRIGGER ALL",
        "ALTER TABLE rewards.ledger DISABLE ROW LEVEL SECURITY",
        "CREATE TABLE rewards.exfil (x int)",
    ],
)
async def test_arbitrary_sql_on_the_api_connection_cannot_forge_rewards(
    rewards_app: FastAPI, statement: str
) -> None:
    """Worst case: an attacker can run SQL of their choice on the API's connection."""
    with pytest.raises(DBAPIError) as caught:
        async with rewards_app.state.db.transaction(STUDENT_A) as conn:
            await conn.execute(text(statement))
    assert getattr(caught.value.orig, "sqlstate", None) == "42501", statement


async def test_api_connection_reads_only_the_callers_rows(
    on: httpx.AsyncClient, rewards_app: FastAPI, tokens: dict[str, str]
) -> None:
    await push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT)])
    await push(on, tokens["student_b"], [answer_op(Q1, Q1_CORRECT), completed_op(SEED_REV_FR)])
    count = text(
        "SELECT (SELECT count(*) FROM rewards.ledger) AS ledger, "
        "(SELECT count(*) FROM rewards.ledger WHERE learner_id <> app.current_actor_id()) AS foreign_ledger, "
        "(SELECT count(*) FROM rewards.balances) AS balances, "
        "(SELECT count(*) FROM rewards.achievement_awards) AS awards, "
        "(SELECT count(*) FROM rewards.streak_state) AS streaks"
    )
    async with rewards_app.state.db.transaction(STUDENT_A) as conn:
        a = (await conn.execute(count)).one()
    async with rewards_app.state.db.transaction(STUDENT_B) as conn:
        b = (await conn.execute(count)).one()
    async with rewards_app.state.db.transaction(None) as conn:
        nobody = (await conn.execute(count)).one()
    assert tuple(a) == (1, 0, 1, 1, 1)
    assert tuple(b) == (3, 0, 1, 2, 1)
    assert tuple(nobody) == (0, 0, 0, 0, 0)


# -------------------------------- the private schema is not in the Data API
async def test_rewards_schema_is_not_reachable_through_the_supabase_data_api(
    on: httpx.AsyncClient, local_env: dict[str, str], tokens: dict[str, str]
) -> None:
    await push(on, tokens["student_a"], [answer_op(Q1, Q1_CORRECT)])
    rest = local_env["LOCAL_SUPABASE_URL"] + "/rest/v1"
    credentials = {
        "publishable key only": {"apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"]},
        "signed-in student": {
            "apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"],
            "Authorization": f"Bearer {tokens['student_a']}",
        },
        "SECRET service key": {"apikey": local_env["LOCAL_SUPABASE_SECRET_KEY"]},
    }
    async with httpx.AsyncClient(timeout=10) as http:
        for label, headers in credentials.items():
            for table in ("ledger", "balances", "rules", "achievement_awards", "streak_state"):
                for profile in ({"Accept-Profile": "rewards"}, {}):
                    response = await http.get(
                        f"{rest}/{table}", params={"select": "*"}, headers={**headers, **profile}
                    )
                    assert response.status_code >= 400, (label, table, profile, response.text[:200])
                    assert "a0000000" not in response.text
            for function, arguments in (
                ("award_for_operation", {"p_op_id": str(uuid.uuid4())}),
                ("reconcile_learner", {"p_limit": 10}),
                ("rebuild_balance", {"p_learner_id": str(STUDENT_A)}),
                ("erase_learner", {"p_user_id": str(STUDENT_A)}),
            ):
                for profile in ({"Content-Profile": "rewards"}, {}):
                    rpc = await http.post(
                        f"{rest}/rpc/{function}", headers={**headers, **profile}, json=arguments
                    )
                    assert rpc.status_code >= 400, (label, function, rpc.text[:200])
        exposed = (await http.get(f"{rest}/", headers=credentials["SECRET service key"])).text
    assert "ledger" not in exposed and "achievement_awards" not in exposed
