"""Run the hosted /ready policy through the real least-privilege login on a disposable DB."""

import httpx
from fastapi import FastAPI

from edu_api.db.staging import SECURITY_SQL


async def test_staging_readiness_policy(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch
) -> None:
    # The fixture engine stays bound to the verified local DB. Only switch the probe branch.
    monkeypatch.setattr(app.state.settings, "environment", "staging")
    assert (await client.get("/ready")).status_code == 200
    # Deterministic degraded dependency without modifying a shared catalog or its ACLs.
    monkeypatch.setattr("edu_api.routers.health.SECURITY_SQL", "SELECT false")
    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "unavailable"}
    assert (await client.get("/health")).status_code == 200
    assert "temp_revoked" in SECURITY_SQL
