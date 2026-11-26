"""Real-PostgreSQL tests of the tutor budget schema PROPOSAL (docs/jude-01/sql).

Each test session creates its OWN database (``jude_tutor_test_<random>``) on a
local server, applies a tiny prelude plus the proposal, and drops the database
afterwards. It never touches the application schema or anyone else's data.

Which server:

* ``JUDE_TEST_ADMIN_DATABASE_URL`` if set (a throwaway PostgreSQL), otherwise
* ``LOCAL_ADMIN_DATABASE_URL`` from ``.env`` (the local Supabase stack, as in CI).

Only local addresses are accepted. With neither, the tests are SKIPPED and say
so; they are not silently counted as passing.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from edu_api.db.session import Database
from edu_api.tutor.pg_store import PostgresUsageStore

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from local_stack import LOCAL_HOSTS, read_env_file  # noqa: E402

PRELUDE = Path(__file__).with_name("prelude.sql")
PROPOSAL = ROOT / "docs" / "jude-01" / "sql" / "tutor_schema.sql"


def _servers() -> tuple[str, str | None] | None:
    """(admin URL, API-login URL or None) of the local server to test on.

    * Throwaway server: the admin is a superuser, and API connections become the
      API role with ``SET ROLE edu_api``.
    * Local Supabase stack (CI): ``postgres`` is not a superuser there, so API
      connections log in as the real ``edu_api_login`` from ``EDU_DATABASE_URL``,
      exactly as the application does.
    """
    explicit = os.environ.get("JUDE_TEST_ADMIN_DATABASE_URL")
    if explicit:
        return explicit, None
    try:
        env = read_env_file()
    except Exception:
        return None
    admin, api = env.get("LOCAL_ADMIN_DATABASE_URL"), env.get("EDU_DATABASE_URL")
    return (admin, api) if admin and api else None


def _with_database(url: str, database: str, scheme: str | None = None) -> str:
    parts = urlsplit(url)
    return urlunsplit((scheme or parts.scheme, parts.netloc, f"/{database}", parts.query, ""))


@pytest.fixture(scope="session")
async def tutor_database_url() -> AsyncIterator[str]:
    servers = _servers()
    if servers is None:
        pytest.skip(
            "no local PostgreSQL for the tutor schema tests: set JUDE_TEST_ADMIN_DATABASE_URL "
            "or start the local stack (make setup)"
        )
    admin_url, api_url = servers
    for url in filter(None, (admin_url, api_url)):
        if urlsplit(url).hostname not in LOCAL_HOSTS:
            pytest.fail("tutor schema tests only run against this machine", pytrace=False)

    name = f"jude_tutor_test_{uuid.uuid4().hex[:12]}"
    maintenance = _with_database(admin_url, urlsplit(admin_url).path.lstrip("/"))
    admin = await asyncpg.connect(maintenance)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    url = _with_database(admin_url, name)
    setup = await asyncpg.connect(url)
    try:
        await setup.execute(PRELUDE.read_text(encoding="utf-8"))
        await setup.execute(PROPOSAL.read_text(encoding="utf-8"))
    finally:
        await setup.close()
    try:
        yield url
    finally:
        admin = await asyncpg.connect(maintenance)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await admin.close()


@pytest.fixture(scope="session")
async def owner(tutor_database_url: str) -> AsyncIterator[asyncpg.Pool]:
    """The database owner: arranges policy and inspects tables. Never used by the store."""
    pool = await asyncpg.create_pool(tutor_database_url, min_size=1, max_size=4)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture(scope="session")
async def database(tutor_database_url: str) -> AsyncIterator[Database]:
    """Connections that run AS THE API ROLE, never as the owner."""
    servers = _servers()
    assert servers is not None
    _, api_url = servers
    name = urlsplit(tutor_database_url).path.lstrip("/")
    server_settings = {"lock_timeout": "10000"}
    if api_url is None:
        url = _with_database(tutor_database_url, name, scheme="postgresql+asyncpg")
        server_settings["role"] = "edu_api"
    else:
        url = _with_database(api_url, name, scheme="postgresql+asyncpg")
    # The real login role has CONNECTION LIMIT 40 (scripts/local_stack.py) and shares it
    # with the application's own pool in the same test session. Twelve connections give
    # twelve genuinely concurrent transactions while staying well inside that limit;
    # further tasks queue for a connection.
    engine = create_async_engine(
        url,
        pool_size=12,
        max_overflow=0,
        pool_timeout=60,
        connect_args={"server_settings": server_settings},
    )
    db = Database(engine)
    try:
        async with db.transaction(None) as conn:
            role = (await conn.execute(text("SELECT current_user"))).scalar_one()
            is_super = (
                await conn.execute(text("SELECT current_setting('is_superuser')"))
            ).scalar_one()
        assert role in ("edu_api", "edu_api_login") and is_super == "off", (role, is_super)
        yield db
    finally:
        await db.dispose()


@pytest.fixture
async def store(database: Database, owner: asyncpg.Pool) -> PostgresUsageStore:
    """A clean ledger with small synthetic limits, not paused."""
    await owner.execute("TRUNCATE tutor.usage_requests, tutor.budget_counters, tutor.admin_audit")
    await owner.execute(
        """
        UPDATE tutor.policy SET paused = false, learner_daily_requests = 5,
            learner_daily_micro = 1000, learner_monthly_micro = 3000,
            global_monthly_micro = 10000, max_concurrent_per_learner = 2,
            max_concurrent_global = 500, reservation_ttl_s = 60
        """
    )
    return PostgresUsageStore(database)
