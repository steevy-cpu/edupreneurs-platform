"""GET /v1/entitlements through the real API with real local Auth tokens, and
proof that nothing about entitlements touches learning (no paywall)."""

# ruff: noqa: F811  (pytest fixtures imported from tests.billing_fixtures are used as arguments)
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.billing_fixtures import (
    SEED_COURSE,
    SEED_GRADE,
    billing_clean,  # noqa: F401  (pytest fixture)
    billing_client,  # noqa: F401  (pytest fixture)
    entitlements_app,
    grant,
    http,
    parse_time,
    revoke,
)
from tests.helpers import (
    EDITOR,
    SEED_LESSON,
    SEED_QUESTIONS_FR,
    SEED_REV_FR,
    STUDENT_A,
    STUDENT_B,
    answer_op,
    bearer,
    completed_op,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("billing_clean")]

BASELINE_PATHS = {
    "/health",
    "/ready",
    "/v1/me",
    "/v1/catalog",
    "/v1/lessons/{lesson_id}",
    "/v1/sync/push",
    "/v1/sync/pull",
}


# ------------------------------------------------------------- flag off (default)
async def test_with_the_flag_off_the_route_does_not_exist(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    await grant(admin, STUDENT_A)
    for headers in ({}, bearer(tokens["student_a"])):
        response = await client.get("/v1/entitlements", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    spec = (await client.get("/openapi.json")).json()
    assert set(spec["paths"]) == BASELINE_PATHS, "flag off: the contract is exactly main's"
    assert not [name for name in spec["components"]["schemas"] if "Entitlement" in name]


# ------------------------------------------------------------------- flag on
async def test_requires_a_valid_token(billing_client: httpx.AsyncClient) -> None:
    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        response = await billing_client.get("/v1/entitlements", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"
        assert response.headers["www-authenticate"] == "Bearer"


async def test_a_learner_without_grants_gets_an_empty_list_and_free_content_flag(
    billing_client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await billing_client.get("/v1/entitlements", headers=bearer(tokens["student_a"]))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"server_time", "free_content_always_available", "entitlements"}
    assert body["entitlements"] == []
    assert body["free_content_always_available"] is True
    server_time = parse_time(body["server_time"])
    assert server_time.tzinfo is not None
    assert abs(server_time - datetime.now(UTC)) < timedelta(minutes=5)
    assert response.headers["cache-control"] == "private, no-store"


async def test_only_own_grants_that_are_active_now_are_listed(
    billing_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    active = await grant(admin, STUDENT_A, source="staff_grant")
    grade = await grant(admin, STUDENT_A, scope_kind="grade", scope_id=SEED_GRADE, lasts="90 days")
    course = await grant(
        admin, STUDENT_A, scope_kind="course", scope_id=SEED_COURSE, lasts="10 days"
    )
    future = await grant(admin, STUDENT_A, starts_in="1 hour")
    expired = await grant(admin, STUDENT_A, starts_in="-23 hours", lasts="22 hours")
    revoked = await grant(admin, STUDENT_A, source="trial")
    await revoke(admin, revoked)
    other = await grant(admin, STUDENT_B, source="promo")

    body = (
        await billing_client.get("/v1/entitlements", headers=bearer(tokens["student_a"]))
    ).json()
    listed = {item["id"]: item for item in body["entitlements"]}
    assert set(listed) == {str(active), str(grade), str(course)}
    for hidden in (future, expired, revoked, other):
        assert str(hidden) not in listed
    # latest end first
    assert [item["id"] for item in body["entitlements"]] == [str(grade), str(active), str(course)]

    item = listed[str(active)]
    assert set(item) == {"id", "scope", "starts_at", "ends_at", "source"}, "no internal field leaks"
    assert item["scope"] == {"kind": "all", "id": None}
    assert item["source"] == "staff_grant"
    assert parse_time(item["ends_at"]) - parse_time(item["starts_at"]) == timedelta(days=30)
    assert (
        parse_time(item["starts_at"])
        <= parse_time(body["server_time"])
        < parse_time(item["ends_at"])
    )
    assert listed[str(grade)]["scope"] == {"kind": "grade", "id": str(SEED_GRADE)}
    assert listed[str(course)]["scope"] == {"kind": "course", "id": str(SEED_COURSE)}

    theirs = (
        await billing_client.get("/v1/entitlements", headers=bearer(tokens["student_b"]))
    ).json()
    assert [entry["id"] for entry in theirs["entitlements"]] == [str(other)]
    assert theirs["entitlements"][0]["source"] == "promo"


async def test_nobody_elses_grants_can_be_requested(
    billing_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    theirs = await grant(admin, STUDENT_B)
    for query in (
        {"learner_id": str(STUDENT_B)},
        {"user_id": str(STUDENT_B)},
        {"id": str(theirs)},
    ):
        response = await billing_client.get(
            "/v1/entitlements", params=query, headers=bearer(tokens["student_a"])
        )
        assert response.status_code == 200
        assert response.json()["entitlements"] == []
        assert str(theirs) not in response.text and str(STUDENT_B) not in response.text
    # a staff account sees no learner's grants either
    staff = await billing_client.get("/v1/entitlements", headers=bearer(tokens["editor"]))
    assert staff.json()["entitlements"] == []


async def test_a_revocation_and_an_expiry_take_effect_on_the_next_read(
    billing_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    headers = bearer(tokens["student_a"])
    entitlement = await grant(admin, STUDENT_A)
    short = await grant(admin, STUDENT_A, lasts="1 second")
    first = (await billing_client.get("/v1/entitlements", headers=headers)).json()
    assert {item["id"] for item in first["entitlements"]} >= {str(entitlement)}
    await revoke(admin, entitlement)
    await asyncio.sleep(1.2)
    after = (await billing_client.get("/v1/entitlements", headers=headers)).json()
    assert after["entitlements"] == [], (short, after)
    # a fresh grant gives access again: history, not a flag on the profile
    again = await grant(admin, STUDENT_A)
    final = (await billing_client.get("/v1/entitlements", headers=headers)).json()
    assert [item["id"] for item in final["entitlements"]] == [str(again)]


async def test_identity_does_not_leak_across_one_pooled_connection(
    local_env: dict[str, str], tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    mine = await grant(admin, STUDENT_A)
    order = ["student_a", "student_b", "student_a", "student_b", "student_b", "student_a"]
    async with (
        entitlements_app(local_env, db_pool_size=1, db_max_overflow=0) as application,
        http(application) as client,
    ):
        responses = await asyncio.gather(
            *(client.get("/v1/entitlements", headers=bearer(tokens[who])) for who in order * 4)
        )
    for who, response in zip(order * 4, responses, strict=True):
        ids = [item["id"] for item in response.json()["entitlements"]]
        assert ids == ([str(mine)] if who == "student_a" else []), who


# --------------------------------- no client request can create or extend a grant
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_the_route_is_read_only(
    billing_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool, method: str
) -> None:
    response = await billing_client.request(
        method,
        "/v1/entitlements",
        headers=bearer(tokens["student_a"]),
        json={"scope": {"kind": "all"}, "ends_at": "2099-01-01T00:00:00Z", "source": "gift"},
    )
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert await admin.fetchval("SELECT count(*) FROM billing.entitlements") == 0


@pytest.mark.parametrize(
    "path",
    [
        "/v1/entitlements/grant",
        "/v1/billing/events",
        "/v1/billing/webhook",
        "/v1/billing/mock/events",
        "/v1/staff/billing/grants",
        "/v1/orders",
    ],
)
async def test_no_grant_order_or_provider_route_exists(
    billing_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool, path: str
) -> None:
    response = await billing_client.post(path, headers=bearer(tokens["student_a"]), json={})
    assert response.status_code == 404, path
    assert await admin.fetchval("SELECT count(*) FROM billing.entitlements") == 0


async def test_sync_cannot_carry_a_grant(
    billing_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    response = await billing_client.post(
        "/v1/sync/push",
        headers=bearer(tokens["student_a"]),
        json={
            "ops": [
                {
                    "op_id": str(uuid.uuid4()),
                    "kind": "entitlement_granted",
                    "payload": {"scope": "all", "days": 3650},
                }
            ]
        },
    )
    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json()["results"][0]["status"] == "rejected"
    assert await admin.fetchval("SELECT count(*) FROM billing.entitlements") == 0


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO billing.entitlements (learner_id, scope_kind, starts_at, ends_at, source, idempotency_key) "
        "VALUES ('a0000000-0000-4000-8000-000000000001', 'all', now(), now() + interval '10 years', 'gift', 'forged-grant-1')",
        "UPDATE billing.entitlements SET ends_at = ends_at + interval '10 years'",
        "DELETE FROM billing.entitlement_revocations",
        "SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, now(), "
        "now() + interval '30 days', 'gift', NULL, 'forged-grant-2', NULL)",
        "SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, 30, "
        "'gift', 'self service', 'forged-grant-3')",
        "SELECT billing.create_order('synthetic-all-30', 'HTG', 'mock', 'forged-order-1')",
        "SELECT billing.apply_provider_event('mock', 'forged-event', 'payment.succeeded', '{}'::jsonb)",
        "SELECT billing.erase_learner('a0000000-0000-4000-8000-000000000002')",
        "SELECT billing.learner_is_entitled_at('a0000000-0000-4000-8000-000000000002', 'all', NULL, now())",
        "SELECT * FROM billing.orders",
        "SELECT * FROM billing.provider_events",
        "SELECT * FROM billing.plan_prices",
        "SELECT idempotency_key FROM billing.entitlements",
        "INSERT INTO billing.providers (code, is_simulated, is_enabled) VALUES ('mock', true, true)",
    ],
)
async def test_even_arbitrary_sql_on_the_api_connection_cannot_touch_grants(
    app, admin: asyncpg.Pool, statement: str
) -> None:  # type: ignore[no-untyped-def]
    """Worst case: an attacker runs SQL of their choice on the API's connection."""
    await grant(admin, STUDENT_A)
    before = await admin.fetchval("SELECT count(*) FROM billing.entitlements")
    with pytest.raises(DBAPIError) as caught:
        async with app.state.db.transaction(STUDENT_A) as conn:
            await conn.execute(text(statement))
    assert getattr(caught.value.orig, "sqlstate", None) == "42501", statement
    assert await admin.fetchval("SELECT count(*) FROM billing.entitlements") == before
    assert await admin.fetchval("SELECT count(*) FROM billing.providers") == 0


async def test_the_api_role_can_ask_only_about_itself(app, admin: asyncpg.Pool) -> None:  # type: ignore[no-untyped-def]
    await grant(admin, STUDENT_B, scope_kind="grade", scope_id=SEED_GRADE)
    asked = text(
        "SELECT billing.is_entitled() AS everything, "
        "billing.is_entitled('grade', :grade) AS grade, billing.is_entitled('course', :course) AS course"
    )
    params = {"grade": SEED_GRADE, "course": SEED_COURSE}
    async with app.state.db.transaction(STUDENT_B, read_only=True) as conn:
        b = (await conn.execute(asked, params)).one()
    async with app.state.db.transaction(STUDENT_A, read_only=True) as conn:
        a = (await conn.execute(asked, params)).one()
    async with app.state.db.transaction(None, read_only=True) as conn:
        nobody = (await conn.execute(asked, params)).one()
    assert tuple(b) == (False, True, True)
    assert tuple(a) == (False, False, False)
    assert tuple(nobody) == (False, False, False)


# ------------------------------------------------ learning is never affected
async def _learning_snapshot(client: httpx.AsyncClient, token: str) -> dict[str, object]:
    """Everything a learner needs to study, as the API returns it."""
    headers = bearer(token)
    out: dict[str, object] = {}
    for name, path in [
        ("catalog_fr", "/v1/catalog?locale=fr"),
        ("catalog_ht", "/v1/catalog?locale=ht"),
        ("lesson_fr", f"/v1/lessons/{SEED_LESSON}?locale=fr"),
        ("lesson_ht", f"/v1/lessons/{SEED_LESSON}?locale=ht"),
    ]:
        response = await client.get(path, headers=headers)
        assert response.status_code == 200, (name, response.text[:200])
        out[name] = response.json()
    push = await client.post(
        "/v1/sync/push",
        headers=headers,
        json={"ops": [answer_op(SEED_QUESTIONS_FR[0][0], "b"), completed_op(SEED_REV_FR)]},
    )
    assert push.status_code == 200, push.text[:200]
    results = push.json()["results"]
    assert [r["status"] for r in results] == ["accepted", "accepted"]
    assert results[0]["result"]["is_correct"] is True
    pull = await client.get("/v1/sync/pull", headers=headers)
    assert pull.status_code == 200
    out["pulled_changes"] = len(pull.json()["changes"])
    me = await client.get("/v1/me", headers=headers)
    assert me.status_code == 200
    out["me"] = me.json()["user_id"]
    return out


async def test_learning_endpoints_are_identical_with_the_flag_on_off_and_any_grant_state(
    client: httpx.AsyncClient,
    billing_client: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    learning = "app.practice_attempts, app.sync_receipts, app.account_change_feed, app.lesson_progress, app.account_sync_state"
    token = tokens["student_a"]
    reference = await _learning_snapshot(client, token)  # flag off, no grant
    assert reference["pulled_changes"] == 2

    states = []
    await admin.execute(f"TRUNCATE {learning}")
    states.append(("flag on, no grant", await _learning_snapshot(billing_client, token)))

    entitlement = await grant(admin, STUDENT_A)
    await admin.execute(f"TRUNCATE {learning}")
    states.append(("flag on, active grant", await _learning_snapshot(billing_client, token)))
    await admin.execute(f"TRUNCATE {learning}")
    states.append(("flag off, active grant", await _learning_snapshot(client, token)))

    await revoke(admin, entitlement)
    await grant(admin, STUDENT_A, starts_in="-23 hours", lasts="22 hours")  # expired
    await admin.execute(f"TRUNCATE {learning}")
    states.append(("flag on, revoked + expired", await _learning_snapshot(billing_client, token)))
    await admin.execute(f"TRUNCATE {learning}")
    states.append(("flag off, revoked + expired", await _learning_snapshot(client, token)))

    for label, state in states:
        assert state == reference, f"learning differs when: {label}"


@asynccontextmanager
async def billing_unreachable(admin: asyncpg.Pool) -> AsyncIterator[None]:
    """Take the whole billing schema away from the student API role, and ALWAYS
    give it back (local disposable database only)."""
    await admin.execute("REVOKE USAGE ON SCHEMA billing FROM edu_api")
    try:
        yield
    finally:
        await admin.execute("GRANT USAGE ON SCHEMA billing TO edu_api")
        assert await admin.fetchval("SELECT has_schema_privilege('edu_api', 'billing', 'USAGE')")


async def test_learning_answers_normally_when_billing_is_unreachable(
    client: httpx.AsyncClient,
    local_env: dict[str, str],
    tokens: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    learning = "app.practice_attempts, app.sync_receipts, app.account_change_feed, app.lesson_progress, app.account_sync_state"
    token = tokens["student_a"]
    await grant(admin, STUDENT_A)
    reference = await _learning_snapshot(client, token)
    await admin.execute(f"TRUNCATE {learning}")

    async with billing_unreachable(admin):
        # A fresh application => fresh connections: no cached statement can
        # hide the missing privilege.
        async with entitlements_app(local_env) as application, http(application) as fresh:
            with pytest.raises(DBAPIError) as caught:
                async with application.state.db.transaction(STUDENT_A) as conn:
                    await conn.execute(text("SELECT count(*) FROM billing.entitlements"))
            assert getattr(caught.value.orig, "sqlstate", None) == "42501", (
                "billing really is unreachable"
            )

            assert await _learning_snapshot(fresh, token) == reference, (
                "flag on, billing unreachable"
            )
            ready = await fresh.get("/ready")
            assert (ready.status_code, ready.json()["status"]) == (200, "ready")

            status = await fresh.get("/v1/entitlements", headers=bearer(token))
            assert status.status_code == 503
            error = status.json()["error"]
            assert error["code"] == "entitlements_unavailable"
            assert "Free content is not affected" in error["message"]
            assert status.headers["retry-after"] == "30"
            assert "billing" not in status.text and "42501" not in status.text
            # still fails closed on identity first
            assert (await fresh.get("/v1/entitlements")).status_code == 401

        await admin.execute(f"TRUNCATE {learning}")
        assert await _learning_snapshot(client, token) == reference, "flag off, billing unreachable"

    async with entitlements_app(local_env) as application, http(application) as restored:
        back = await restored.get("/v1/entitlements", headers=bearer(token))
        assert back.status_code == 200 and len(back.json()["entitlements"]) == 1


async def test_database_outage_gives_the_standard_503(
    local_env: dict[str, str], tokens: dict[str, str]
) -> None:
    async with (
        entitlements_app(
            local_env,
            database_url="postgresql+asyncpg://edu_api_login:unused@127.0.0.1:1/postgres",
            db_connect_timeout_s=1.0,
            db_pool_timeout_s=1.0,
        ) as application,
        http(application) as client,
    ):
        response = await client.get("/v1/entitlements", headers=bearer(tokens["student_a"]))
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "dependency_unavailable"
        assert response.headers["retry-after"] == "5"
        assert "127.0.0.1" not in response.text and "edu_api_login" not in response.text


# ---------------------------------- the private schema is not in the Data API
async def test_billing_schema_is_not_reachable_through_the_supabase_data_api(
    local_env: dict[str, str], tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    entitlement = await grant(admin, STUDENT_A)
    rest = local_env["LOCAL_SUPABASE_URL"] + "/rest/v1"
    credentials = {
        "publishable key only": {"apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"]},
        "signed-in student": {
            "apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"],
            "Authorization": f"Bearer {tokens['student_a']}",
        },
        "SECRET service key": {"apikey": local_env["LOCAL_SUPABASE_SECRET_KEY"]},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        for label, headers in credentials.items():
            for table in (
                "entitlements",
                "entitlement_revocations",
                "orders",
                "provider_events",
                "plans",
                "plan_prices",
                "providers",
                "refunds",
            ):
                for profile in ({"Accept-Profile": "billing"}, {}):
                    response = await client.get(
                        f"{rest}/{table}", params={"select": "*"}, headers={**headers, **profile}
                    )
                    assert response.status_code >= 400, (label, table, profile, response.text[:200])
                    assert str(entitlement) not in response.text
                    assert "a0000000" not in response.text
                write = await client.post(
                    f"{rest}/{table}",
                    headers={**headers, "Content-Profile": "billing"},
                    json={"learner_id": str(STUDENT_A), "scope_kind": "all"},
                )
                assert write.status_code >= 400, (label, table, write.text[:200])
            for function, arguments in [
                ("is_entitled", {}),
                (
                    "grant_entitlement",
                    {
                        "p_learner_id": str(STUDENT_A),
                        "p_scope_kind": "all",
                        "p_scope_id": None,
                        "p_starts_at": "2026-01-01T00:00:00Z",
                        "p_ends_at": "2036-01-01T00:00:00Z",
                        "p_source": "gift",
                        "p_source_ref": None,
                        "p_idempotency_key": "data-api-forged-grant",
                        "p_granted_by": None,
                    },
                ),
                (
                    "staff_grant_entitlement",
                    {
                        "p_learner_id": str(STUDENT_A),
                        "p_scope_kind": "all",
                        "p_scope_id": None,
                        "p_duration_days": 30,
                        "p_source": "gift",
                        "p_reason": "data api",
                        "p_idempotency_key": "data-api-forged-staff-grant",
                    },
                ),
                (
                    "apply_provider_event",
                    {
                        "p_provider": "mock",
                        "p_provider_event_id": "data-api-forged-event",
                        "p_event_type": "payment.succeeded",
                        "p_payload": {},
                    },
                ),
            ]:
                for profile in ({"Content-Profile": "billing"}, {}):
                    rpc = await client.post(
                        f"{rest}/rpc/{function}", headers={**headers, **profile}, json=arguments
                    )
                    assert rpc.status_code >= 400, (label, function, profile, rpc.text[:200])
        exposed = (await client.get(f"{rest}/", headers=credentials["SECRET service key"])).text
    assert "entitlements" not in exposed and "provider_events" not in exposed
    assert await admin.fetchval("SELECT count(*) FROM billing.entitlements") == 1
    assert await admin.fetchval("SELECT count(*) FROM billing.provider_events") == 0


# ------------------------------------------------------------------ contract
@pytest.mark.parametrize("environment", ["local", "test", "staging", "production"])
async def test_openapi_with_the_flag_on_adds_exactly_one_read_only_route(
    local_env: dict[str, str], environment: str
) -> None:
    async with (
        entitlements_app(local_env, environment=environment) as application,
        http(application) as client,
    ):
        spec = (await client.get("/openapi.json")).json()
    assert set(spec["paths"]) == BASELINE_PATHS | {"/v1/entitlements"}, environment
    assert set(spec["paths"]["/v1/entitlements"]) == {"get"}, "read-only in every environment"
    operation = spec["paths"]["/v1/entitlements"]["get"]
    assert set(operation["responses"]) == {"200", "401", "503"}
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for status in ("401", "503"):
        assert operation["responses"][status]["content"]["application/json"]["schema"] == error_ref
    assert operation["security"] == [{"HTTPBearer": []}]
    assert "HTTPValidationError" not in spec["components"]["schemas"], "one error shape only"
    flag = spec["components"]["schemas"]["EntitlementsResponse"]["properties"][
        "free_content_always_available"
    ]
    assert flag.get("const") is True, "the contract itself says it can only be true"
    for path in spec["paths"]:
        assert not any(word in path for word in ("provider", "webhook", "mock", "order", "staff"))


async def test_a_grant_for_a_staff_account_is_just_a_grant(
    billing_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    entitlement = await grant(admin, EDITOR, source="migration")
    body = (await billing_client.get("/v1/entitlements", headers=bearer(tokens["editor"]))).json()
    assert [(item["id"], item["source"]) for item in body["entitlements"]] == [
        (str(entitlement), "migration")
    ]
