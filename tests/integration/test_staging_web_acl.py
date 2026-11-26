"""Effective PG17 rights on the verified disposable database. No privilege is delegated."""

import pytest
from sqlalchemy import text

from edu_api.db.staging import SECURITY_SQL
from edu_api.main import create_app
from staging_verify import check_session, versions


@pytest.mark.parametrize(
    ("grant", "effective", "failed_check"),
    [
        (
            "MAINTAIN ON app.lessons TO edu_api",
            "has_table_privilege('edu_api_login', 'app.lessons', 'MAINTAIN')",
            "private_tables",
        ),
        (
            "MAINTAIN ON app.lessons TO PUBLIC",
            "has_table_privilege('edu_api_login', 'app.lessons', 'MAINTAIN')",
            "private_tables",
        ),
        (
            "SELECT ON app.lessons TO edu_api WITH GRANT OPTION",
            "has_table_privilege('edu_api_login', 'app.lessons', 'SELECT WITH GRANT OPTION')",
            "web_cannot_delegate",
        ),
        (
            "SELECT(id) ON app.lessons TO edu_api_login WITH GRANT OPTION",
            "has_column_privilege('edu_api_login', 'app.lessons', 'id', 'SELECT WITH GRANT OPTION')",
            "web_cannot_delegate",
        ),
        (
            "INSERT(user_id) ON app.learner_profiles TO edu_api WITH GRANT OPTION",
            "has_column_privilege('edu_api_login', 'app.learner_profiles', 'user_id', 'INSERT WITH GRANT OPTION')",
            "web_cannot_delegate",
        ),
        (
            "CONNECT ON DATABASE postgres TO edu_api_login WITH GRANT OPTION",
            "has_database_privilege('edu_api_login', current_database(), 'CONNECT WITH GRANT OPTION')",
            "web_cannot_delegate",
        ),
        (
            "USAGE ON SCHEMA app TO edu_api WITH GRANT OPTION",
            "has_schema_privilege('edu_api_login', 'app', 'USAGE WITH GRANT OPTION')",
            "web_cannot_delegate",
        ),
        (
            "EXECUTE ON FUNCTION app.current_actor_id() TO edu_api WITH GRANT OPTION",
            "has_function_privilege('edu_api_login', 'app.current_actor_id()', 'EXECUTE WITH GRANT OPTION')",
            "web_cannot_delegate",
        ),
    ],
)
async def test_effective_acl_blocks_release(admin, grant, effective, failed_check):
    expected = versions()
    async with admin.acquire() as db:
        await check_session(db, "postgres", expected)
        tx = db.transaction()
        await tx.start()
        try:
            await db.execute(f"GRANT {grant}")
            assert await db.fetchval(f"SELECT {effective}")
            policy = await db.fetchrow(SECURITY_SQL)
            assert [name for name, ok in policy.items() if not ok] == [failed_check]
            with pytest.raises(ValueError, match=failed_check):
                await check_session(db, "postgres", expected)
        finally:
            await tx.rollback()
        await check_session(db, "postgres", expected)


@pytest.mark.parametrize(
    ("grant", "revoke"),
    [
        (
            "GRANT MAINTAIN ON app.courses TO edu_api_login",
            "REVOKE MAINTAIN ON app.courses FROM edu_api_login",
        ),
        (
            "GRANT SELECT ON app.courses TO edu_api WITH GRANT OPTION",
            "REVOKE GRANT OPTION FOR SELECT ON app.courses FROM edu_api",
        ),
    ],
)
async def test_web_acl_readiness_and_startup(
    admin, client, app, settings, monkeypatch, grant, revoke
):
    # Both HTTP and startup use their own connections, so grant changes must be
    # committed on this serial, checkout-bound disposable database.
    probe = create_app(settings.model_copy())
    probe.state.settings.environment = "staging"
    monkeypatch.setattr(app.state.settings, "environment", "staging")
    assert (await client.get("/ready")).status_code == 200
    async with admin.acquire() as db:
        await db.execute(grant)
        try:
            failed = await client.get("/ready")
            assert failed.status_code == 503
            assert failed.json() == {"status": "not_ready", "checks": {"database": "unavailable"}}
            live = await client.get("/health")
            assert live.status_code == 200 and live.json() == {"status": "ok"}
            with pytest.raises(ValueError, match="database staging invariants failed"):
                async with probe.router.lifespan_context(probe):
                    pytest.fail("startup admitted the overprivileged web login")
        finally:
            await db.execute(revoke)
    async with (
        probe.router.lifespan_context(probe),
        probe.state.db.transaction(None, read_only=True) as conn,
    ):
        assert await conn.scalar(text("SELECT current_user")) == "edu_api_login"
        await conn.execute(text("SELECT id FROM app.courses LIMIT 1"))
        assert await conn.scalar(
            text(
                "SELECT has_column_privilege(current_user, 'app.learner_profiles', 'user_id', 'INSERT')"
            )
        )
    ready = await client.get("/ready")
    assert ready.status_code == 200 and ready.json()["status"] == "ready"
