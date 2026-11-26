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
