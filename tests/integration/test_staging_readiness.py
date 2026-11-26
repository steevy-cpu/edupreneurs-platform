"""Run the hosted /ready policy through the real least-privilege login on a disposable DB."""

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from staging_verify import check_session, versions


async def test_staging_readiness_policy(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch
) -> None:
    # The fixture engine stays bound to the verified local DB. Only switch the probe branch.
    monkeypatch.setattr(app.state.settings, "environment", "staging")
    assert (await client.get("/ready")).status_code == 200
    # Deterministic degraded dependency without modifying a shared catalog or its ACLs.
    monkeypatch.setattr("edu_api.db.staging.SECURITY_SQL", "SELECT false")
    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "unavailable"}
    assert (await client.get("/health")).status_code == 200
    with pytest.raises(ValueError, match="invariants"):
        async with app.router.lifespan_context(app):
            pytest.fail("unsafe staging startup was accepted")


async def test_metadata_reader_can_audit_without_application_data(admin: asyncpg.Pool) -> None:
    async with admin.acquire() as db:
        tx = db.transaction()
        await tx.start()
        try:
            await db.execute("CREATE ROLE edu_staging_auditor LOGIN")
            await db.execute("GRANT USAGE ON SCHEMA supabase_migrations TO edu_staging_auditor")
            await db.execute(
                "GRANT SELECT(version) ON supabase_migrations.schema_migrations TO edu_staging_auditor"
            )
            # PG17 gives a CREATEROLE creator ADMIN, but not necessarily SET membership.
            # Only the test operator assumes the narrow role, inside this rolled-back fixture.
            await db.execute("GRANT edu_staging_auditor TO CURRENT_USER WITH SET TRUE")
            await db.execute("SET LOCAL ROLE edu_staging_auditor")
            await check_session(db, "edu_staging_auditor", versions())
        finally:
            await tx.rollback()


@pytest.mark.parametrize(
    ("grant", "to_role"),
    [
        ("UPDATE", "edu_staging_auditor"),
        ("INSERT(version)", "PUBLIC"),
        ("DELETE", "PUBLIC"),
        ("REFERENCES(version)", "edu_staging_auditor"),
        ("TRUNCATE", "fixture_ledger_parent"),
    ],
)
async def test_effective_auditor_privilege_sources(admin, grant, to_role):
    async with admin.acquire() as db:
        tx = db.transaction()
        await tx.start()
        try:
            await db.execute("CREATE ROLE edu_staging_auditor LOGIN")
            await db.execute("GRANT USAGE ON SCHEMA supabase_migrations TO edu_staging_auditor")
            ledger = "supabase_migrations.schema_migrations"
            await db.execute(f"GRANT SELECT(version) ON {ledger} TO edu_staging_auditor")
            if to_role == "fixture_ledger_parent":
                await db.execute("CREATE ROLE fixture_ledger_parent")
                await db.execute("GRANT fixture_ledger_parent TO edu_staging_auditor")
            await db.execute(f"GRANT {grant} ON {ledger} TO {to_role}")
            await db.execute("GRANT edu_staging_auditor TO CURRENT_USER WITH SET TRUE")
            await db.execute("SET LOCAL ROLE edu_staging_auditor")
            if "(" in grant:
                assert await db.fetchval(
                    "SELECT has_column_privilege(current_user, $1, 'version', $2)",
                    ledger,
                    grant.split("(")[0],
                )
            else:
                assert await db.fetchval(
                    "SELECT has_table_privilege(current_user, $1, $2)", ledger, grant
                )
            with pytest.raises(ValueError, match="audit login privileges"):
                await check_session(db, "edu_staging_auditor", versions(), plan=True)
        finally:
            await tx.rollback()


async def test_http_readiness_requires_catalog_select(admin, app, client, monkeypatch):
    # The independent HTTP session must observe the ACL change. This suite runs serially
    # on the verified disposable database containing the exact migration grant.
    monkeypatch.setattr(app.state.settings, "environment", "staging")
    assert (await client.get("/ready")).status_code == 200
    async with admin.acquire() as db:
        try:
            await db.execute("REVOKE SELECT ON app.courses FROM edu_api")
            response = await client.get("/ready")
            assert response.status_code == 503
            assert response.json()["checks"] == {"database": "unavailable"}
            assert (await client.get("/health")).status_code == 200
        finally:
            await db.execute("GRANT SELECT ON app.courses TO edu_api")
    assert (await client.get("/ready")).status_code == 200
