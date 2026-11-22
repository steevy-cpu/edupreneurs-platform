"""Connection-pool identity isolation, database role, outage behaviour, Data API exposure, contract."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import asyncpg
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from edu_api.db.session import Database, build_engine
from edu_api.main import create_app
from tests.conftest import build_settings
from tests.helpers import SEED_QUESTIONS_FR, STUDENT_A, STUDENT_B, answer_op, bearer

pytestmark = pytest.mark.integration
ACTOR_NOW = text(
    "SELECT current_setting('edu.actor_id', true) AS raw, app.current_actor_id() AS actor, "
    "pg_backend_pid() AS pid, current_user AS role"
)


# ------------------------------------------------ transaction-local actor context
async def test_actor_is_cleared_between_transactions_on_one_connection(
    local_env: dict[str, str],
) -> None:
    """A pool of exactly ONE connection: every request reuses the same backend."""
    db = Database(build_engine(build_settings(local_env, db_pool_size=1, db_max_overflow=0)))
    try:
        async with db.transaction(STUDENT_A) as conn:
            a = (await conn.execute(ACTOR_NOW)).one()
            a_profiles = (
                (await conn.execute(text("SELECT user_id FROM app.learner_profiles")))
                .scalars()
                .all()
            )
        async with db.transaction(None) as conn:
            nobody = (await conn.execute(ACTOR_NOW)).one()
            nobody_profiles = (
                await conn.execute(text("SELECT count(*) FROM app.learner_profiles"))
            ).scalar_one()
        async with db.transaction(STUDENT_B) as conn:
            b = (await conn.execute(ACTOR_NOW)).one()
            b_profiles = (
                (await conn.execute(text("SELECT user_id FROM app.learner_profiles")))
                .scalars()
                .all()
            )

        assert a.pid == nobody.pid == b.pid, "the same pooled connection served all three"
        assert (a.actor, a_profiles) == (STUDENT_A, [STUDENT_A])
        assert nobody.actor is None and nobody.raw in ("", None) and nobody_profiles == 0
        assert (b.actor, b_profiles) == (STUDENT_B, [STUDENT_B])
        assert a.role == b.role == "edu_api_login"

        # rollback path: an error inside the transaction must clear the actor too
        with pytest.raises(DBAPIError):
            async with db.transaction(STUDENT_A) as conn:
                await conn.execute(text("SELECT 1/0"))
        with pytest.raises(RuntimeError, match="boom"):
            async with db.transaction(STUDENT_A) as conn:
                await conn.execute(text("SELECT 1"))
                raise RuntimeError("boom")
        async with db.transaction(None) as conn:
            after = (await conn.execute(ACTOR_NOW)).one()
        assert after.pid == a.pid and after.actor is None

        # read-only transactions really are read-only
        with pytest.raises(DBAPIError):
            async with db.transaction(STUDENT_A, read_only=True) as conn:
                await conn.execute(
                    text("INSERT INTO app.learner_profiles (user_id) VALUES (:u)"), {"u": STUDENT_A}
                )
    finally:
        await db.dispose()


async def test_account_switch_over_a_single_pooled_connection(
    local_env: dict[str, str], tokens: dict[str, str]
) -> None:
    application = create_app(build_settings(local_env, db_pool_size=1, db_max_overflow=0))
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
            await http.post(
                "/v1/sync/push",
                headers=bearer(tokens["student_a"]),
                json={"ops": [answer_op(SEED_QUESTIONS_FR[0][0], "b")]},
            )
            order = ["student_a", "student_b", "student_a", "student_b", "student_b", "student_a"]
            for who in order:
                me = (await http.get("/v1/me", headers=bearer(tokens[who]))).json()
                feed = (await http.get("/v1/sync/pull", headers=bearer(tokens[who]))).json()
                assert me["user_id"] == str(STUDENT_A if who == "student_a" else STUDENT_B)
                assert len(feed["changes"]) == (1 if who == "student_a" else 0), who
            # a rejected (401) request in between must not inherit anything either
            assert (await http.get("/v1/sync/pull")).status_code == 401
            # interleaved concurrent requests of both accounts through the one connection
            mixed = await asyncio.gather(
                *(http.get("/v1/sync/pull", headers=bearer(tokens[who])) for who in order * 5)
            )
            for who, response in zip(order * 5, mixed, strict=True):
                assert len(response.json()["changes"]) == (1 if who == "student_a" else 0)
        async with application.state.db.transaction(None) as conn:
            leftover = (await conn.execute(ACTOR_NOW)).one()
        assert leftover.actor is None, "no identity is left on the pooled connection"
    finally:
        await application.state.db.dispose()


# ----------------------------------------------------------- the API's DB role
async def test_api_connects_with_a_least_privilege_role(app, admin: asyncpg.Pool) -> None:  # type: ignore[no-untyped-def]
    async with app.state.db.transaction(None) as conn:
        who = (await conn.execute(text("SELECT current_user AS u, session_user AS s"))).one()
    assert (who.u, who.s) == ("edu_api_login", "edu_api_login")
    role = await admin.fetchrow(
        "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication FROM pg_roles WHERE rolname = 'edu_api_login'"
    )
    assert not any(role.values()), dict(role)
    memberships = await admin.fetch(
        "SELECT g.rolname FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid "
        "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = 'edu_api_login'"
    )
    assert [m["rolname"] for m in memberships] == ["edu_api"]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE app.practice_attempts SET score = 1",
        "INSERT INTO app.account_change_feed (learner_id, version, entity_type, entity_id, change_data) "
        "VALUES ('a0000000-0000-4000-8000-000000000001', 1, 'practice_attempt', gen_random_uuid(), '{}')",
        "UPDATE app.account_sync_state SET current_version = 0",
        "INSERT INTO app.audit_events (actor_kind, action, outcome) VALUES ('system', 'forged', 'allowed')",
        "SELECT * FROM app.staff_roles",
        "SELECT * FROM auth.users",
        "SET ROLE postgres",
        "SET ROLE service_role",
        "CREATE TABLE public.exfil (x int)",
        "ALTER TABLE app.practice_attempts DISABLE ROW LEVEL SECURITY",
        "SELECT app.revision_is_syncable('c0000000-0000-4000-8000-000000000001')",
    ],
)
async def test_even_arbitrary_sql_on_the_api_connection_cannot_forge_state(
    app, statement: str
) -> None:  # type: ignore[no-untyped-def]
    """Worst case: an attacker can run SQL of their choice on the API's connection."""
    with pytest.raises(DBAPIError) as caught:
        async with app.state.db.transaction(STUDENT_A) as conn:
            await conn.execute(text(statement))
    assert getattr(caught.value.orig, "sqlstate", None) == "42501", statement


# ------------------------------------------------------------------- outages
async def test_database_outage_has_clear_error_behaviour(
    local_env: dict[str, str], tokens: dict[str, str]
) -> None:
    dead = build_settings(
        local_env,
        database_url="postgresql+asyncpg://edu_api_login:unused@127.0.0.1:1/postgres",
        db_connect_timeout_s=1.0,
        db_pool_timeout_s=1.0,
    )
    application = create_app(dead)
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
            assert (await http.get("/health")).json() == {"status": "ok"}
            ready = await http.get("/ready")
            assert ready.status_code == 503
            assert ready.json() == {"status": "not_ready", "checks": {"database": "unavailable"}}
            for method, path, kwargs in [
                ("GET", "/v1/me", {}),
                ("GET", "/v1/catalog?locale=fr", {}),
                ("GET", "/v1/sync/pull", {}),
                (
                    "POST",
                    "/v1/sync/push",
                    {"json": {"ops": [answer_op(SEED_QUESTIONS_FR[0][0], "b")]}},
                ),
            ]:
                response = await http.request(
                    method, path, headers=bearer(tokens["student_a"]), **kwargs
                )
                assert response.status_code == 503, path
                error = response.json()["error"]
                assert (
                    error["code"] == "dependency_unavailable"
                    and response.headers["retry-after"] == "5"
                )
                assert "127.0.0.1" not in response.text and "edu_api_login" not in response.text
            # authentication still fails closed before any database work
            assert (await http.get("/v1/me")).status_code == 401
    finally:
        await application.state.db.dispose()


async def test_auth_key_service_outage_fails_closed(
    local_env: dict[str, str], tokens: dict[str, str]
) -> None:
    application = create_app(
        build_settings(local_env, auth_jwks_url="http://127.0.0.1:1/jwks.json")
    )
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
            response = await http.get("/v1/me", headers=bearer(tokens["student_a"]))
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "dependency_unavailable"
    finally:
        await application.state.db.dispose()
        await application.state.token_verifier._keys.aclose()


async def test_ready_when_database_is_up(client: httpx.AsyncClient) -> None:
    response = await client.get("/ready")
    assert (response.status_code, response.json()) == (
        200,
        {"status": "ready", "checks": {"database": "ok"}},
    )


# -------------------------------- the private schema is not in the Data API
async def test_app_schema_is_not_reachable_through_the_supabase_data_api(
    local_env: dict[str, str], tokens: dict[str, str]
) -> None:
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
            for table in (
                "learner_profiles",
                "practice_attempts",
                "lesson_revisions",
                "question_revisions",
                "staff_roles",
            ):
                for profile in ({"Accept-Profile": "app"}, {}):
                    response = await http.get(
                        f"{rest}/{table}", params={"select": "*"}, headers={**headers, **profile}
                    )
                    assert response.status_code >= 400, (label, table, profile, response.text[:200])
                    assert "a0000000" not in response.text
            rpc = await http.post(
                f"{rest}/rpc/sync_apply_operation",
                headers={**headers, "Content-Profile": "app"},
                json={
                    "p_op_id": str(uuid.uuid4()),
                    "p_kind": "lesson_completed",
                    "p_payload": {},
                    "p_payload_sha256": "\\x00",
                    "p_canon_version": "x",
                },
            )
            assert rpc.status_code >= 400, (label, rpc.text[:200])
        exposed = (await http.get(f"{rest}/", headers=credentials["SECRET service key"])).text
    assert "learner_profiles" not in exposed and "practice_attempts" not in exposed


# ------------------------------------------------------------------ contract
async def test_openapi_contract(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    assert set(spec["paths"]) == {
        "/health",
        "/ready",
        "/v1/me",
        "/v1/catalog",
        "/v1/lessons/{lesson_id}",
        "/v1/sync/push",
        "/v1/sync/pull",
    }
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for path, operations in spec["paths"].items():
        for operation in operations.values():
            for status, response in operation["responses"].items():
                if path.startswith("/v1") and status != "200":
                    assert response["content"]["application/json"]["schema"] == error_ref, (
                        path,
                        status,
                    )
            if path.startswith("/v1"):
                assert operation["security"] == [{"HTTPBearer": []}], path
    assert "HTTPValidationError" not in spec["components"]["schemas"], "one error shape only"

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import export_openapi

    assert export_openapi.TARGET.read_text(encoding="utf-8") == export_openapi.render(), (
        "packages/contracts/openapi.json is stale; run `make openapi`"
    )
