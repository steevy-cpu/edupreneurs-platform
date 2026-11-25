"""Fixtures and helpers for the rewards lane tests.

The baseline ``app`` fixture is built with default settings (rewards OFF unless
``EDU_REWARDS_ENABLED`` is set in the environment). These fixtures build their
own applications with the flag set explicitly, so the rewards tests mean the
same thing whichever way the baseline suite is being run.
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


@pytest.fixture(scope="session")
async def rewards_app(local_env: dict[str, str]) -> AsyncIterator[FastAPI]:
    application = create_app(build_settings(local_env, rewards_enabled=True))
    yield application
    await application.state.db.dispose()


@pytest.fixture(scope="session")
async def rewards_off_app(local_env: dict[str, str]) -> AsyncIterator[FastAPI]:
    application = create_app(build_settings(local_env, rewards_enabled=False))
    yield application
    await application.state.db.dispose()


@pytest.fixture
async def on(rewards_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client for an API with EDU_REWARDS_ENABLED=true."""
    transport = httpx.ASGITransport(app=rewards_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http


@pytest.fixture
async def off(rewards_off_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client for an API with EDU_REWARDS_ENABLED=false (the default)."""
    transport = httpx.ASGITransport(app=rewards_off_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http


@pytest.fixture
async def clean_rewards(admin: asyncpg.Pool) -> None:
    """No rewards rows left over for the two synthetic students.

    Uses the real erasure hook (the ledger is append-only for everyone else).
    The integration conftest truncates the learning tables on its own.
    """
    for learner in (STUDENT_A, STUDENT_B):
        await admin.fetchval("SELECT rewards.erase_learner($1)", learner)


async def push(client: httpx.AsyncClient, token: str, ops: list[dict[str, Any]]) -> httpx.Response:
    return await client.post("/v1/sync/push", json={"ops": ops}, headers=bearer(token))


async def summary(client: httpx.AsyncClient, token: str) -> dict[str, Any]:
    response = await client.get("/v1/rewards/summary", headers=bearer(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def ledger_rows(admin: asyncpg.Pool, learner: uuid.UUID) -> list[asyncpg.Record]:
    """Canonical ledger state, read as the database owner (not through the API)."""
    rows: list[asyncpg.Record] = await admin.fetch(
        "SELECT source_key, source_kind, entry_kind, amount, source_op_id, rule_code, rule_version, "
        "accepted_day FROM rewards.ledger WHERE learner_id = $1 ORDER BY seq",
        learner,
    )
    return rows


async def ledger_total(admin: asyncpg.Pool, learner: uuid.UUID) -> tuple[int, int]:
    row = await admin.fetchrow(
        "SELECT count(*) AS n, COALESCE(sum(amount), 0) AS gold FROM rewards.ledger WHERE learner_id = $1",
        learner,
    )
    return int(row["n"]), int(row["gold"])


async def assert_balance_matches_ledger(admin: asyncpg.Pool, learner: uuid.UUID) -> int:
    """THE invariant: cached balance == sum(ledger). Returns the balance."""
    row = await admin.fetchrow(
        "SELECT COALESCE((SELECT sum(amount) FROM rewards.ledger WHERE learner_id = $1), 0) AS ledger, "
        "COALESCE((SELECT balance FROM rewards.balances WHERE learner_id = $1), 0) AS balance, "
        "(SELECT count(*) FROM (SELECT source_key FROM rewards.ledger WHERE learner_id = $1 "
        " GROUP BY source_key HAVING count(*) > 1) d) AS duplicated_keys",
        learner,
    )
    assert row["ledger"] == row["balance"], dict(row)
    assert row["duplicated_keys"] == 0, dict(row)
    return int(row["balance"])


async def unexamined(admin: asyncpg.Pool, learner: uuid.UUID) -> int:
    """Accepted operations the rewards engine has not looked at yet."""
    value: int = await admin.fetchval(
        "SELECT count(*) FROM app.sync_receipts r WHERE r.learner_id = $1 AND r.result_code = 'accepted' "
        "AND NOT EXISTS (SELECT 1 FROM rewards.processed_operations p "
        "                WHERE p.learner_id = r.learner_id AND p.op_id = r.op_id)",
        learner,
    )
    return value
