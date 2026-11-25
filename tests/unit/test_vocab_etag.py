"""Pure logic of the Word of the Day endpoint: entity tags, If-None-Match, the flag."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from edu_api.auth.jwks import StaticKeyProvider
from edu_api.config import Settings
from edu_api.main import create_app
from edu_api.vocab.service import build_response, compute_etag, if_none_match_matches

REVISION = uuid.UUID("11111111-1111-4111-8111-111111111111")
AUDIO = uuid.UUID("22222222-2222-4222-8222-222222222222")


def row(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "haiti_date": date(2026, 11, 24),
        "requested_locale": "fr",
        "locale": "fr",
        "is_fallback_locale": False,
        "word_id": uuid.UUID("33333333-3333-4333-8333-333333333333"),
        "word_revision_id": REVISION,
        "revision": 1,
        "term": "mot",
        "pronunciation": None,
        "part_of_speech": "noun",
        "definition": "Définition synthétique.",
        "example": "Exemple synthétique.",
        "gloss": None,
        "audio_asset_id": None,
        "audio_mime_type": None,
        "audio_byte_size": None,
        "audio_duration_ms": None,
        "audio_sha256": None,
        "valid_until": datetime(2026, 11, 25, 5, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def settings(**overrides: Any) -> Settings:
    return Settings(
        environment="test",
        database_url=SecretStr("postgresql+asyncpg://unused@127.0.0.1:1/unused"),
        auth_issuer="http://127.0.0.1:1/auth/v1",
        auth_jwks_url="http://127.0.0.1:1/auth/v1/.well-known/jwks.json",
        _env_file=None,
        **overrides,
    )


# ---------------------------------------------------------------- entity tag
def test_etag_is_strong_stable_and_opaque() -> None:
    tag = compute_etag(row())
    assert tag == compute_etag(row())
    assert tag.startswith('"dw1-') and tag.endswith('"') and not tag.startswith("W/")
    assert len(tag) == len('"dw1-"') + 32
    # Opaque: neither the date nor the revision id can be read from it.
    assert "2026" not in tag and str(REVISION)[:8] not in tag


def test_etag_ignores_text_because_an_approved_revision_is_immutable() -> None:
    assert compute_etag(row(term="autre", definition="autre")) == compute_etag(row())


@pytest.mark.parametrize(
    "change",
    [
        {"haiti_date": date(2026, 11, 25)},  # the same word scheduled again another day
        {"requested_locale": "ht", "is_fallback_locale": True},  # fallback representation
        {"requested_locale": "ht", "locale": "ht"},
        {"word_revision_id": uuid.UUID("44444444-4444-4444-8444-444444444444")},
        {"audio_asset_id": AUDIO},  # recording present vs withdrawn
    ],
)
def test_etag_changes_whenever_the_representation_can_change(change: dict[str, Any]) -> None:
    assert compute_etag(row(**change)) != compute_etag(row())


def test_all_distinct_assignments_get_distinct_tags() -> None:
    tags = {
        compute_etag(row(haiti_date=date(2026, 1, day), requested_locale=req, locale=served))
        for day in range(1, 29)
        for req, served in (("fr", "fr"), ("ht", "ht"), ("ht", "fr"))
    }
    assert len(tags) == 28 * 3


# ---------------------------------------------------------------- If-None-Match
ETAG = '"dw1-0123456789abcdef0123456789abcdef"'


@pytest.mark.parametrize(
    "header",
    [ETAG, f"W/{ETAG}", "*", f'"a", {ETAG}', f'"a",{ETAG},"b"', f"  {ETAG}  ", f'W/"a" , W/{ETAG}'],
)
def test_if_none_match_matches(header: str) -> None:
    assert if_none_match_matches(header, ETAG) is True


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        '"dw1-ffffffffffffffffffffffffffffffff"',
        ETAG.strip('"'),  # unquoted: not an entity tag
        ETAG[:-2] + '"',  # prefix of the tag
        '""',
        "W/",
        ",",
        "**",
    ],
)
def test_if_none_match_does_not_match(header: str | None) -> None:
    assert if_none_match_matches(header, ETAG) is False


# ---------------------------------------------------------------- response model
def test_build_response_without_and_with_audio() -> None:
    plain = build_response(row())
    assert plain.audio is None and plain.word.revision_id == REVISION
    assert plain.model_dump(mode="json")["valid_until"] == "2026-11-25T05:00:00Z"
    with_audio = build_response(
        row(
            audio_asset_id=AUDIO,
            audio_mime_type="audio/mp4",
            audio_byte_size=20480,
            audio_duration_ms=1200,
            audio_sha256="ab" * 32,
        )
    )
    assert with_audio.audio is not None
    assert with_audio.audio.model_dump(mode="json") == {
        "asset_id": str(AUDIO),
        "mime_type": "audio/mp4",
        "byte_size": 20480,
        "duration_ms": 1200,
        "sha256": "ab" * 32,
    }
    assert "autoplay" not in with_audio.model_dump_json()


# ---------------------------------------------------------------- feature flag
def test_flag_defaults_to_off_and_the_route_is_absent() -> None:
    assert settings().daily_word_enabled is False
    app = create_app(settings(), key_provider=StaticKeyProvider({}))
    assert "/v1/daily-word" not in {getattr(route, "path", None) for route in app.routes}
    assert "/v1/daily-word" not in app.openapi()["paths"]


def test_flag_on_mounts_the_route(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(settings(daily_word_enabled=True), key_provider=StaticKeyProvider({}))
    assert "/v1/daily-word" in app.openapi()["paths"]
    # The setting is read from EDU_DAILY_WORD_ENABLED.
    monkeypatch.setenv("EDU_DAILY_WORD_ENABLED", "true")
    assert settings().daily_word_enabled is True
