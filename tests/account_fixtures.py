"""Fixtures for the identity lane (`account` routes).

* An application instance with the lane's feature flags ON (they default to
  OFF, so the shared ``app`` fixture never registers these routes).
* A small pool of throw-away SYNTHETIC learners created through the LOCAL Auth
  admin API. The seed students are deliberately not used: other tests assert
  their grade, language and display name.

The pool is created once per session (local Auth rate-limits sign-ins) and each
test starts from a clean slate for those accounts.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from local_stack import LOCAL_HOSTS
from tests.conftest import build_settings

ACCOUNT_FLAGS = {
    "profile_edit_enabled": True,
    "onboarding_enabled": True,
    "account_lifecycle_enabled": True,
}


@dataclass(frozen=True, slots=True)
class SyntheticLearner:
    user_id: uuid.UUID
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def create_synthetic_learner(env: dict[str, str]) -> SyntheticLearner:
    """A brand-new Auth account with a random address under the reserved
    ``.test`` domain and a random password that is forgotten immediately."""
    base = env["LOCAL_SUPABASE_URL"].rstrip("/")
    if urlsplit(base).hostname not in LOCAL_HOSTS:
        pytest.fail("LOCAL_SUPABASE_URL is not this machine.", pytrace=False)
    email = f"synthetic.{uuid.uuid4().hex[:16]}@edupreneur.test"
    password = secrets.token_urlsafe(32)
    secret_key = env["LOCAL_SUPABASE_SECRET_KEY"]
    with httpx.Client(timeout=10) as http:
        created = http.post(
            f"{base}/auth/v1/admin/users",
            headers={"apikey": secret_key, "Authorization": f"Bearer {secret_key}"},
            json={"email": email, "password": password, "email_confirm": True},
        )
        created.raise_for_status()
        signed_in = http.post(
            f"{base}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": env["LOCAL_SUPABASE_PUBLISHABLE_KEY"]},
            json={"email": email, "password": password},
        )
        signed_in.raise_for_status()
    return SyntheticLearner(
        user_id=uuid.UUID(created.json()["id"]), token=str(signed_in.json()["access_token"])
    )


def delete_auth_user(env: dict[str, str], user_id: uuid.UUID) -> httpx.Response:
    """Ask the LOCAL Auth server to delete an account (it owns ``auth.users``)."""
    base = env["LOCAL_SUPABASE_URL"].rstrip("/")
    secret_key = env["LOCAL_SUPABASE_SECRET_KEY"]
    with httpx.Client(timeout=10) as http:
        return http.delete(
            f"{base}/auth/v1/admin/users/{user_id}",
            headers={"apikey": secret_key, "Authorization": f"Bearer {secret_key}"},
        )


@pytest.fixture(scope="session")
async def account_app(local_env: dict[str, str]) -> AsyncIterator[FastAPI]:
    from edu_api.main import create_app

    application = create_app(build_settings(local_env, **ACCOUNT_FLAGS))
    yield application
    await application.state.db.dispose()


@pytest.fixture
async def included_spec(
    local_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """The OpenAPI document as it will be once the director sets
    ``INCLUDE_IN_SCHEMA = True`` at integration (ruling R-01)."""
    from edu_api.main import create_app
    from edu_api.routers import account as account_router

    monkeypatch.setattr(account_router, "INCLUDE_IN_SCHEMA", True)
    application = create_app(build_settings(local_env, **ACCOUNT_FLAGS))
    try:
        spec: dict[str, Any] = application.openapi()
    finally:
        await application.state.db.dispose()
    return spec


@pytest.fixture
async def account_client(account_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=account_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http


@pytest.fixture(scope="session")
def learner_pool(local_env: dict[str, str]) -> dict[str, SyntheticLearner]:
    return {name: create_synthetic_learner(local_env) for name in ("x", "y")}


async def reset_account_state(admin: asyncpg.Pool, user_ids: list[uuid.UUID]) -> None:
    """Fixture-role clean-up for the pool accounts only (never the seed students)."""
    for table in await admin.fetch(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'user_id' "
        "WHERE n.nspname = 'account' AND c.relkind = 'r' ORDER BY c.relname"
    ):
        await admin.execute(
            f'DELETE FROM account."{table["relname"]}" WHERE user_id = ANY($1::uuid[])', user_ids
        )
    await admin.execute(
        "UPDATE app.learner_profiles SET grade_id = NULL, preferred_locale = 'fr', "
        "display_name = NULL WHERE user_id = ANY($1::uuid[])",
        user_ids,
    )


@pytest.fixture
async def learners(
    learner_pool: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> dict[str, SyntheticLearner]:
    """Learners ``x`` and ``y`` with default profiles and no account-lane rows."""
    await reset_account_state(admin, [learner.user_id for learner in learner_pool.values()])
    return learner_pool
