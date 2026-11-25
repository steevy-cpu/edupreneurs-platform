"""Response models of ``GET /v1/daily-word``."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

PartOfSpeech = Literal[
    "noun",
    "verb",
    "adjective",
    "adverb",
    "pronoun",
    "preposition",
    "conjunction",
    "interjection",
    "determiner",
    "expression",
]


class DailyWordContent(BaseModel):
    word_id: uuid.UUID = Field(description="Stable identity of the word across revisions.")
    revision_id: uuid.UUID = Field(description="The exact approved revision that is served.")
    revision: int
    term: str
    pronunciation: str | None = Field(description="Pronunciation help as text; not audio.")
    part_of_speech: PartOfSpeech = Field(
        description="Language-neutral code; the app shows its own localised label."
    )
    definition: str
    example: str
    gloss: str | None = Field(
        description="Optional short gloss in the other language (Creole for `fr`, French for `ht`)."
    )


class DailyWordAudio(BaseModel):
    """Metadata only. There is no download route yet and the app must never autoplay."""

    asset_id: uuid.UUID
    mime_type: str
    byte_size: int = Field(description="Size of the recording; never more than 102400 bytes.")
    duration_ms: int
    sha256: str = Field(description="Hex SHA-256 of the recording's bytes.")


class DailyWordResponse(BaseModel):
    haiti_date: date = Field(
        description="The America/Port-au-Prince calendar date this word belongs to, "
        "decided by the server clock."
    )
    locale: Literal["fr", "ht"] = Field(description="Language of the word that is served.")
    requested_locale: Literal["fr", "ht"]
    is_fallback_locale: bool = Field(
        description="True when the requested language has no approved translation today "
        "and the French word is served instead."
    )
    word: DailyWordContent
    audio: DailyWordAudio | None
    valid_until: datetime = Field(
        description="The instant of the next Haiti midnight (UTC). After it, a cached copy "
        "is no longer today's word and must be labelled as the last downloaded word."
    )
