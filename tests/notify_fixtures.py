"""Fixtures for the notify lane (loaded with ``pytest_plugins`` by its test modules).

Nothing is mocked: real local Auth tokens, the real local PostgreSQL, the API's
own least-privileged login. ``admin`` (the local owner) is used only to arrange
state and to stand in for server-side producers. The delivery worker uses its own
real login (``worker_engine``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from edu_api.config import Settings
from edu_api.main import create_app
from tests.conftest import build_settings

NOTIFY_TABLES = "notify.delivery_attempts, notify.deliveries, notify.outbox, notify.preferences"
_RESET_POLICY = (
    "UPDATE notify.policy SET quiet_start = '21:00', quiet_end = '06:00', max_attempts = 5, "
    "backoff_base_seconds = 60, backoff_cap_seconds = 3600"
)

Enqueue = Callable[..., Awaitable[uuid.UUID]]


@pytest.fixture(scope="session")
def notify_settings(local_env: dict[str, str]) -> Settings:
    return build_settings(local_env, notifications_enabled=True)


@pytest.fixture(scope="session")
async def notify_app(notify_settings: Settings) -> AsyncIterator[FastAPI]:
    """The API with ``EDU_NOTIFICATIONS_ENABLED=true`` (the default app has it off)."""
    application = create_app(notify_settings)
    yield application
    await application.state.db.dispose()
    await application.state.notify_db.dispose()


@pytest.fixture
async def clean_notify_state(admin: asyncpg.Pool) -> AsyncIterator[None]:
    """Empty notify tables and the default policy, before AND after the test, so
    the pgTAP suite and other tests always find the state the migration left."""
    await admin.execute(f"TRUNCATE {NOTIFY_TABLES}")
    await admin.execute(_RESET_POLICY)
    yield
    await admin.execute(f"TRUNCATE {NOTIFY_TABLES}")
    await admin.execute(_RESET_POLICY)


@pytest.fixture
async def notify_client(
    notify_app: FastAPI, clean_notify_state: None
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=notify_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http


@pytest.fixture
def enqueue(admin: asyncpg.Pool, clean_notify_state: None) -> Enqueue:
    """SEAM(notify-producer): stands in for server-side producers (vocab, billing, ...),
    which will call ``notify.enqueue`` from their own definer functions. It runs as
    the database owner because the function is executable by nobody else."""

    async def _enqueue(
        recipient: uuid.UUID,
        kind: str,
        refs: str = "{}",
        dedupe_key: str | None = None,
        channels: tuple[str, ...] = ("in_app",),
        **extra: Any,
    ) -> uuid.UUID:
        columns = "".join(f", p_{name} => ${index}" for index, name in enumerate(extra, start=6))
        result: uuid.UUID = await admin.fetchval(
            f"SELECT notify.enqueue($1, $2, $3::jsonb, $4, $5::text[]{columns})",
            recipient,
            kind,
            refs,
            dedupe_key or uuid.uuid4().hex,
            list(channels),
            *extra.values(),
        )
        return result

    return _enqueue


@pytest.fixture
async def worker_engine(local_env: dict[str, str]) -> AsyncIterator[AsyncEngine]:
    """The delivery worker's REAL database connection: it logs in as
    ``edu_worker_login`` (member of ``edu_worker`` only), exactly as a worker
    process will. Nothing in the delivery tests runs as the database owner."""
    url = local_env.get("EDU_WORKER_DATABASE_URL")
    if not url:
        pytest.fail(
            ".env has no EDU_WORKER_DATABASE_URL. Run `make db-reset` (it provisions "
            "edu_worker_login).",
            pytrace=False,
        )
    engine = create_async_engine(url, pool_size=4, max_overflow=0)
    yield engine
    await engine.dispose()


@pytest.fixture
async def outside_quiet_hours(admin: asyncpg.Pool, clean_notify_state: None) -> None:
    """Move the PLATFORM quiet window away from the present moment, so a test of the
    real-clock ``notify.claim_due`` does not depend on the hour it runs at (exact
    quiet-hour instants are tested in supabase/tests/242_notify_delivery.sql).
    ``clean_notify_state`` restores 21:00-06:00 afterwards."""
    await admin.execute(
        "UPDATE notify.policy SET "
        "quiet_start = ((now() AT TIME ZONE 'America/Port-au-Prince') + interval '6 hours')::time, "
        "quiet_end = ((now() AT TIME ZONE 'America/Port-au-Prince') + interval '7 hours')::time"
    )
