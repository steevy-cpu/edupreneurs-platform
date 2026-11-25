"""Fixtures and helpers for tests that need the STAFF side of the API (LOCAL stack only).

Fixtures in this file are not auto-discovered. Import the ones a test module
needs by name; pytest then treats them like fixtures defined in that module.
Import every fixture in the chain you use (``staff_client`` needs ``staff_app``,
which needs ``staff_settings``)::

    # ruff: noqa: F811            <- first line of the test module
    from tests.staff_fixtures import (  # noqa: F401
        staff_app, staff_client, staff_settings, staff_tokens, make_staff,
    )

    async def test_x(staff_client, staff_tokens, make_staff):
        publisher = await make_staff("publisher")
        r = await staff_client.get("/v1/staff/me", headers=bearer(publisher.token))

What they give you:

* ``staff_settings`` / ``staff_app`` / ``staff_client`` — the API with the staff
  side switched on (``staff_database_url`` = the ``edu_staff_login`` pool). The
  plain ``app`` / ``client`` fixtures of ``tests/conftest.py`` keep it off.
* ``staff_tokens`` — real access tokens for the seeded ``editor`` and ``reviewer``.
* ``make_staff(*roles)`` — a NEW synthetic account with the given active roles
  (for example ``publisher`` or ``admin``, which the seed does not contain),
  created through the local Auth admin API + the admin pool. ``seed.sql`` is not
  touched. After the test the account loses its roles and is deleted when
  nothing references it (otherwise ``make db-reset`` clears it).
* ``worker_url(local_env)`` / ``staff_url(local_env)`` — plain ``postgresql://``
  URLs for a direct asyncpg connection as the worker / staff login role.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from dev_token import issue_token
from edu_api.config import Settings
from edu_api.main import create_app
from local_stack import LOCAL_HOSTS
from tests.conftest import build_settings

STAFF_ENV_KEYS = ("EDU_STAFF_DATABASE_URL", "EDU_WORKER_DATABASE_URL")


@dataclass(frozen=True)
class StaffAccount:
    user_id: uuid.UUID
    email: str
    roles: tuple[str, ...]
    token: str


def _require_staff_env(env: dict[str, str]) -> None:
    missing = [name for name in STAFF_ENV_KEYS if not env.get(name)]
    if missing:
        pytest.fail(
            f".env is missing {missing}. Re-provision the local stack: `make db-reset` "
            "(or `uv run python scripts/local_stack.py env` then `... provision`).",
            pytrace=False,
        )
    for name in STAFF_ENV_KEYS:
        if urlsplit(env[name]).hostname not in LOCAL_HOSTS:
            pytest.fail(f"{name} is not a local address.", pytrace=False)


def staff_url(env: dict[str, str]) -> str:
    """``postgresql://`` URL of the staff login role, for a direct asyncpg connection."""
    _require_staff_env(env)
    return env["EDU_STAFF_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)


def worker_url(env: dict[str, str]) -> str:
    """``postgresql://`` URL of the worker login role, for a direct asyncpg connection."""
    _require_staff_env(env)
    return env["EDU_WORKER_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)


def build_staff_settings(env: dict[str, str], **overrides: object) -> Settings:
    """Settings with the staff side switched on. ``overrides`` as in ``build_settings``."""
    _require_staff_env(env)
    values: dict[str, object] = {"staff_database_url": SecretStr(env["EDU_STAFF_DATABASE_URL"])}
    values.update(overrides)
    return build_settings(env, **values)


async def dispose_app(application: FastAPI) -> None:
    await application.state.db.dispose()
    if application.state.staff_db is not None:
        await application.state.staff_db.dispose()


@pytest.fixture(scope="session")
def staff_settings(local_env: dict[str, str]) -> Settings:
    return build_staff_settings(local_env)


@pytest.fixture(scope="session")
async def staff_app(staff_settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(staff_settings)
    yield application
    await dispose_app(application)


@pytest.fixture
async def staff_client(staff_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=staff_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http


@pytest.fixture(scope="session")
def staff_tokens(local_env: dict[str, str]) -> dict[str, str]:
    """Real access tokens from the local Auth server for the seeded staff accounts."""
    return {name: issue_token(name, local_env) for name in ("editor", "reviewer")}


# --- additional synthetic staff accounts ----------------------------------------
def _admin_headers(env: dict[str, str]) -> dict[str, str]:
    secret_key = env["LOCAL_SUPABASE_SECRET_KEY"]
    return {"apikey": secret_key, "Authorization": f"Bearer {secret_key}"}


def _auth_base(env: dict[str, str]) -> str:
    base = env["LOCAL_SUPABASE_URL"].rstrip("/")
    if urlsplit(base).hostname not in LOCAL_HOSTS:
        pytest.fail("LOCAL_SUPABASE_URL is not this machine.", pytrace=False)
    return base


async def create_account(env: dict[str, str]) -> tuple[uuid.UUID, str, str]:
    """A new synthetic Auth account WITHOUT any staff role: ``(user_id, email, token)``.

    The address uses the reserved ``.test`` domain and a random tag; the random
    password is used once to sign in and then forgotten.
    """
    base = _auth_base(env)
    email = f"synthetic-{uuid.uuid4().hex[:16]}@edupreneur.test"
    password = secrets.token_urlsafe(32)
    async with httpx.AsyncClient(timeout=10) as http:
        created = await http.post(
            f"{base}/auth/v1/admin/users",
            headers=_admin_headers(env),
            json={"email": email, "password": password, "email_confirm": True},
        )
        created.raise_for_status()
        user_id = uuid.UUID(created.json()["id"])
        signed_in = await http.post(
            f"{base}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": env["LOCAL_SUPABASE_PUBLISHABLE_KEY"]},
            json={"email": email, "password": password},
        )
        signed_in.raise_for_status()
    return user_id, email, str(signed_in.json()["access_token"])


async def create_staff_account(
    admin: asyncpg.Pool, env: dict[str, str], *roles: str, granted_by: uuid.UUID | None = None
) -> StaffAccount:
    """A new synthetic account holding ``roles`` (active). Arranged with the admin
    pool, as a test fixture only: the product path for granting roles is the
    audited staff function, not this helper."""
    user_id, email, token = await create_account(env)
    for role in roles:
        await admin.execute(
            "INSERT INTO app.staff_roles (user_id, role, granted_by) VALUES ($1, $2, $3)",
            user_id,
            role,
            granted_by,
        )
    return StaffAccount(user_id=user_id, email=email, roles=tuple(roles), token=token)


async def set_role_active(admin: asyncpg.Pool, user_id: uuid.UUID, role: str, active: bool) -> None:
    await admin.execute(
        "UPDATE app.staff_roles SET is_active = $3 WHERE user_id = $1 AND role = $2",
        user_id,
        role,
        active,
    )


async def remove_account(admin: asyncpg.Pool, env: dict[str, str], user_id: uuid.UUID) -> None:
    """Best-effort clean-up: the account loses its staff roles in every case.

    The Auth account itself cannot be deleted while content or learning data
    references it (foreign keys RESTRICT, by design); it then simply stays
    behind without any role until the next ``make db-reset``.
    """
    await admin.execute("DELETE FROM app.staff_roles WHERE user_id = $1", user_id)
    try:
        await admin.execute("DELETE FROM app.learner_profiles WHERE user_id = $1", user_id)
    except asyncpg.PostgresError:
        return
    async with httpx.AsyncClient(timeout=10) as http:
        await http.delete(
            f"{_auth_base(env)}/auth/v1/admin/users/{user_id}", headers=_admin_headers(env)
        )


async def reset_denial_windows(admin: asyncpg.Pool, *user_ids: uuid.UUID) -> None:
    """Forget the 60-second "refusal already audited" windows (all, or of the given
    accounts), so that a test's next refused request is written to the audit log
    again. A test-only shortcut for waiting a minute."""
    if user_ids:
        await admin.execute(
            "DELETE FROM ops.access_denial_windows WHERE actor_id = ANY($1::uuid[])",
            list(user_ids),
        )
    else:
        await admin.execute("DELETE FROM ops.access_denial_windows")


MakeStaff = Callable[..., Awaitable[StaffAccount]]


@pytest.fixture
async def make_staff(admin: asyncpg.Pool, local_env: dict[str, str]) -> AsyncIterator[MakeStaff]:
    """``await make_staff("publisher")`` → a fresh StaffAccount; cleaned up after the test."""
    created: list[StaffAccount] = []

    async def factory(*roles: str, granted_by: uuid.UUID | None = None) -> StaffAccount:
        account = await create_staff_account(admin, local_env, *roles, granted_by=granted_by)
        created.append(account)
        return account

    yield factory
    for account in created:
        await remove_account(admin, local_env, account.user_id)
