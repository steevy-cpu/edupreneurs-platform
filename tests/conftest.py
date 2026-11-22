"""Fixtures for tests that need the LOCAL Supabase stack.

Nothing here is mocked except where a test says so: tokens are issued by the
real local Auth server, and every query hits the real local PostgreSQL.

Database connections used by tests:
* the application's own engine, logging in as ``edu_api_login`` (least privilege);
* ``admin`` — the local ``postgres`` owner, used ONLY as a test fixture role to
  arrange content (publish a revision) and to inspect canonical state.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dev_token import issue_token  # noqa: E402
from edu_api.config import Settings  # noqa: E402
from edu_api.main import create_app  # noqa: E402
from local_stack import LOCAL_HOSTS, read_env_file  # noqa: E402
from tests.helpers import EDITOR, REVIEWER, SEED_SOURCE, SEED_UNIT  # noqa: E402

LEARNING_TABLES = (
    "app.practice_attempts, app.sync_receipts, app.account_change_feed, "
    "app.lesson_progress, app.account_sync_state"
)


@pytest.fixture(scope="session")
def local_env() -> dict[str, str]:
    env = read_env_file()
    required = [
        "EDU_DATABASE_URL",
        "EDU_AUTH_ISSUER",
        "EDU_AUTH_JWKS_URL",
        "LOCAL_ADMIN_DATABASE_URL",
        "LOCAL_SUPABASE_URL",
        "LOCAL_SUPABASE_PUBLISHABLE_KEY",
        "LOCAL_SUPABASE_SECRET_KEY",
    ]
    missing = [name for name in required if not env.get(name)]
    if missing:
        pytest.fail(
            f".env is missing {missing}. Start the local stack first: `make setup` "
            "(or `make start && make db-reset`). Integration tests are never silently skipped.",
            pytrace=False,
        )
    for name in ("EDU_DATABASE_URL", "LOCAL_ADMIN_DATABASE_URL", "LOCAL_SUPABASE_URL"):
        if urlsplit(env[name]).hostname not in LOCAL_HOSTS:
            pytest.fail(
                f"{name} is not a local address. Tests only run against this machine.",
                pytrace=False,
            )
    return env


def build_settings(env: dict[str, str], **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": SecretStr(env["EDU_DATABASE_URL"]),
        "auth_issuer": env["EDU_AUTH_ISSUER"],
        "auth_jwks_url": env["EDU_AUTH_JWKS_URL"],
        "auth_audience": "authenticated",
        "auth_algorithms": ("ES256",),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture(scope="session")
def settings(local_env: dict[str, str]) -> Settings:
    return build_settings(local_env)


@pytest.fixture(scope="session")
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    yield application
    await application.state.db.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http


@pytest.fixture(scope="session")
async def admin(local_env: dict[str, str]) -> AsyncIterator[asyncpg.Pool]:
    pool = await asyncpg.create_pool(local_env["LOCAL_ADMIN_DATABASE_URL"], min_size=1, max_size=3)
    yield pool
    await pool.close()


@pytest.fixture(scope="session")
def tokens(local_env: dict[str, str]) -> dict[str, str]:
    """Real access tokens from the local Auth server for the synthetic accounts."""
    return {name: issue_token(name, local_env) for name in ("student_a", "student_b", "editor")}


# --- content fixtures (through the REAL editorial workflow; no trigger is bypassed) ---
MCQ_SPEC = (
    '{"choices": [{"id": "a", "text": "1"}, {"id": "b", "text": "2"}, {"id": "c", "text": "3"}]}'
)


async def create_lesson(admin: asyncpg.Pool) -> uuid.UUID:
    """A fresh synthetic lesson in the seed unit. Test lessons are never removed
    (published content is immutable by design); `make db-reset` clears them."""
    tag = uuid.uuid4().hex[:12]
    position = int(uuid.uuid4().int % 2_000_000_000) + 1000
    return await admin.fetchval(
        "INSERT INTO app.lessons (unit_id, slug, position) VALUES ($1, $2, $3) RETURNING id",
        SEED_UNIT,
        f"it-{tag}",
        position,
    )


async def create_revision(
    admin: asyncpg.Pool,
    lesson_id: uuid.UUID,
    *,
    revision: int,
    locale: str = "fr",
    questions: tuple[tuple[str, str], ...] = (("mcq", "b"),),
    title: str | None = None,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Insert a DRAFT revision with questions and a cleared source."""
    revision_id = await admin.fetchval(
        "INSERT INTO app.lesson_revisions (lesson_id, revision, locale, title, blocks, created_by) "
        "VALUES ($1, $2, $3, $4, $5::jsonb, $6) RETURNING id",
        lesson_id,
        revision,
        locale,
        title or f"Synthetic test lesson r{revision}",
        '[{"key": "p1", "type": "paragraph", "text": "Synthetic test content."}]',
        EDITOR,
    )
    question_ids = []
    for position, (kind, correct) in enumerate(questions, start=1):
        question_ids.append(
            await admin.fetchval(
                "INSERT INTO app.question_revisions (lesson_revision_id, question_key, position, kind, "
                "prompt, response_spec, answer_key, explanation) "
                'VALUES ($1, $2, $3, $4, \'{"text": "?"}\', $5::jsonb, $6::jsonb, \'{"text": "."}\') '
                "RETURNING id",
                revision_id,
                f"q{position}",
                position,
                kind,
                MCQ_SPEC,
                json.dumps({"correct_choice_id": correct}),
            )
        )
    await admin.execute(
        "INSERT INTO app.lesson_revision_sources (lesson_revision_id, source_id) VALUES ($1, $2)",
        revision_id,
        SEED_SOURCE,
    )
    return revision_id, question_ids


async def approve_revision(admin: asyncpg.Pool, revision_id: uuid.UUID) -> None:
    await admin.execute(
        "UPDATE app.lesson_revisions SET status = 'in_review' WHERE id = $1", revision_id
    )
    await admin.execute(
        "INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) "
        "VALUES ($1, $2, 'approved')",
        revision_id,
        REVIEWER,
    )
    await admin.execute(
        "UPDATE app.lesson_revisions SET status = 'approved', approved_by = $2, approved_at = now() "
        "WHERE id = $1",
        revision_id,
        REVIEWER,
    )


async def release_pack(
    admin: asyncpg.Pool,
    pack_key: str,
    revision_id: uuid.UUID,
    *,
    pack_revision: int,
    locale: str = "fr",
) -> uuid.UUID:
    """Build, finalize, activate and make current a pack containing one revision.
    The previously current release of the same pack (if any) is retired."""
    async with admin.acquire() as conn, conn.transaction():
        release_id = await conn.fetchval(
            "INSERT INTO app.pack_releases (pack_key, revision, locale, created_by) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            pack_key,
            pack_revision,
            locale,
            EDITOR,
        )
        await conn.execute(
            "INSERT INTO app.pack_items (pack_release_id, lesson_revision_id, position) "
            "VALUES ($1, $2, 1)",
            release_id,
            revision_id,
        )
        await conn.execute(
            "UPDATE app.pack_releases SET status = 'ready', manifest_object_key = 'synthetic/' || id, "
            "manifest_sha256 = sha256(convert_to(id::text, 'UTF8')), compressed_bytes = 1 WHERE id = $1",
            release_id,
        )
        await conn.execute(
            "UPDATE app.pack_releases SET status = 'active' WHERE id = $1", release_id
        )
        previous = await conn.fetchval(
            "SELECT release_id FROM app.pack_current WHERE pack_key = $1 AND locale = $2",
            pack_key,
            locale,
        )
        await conn.execute(
            "INSERT INTO app.pack_current (pack_key, locale, release_id) VALUES ($1, $2, $3) "
            "ON CONFLICT (pack_key, locale) DO UPDATE SET release_id = EXCLUDED.release_id, "
            "switched_at = now()",
            pack_key,
            locale,
            release_id,
        )
        if previous is not None:
            await conn.execute(
                "UPDATE app.pack_releases SET status = 'retired' WHERE id = $1", previous
            )
    return release_id


async def publish_new_lesson(
    admin: asyncpg.Pool,
    *,
    questions: tuple[tuple[str, str], ...] = (("mcq", "b"),),
) -> dict[str, Any]:
    lesson_id = await create_lesson(admin)
    revision_id, question_ids = await create_revision(
        admin, lesson_id, revision=1, questions=questions
    )
    await approve_revision(admin, revision_id)
    pack_key = f"it-{uuid.uuid4().hex[:12]}"
    await release_pack(admin, pack_key, revision_id, pack_revision=1)
    return {
        "lesson_id": lesson_id,
        "revision_id": revision_id,
        "question_ids": question_ids,
        "pack_key": pack_key,
    }
