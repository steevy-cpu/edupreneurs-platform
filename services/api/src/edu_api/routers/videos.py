"""YouTube-01: the teacher-approved videos of one lesson (read-only).

The learner receives small video cards: id, title, channel, duration and links built
from the validated id. Playback happens in the official YouTube player, loaded only
when the learner taps Watch; nothing here downloads, proxies or caches video.

What this endpoint never does:

* contact YouTube (no key is used, no quota is spent on a learner request);
* return anything about the review (who approved, notes) or any provider secret;
* return a video that is not currently presentable. Row-level security in the
  database decides: approved by a second person, active, available, embeddable,
  not age-restricted, not blocked in Haiti, and metadata not expired.

A lesson without presentable videos returns an empty list: the lesson works without
them. The feature is behind ``EDU_VIDEOS_ENABLED`` (default false: 404).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text

from edu_api.deps import AppSettings, CurrentPrincipal, Db, Locale
from edu_api.errors import ApiError, error_responses
from edu_api.videos.ids import InvalidVideoId, channel_url, embed_url, thumbnail_url, watch_url


def _require_enabled(settings: AppSettings) -> None:
    if not settings.videos_enabled:
        raise ApiError(404, "not_found", "Not found.")


router = APIRouter(prefix="/v1", tags=["videos"], dependencies=[Depends(_require_enabled)])


class VideoCard(BaseModel):
    link_id: uuid.UUID
    provider: Literal["youtube"] = "youtube"
    video_id: str = Field(description="11-character YouTube video id.")
    title: str = Field(description="Title as published on YouTube; display unchanged.")
    channel_title: str = Field(description="Channel name; always displayed with the video.")
    channel_url: str
    duration_seconds: int
    start_seconds: int
    purpose: Literal["explanation", "example", "exercise_help", "enrichment"]
    audio_language: str | None
    made_for_kids: bool = Field(
        description="YouTube's Made-for-Kids designation. The app adds no engagement "
        "feature (comments, likes, sharing, tracking) around any video."
    )
    thumbnail_url: str = Field(
        description="Served by YouTube; display as-is, do not store or alter."
    )
    embed_url: str = Field(
        description="Official embedded player. Load only after the learner taps Watch."
    )
    watch_url: str = Field(
        description="Opens the video on YouTube: the fallback when embedding fails."
    )
    metadata_checked_at: dt.datetime


class LessonVideosResponse(BaseModel):
    lesson_id: uuid.UUID
    locale: Literal["fr", "ht"]
    requires_network: Literal[True] = Field(
        default=True, description="Videos are never available offline; the lesson text is."
    )
    videos: list[VideoCard]


_LESSON_VISIBLE = text(
    """
    SELECT 1 FROM app.lesson_revisions r
    WHERE r.lesson_id = :lesson_id AND r.locale = :locale
    LIMIT 1
    """
)

_VIDEOS = text(
    """
    SELECT k.id AS link_id, k.position, k.purpose, k.start_seconds,
           v.provider_video_id, v.title, v.channel_id, v.channel_title, v.duration_seconds,
           v.audio_language, v.made_for_kids, v.metadata_fetched_at
    FROM app.lesson_video_links k
    JOIN app.videos v ON v.id = k.video_id
    WHERE k.lesson_id = :lesson_id AND :locale = ANY (k.locales)
    ORDER BY k.position
    """
)


@router.get(
    "/lessons/{lesson_id}/videos",
    response_model=LessonVideosResponse,
    responses=error_responses(401, 404, 422, 503),
    summary="Teacher-approved YouTube videos for one published lesson",
)
async def get_lesson_videos(
    lesson_id: uuid.UUID, principal: CurrentPrincipal, db: Db, locale: Locale
) -> LessonVideosResponse:
    """Video cards for the lesson in `locale`, in teacher-chosen order.

    Same 404 as `GET /v1/lessons/{id}` for an unknown or unpublished lesson. An
    empty `videos` list is normal: the lesson is complete without video.
    """
    async with db.transaction(principal.user_id, read_only=True) as conn:
        visible = await conn.execute(_LESSON_VISIBLE, {"lesson_id": lesson_id, "locale": locale})
        if visible.one_or_none() is None:
            raise ApiError(404, "lesson_not_found", "No published lesson with this id and locale.")
        rows = (await conn.execute(_VIDEOS, {"lesson_id": lesson_id, "locale": locale})).all()

    cards: list[VideoCard] = []
    for r in rows:
        try:  # defence in depth: the database already constrains both ids
            cards.append(
                VideoCard(
                    link_id=r.link_id,
                    video_id=r.provider_video_id,
                    title=r.title,
                    channel_title=r.channel_title,
                    channel_url=channel_url(r.channel_id),
                    duration_seconds=r.duration_seconds,
                    start_seconds=r.start_seconds,
                    purpose=r.purpose,
                    audio_language=r.audio_language,
                    made_for_kids=r.made_for_kids,
                    thumbnail_url=thumbnail_url(r.provider_video_id),
                    embed_url=embed_url(r.provider_video_id),
                    watch_url=watch_url(r.provider_video_id, r.start_seconds),
                    metadata_checked_at=r.metadata_fetched_at,
                )
            )
        except InvalidVideoId:
            continue  # an unusable row is skipped, never shown
    return LessonVideosResponse(lesson_id=lesson_id, locale=locale, videos=cards)
