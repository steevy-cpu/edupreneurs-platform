"""GET /v1/daily-word through the real API, real local Auth tokens and PostgreSQL."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from tests import vocab_fixtures
from tests.helpers import STUDENT_A, STUDENT_B, bearer
from tests.vocab_fixtures import (
    SYNTHETIC_AUDIO,
    VOCAB_TABLES,
    approved_word,
    assign,
    create_revision,
    create_source,
    haiti_today,
    set_rights,
)

# Fixtures of this lane live in tests/vocab_fixtures.py (tests/conftest.py is read-only).
vocab_app = vocab_fixtures.vocab_app
vocab_client = vocab_fixtures.vocab_client
clean_vocab = vocab_fixtures.clean_vocab

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_vocab")]

URL = "/v1/daily-word"
#: Owner's target for the uncompressed JSON body.
SIZE_BUDGET_BYTES = 1536
STRONG_ETAG = re.compile(r'^"dw1-[0-9a-f]{32}"$')


def assert_error_shape(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    assert set(body["error"]) <= {"code", "message", "request_id", "details"}


# ------------------------------------------------------------------ feature flag
async def test_flag_off_is_the_default_and_the_route_does_not_exist(
    client: httpx.AsyncClient, app: FastAPI, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    word = await approved_word(admin, term="DRAPEAU")
    await assign(admin, word["word_id"])
    assert app.state.settings.daily_word_enabled is False

    with_token = await client.get(URL, params={"locale": "fr"}, headers=bearer(tokens["student_a"]))
    assert_error_shape(with_token, 404, "not_found")
    assert "DRAPEAU" not in with_token.text
    assert_error_shape(await client.get(URL, params={"locale": "fr"}), 404, "not_found")
    assert URL not in (await client.get("/openapi.json")).json()["paths"]


async def test_flag_on_openapi_documents_the_route_in_the_single_error_shape(
    vocab_client: httpx.AsyncClient,
) -> None:
    spec = (await vocab_client.get("/openapi.json")).json()
    operations = spec["paths"][URL]
    assert set(operations) == {"get"}
    operation = operations["get"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert set(operation["responses"]) == {"200", "401", "404", "422", "503"}
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for status, declared in operation["responses"].items():
        if status != "200":
            assert declared["content"]["application/json"]["schema"] == error_ref, status
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    # The ONLY inputs: a locale and a cache validator. No date, no time, no user.
    assert {(p["name"], p["in"]) for p in operation["parameters"]} == {
        ("locale", "query"),
        ("if-none-match", "header"),
    }


# ------------------------------------------------------------------ auth + validation
async def test_requires_a_token(vocab_client: httpx.AsyncClient, admin: asyncpg.Pool) -> None:
    word = await approved_word(admin, term="SECRET")
    await assign(admin, word["word_id"])
    response = await vocab_client.get(URL, params={"locale": "fr"})
    assert_error_shape(response, 401, "unauthenticated")
    assert response.headers["www-authenticate"] == "Bearer"
    assert "SECRET" not in response.text
    forged = await vocab_client.get(URL, params={"locale": "fr"}, headers=bearer("not-a-token"))
    assert_error_shape(forged, 401, "unauthenticated")


@pytest.mark.parametrize("params", [{}, {"locale": "en"}, {"locale": ""}, {"locale": "FR"}])
async def test_locale_is_validated(
    vocab_client: httpx.AsyncClient, tokens: dict[str, str], params: dict[str, str]
) -> None:
    response = await vocab_client.get(URL, params=params, headers=bearer(tokens["student_a"]))
    assert_error_shape(response, 422, "validation_error")


async def test_only_get_is_allowed(vocab_client: httpx.AsyncClient, tokens: dict[str, str]) -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = await vocab_client.request(
            method, URL, params={"locale": "fr"}, headers=bearer(tokens["student_a"])
        )
        assert_error_shape(response, 405, "method_not_allowed")


# ------------------------------------------------------------------ nothing assigned
async def test_nothing_assigned_is_404_never_an_invented_word(
    vocab_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    # Approved words exist, and one is scheduled for TOMORROW — but not today.
    today = await haiti_today(admin)
    await approved_word(admin, term="DISPONIBLE")
    tomorrow_word = await approved_word(admin, term="DEMAIN")
    await assign(admin, tomorrow_word["word_id"], today + timedelta(days=1))

    for locale in ("fr", "ht"):
        response = await vocab_client.get(
            URL, params={"locale": locale}, headers=bearer(tokens["student_a"])
        )
        assert_error_shape(response, 404, "daily_word_not_available")
        assert response.headers["cache-control"] == "private, no-store"
        assert "etag" not in response.headers
        assert "DISPONIBLE" not in response.text and "DEMAIN" not in response.text


# ------------------------------------------------------------------ the contract
async def test_todays_word_full_contract(
    vocab_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    audio_source = await create_source(admin)
    word = await approved_word(admin, term="MOT", audio_source_id=audio_source)
    today = await assign(admin, word["word_id"])
    next_midnight = await admin.fetchval("SELECT vocab.haiti_day_start($1::date + 1)", today)

    response = await vocab_client.get(
        URL, params={"locale": "fr"}, headers=bearer(tokens["student_a"])
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json"
    assert STRONG_ETAG.match(response.headers["etag"]), response.headers["etag"]
    assert response.headers["cache-control"] == "private, no-cache"
    body = response.json()
    assert set(body) == {
        "haiti_date",
        "locale",
        "requested_locale",
        "is_fallback_locale",
        "word",
        "audio",
        "valid_until",
    }
    assert body["haiti_date"] == today.isoformat()
    assert (body["locale"], body["requested_locale"], body["is_fallback_locale"]) == (
        "fr",
        "fr",
        False,
    )
    assert body["word"] == {
        "word_id": str(word["word_id"]),
        "revision_id": str(word["revisions"]["fr"]),
        "revision": 1,
        "term": "MOT-fr",
        "pronunciation": "pro-non-sya-syon",
        "part_of_speech": "noun",
        "definition": "Définition synthétique de test.",
        "example": "Exemple synthétique de test.",
        "gloss": "glose de test",
    }
    audio_id = await admin.fetchval(
        "SELECT id FROM vocab.audio_assets WHERE word_revision_id = $1", word["revisions"]["fr"]
    )
    assert body["audio"] == {
        "asset_id": str(audio_id),
        "mime_type": "audio/mp4",
        "byte_size": len(SYNTHETIC_AUDIO),
        "duration_ms": 1200,
        "sha256": hashlib.sha256(SYNTHETIC_AUDIO).hexdigest(),
    }
    # valid_until is the next Haiti midnight, as a UTC instant.
    assert body["valid_until"] == next_midnight.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert next_midnight.hour in (4, 5)  # 04:00Z in summer time, 05:00Z in winter
    # Nothing internal leaks: no storage key, author, reviewer, source or licence.
    for forbidden in ("vocab/test/", "object_key", "source", "licence", "created_by", "a0000000"):
        assert forbidden not in response.text, forbidden

    creole = await vocab_client.get(
        URL, params={"locale": "ht"}, headers=bearer(tokens["student_a"])
    )
    creole_body = creole.json()
    assert (creole_body["locale"], creole_body["is_fallback_locale"]) == ("ht", False)
    assert creole_body["word"]["term"] == "MOT-ht"
    assert creole_body["word"]["word_id"] == body["word"]["word_id"]  # same word, other language
    assert creole_body["audio"] is None  # the recording belongs to the French revision
    assert creole.headers["etag"] != response.headers["etag"]


async def test_missing_translation_falls_back_to_french(
    vocab_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    word = await approved_word(admin, term="SEUL", locales=("fr",))
    # A Creole DRAFT exists, which must not count as a translation.
    await create_revision(
        admin, word["word_id"], "ht", word["source_id"], term="BOUYON", outcome="draft"
    )
    await assign(admin, word["word_id"])

    french = await vocab_client.get(
        URL, params={"locale": "fr"}, headers=bearer(tokens["student_a"])
    )
    creole = await vocab_client.get(
        URL, params={"locale": "ht"}, headers=bearer(tokens["student_a"])
    )
    assert creole.status_code == 200, creole.text
    body = creole.json()
    assert (body["requested_locale"], body["locale"], body["is_fallback_locale"]) == (
        "ht",
        "fr",
        True,
    )
    assert body["word"] == french.json()["word"]
    assert "BOUYON" not in creole.text
    # Different representations (requested_locale differs) => different strong tags.
    assert creole.headers["etag"] != french.headers["etag"]


# ------------------------------------------------------------------ ETag / 304
async def test_etag_and_conditional_requests(
    vocab_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    word = await approved_word(admin, term="ETIQUETTE")
    await assign(admin, word["word_id"])
    auth = bearer(tokens["student_a"])

    first = await vocab_client.get(URL, params={"locale": "fr"}, headers=auth)
    etag = first.headers["etag"]
    again = await vocab_client.get(URL, params={"locale": "fr"}, headers=auth)
    assert again.headers["etag"] == etag and again.content == first.content

    for validator in (etag, f"W/{etag}", f'"other", {etag}', "*"):
        cached = await vocab_client.get(
            URL, params={"locale": "fr"}, headers={**auth, "If-None-Match": validator}
        )
        assert cached.status_code == 304, validator
        assert cached.content == b""
        assert cached.headers["etag"] == etag
        assert cached.headers["cache-control"] == "private, no-cache"
        assert "x-request-id" in cached.headers

    for validator in ('"dw1-00000000000000000000000000000000"', etag.strip('"'), '""'):
        fresh = await vocab_client.get(
            URL, params={"locale": "fr"}, headers={**auth, "If-None-Match": validator}
        )
        assert fresh.status_code == 200, validator
        assert fresh.content == first.content

    # The French tag does not validate the Creole representation.
    creole = await vocab_client.get(
        URL, params={"locale": "ht"}, headers={**auth, "If-None-Match": etag}
    )
    assert creole.status_code == 200
    # A validator never opens the door: no token, no 304.
    anonymous = await vocab_client.get(
        URL, params={"locale": "fr"}, headers={"If-None-Match": etag}
    )
    assert_error_shape(anonymous, 401, "unauthenticated")


# ------------------------------------------------------------------ cross-account
async def test_cross_account_same_word_and_nothing_is_recorded(
    vocab_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    word = await approved_word(admin, term="PARTAGE")
    await assign(admin, word["word_id"])

    async def snapshot() -> dict[str, int]:
        counts: dict[str, int] = {}
        for table in (
            *VOCAB_TABLES.split(", "),
            "app.audit_events",
            "app.practice_attempts",
            "app.lesson_progress",
            "app.account_change_feed",
            "app.sync_receipts",
            "app.account_sync_state",
            "app.learner_profiles",
        ):
            counts[table] = await admin.fetchval(f"SELECT count(*) FROM {table}")
        return counts

    before = await snapshot()
    responses = {}
    for account in ("student_a", "student_b", "editor"):
        for locale in ("fr", "ht"):
            response = await vocab_client.get(
                URL, params={"locale": locale}, headers=bearer(tokens[account])
            )
            assert response.status_code == 200, (account, response.text)
            responses[(account, locale)] = response
    for locale in ("fr", "ht"):
        a, b, staff = (responses[(who, locale)] for who in ("student_a", "student_b", "editor"))
        assert a.content == b.content == staff.content
        assert a.headers["etag"] == b.headers["etag"] == staff.headers["etag"]
        assert str(STUDENT_A) not in a.text and str(STUDENT_B) not in b.text
    # Opening the word creates no Gold, no mastery, no tracking row, no profile.
    assert await snapshot() == before
    # ... and there is nowhere it COULD be recorded: the schema has no per-learner table.
    tables = await admin.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'vocab'")
    assert {row["tablename"] for row in tables} == {
        name.removeprefix("vocab.") for name in VOCAB_TABLES.split(", ")
    }


# ------------------------------------------------------------------ visibility
async def test_draft_in_review_rejected_and_future_content_is_invisible(
    vocab_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    today = await haiti_today(admin)
    word = await approved_word(admin, term="VISIBLE", locales=("fr",))
    source = word["source_id"]
    await assign(admin, word["word_id"])
    hidden_terms = []
    for outcome in ("draft", "in_review", "rejected"):
        for locale in ("fr", "ht"):
            term = f"CACHE-{outcome}-{locale}".upper()
            hidden_terms.append(term)
            await create_revision(
                admin, word["word_id"], locale, source, term=term, outcome=outcome
            )
    future = await approved_word(admin, term="FUTUR")
    await assign(admin, future["word_id"], today + timedelta(days=1))
    never_scheduled = await approved_word(admin, term="JAMAIS")
    assert never_scheduled["word_id"]

    for account in ("student_a", "student_b"):
        for locale in ("fr", "ht"):
            response = await vocab_client.get(
                URL, params={"locale": locale}, headers=bearer(tokens[account])
            )
            assert response.status_code == 200
            assert response.json()["word"]["term"] == "VISIBLE-fr"
            for term in (*hidden_terms, "FUTUR", "JAMAIS"):
                assert term not in response.text, (account, locale, term)
    # A learner cannot ask for another day: unknown parameters and client clocks are ignored.
    probing = await vocab_client.get(
        URL,
        params={
            "locale": "fr",
            "date": (today + timedelta(days=1)).isoformat(),
            "haiti_date": (today + timedelta(days=1)).isoformat(),
            "now": "2099-01-01T00:00:00Z",
            "offset": "1",
        },
        headers={
            **bearer(tokens["student_a"]),
            "Date": "Wed, 01 Jan 2099 00:00:00 GMT",
            "X-Client-Time": "2099-01-01T00:00:00Z",
            "X-Timezone": "Pacific/Kiritimati",
        },
    )
    assert probing.status_code == 200
    assert probing.json()["haiti_date"] == today.isoformat()
    assert probing.json()["word"]["term"] == "VISIBLE-fr"


async def test_word_edited_after_assignment_keeps_todays_word(
    vocab_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    word = await approved_word(admin, term="ORIGINAL", locales=("fr",))
    await assign(admin, word["word_id"])
    auth = bearer(tokens["student_a"])
    before = await vocab_client.get(URL, params={"locale": "fr"}, headers=auth)

    # A corrected French revision AND a first Creole translation are approved later today.
    await create_revision(admin, word["word_id"], "fr", word["source_id"], term="CORRIGE")
    await create_revision(admin, word["word_id"], "ht", word["source_id"], term="TRADUIT")

    after = await vocab_client.get(
        URL, params={"locale": "fr"}, headers={**auth, "If-None-Match": before.headers["etag"]}
    )
    assert after.status_code == 304
    full = await vocab_client.get(URL, params={"locale": "fr"}, headers=auth)
    assert full.content == before.content
    assert full.json()["word"]["term"] == "ORIGINAL-fr"
    creole = await vocab_client.get(URL, params={"locale": "ht"}, headers=auth)
    assert creole.json()["is_fallback_locale"] is True
    assert "TRADUIT" not in creole.text and "CORRIGE" not in creole.text

    # Retiring the word later does not change today either.
    await admin.execute("UPDATE vocab.words SET is_active = false WHERE id = $1", word["word_id"])
    retired = await vocab_client.get(URL, params={"locale": "fr"}, headers=auth)
    assert retired.content == before.content


async def test_rights_withdrawn_hides_word_or_recording(
    vocab_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    audio_source = await create_source(admin)
    word = await approved_word(admin, term="DROITS", audio_source_id=audio_source)
    await assign(admin, word["word_id"])
    auth = bearer(tokens["student_a"])
    with_audio = await vocab_client.get(URL, params={"locale": "fr"}, headers=auth)
    assert with_audio.json()["audio"] is not None

    await set_rights(admin, audio_source, "restricted")
    without_audio = await vocab_client.get(
        URL, params={"locale": "fr"}, headers={**auth, "If-None-Match": with_audio.headers["etag"]}
    )
    assert without_audio.status_code == 200, "the body changed, so the strong tag must change"
    assert without_audio.json()["audio"] is None
    assert without_audio.json()["word"] == with_audio.json()["word"]
    assert without_audio.headers["etag"] != with_audio.headers["etag"]

    await set_rights(admin, word["source_id"], "blocked")
    gone = await vocab_client.get(
        URL,
        params={"locale": "fr"},
        headers={**auth, "If-None-Match": without_audio.headers["etag"]},
    )
    assert_error_shape(gone, 404, "daily_word_not_available")
    assert "DROITS" not in gone.text


# ------------------------------------------------------------------ size budget
async def test_response_size_budget(
    vocab_client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    """The LARGEST word the database accepts, with a recording, still fits the budget."""
    source = await create_source(admin)
    word = await approved_word(admin, term="petit", locales=())
    # Exactly the 800-byte payload budget of vocab.word_revisions (JSON text, quotes
    # included): 3 x 82 + 302 + 252. Accented letters are 2 bytes each in UTF-8.
    biggest = {
        "term": "é" * 40,
        "pronunciation": "è" * 40,
        "gloss": "ò" * 40,
        "definition": "é" * 150,
        "example": "à" * 125,
    }
    payload_bytes = sum(len(json.dumps(v, ensure_ascii=False).encode()) for v in biggest.values())
    assert payload_bytes == 800
    await create_revision(
        admin,
        word["word_id"],
        "fr",
        source,
        part_of_speech="interjection",
        audio_source_id=source,
        **biggest,
    )
    with pytest.raises(asyncpg.CheckViolationError):
        await create_revision(
            admin, word["word_id"], "fr", source, **{**biggest, "example": "à" * 126}
        )
    await assign(admin, word["word_id"])

    for locale in ("fr", "ht"):  # "ht" adds the fallback flag to the same word
        response = await vocab_client.get(
            URL, params={"locale": locale}, headers=bearer(tokens["student_a"])
        )
        assert response.status_code == 200, response.text
        assert response.json()["word"]["definition"] == biggest["definition"]
        assert response.json()["audio"]["byte_size"] == len(SYNTHETIC_AUDIO)
        assert len(response.content) <= SIZE_BUDGET_BYTES, len(response.content)
        assert int(response.headers["content-length"]) == len(response.content)
    # Measured on 2026-11-24: 1338 bytes (fr) / 1337 bytes (ht) for this worst case.
    # And a 304 costs no body at all.
    cached = await vocab_client.get(
        URL,
        params={"locale": "ht"},
        headers={**bearer(tokens["student_a"]), "If-None-Match": response.headers["etag"]},
    )
    assert (cached.status_code, cached.content) == (304, b"")


async def test_audio_size_cap_is_enforced_by_the_database(admin: asyncpg.Pool) -> None:
    source = await create_source(admin)
    word = await approved_word(admin, term="son", locales=())
    draft = await create_revision(admin, word["word_id"], "fr", source, term="son", outcome="draft")
    for too_big in (102_401, 1_000_000):
        with pytest.raises(asyncpg.CheckViolationError):
            await admin.execute(
                "INSERT INTO vocab.audio_assets (word_revision_id, object_key, byte_size, sha256, "
                "mime_type, duration_ms, source_id, created_by) "
                "VALUES ($1, 'vocab/test/too-big.m4a', $2, sha256('x'), 'audio/mp4', 900, $3, "
                "(SELECT created_by FROM vocab.word_revisions WHERE id = $1))",
                draft,
                too_big,
                source,
            )
    assert await admin.fetchval("SELECT count(*) FROM vocab.audio_assets") == 0
    assert len(SYNTHETIC_AUDIO) < 64  # the only "audio" bytes in this repository's tests
