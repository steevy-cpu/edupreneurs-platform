"""Fixtures and helpers for the leaderboard lane tests.

Applications are built with the flags set explicitly, so the tests mean the
same thing whatever ``EDU_*`` variables the surrounding shell exports. Cohorts,
memberships and refreshes are arranged with the admin pool through the
schema's own functions (there is no learner or staff route for them yet).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from edu_api.main import create_app
from tests.conftest import build_settings
from tests.helpers import STUDENT_A, STUDENT_B, bearer

ME = "/v1/leaderboard/me"


@pytest.fixture(scope="session")
async def leaderboard_app(local_env: dict[str, str]) -> AsyncIterator[FastAPI]:
    """Rewards ON (so pushes earn Gold) and the private-standing flag ON."""
    application = create_app(
        build_settings(local_env, rewards_enabled=True, leaderboard_enabled=True)
    )
    yield application
    await application.state.db.dispose()


@pytest.fixture(scope="session")
async def leaderboard_off_app(local_env: dict[str, str]) -> AsyncIterator[FastAPI]:
    """Rewards ON, leaderboard OFF (the default)."""
    application = create_app(
        build_settings(local_env, rewards_enabled=True, leaderboard_enabled=False)
    )
    yield application
    await application.state.db.dispose()


@pytest.fixture
async def lb(leaderboard_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=leaderboard_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http


@pytest.fixture
async def lb_off(leaderboard_off_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=leaderboard_off_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http


async def _wipe(admin: asyncpg.Pool) -> None:
    await admin.execute(
        "DELETE FROM leaderboard.snapshots; DELETE FROM leaderboard.snapshot_runs; "
        "DELETE FROM leaderboard.memberships; DELETE FROM leaderboard.cohorts; "
        "DELETE FROM leaderboard.periods"
    )
    for learner in (STUDENT_A, STUDENT_B):
        await admin.fetchval("SELECT rewards.erase_learner($1)", learner)


@pytest.fixture
async def clean_leaderboard(admin: asyncpg.Pool) -> AsyncIterator[None]:
    """No leaderboard row and no Gold for the two synthetic students, before and after."""
    await _wipe(admin)
    yield
    await _wipe(admin)


async def make_cohort(admin: asyncpg.Pool, kind: str = "class") -> uuid.UUID:
    cohort_id: uuid.UUID = await admin.fetchval(
        "INSERT INTO leaderboard.cohorts (kind, code) VALUES ($1, $2) RETURNING id",
        kind,
        f"synthetic-{uuid.uuid4().hex[:12]}",
    )
    return cohort_id


async def enroll(admin: asyncpg.Pool, cohort_id: uuid.UUID, learner: uuid.UUID) -> str:
    """Opt a learner in; returns the pseudonym the server assigned."""
    pseudonym: str = await admin.fetchval(
        "SELECT leaderboard.enroll($1, $2) ->> 'pseudonym'", cohort_id, learner
    )
    return pseudonym


async def refresh(admin: asyncpg.Pool, cohort_id: uuid.UUID, period: str = "week") -> None:
    await admin.fetchval("SELECT leaderboard.refresh_snapshot($1, $2)", cohort_id, period)


async def push(client: httpx.AsyncClient, token: str, ops: list[dict[str, Any]]) -> httpx.Response:
    return await client.post("/v1/sync/push", json={"ops": ops}, headers=bearer(token))


async def me(client: httpx.AsyncClient, token: str, period: str | None = None) -> dict[str, Any]:
    params = {} if period is None else {"period": period}
    response = await client.get(ME, params=params, headers=bearer(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body
