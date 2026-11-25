"""Fixtures and helpers for the `billing` (entitlements) tests.

Everything here is synthetic and local:
* grants, plans, prices and the simulated provider are created by these helpers
  through the LOCAL owner connection (`admin`) and removed again by
  ``billing_clean`` — no migration and no seed file contains any of them;
* the plan below is NOT a price list. Real plans and prices are
  BLOCKED_BY_OWNER (PO-01, PO-05);
* the provider signing secret is generated per test run and never stored.
"""

from __future__ import annotations

import json
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from edu_api.billing.mock_provider import MockProvider
from edu_api.main import create_app
from tests.conftest import build_settings
from tests.staff_fixtures import build_staff_settings, dispose_app

BILLING_TABLES = (
    "billing.refunds, billing.entitlement_revocations, billing.entitlements, "
    "billing.provider_events, billing.orders, billing.plan_prices, billing.plans, "
    "billing.providers"
)

SEED_GRADE = uuid.UUID("b0000000-0000-4000-8000-000000000001")
SEED_COURSE = uuid.UUID("b0000000-0000-4000-8000-000000000003")

#: Synthetic test plan. NOT a decided product or price (BLOCKED_BY_OWNER PO-01/PO-05).
SYNTHETIC_PLAN_CODE = "synthetic-all-30"
SYNTHETIC_PLAN_DAYS = 30
SYNTHETIC_PRICE_MINOR = 50_000
SYNTHETIC_CURRENCY = "HTG"


@pytest.fixture
async def billing_clean(admin: asyncpg.Pool) -> AsyncIterator[None]:
    """Empty billing tables before AND after a test, so nothing leaks into
    another test file (the database is shared by the whole run). Also restores
    the API role's access to the schema, in case an earlier run was killed inside
    the "billing unreachable" test (review finding L5)."""
    await admin.execute("GRANT USAGE ON SCHEMA billing TO edu_api")
    await admin.execute(f"TRUNCATE {BILLING_TABLES}")
    yield
    await admin.execute(f"TRUNCATE {BILLING_TABLES}")


@asynccontextmanager
async def entitlements_app(local_env: dict[str, str], **overrides: Any) -> AsyncIterator[FastAPI]:
    """The API with EDU_ENTITLEMENTS_ENABLED on (the default is off)."""
    application = create_app(build_settings(local_env, entitlements_enabled=True, **overrides))
    try:
        yield application
    finally:
        await dispose_app(application)


@asynccontextmanager
async def entitlements_staff_app(
    local_env: dict[str, str], **overrides: Any
) -> AsyncIterator[FastAPI]:
    """The API with the flag on AND the staff side configured (edu_staff_login pool)."""
    application = create_app(
        build_staff_settings(local_env, entitlements_enabled=True, **overrides)
    )
    try:
        yield application
    finally:
        await dispose_app(application)


@asynccontextmanager
async def http(application: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
        yield client


@pytest.fixture
async def billing_client(local_env: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    async with entitlements_app(local_env) as application, http(application) as client:
        yield client


@pytest.fixture
async def billing_staff_app(local_env: dict[str, str]) -> AsyncIterator[FastAPI]:
    async with entitlements_staff_app(local_env) as application:
        yield application


@pytest.fixture
async def billing_staff_client(billing_staff_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with http(billing_staff_app) as client:
        yield client


# ------------------------------------------------------------------ grants
async def grant(
    admin: asyncpg.Pool,
    learner: uuid.UUID,
    *,
    scope_kind: str = "all",
    scope_id: uuid.UUID | None = None,
    starts_in: str = "0 seconds",
    lasts: str = "30 days",
    source: str = "gift",
    key: str | None = None,
) -> uuid.UUID:
    """One grant through billing.grant_entitlement (as the local owner: no
    other role can execute it)."""
    outcome = json.loads(
        await admin.fetchval(
            "SELECT billing.grant_entitlement($1, $2, $3, now() + $4::text::interval, "
            "now() + $4::text::interval + $5::text::interval, $6, NULL, $7, NULL)",
            learner,
            scope_kind,
            scope_id,
            starts_in,
            lasts,
            source,
            key or f"test-grant-{uuid.uuid4()}",
        )
    )
    assert outcome["status"] == "granted", outcome
    return uuid.UUID(outcome["entitlement_id"])


async def revoke(admin: asyncpg.Pool, entitlement_id: uuid.UUID) -> None:
    await admin.fetchval(
        "SELECT billing.revoke_entitlement($1, 'staff_revoke', NULL)", entitlement_id
    )


async def snapshot(admin: asyncpg.Pool) -> dict[str, int]:
    """Row counts of everything a provider event could change."""
    row = await admin.fetchrow(
        "SELECT (SELECT count(*) FROM billing.entitlements) AS grants, "
        "(SELECT count(*) FROM billing.entitlement_revocations) AS revocations, "
        "(SELECT count(*) FROM billing.provider_events) AS events, "
        "(SELECT count(*) FROM billing.refunds) AS refunds, "
        "(SELECT count(*) FROM billing.orders WHERE status <> 'pending') AS settled_orders"
    )
    return dict(row)


# ------------------------------------------------- simulated provider (tests only)
@pytest.fixture
def mock_provider() -> MockProvider:
    """A simulated provider whose secret exists only in this test's memory."""
    return MockProvider(secrets.token_bytes(32), environment="test")


@pytest.fixture
async def mock_billing(admin: asyncpg.Pool, billing_clean: None) -> None:
    """Register the simulated provider and one synthetic plan (local database only)."""
    await admin.execute(
        "INSERT INTO billing.providers (code, is_simulated, is_enabled) VALUES ('mock', true, true)"
    )
    plan_id = await admin.fetchval(
        "INSERT INTO billing.plans (code, scope_kind, duration_days, is_synthetic) "
        "VALUES ($1, 'all', $2, true) RETURNING id",
        SYNTHETIC_PLAN_CODE,
        SYNTHETIC_PLAN_DAYS,
    )
    await admin.execute(
        "INSERT INTO billing.plan_prices (plan_id, currency, amount_minor) VALUES ($1, $2, $3)",
        plan_id,
        SYNTHETIC_CURRENCY,
        SYNTHETIC_PRICE_MINOR,
    )


async def create_order(admin: asyncpg.Pool, learner: uuid.UUID) -> uuid.UUID:
    """An order for `learner`, created the way a future checkout would: the
    learner is the transaction's verified actor and the price comes from the
    server. (No checkout route exists; PO-06.)"""
    async with admin.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('edu.actor_id', $1, true)", str(learner))
        outcome = json.loads(
            await conn.fetchval(
                "SELECT billing.create_order($1, $2, 'mock', $3)",
                SYNTHETIC_PLAN_CODE,
                SYNTHETIC_CURRENCY,
                f"test-order-{uuid.uuid4()}",
            )
        )
    assert outcome["status"] == "created", outcome
    assert outcome["amount_expected_minor"] == SYNTHETIC_PRICE_MINOR
    return uuid.UUID(outcome["order_id"])


class AdminEventSink:
    """Applies an authenticated event as the LOCAL database owner. Test-only:
    the application ships no sink, and its own role cannot execute the function."""

    def __init__(self, admin: asyncpg.Pool) -> None:
        self._admin = admin
        self.calls = 0

    async def __call__(
        self, provider: str, event_id: str, event_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls += 1
        outcome: dict[str, Any] = json.loads(
            await self._admin.fetchval(
                "SELECT billing.apply_provider_event($1, $2, $3, $4::jsonb)",
                provider,
                event_id,
                event_type,
                json.dumps(payload),
            )
        )
        return outcome


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
