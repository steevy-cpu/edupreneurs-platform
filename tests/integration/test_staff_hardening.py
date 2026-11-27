"""Hardening after the security review of B1: no temporary objects for API
logins (pg_temp shadowing), a staff pool that proves it is a staff login, and
refusals that never turn into 500s."""

# ruff: noqa: F811  (fixtures imported from tests.staff_fixtures are requested by name)
from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

import asyncpg
import httpx
import pytest
from fastapi import Depends

from edu_api.main import create_app
from edu_api.staff.deps import StaffPrincipal, require_staff
from tests.helpers import EDITOR, STUDENT_A, bearer
from tests.staff_fixtures import (  # noqa: F401
    build_staff_settings,
    create_account,
    dispose_app,
    remove_account,
    reset_denial_windows,
    staff_app,
    staff_client,
    staff_settings,
    staff_tokens,
    staff_url,
    worker_url,
)

pytestmark = pytest.mark.integration


def login_urls(env: dict[str, str]) -> dict[str, str]:
    return {
        "edu_api_login": env["EDU_DATABASE_URL"].replace(
            "postgresql+asyncpg://", "postgresql://", 1
        ),
        "edu_staff_login": staff_url(env),
        "edu_worker_login": worker_url(env),
    }


LOGINS = ("edu_api_login", "edu_staff_login", "edu_worker_login")

TEMP_OBJECTS = [
    "CREATE TEMP TABLE loot (x int)",
    "CREATE TEMPORARY VIEW loot_view AS SELECT 1 AS x",
    "CREATE TEMP SEQUENCE loot_seq",
    "CREATE DOMAIN pg_temp.text AS pg_catalog.text",
    "CREATE DOMAIN pg_temp.uuid AS pg_catalog.uuid",
    "CREATE DOMAIN pg_temp.jsonb AS pg_catalog.jsonb",
    "CREATE TYPE pg_temp.text AS (x int)",
    "CREATE FUNCTION pg_temp.evil(v pg_catalog.text) RETURNS pg_catalog.bool LANGUAGE sql AS 'SELECT true'",
    "CREATE TABLE pg_temp.loot (x int)",
    "SELECT 1 INTO TEMP loot",
]


@pytest.mark.parametrize("login", LOGINS)
async def test_api_logins_cannot_create_temporary_objects(
    local_env: dict[str, str], login: str
) -> None:
    """Without temporary objects there is nothing to shadow a type name with."""
    conn = await asyncpg.connect(login_urls(local_env)[login], timeout=10)
    try:
        assert await conn.fetchval("SELECT session_user") == login
        assert (
            await conn.fetchval("SELECT has_database_privilege(current_database(), 'TEMP')")
            is False
        )
        for statement in TEMP_OBJECTS:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(statement)
        assert (
            await conn.fetchval("SELECT count(*) FROM pg_namespace WHERE oid = pg_my_temp_schema()")
            == 0
        )
        for statement in (
            "SET SESSION AUTHORIZATION postgres",
            "SET SESSION AUTHORIZATION edu_staff_login",
        ):
            if statement.endswith(login):
                continue
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(statement)
    finally:
        await conn.close()


async def test_the_type_shadowing_attack_of_the_review_no_longer_works(
    local_env: dict[str, str], admin: asyncpg.Pool
) -> None:
    """The reviewer's reproduction, step by step, as each real login: every step
    that would plant the payload is refused, the definer functions still work,
    and the learner used as actor gains nothing."""
    roles_before = await admin.fetchval("SELECT count(*) FROM app.staff_roles")
    payload = [
        "CREATE TEMP TABLE loot (who text, n bigint)",
        "CREATE FUNCTION pg_temp.evil(v pg_catalog.text) RETURNS pg_catalog.bool LANGUAGE plpgsql AS "
        f"$$ BEGIN INSERT INTO app.staff_roles (user_id, role) VALUES ('{STUDENT_A}', 'admin'); RETURN true; END $$",
        "CREATE DOMAIN pg_temp.text AS pg_catalog.text CHECK (pg_temp.evil(VALUE))",
        "CREATE DOMAIN pg_temp.uuid AS pg_catalog.uuid CHECK (pg_temp.evil(VALUE::pg_catalog.text))",
    ]
    carriers = {
        "edu_api_login": "SELECT app.sync_apply_operation(gen_random_uuid(), 'lesson_completed', "
        "'{\"lesson_revision_id\":\"c0000000-0000-4000-8000-000000000001\"}', sha256('x'), 'mep-canon-1') ->> 'status'",
        "edu_staff_login": "SELECT ops.audit_write('test_fixture.probe', NULL, NULL, 'allowed', '{}')::text",
        "edu_worker_login": "SELECT ops.audit_write('test_fixture.probe', NULL, NULL, 'allowed', '{}')::text",
    }
    for login, url in login_urls(local_env).items():
        conn = await asyncpg.connect(url, timeout=10)
        try:
            for statement in payload:
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await conn.execute(statement)
            async with conn.transaction():
                await conn.execute("SELECT set_config('edu.actor_id', $1, true)", str(STUDENT_A))
                assert await conn.fetchval(carriers[login]) is not None, (
                    "the function itself still works"
                )
                if login == "edu_staff_login":
                    assert await conn.fetchval("SELECT staff.actor_roles()") == []
                    with pytest.raises(asyncpg.InsufficientPrivilegeError):
                        await conn.execute("SELECT staff.require_role('admin')")
        finally:
            await conn.close()
    assert await admin.fetchval("SELECT count(*) FROM app.staff_roles") == roles_before
    assert (
        await admin.fetchval("SELECT count(*) FROM app.staff_roles WHERE user_id = $1", STUDENT_A)
        == 0
    )


async def test_auth_and_the_learner_api_still_work_without_temp_privilege(
    client: httpx.AsyncClient, local_env: dict[str, str], admin: asyncpg.Pool
) -> None:
    """The revoke is database-wide: the Auth service must still create accounts
    and issue tokens, and the learner API must still serve them."""
    holders = await admin.fetch(
        "SELECT rolname FROM pg_roles WHERE has_database_privilege(rolname, current_database(), 'TEMP') "
        "AND NOT rolsuper ORDER BY 1"
    )
    assert {row["rolname"] for row in holders} <= {"postgres", "dashboard_user"}, holders
    user_id, _, token = await create_account(local_env)
    try:
        me = await client.get("/v1/me", headers=bearer(token))
        assert (me.status_code, me.json()["user_id"]) == (200, str(user_id))
        catalog = await client.get("/v1/catalog", params={"locale": "fr"}, headers=bearer(token))
        assert catalog.status_code == 200 and catalog.json()["courses"]
    finally:
        await remove_account(admin, local_env, user_id)


# ------------------------------------------------ a refusal never becomes a 500
async def test_a_route_with_unusual_characters_is_still_refused_and_audited(
    local_env: dict[str, str], tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    await reset_denial_windows(admin, STUDENT_A)
    application = create_app(build_staff_settings(local_env))

    @application.get("/v1/staff/probe/odd~route/{thing}")
    async def odd(
        thing: str, staff: Annotated[StaffPrincipal, Depends(require_staff("admin"))]
    ) -> dict[str, Any]:
        return {}

    before = await admin.fetchval(
        "SELECT count(*) FROM app.audit_events WHERE actor_id = $1 AND outcome = 'denied'",
        STUDENT_A,
    )
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
            for thing in ("plain", "with space", "é", "a" * 200, "x;DROP TABLE y"):
                await reset_denial_windows(admin, STUDENT_A)
                response = await http.get(
                    f"/v1/staff/probe/odd~route/{thing}", headers=bearer(tokens["student_a"])
                )
                assert response.status_code == 403, (thing, response.text)
                assert response.json()["error"]["code"] == "forbidden"
    finally:
        await dispose_app(application)
    rows = await admin.fetch(
        "SELECT details FROM app.audit_events WHERE actor_id = $1 AND outcome = 'denied' "
        "ORDER BY created_at DESC, id LIMIT 5",
        STUDENT_A,
    )
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.audit_events WHERE actor_id = $1 AND outcome = 'denied'",
            STUDENT_A,
        )
        == before + 5
    ), "every refusal was recorded"
    assert {json.loads(row["details"])["route"] for row in rows} == {"unknown"}


# ------------------------------------- the staff pool must be a staff login
def _asyncpg_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


async def _staff_me(
    local_env: dict[str, str], token: str, **overrides: Any
) -> list[httpx.Response]:
    application = create_app(
        build_staff_settings(
            local_env, db_connect_timeout_s=2.0, db_pool_timeout_s=2.0, **overrides
        )
    )
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
            return [
                await http.get("/v1/staff/me", headers=bearer(token)),
                await http.get("/v1/staff/me", headers=bearer(token)),
                await http.get("/v1/staff/revisions", headers=bearer(token)),
                await http.get("/v1/me", headers=bearer(token)),
            ]
    finally:
        await dispose_app(application)


@pytest.mark.parametrize(
    ("which", "code"),
    [
        ("wrong password", "dependency_unavailable"),
        ("student login", "staff_unavailable"),
        ("worker login", "staff_unavailable"),
        ("database owner", "staff_unavailable"),
    ],
)
async def test_a_staff_pool_with_the_wrong_login_refuses_to_work(
    local_env: dict[str, str],
    staff_tokens: dict[str, str],
    admin: asyncpg.Pool,
    which: str,
    code: str,
) -> None:
    good = local_env["EDU_STAFF_DATABASE_URL"]
    host = good.rsplit("@", 1)[1]
    url = {
        "wrong password": f"postgresql+asyncpg://edu_staff_login:{uuid.uuid4().hex}@{host}",
        "student login": local_env["EDU_DATABASE_URL"],
        "worker login": local_env["EDU_WORKER_DATABASE_URL"],
        "database owner": _asyncpg_url(local_env["LOCAL_ADMIN_DATABASE_URL"]),
    }[which]
    audit_before = await admin.fetchval("SELECT count(*) FROM app.audit_events")
    *staff_responses, learner = await _staff_me(
        local_env, staff_tokens["editor"], staff_database_url=url
    )
    for response in staff_responses:
        assert response.status_code == 503, (which, response.text)
        assert response.json()["error"]["code"] == code
        assert (
            "edu_" not in response.text
            and "127.0.0.1" not in response.text
            and "password" not in response.text
        )
    assert (learner.status_code, learner.json()["user_id"]) == (200, str(EDITOR)), (
        "the learner side is unaffected"
    )
    assert await admin.fetchval("SELECT count(*) FROM app.audit_events") == audit_before, (
        "a wrongly configured pool wrote nothing, under any attribution"
    )


async def test_the_real_staff_pool_reports_session_kind_staff(
    staff_app, local_env: dict[str, str]
) -> None:  # type: ignore[no-untyped-def]
    async with staff_app.state.staff_db.transaction(None, read_only=True) as conn:
        from sqlalchemy import text

        assert (await conn.execute(text("SELECT ops.session_kind()"))).scalar_one() == "staff"
    worker = await asyncpg.connect(worker_url(local_env), timeout=10)
    try:
        assert await worker.fetchval("SELECT ops.session_kind()") == "worker"
    finally:
        await worker.close()
