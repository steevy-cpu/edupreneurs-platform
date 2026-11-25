"""Private standing API: flag behaviour, contract, end-to-end from /v1/sync/push,
exclusions, immediate opt-out and erasure, and "never anyone else's data"."""

# ruff: noqa: F811 — fixtures are imported from tests/leaderboard_fixtures.py and requested by
# parameter name, which pyflakes reads as a redefinition.

from __future__ import annotations

import datetime as dt
import uuid

import asyncpg
import httpx
import pytest

from tests.helpers import SEED_QUESTIONS_FR, STUDENT_A, STUDENT_B, answer_op, bearer
from tests.leaderboard_fixtures import (  # noqa: F401  (fixtures are used by name)
    ME,
    clean_leaderboard,
    enroll,
    lb,
    lb_off,
    leaderboard_app,
    leaderboard_off_app,
    low_floor,
    make_cohort,
    me,
    push,
    refresh,
)

# Ranking tests run with the minimum cohort size lowered to 1 (``low_floor``): the two synthetic
# students cannot form a cohort of the production floor. The floor itself is tested in
# test_leaderboard_review_fixes.py and in pgTAP 210.
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_leaderboard", "low_floor")]

Q1, Q1_OK = SEED_QUESTIONS_FR[0]
Q2, Q2_OK = SEED_QUESTIONS_FR[1]
Q3, Q3_OK = SEED_QUESTIONS_FR[2]
STANDING_KEYS = {"period", "kind", "starts_on", "ends_on", "closed", "gold", "cohort"}
COHORT_KEYS = {"cohort_id", "pseudonym", "rank", "size", "snapshot_gold", "computed_at", "frozen"}


# ---------------------------------------------------------------- flag behaviour
async def test_flag_off_the_route_does_not_exist(
    lb_off: httpx.AsyncClient, client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    # `client` is the baseline application built with default settings.
    for http in (lb_off, client):
        unknown = await http.get("/v1/definitely-not-a-route")
        for path in (ME, ME + "?period=all", "/v1/leaderboard", "/v1/leaderboard/global"):
            for headers in ({}, bearer(tokens["student_a"])):
                response = await http.get(path, headers=headers)
                assert response.status_code == 404
                body = response.json()
                assert set(body) == {"error"}
                assert body["error"]["code"] == "not_found"
                assert body["error"]["message"] == unknown.json()["error"]["message"]
                assert "www-authenticate" not in response.headers


def test_both_flags_default_to_off(
    local_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import build_settings

    monkeypatch.delenv("EDU_LEADERBOARD_ENABLED", raising=False)
    monkeypatch.delenv("EDU_LEADERBOARD_COHORTS_ENABLED", raising=False)
    settings = build_settings(local_env)
    assert settings.leaderboard_enabled is False
    assert settings.leaderboard_cohorts_enabled is False


async def test_routes_are_not_yet_in_the_generated_contract(lb: httpx.AsyncClient) -> None:
    documented = (await lb.get("/openapi.json")).json()["paths"]
    assert not any(path.startswith("/v1/leaderboard") for path in documented)


def test_with_the_schema_constant_on_the_contract_is_bearer_only_and_one_error_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling R-01: what the generated contract will contain once the integrator
    flips INCLUDE_IN_SCHEMA."""
    from fastapi.openapi.utils import get_openapi

    from edu_api.routers import leaderboard as leaderboard_router

    assert leaderboard_router.INCLUDE_IN_SCHEMA is False, "the integrator flips this, not a lane"
    for route in leaderboard_router.router.routes:
        monkeypatch.setattr(route, "include_in_schema", True)
    spec = get_openapi(title="leaderboard", version="0", routes=leaderboard_router.router.routes)

    assert set(spec["paths"]) == {ME}
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for path, operations in spec["paths"].items():
        assert set(operations) == {"get"}, path
        operation = operations["get"]
        assert operation["security"] == [{"HTTPBearer": []}], path
        assert {"200", "401", "404", "422", "503"} <= set(operation["responses"]), path
        for status, response in operation["responses"].items():
            if status != "200":
                assert response["content"]["application/json"]["schema"] == error_ref, (
                    path,
                    status,
                )
        assert "requestBody" not in operation, "read-only: nothing can be sent"
        # The only input is the period: no learner id, no cohort id, no score.
        assert [p["name"] for p in operation["parameters"]] == ["period"]
    schemas = spec["components"]["schemas"]
    assert "HTTPValidationError" not in schemas, "one error shape only"
    assert {"MyStanding", "CohortStanding", "ErrorResponse"} <= set(schemas)
    assert set(schemas["MyStanding"]["properties"]) == STANDING_KEYS
    assert set(schemas["CohortStanding"]["properties"]) == COHORT_KEYS
    assert spec["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


async def test_flag_on_a_token_is_required(lb: httpx.AsyncClient) -> None:
    response = await lb.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
async def test_nothing_can_be_written_through_the_route(
    lb: httpx.AsyncClient, tokens: dict[str, str], method: str
) -> None:
    response = await lb.request(
        method, ME, headers=bearer(tokens["student_a"]), json={"gold": 9999, "rank": 1}
    )
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.parametrize(
    "period", ["global", "month", "2026-11-17", "2999-01-04", "2026-13-45", "", "all;", "week "]
)
async def test_an_unknown_period_is_a_422_in_the_standard_shape(
    lb: httpx.AsyncClient, tokens: dict[str, str], period: str
) -> None:
    response = await lb.get(ME, params={"period": period}, headers=bearer(tokens["student_a"]))
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"


# ------------------------------------------------------------------ own standing
async def test_a_learner_with_no_activity_and_no_cohort(
    lb: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    # The period is read back from the response, never recomputed from the clock here: a run
    # that straddles Sunday->Monday midnight in Haiti must not flake.
    week = await me(lb, tokens["student_a"])
    monday = dt.date.fromisoformat(week["period"])
    assert monday.isoweekday() == 1
    assert week == {
        "period": monday.isoformat(),
        "kind": "week",
        "starts_on": monday.isoformat(),
        "ends_on": (monday + dt.timedelta(days=6)).isoformat(),
        "closed": False,
        "gold": 0,
        "cohort": None,
    }
    assert await me(lb, tokens["student_a"], "all") == {
        "period": "all",
        "kind": "all_time",
        "starts_on": None,
        "ends_on": None,
        "closed": False,
        "gold": 0,
        "cohort": None,
    }
    last_week = (monday - dt.timedelta(days=7)).isoformat()
    past = await me(lb, tokens["student_a"], last_week)
    assert (past["period"], past["closed"], past["gold"]) == (last_week, True, 0)
    # A closed week named explicitly is closed whatever the clock says.
    explicit = await me(lb, tokens["student_a"], "2026-03-02")
    assert (explicit["period"], explicit["ends_on"], explicit["closed"]) == (
        "2026-03-02",
        "2026-03-08",
        True,
    )


async def test_end_to_end_push_then_refresh_then_my_standing(
    lb: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    a, b = tokens["student_a"], tokens["student_b"]
    a_ops = [answer_op(Q1, Q1_OK), answer_op(Q2, Q2_OK), answer_op(Q3, Q3_OK)]
    b_ops = [answer_op(Q1, Q1_OK), answer_op(Q2, "zz-wrong")]
    assert (await push(lb, a, a_ops)).status_code == 200
    assert (await push(lb, b, b_ops)).status_code == 200

    # Gold is the server's (3 x 5 and 1 x 5 with the placeholder rules); nobody is a member yet.
    for period in ("week", "all"):
        mine = await me(lb, a, period)
        assert (mine["gold"], mine["cohort"]) == (15, None)
        theirs = await me(lb, b, period)
        assert (theirs["gold"], theirs["cohort"]) == (5, None)

    cohort = await make_cohort(admin)
    pseudonym_a = await enroll(admin, cohort, STUDENT_A)
    pseudonym_b = await enroll(admin, cohort, STUDENT_B)
    assert pseudonym_a != pseudonym_b

    # Opted in but not computed yet: no rank is invented.
    waiting = (await me(lb, a))["cohort"]
    assert set(waiting) == COHORT_KEYS
    assert (waiting["rank"], waiting["size"], waiting["computed_at"]) == (None, None, None)

    await refresh(admin, cohort, "week")
    mine = await me(lb, a)
    assert set(mine) == STANDING_KEYS
    assert mine["gold"] == 15
    assert mine["cohort"] == {
        "cohort_id": str(cohort),
        "pseudonym": pseudonym_a,
        "rank": 1,
        "size": 2,
        "snapshot_gold": 15,
        "computed_at": mine["cohort"]["computed_at"],
        "frozen": False,
    }
    assert mine["cohort"]["computed_at"] is not None
    theirs = await me(lb, b)
    assert (theirs["cohort"]["rank"], theirs["cohort"]["size"], theirs["cohort"]["pseudonym"]) == (
        2,
        2,
        pseudonym_b,
    )

    # Exactly-once end to end: replays and re-sent answers under new op ids move nothing.
    assert (await push(lb, b, b_ops)).status_code == 200
    again = [answer_op(Q1, Q1_OK), answer_op(Q1, Q1_OK), answer_op(Q1, Q1_OK), answer_op(Q1, Q1_OK)]
    assert (await push(lb, b, again)).status_code == 200
    await refresh(admin, cohort, "week")
    after = await me(lb, b)
    assert (after["gold"], after["cohort"]["rank"], after["cohort"]["snapshot_gold"]) == (5, 2, 5)
    assert (await me(lb, a))["cohort"]["rank"] == 1

    # A real new answer does move it — after the next refresh, and the stale read says so.
    assert (await push(lb, b, [answer_op(Q2, Q2_OK), answer_op(Q3, Q3_OK)])).status_code == 200
    stale = await me(lb, b)
    assert (stale["gold"], stale["cohort"]["rank"], stale["cohort"]["snapshot_gold"]) == (15, 2, 5)
    await refresh(admin, cohort, "week")
    tied_a, tied_b = await me(lb, a), await me(lb, b)
    assert (tied_a["cohort"]["rank"], tied_b["cohort"]["rank"]) == (1, 1), "equal Gold, equal rank"
    assert tied_b["cohort"]["computed_at"] > stale["cohort"]["computed_at"]


async def test_the_answer_never_contains_anyone_elses_data_or_any_identity(
    lb: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    assert (await push(lb, tokens["student_a"], [answer_op(Q1, Q1_OK)])).status_code == 200
    assert (await push(lb, tokens["student_b"], [answer_op(Q1, Q1_OK)])).status_code == 200
    cohort = await make_cohort(admin)
    pseudonym_a = await enroll(admin, cohort, STUDENT_A)
    pseudonym_b = await enroll(admin, cohort, STUDENT_B)
    await refresh(admin, cohort, "all")

    response = await lb.get(ME, params={"period": "all"}, headers=bearer(tokens["student_b"]))
    raw = response.text
    assert pseudonym_b in raw
    assert pseudonym_a not in raw
    assert str(STUDENT_A) not in raw and str(STUDENT_B) not in raw
    assert "@" not in raw
    rows = await admin.fetch(
        "SELECT p.display_name, u.email FROM app.learner_profiles p JOIN auth.users u "
        "ON u.id = p.user_id WHERE p.user_id = ANY($1::uuid[])",
        [STUDENT_A, STUDENT_B],
    )
    for row in rows:
        for value in (row["display_name"], row["email"]):
            if value:
                assert value not in raw
    # A query parameter cannot point the route at someone else or at another cohort.
    spoofed = await lb.get(
        ME,
        params={"period": "all", "learner_id": str(STUDENT_A), "cohort_id": str(uuid.uuid4())},
        headers=bearer(tokens["student_b"]),
    )
    assert spoofed.json() == response.json()


async def test_opt_out_and_erasure_take_effect_on_the_next_read(
    lb: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    a, b = tokens["student_a"], tokens["student_b"]
    assert (await push(lb, a, [answer_op(Q1, Q1_OK), answer_op(Q2, Q2_OK)])).status_code == 200
    assert (await push(lb, b, [answer_op(Q1, Q1_OK)])).status_code == 200
    cohort = await make_cohort(admin)
    await enroll(admin, cohort, STUDENT_A)
    await enroll(admin, cohort, STUDENT_B)
    await refresh(admin, cohort, "week")
    assert (await me(lb, b))["cohort"]["rank"] == 2

    # A opts out: no refresh in between.
    assert await admin.fetchval("SELECT leaderboard.withdraw($1, $2)", cohort, STUDENT_A) is True
    gone = await me(lb, a)
    assert (gone["gold"], gone["cohort"]) == (10, None)
    # LB-1: the others' rank and size stay as of the snapshot until the next refresh, so A's
    # decision is not observable by B.
    left = (await me(lb, b))["cohort"]
    assert (left["rank"], left["size"]) == (2, 2)

    # B is erased from the leaderboard: no refresh in between.
    erased = await admin.fetchval("SELECT leaderboard.erase_learner($1)::text", STUDENT_B)
    assert '"memberships": 1' in erased
    assert (await me(lb, b))["cohort"] is None


async def test_a_staff_account_is_never_ranked(
    lb: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    a, b = tokens["student_a"], tokens["student_b"]
    assert (await push(lb, a, [answer_op(Q1, Q1_OK)])).status_code == 200
    assert (await push(lb, b, [answer_op(Q1, Q1_OK), answer_op(Q2, Q2_OK)])).status_code == 200
    cohort = await make_cohort(admin)
    await enroll(admin, cohort, STUDENT_A)
    await enroll(admin, cohort, STUDENT_B)
    await refresh(admin, cohort, "week")
    assert (await me(lb, a))["cohort"]["rank"] == 2
    try:
        # Test arrangement only: the product path for roles is the audited staff function.
        await admin.execute(
            "INSERT INTO app.staff_roles (user_id, role) VALUES ($1, 'editor')", STUDENT_B
        )
        hidden = await me(lb, b)
        assert (hidden["gold"], hidden["cohort"]) == (10, None)
        still = (await me(lb, a))["cohort"]
        assert (still["rank"], still["size"]) == (2, 2), "the snapshot answers until a refresh"
        await refresh(admin, cohort, "week")
        assert (
            await admin.fetchval(
                "SELECT count(*) FROM leaderboard.snapshots WHERE learner_id = $1", STUDENT_B
            )
            == 0
        )
    finally:
        await admin.execute("DELETE FROM app.staff_roles WHERE user_id = $1", STUDENT_B)


async def test_cohorts_are_isolated_from_each_other(
    lb: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    a, b = tokens["student_a"], tokens["student_b"]
    assert (await push(lb, a, [answer_op(Q1, Q1_OK)])).status_code == 200
    assert (await push(lb, b, [answer_op(Q1, Q1_OK), answer_op(Q2, Q2_OK)])).status_code == 200
    one, two = await make_cohort(admin), await make_cohort(admin, "school")
    await enroll(admin, one, STUDENT_A)
    await enroll(admin, two, STUDENT_B)
    await refresh(admin, one, "week")
    await refresh(admin, two, "week")
    mine, theirs = await me(lb, a), await me(lb, b)
    # Each is first of one in its own cohort; B's higher Gold is invisible to A.
    assert (mine["cohort"]["cohort_id"], mine["cohort"]["rank"], mine["cohort"]["size"]) == (
        str(one),
        1,
        1,
    )
    assert (theirs["cohort"]["cohort_id"], theirs["cohort"]["rank"], theirs["cohort"]["size"]) == (
        str(two),
        1,
        1,
    )


async def test_the_api_role_cannot_reach_the_tables_or_the_other_functions(
    leaderboard_app: object, admin: asyncpg.Pool
) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    cohort = await make_cohort(admin)
    db = leaderboard_app.state.db  # type: ignore[attr-defined]
    statements = [
        "SELECT count(*) FROM leaderboard.snapshots",
        "SELECT count(*) FROM leaderboard.memberships",
        "SELECT count(*) FROM leaderboard.cohorts",
        f"SELECT leaderboard.enroll('{cohort}', '{STUDENT_A}')",
        f"SELECT leaderboard.refresh_snapshot('{cohort}', 'all')",
        f"SELECT leaderboard.erase_learner('{STUDENT_B}')",
        f"SELECT leaderboard.period_gold('{STUDENT_B}', NULL, NULL)",
        f"SELECT count(*) FROM leaderboard.visible_rows('{cohort}', 'all')",
    ]
    for statement in statements:
        with pytest.raises(DBAPIError) as caught:
            async with db.transaction(STUDENT_A) as conn:
                await conn.execute(text(statement))
        assert getattr(caught.value.orig, "sqlstate", None) == "42501", statement
