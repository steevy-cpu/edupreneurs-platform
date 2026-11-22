"""Learner profile access."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_INSERT_PROFILE = text(
    "INSERT INTO app.learner_profiles (user_id) VALUES (:user_id) ON CONFLICT (user_id) DO NOTHING"
)

_SELECT_PROFILE = text(
    "SELECT p.user_id, p.preferred_locale, p.display_name, p.created_at, "
    "       g.id AS grade_id, g.code AS grade_code, "
    "       COALESCE(g.labels ->> p.preferred_locale, g.labels ->> 'fr') AS grade_label "
    "FROM app.learner_profiles p "
    "LEFT JOIN app.grades g ON g.id = p.grade_id "
    "WHERE p.user_id = :user_id"
)


class GradeRef(BaseModel):
    id: uuid.UUID
    code: str
    label: str


class MeResponse(BaseModel):
    user_id: uuid.UUID
    preferred_locale: str
    display_name: str | None
    grade: GradeRef | None
    created_at: datetime


async def ensure_learner_profile(conn: AsyncConnection, user_id: uuid.UUID) -> None:
    """Create the caller's profile row if it does not exist yet (idempotent).

    Any signed-in account becomes a learner on first contact. The row can only
    be the caller's own: the INSERT policy requires
    ``user_id = app.current_actor_id()`` and the API role may set no other column.
    """
    await conn.execute(_INSERT_PROFILE, {"user_id": user_id})


async def load_profile(conn: AsyncConnection, user_id: uuid.UUID) -> MeResponse | None:
    row = (await conn.execute(_SELECT_PROFILE, {"user_id": user_id})).one_or_none()
    if row is None:
        return None
    grade = (
        GradeRef(id=row.grade_id, code=row.grade_code, label=row.grade_label)
        if row.grade_id is not None and row.grade_code is not None
        else None
    )
    return MeResponse(
        user_id=row.user_id,
        preferred_locale=row.preferred_locale,
        display_name=row.display_name,
        grade=grade,
        created_at=row.created_at,
    )
