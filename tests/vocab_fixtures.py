"""Fixtures and helpers for the Word-of-the-Day tests (lane VOCAB).

``tests/conftest.py`` is read-only for this lane, so a test module binds the
fixtures it needs by name::

    from tests import vocab_fixtures
    vocab_client = vocab_fixtures.vocab_client

Everything is synthetic test content. Words are created through the REAL
editorial workflow functions (the seed editor writes, the seed reviewer
approves) on the ``admin`` connection, with the acting person placed in the
transaction exactly as the API does it. Two things are arranged directly as the
table owner, and the integrity triggers still check both:

* a source's rights are set to ``cleared`` with a plain UPDATE (the staff
  function needs a ``publisher``, which the seed data does not have);
* a word is put on a date with ``vocab._assign_word`` (the staff function needs
  a ``publisher`` too).
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from edu_api.main import create_app
from tests.conftest import build_settings
from tests.helpers import EDITOR, REVIEWER

VOCAB_TABLES = (
    "vocab.daily_assignments, vocab.audio_assets, vocab.reviews, "
    "vocab.word_revisions, vocab.words, vocab.sources"
)

#: Tiny synthetic bytes: only their length and checksum are ever stored.
SYNTHETIC_AUDIO = b"synthetic test bytes - not a recording"


@pytest.fixture(scope="session")
async def vocab_app(local_env: dict[str, str]) -> AsyncIterator[FastAPI]:
    """The API with ``EDU_DAILY_WORD_ENABLED`` switched on."""
    application = create_app(build_settings(local_env, daily_word_enabled=True))
    yield application
    await application.state.db.dispose()
    await application.state.token_verifier._keys.aclose()


@pytest.fixture
async def vocab_client(vocab_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=vocab_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http


@pytest.fixture
async def clean_vocab(admin: asyncpg.Pool) -> AsyncIterator[None]:
    """Empty vocab tables before AND after the test, so neither the next test
    nor the database tests that run afterwards see leftovers. TRUNCATE on the
    local disposable database by its owner; nothing else can remove a day that
    has opened."""
    await wait_out_haiti_midnight(admin)
    await admin.execute(f"TRUNCATE {VOCAB_TABLES}")
    yield
    await admin.execute(f"TRUNCATE {VOCAB_TABLES}")


async def wait_out_haiti_midnight(admin: asyncpg.Pool, margin_s: float = 20.0) -> None:
    """Tests place a word on "today" and then read "today" again. If the Haiti
    date is about to change, wait until it has, so no test straddles midnight."""
    remaining: float = await admin.fetchval(
        "SELECT EXTRACT(epoch FROM vocab.haiti_day_start(vocab.haiti_date(clock_timestamp()) + 1)"
        " - clock_timestamp())::float8"
    )
    if remaining < margin_s:
        await asyncio.sleep(remaining + 0.5)


def documented_openapi(settings: Any, *routers: Any) -> dict[str, Any]:
    """The OpenAPI document as it will be once ``INCLUDE_IN_SCHEMA`` is flipped
    in ``routers`` (ruling R-01): the flag each route got from the constant is
    switched on, a fresh app is built, and the flags are restored."""
    from edu_api.auth.jwks import StaticKeyProvider

    routes = [route for router in routers for route in router.routes]
    try:
        for route in routes:
            route.include_in_schema = True
        application = create_app(settings, key_provider=StaticKeyProvider({}))
        return application.openapi()
    finally:
        for route in routes:
            route.include_in_schema = False


async def _act_as(conn: asyncpg.Connection, actor: uuid.UUID) -> None:
    await conn.execute("SELECT set_config('edu.actor_id', $1, true)", str(actor))


async def haiti_today(admin: asyncpg.Pool) -> date:
    today: date = await admin.fetchval("SELECT vocab.haiti_date(clock_timestamp())")
    return today


async def create_source(admin: asyncpg.Pool, *, rights: str = "cleared") -> uuid.UUID:
    async with admin.acquire() as conn, conn.transaction():
        await _act_as(conn, EDITOR)
        source_id: uuid.UUID = await conn.fetchval(
            "SELECT vocab.register_source($1, NULL, 'synthetic-test-only')",
            f"Synthetic test source {uuid.uuid4().hex[:8]}",
        )
        if rights != "unverified":
            await conn.execute(
                "UPDATE vocab.sources SET rights_status = $2 WHERE id = $1", source_id, rights
            )
    return source_id


async def set_rights(admin: asyncpg.Pool, source_id: uuid.UUID, rights: str) -> None:
    await admin.execute(
        "UPDATE vocab.sources SET rights_status = $2 WHERE id = $1", source_id, rights
    )


async def create_word(admin: asyncpg.Pool) -> uuid.UUID:
    async with admin.acquire() as conn, conn.transaction():
        await _act_as(conn, EDITOR)
        word_id: uuid.UUID = await conn.fetchval(
            "SELECT vocab.create_word($1)", f"it-{uuid.uuid4().hex[:12]}"
        )
    return word_id


async def create_revision(
    admin: asyncpg.Pool,
    word_id: uuid.UUID,
    locale: str,
    source_id: uuid.UUID,
    *,
    term: str,
    outcome: str = "approved",
    pronunciation: str | None = "pro-non-sya-syon",
    part_of_speech: str = "noun",
    definition: str = "Définition synthétique de test.",
    example: str = "Exemple synthétique de test.",
    gloss: str | None = "glose de test",
    audio_source_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A revision in the requested final state: ``draft``, ``in_review``,
    ``approved`` or ``rejected``. ``audio_source_id`` attaches recording
    METADATA (no file exists anywhere)."""
    async with admin.acquire() as conn, conn.transaction():
        await _act_as(conn, EDITOR)
        revision_id: uuid.UUID = await conn.fetchval(
            "SELECT vocab.create_draft($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            word_id,
            locale,
            term,
            pronunciation,
            part_of_speech,
            definition,
            example,
            gloss,
            source_id,
        )
        if audio_source_id is not None:
            await conn.execute(
                "SELECT vocab.set_audio($1, $2, $3, $4, 'audio/mp4', 1200, $5)",
                revision_id,
                f"vocab/test/{revision_id}.m4a",
                len(SYNTHETIC_AUDIO),
                hashlib.sha256(SYNTHETIC_AUDIO).digest(),
                audio_source_id,
            )
        if outcome != "draft":
            await conn.execute("SELECT vocab.submit_revision($1)", revision_id)
        if outcome in ("approved", "rejected"):
            await _act_as(conn, REVIEWER)
            await conn.execute("SELECT vocab.review_revision($1, $2)", revision_id, outcome)
    return revision_id


async def approved_word(
    admin: asyncpg.Pool,
    *,
    term: str,
    locales: tuple[str, ...] = ("fr", "ht"),
    source_id: uuid.UUID | None = None,
    audio_source_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """A word with one approved revision per requested locale (audio on French)."""
    source = source_id or await create_source(admin)
    word_id = await create_word(admin)
    revisions: dict[str, uuid.UUID] = {}
    for locale in locales:
        revisions[locale] = await create_revision(
            admin,
            word_id,
            locale,
            source,
            term=f"{term}-{locale}",
            audio_source_id=audio_source_id if locale == "fr" else None,
        )
    return {"word_id": word_id, "source_id": source, "revisions": revisions, "term": term}


async def assign(admin: asyncpg.Pool, word_id: uuid.UUID, haiti_date: date | None = None) -> date:
    """Record ``word_id`` as the word of ``haiti_date`` (default: today in Haiti)."""
    async with admin.acquire() as conn, conn.transaction():
        day: date = haiti_date or await conn.fetchval("SELECT vocab.haiti_date(clock_timestamp())")
        await conn.execute("SELECT vocab._assign_word($1, $2, 'auto')", day, word_id)
    return day


async def schedule_rows(admin: asyncpg.Pool) -> list[tuple[date, str, uuid.UUID]]:
    rows = await admin.fetch(
        "SELECT haiti_date, locale, word_revision_id FROM vocab.daily_assignments "
        "ORDER BY haiti_date, locale"
    )
    return [(row["haiti_date"], row["locale"], row["word_revision_id"]) for row in rows]
