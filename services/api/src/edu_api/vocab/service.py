"""Word of the Day: the one query, the entity tag, and ``If-None-Match`` matching.

The student API role can execute exactly one function in schema ``vocab``:
``vocab.daily_word(locale)``. That function decides what "today" is (the
America/Port-au-Prince date of the SERVER clock) and returns at most one row:
an approved revision assigned to exactly that date. Nothing here accepts a
date or a time from the client.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from edu_api.vocab.schemas import DailyWordAudio, DailyWordContent, DailyWordResponse

_DAILY_WORD = text("SELECT * FROM vocab.daily_word(:locale)")

#: Bump when the JSON representation changes for the same assignment, so that
#: every cached entity tag stops matching.
ETAG_VERSION = "dw1"


async def load_daily_word(conn: AsyncConnection, locale: str) -> Any | None:
    """Today's row for ``locale`` (French fallback applied in SQL), or ``None``."""
    return (await conn.execute(_DAILY_WORD, {"locale": locale})).one_or_none()


def compute_etag(row: Any) -> str:
    """Strong entity tag derived from the assignment identity.

    The response body is a pure function of: the Haiti date, the requested and
    the served locale, the served revision (approved revisions are immutable)
    and whether its recording is included (recording metadata is immutable
    too, but its rights can be withdrawn). So those are exactly the inputs.
    """
    identity = "|".join(
        (
            ETAG_VERSION,
            row.haiti_date.isoformat(),
            row.requested_locale,
            row.locale,
            str(row.word_revision_id),
            str(row.audio_asset_id) if row.audio_asset_id is not None else "-",
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f'"{ETAG_VERSION}-{digest}"'


def if_none_match_matches(header: str | None, etag: str) -> bool:
    """RFC 9110 §13.1.2: weak comparison of each listed tag, or ``*``."""
    if header is None:
        return False
    opaque = etag.removeprefix("W/")
    for candidate in header.split(","):
        candidate = candidate.strip()
        if candidate == "*" or candidate.removeprefix("W/") == opaque:
            return True
    return False


def build_response(row: Any) -> DailyWordResponse:
    audio = (
        DailyWordAudio(
            asset_id=row.audio_asset_id,
            mime_type=row.audio_mime_type,
            byte_size=row.audio_byte_size,
            duration_ms=row.audio_duration_ms,
            sha256=row.audio_sha256,
        )
        if row.audio_asset_id is not None
        else None
    )
    return DailyWordResponse(
        haiti_date=row.haiti_date,
        locale=row.locale,
        requested_locale=row.requested_locale,
        is_fallback_locale=row.is_fallback_locale,
        word=DailyWordContent(
            word_id=row.word_id,
            revision_id=row.word_revision_id,
            revision=row.revision,
            term=row.term,
            pronunciation=row.pronunciation,
            part_of_speech=row.part_of_speech,
            definition=row.definition,
            example=row.example,
            gloss=row.gloss,
        ),
        audio=audio,
        valid_until=row.valid_until,
    )
