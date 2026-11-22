"""Published curriculum: catalog and lesson content.

Every query here runs as the least-privileged ``edu_api`` role, whose row-level
security policies only reveal approved revisions that are in a *current* pack
of a *published* course. The SQL below does not repeat those rules: if a draft
ever appeared in a response, tests/integration/test_content_visibility.py fails.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from edu_api.deps import CurrentPrincipal, Db, Locale
from edu_api.errors import ApiError, error_responses

router = APIRouter(prefix="/v1", tags=["catalog"])


# --- catalog --------------------------------------------------------------------
class CatalogLesson(BaseModel):
    id: uuid.UUID
    slug: str
    position: int
    title: str
    revision_id: uuid.UUID
    revision: int


class CatalogUnit(BaseModel):
    id: uuid.UUID
    slug: str
    position: int
    title: str
    lessons: list[CatalogLesson]


class LabelledCode(BaseModel):
    code: str
    label: str


class LabelledSlug(BaseModel):
    slug: str
    label: str


class CatalogCourse(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    grade: LabelledCode
    subject: LabelledSlug
    units: list[CatalogUnit]


class CatalogResponse(BaseModel):
    locale: Literal["fr", "ht"]
    courses: list[CatalogCourse]


# Labels fall back to French when a Creole label is missing (labels always have 'fr').
_CATALOG = text(
    """
    SELECT c.id AS course_id, c.slug AS course_slug,
           COALESCE(c.titles ->> :locale, c.titles ->> 'fr') AS course_title,
           g.code AS grade_code,
           COALESCE(g.labels ->> :locale, g.labels ->> 'fr') AS grade_label,
           s.slug AS subject_slug,
           COALESCE(s.labels ->> :locale, s.labels ->> 'fr') AS subject_label,
           u.id AS unit_id, u.slug AS unit_slug, u.position AS unit_position,
           COALESCE(u.titles ->> :locale, u.titles ->> 'fr') AS unit_title,
           l.id AS lesson_id, l.slug AS lesson_slug, l.position AS lesson_position,
           lr.id AS revision_id, lr.revision AS revision, lr.title AS lesson_title
    FROM app.courses c
    JOIN app.grades g ON g.id = c.grade_id
    JOIN app.subjects s ON s.id = c.subject_id
    JOIN app.units u ON u.course_id = c.id
    JOIN app.lessons l ON l.unit_id = u.id
    JOIN LATERAL (
        SELECT r.id, r.revision, r.title
        FROM app.lesson_revisions r
        WHERE r.lesson_id = l.id AND r.locale = :locale
        ORDER BY r.revision DESC
        LIMIT 1
    ) lr ON true
    ORDER BY g.sort_order, s.slug, c.slug, u.position, l.position
    """
)


@router.get(
    "/catalog",
    response_model=CatalogResponse,
    responses=error_responses(401, 422, 503),
    summary="Published courses, units and lessons for one language",
)
async def get_catalog(principal: CurrentPrincipal, db: Db, locale: Locale) -> CatalogResponse:
    """Compact tree of everything a learner can open in `locale`.

    Only lessons that have a published revision in that language are listed.
    """
    async with db.transaction(principal.user_id, read_only=True) as conn:
        rows = (await conn.execute(_CATALOG, {"locale": locale})).all()

    courses: dict[uuid.UUID, CatalogCourse] = {}
    units: dict[uuid.UUID, CatalogUnit] = {}
    for row in rows:
        course = courses.get(row.course_id)
        if course is None:
            course = courses[row.course_id] = CatalogCourse(
                id=row.course_id,
                slug=row.course_slug,
                title=row.course_title,
                grade=LabelledCode(code=row.grade_code, label=row.grade_label),
                subject=LabelledSlug(slug=row.subject_slug, label=row.subject_label),
                units=[],
            )
        unit = units.get(row.unit_id)
        if unit is None:
            unit = units[row.unit_id] = CatalogUnit(
                id=row.unit_id,
                slug=row.unit_slug,
                position=row.unit_position,
                title=row.unit_title,
                lessons=[],
            )
            course.units.append(unit)
        unit.lessons.append(
            CatalogLesson(
                id=row.lesson_id,
                slug=row.lesson_slug,
                position=row.lesson_position,
                title=row.lesson_title,
                revision_id=row.revision_id,
                revision=row.revision,
            )
        )
    return CatalogResponse(locale=locale, courses=list(courses.values()))


# --- lesson ---------------------------------------------------------------------
class PracticeQuestion(BaseModel):
    id: uuid.UUID = Field(description="question_revision_id to send back in practice_answer.")
    question_key: str
    position: int
    kind: str
    prompt: dict[str, Any]
    response_spec: dict[str, Any]
    answer_key: dict[str, Any] = Field(
        description="Shipped so the phone can give feedback OFFLINE. Practice only: "
        "the server still re-scores every synced answer itself."
    )
    explanation: dict[str, Any]


class LessonResponse(BaseModel):
    lesson_id: uuid.UUID
    revision_id: uuid.UUID
    revision: int
    locale: Literal["fr", "ht"]
    title: str
    blocks: list[dict[str, Any]]
    questions: list[PracticeQuestion]
    assessment_mode: Literal["offline_practice"] = Field(
        default="offline_practice",
        description="These questions include their answer keys and must never be used "
        "for graded or high-stakes assessment.",
    )


_LESSON_REVISION = text(
    """
    SELECT r.id, r.lesson_id, r.revision, r.locale, r.title, r.blocks
    FROM app.lesson_revisions r
    WHERE r.lesson_id = :lesson_id AND r.locale = :locale
    ORDER BY r.revision DESC
    LIMIT 1
    """
)

_LESSON_QUESTIONS = text(
    """
    SELECT q.id, q.question_key, q.position, q.kind, q.prompt, q.response_spec,
           q.answer_key, q.explanation
    FROM app.question_revisions q
    WHERE q.lesson_revision_id = :revision_id
    ORDER BY q.position
    """
)


@router.get(
    "/lessons/{lesson_id}",
    response_model=LessonResponse,
    responses=error_responses(401, 404, 422, 503),
    summary="One published lesson with its offline-practice questions",
)
async def get_lesson(
    lesson_id: uuid.UUID, principal: CurrentPrincipal, db: Db, locale: Locale
) -> LessonResponse:
    """The currently published revision of a lesson in `locale`.

    Unknown lessons, drafts, rejected revisions and lessons without a published
    revision in this language all return the same 404.
    """
    async with db.transaction(principal.user_id, read_only=True) as conn:
        revision = (
            await conn.execute(_LESSON_REVISION, {"lesson_id": lesson_id, "locale": locale})
        ).one_or_none()
        if revision is None:
            raise ApiError(404, "lesson_not_found", "No published lesson with this id and locale.")
        questions = (await conn.execute(_LESSON_QUESTIONS, {"revision_id": revision.id})).all()

    return LessonResponse(
        lesson_id=revision.lesson_id,
        revision_id=revision.id,
        revision=revision.revision,
        locale=revision.locale,
        title=revision.title,
        blocks=revision.blocks,
        questions=[
            PracticeQuestion(
                id=q.id,
                question_key=q.question_key,
                position=q.position,
                kind=q.kind,
                prompt=q.prompt,
                response_spec=q.response_spec,
                answer_key=q.answer_key,
                explanation=q.explanation,
            )
            for q in questions
        ],
    )
