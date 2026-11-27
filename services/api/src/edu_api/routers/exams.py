"""ExamHub-01: catalog -> attempt -> answers -> server scoring -> explanation -> history.

What makes this different from lesson practice:

* Questions are delivered WITHOUT their answer key or explanation. The API's
  database role cannot even select those columns; they come back only from the
  database functions, after the learner has answered (practice) or finished
  (timed).
* The score is computed by the database from the stored key. The client never
  sends a score, a verdict or a time.
* A timed attempt is bounded by the server clock. The phone's countdown is a
  display; an answer that arrives after the deadline is refused.

The whole feature is behind ``EDU_EXAMS_ENABLED`` (default false). While it is
off every route here answers 404.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from edu_api.deps import AppSettings, CurrentPrincipal, Db, Locale
from edu_api.errors import ApiError, error_responses
from edu_api.identity import ensure_learner_profile
from edu_api.routers.catalog import LabelledCode, LabelledSlug

ExamType = Literal["official", "model", "practice", "rattrapage"]
Series = Literal["SMP", "SES", "SVT", "LLA"]
Mode = Literal["practice", "timed"]
AttemptStatus = Literal["in_progress", "finished", "expired"]


def _require_enabled(settings: AppSettings) -> None:
    if not settings.exams_enabled:
        raise ApiError(404, "not_found", "Not found.")


router = APIRouter(prefix="/v1", tags=["exams"], dependencies=[Depends(_require_enabled)])


# --- models -----------------------------------------------------------------------
class ExamSummary(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    grade: LabelledCode
    subject: LabelledSlug
    series: Series | None
    exam_type: ExamType
    session_year: int | None
    duration_minutes: int
    question_count: int = Field(description="Questions available in the requested language.")
    max_points: int = Field(
        description="Points that can be scored automatically (multiple choice)."
    )


class ExamCatalogResponse(BaseModel):
    locale: Literal["fr", "ht"]
    exams: list[ExamSummary]


class ExamQuestion(BaseModel):
    """A question as delivered during an attempt: never with its key or explanation."""

    id: uuid.UUID
    position: int
    kind: Literal["mcq", "open"]
    points: int
    prompt: dict[str, Any]
    response_spec: dict[str, Any]


class Attempt(BaseModel):
    id: uuid.UUID
    exam_id: uuid.UUID
    locale: Literal["fr", "ht"]
    mode: Mode
    status: AttemptStatus
    started_at: dt.datetime
    expires_at: dt.datetime | None = Field(
        description="Timed attempts only. Server time after which answers are refused."
    )
    finished_at: dt.datetime | None
    score_points: int | None = Field(description="Null until the attempt is closed.")
    max_points: int | None
    counts_as_exam_score: bool = Field(
        description="True only for a timed attempt. A practice attempt is never an exam score."
    )


class StartAttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Mode
    locale: Literal["fr", "ht"] = "fr"


class StartAttemptResponse(BaseModel):
    attempt: Attempt
    resumed: bool = Field(
        description="True when an open timed attempt was returned instead of a new one."
    )
    server_time: dt.datetime
    questions: list[ExamQuestion]


class SubmitAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: uuid.UUID
    response: dict[str, Any] = Field(
        description='`{"choice_id": "..."}` (multiple choice) or `{"text": "..."}` (open answer).'
    )


class SubmitAnswerResponse(BaseModel):
    recorded: Literal[True] = True
    feedback_available: bool = Field(
        description="True in practice mode. In timed mode nothing is revealed before finishing."
    )
    is_correct: bool | None = Field(
        default=None,
        description="Null in timed mode and for open answers (not scored automatically).",
    )
    answer_key: dict[str, Any] | None = None
    explanation: dict[str, Any] | None = None


class ReviewItem(BaseModel):
    question_id: uuid.UUID
    position: int
    kind: Literal["mcq", "open"]
    points: int
    prompt: dict[str, Any]
    response_spec: dict[str, Any]
    response: dict[str, Any] | None
    is_correct: bool | None
    points_awarded: int
    revealed: bool = Field(description="False while the key of this question is still withheld.")
    answer_key: dict[str, Any] | None
    explanation: dict[str, Any] | None


class AttemptDetailResponse(BaseModel):
    attempt: Attempt
    server_time: dt.datetime
    items: list[ReviewItem]


class AttemptHistoryResponse(BaseModel):
    attempts: list[Attempt]


# --- SQL ---------------------------------------------------------------------------
_EXAMS = text(
    """
    SELECT e.id, e.slug, COALESCE(e.titles ->> :locale, e.titles ->> 'fr') AS title,
           g.code AS grade_code, COALESCE(g.labels ->> :locale, g.labels ->> 'fr') AS grade_label,
           s.slug AS subject_slug,
           COALESCE(s.labels ->> :locale, s.labels ->> 'fr') AS subject_label,
           e.series, e.exam_type, e.session_year, e.duration_minutes,
           q.question_count, q.max_points
    FROM app.exams e
    JOIN app.grades g ON g.id = e.grade_id
    JOIN app.subjects s ON s.id = e.subject_id
    JOIN LATERAL (
        SELECT count(*) AS question_count,
               COALESCE(sum(x.points) FILTER (WHERE x.kind = 'mcq'), 0) AS max_points
        FROM app.exam_questions x
        WHERE x.exam_id = e.id AND x.locale = :locale
    ) q ON q.question_count > 0
    WHERE (CAST(:exam_id AS uuid) IS NULL OR e.id = CAST(:exam_id AS uuid))
      AND (CAST(:grade AS text) IS NULL OR g.code = CAST(:grade AS text))
      AND (CAST(:subject AS text) IS NULL OR s.slug = CAST(:subject AS text))
      AND (CAST(:series AS text) IS NULL OR e.series = CAST(:series AS text))
      AND (CAST(:exam_type AS text) IS NULL OR e.exam_type = CAST(:exam_type AS text))
    ORDER BY g.sort_order, s.slug, e.session_year DESC NULLS LAST, e.slug
    """
)

_QUESTIONS = text(
    """
    SELECT q.id, q.position, q.kind, q.points, q.prompt, q.response_spec
    FROM app.exam_questions q
    WHERE q.exam_id = :exam_id AND q.locale = :locale
    ORDER BY q.position
    """
)

_ATTEMPT_COLUMNS = """
    a.id, a.exam_id, a.locale, a.mode, a.status, a.started_at, a.expires_at,
    a.finished_at, a.score_points, a.max_points
"""
_ATTEMPT = text(f"SELECT {_ATTEMPT_COLUMNS} FROM app.exam_attempts a WHERE a.id = :attempt_id")  # noqa: S608
_ATTEMPTS = text(
    f"""
    SELECT {_ATTEMPT_COLUMNS} FROM app.exam_attempts a
    WHERE (CAST(:exam_id AS uuid) IS NULL OR a.exam_id = CAST(:exam_id AS uuid))
    ORDER BY a.started_at DESC, a.id
    LIMIT :limit
    """  # noqa: S608
)
_START = text("SELECT app.exam_start_attempt(:exam_id, :locale, :mode)")
_SUBMIT = text("SELECT app.exam_submit_answer(:attempt_id, :question_id, CAST(:response AS jsonb))")
_FINISH = text("SELECT app.exam_finish_attempt(:attempt_id)")
_REVIEW = text("SELECT app.exam_attempt_review(:attempt_id)")
_NOW = text("SELECT now()")


def _summary(row: Any) -> ExamSummary:
    return ExamSummary(
        id=row.id,
        slug=row.slug,
        title=row.title,
        grade=LabelledCode(code=row.grade_code, label=row.grade_label),
        subject=LabelledSlug(slug=row.subject_slug, label=row.subject_label),
        series=row.series,
        exam_type=row.exam_type,
        session_year=row.session_year,
        duration_minutes=row.duration_minutes,
        question_count=row.question_count,
        max_points=row.max_points,
    )


def _attempt(row: Any) -> Attempt:
    return Attempt(
        id=row.id,
        exam_id=row.exam_id,
        locale=row.locale,
        mode=row.mode,
        status=row.status,
        started_at=row.started_at,
        expires_at=row.expires_at,
        finished_at=row.finished_at,
        score_points=row.score_points,
        max_points=row.max_points,
        counts_as_exam_score=row.mode == "timed",
    )


def _not_found() -> ApiError:
    # One message for "does not exist", "not published", "not in this language" and "not yours".
    return ApiError(404, "not_found", "Not found.")


async def _load_attempt(conn: AsyncConnection, attempt_id: uuid.UUID) -> Attempt:
    """The caller's own attempt (row-level security hides everyone else's)."""
    row = (await conn.execute(_ATTEMPT, {"attempt_id": attempt_id})).one_or_none()
    if row is None:
        raise _not_found()
    return _attempt(row)


# --- catalog -----------------------------------------------------------------------
@router.get(
    "/exams",
    response_model=ExamCatalogResponse,
    responses=error_responses(401, 404, 422, 503),
    summary="Published exams available in one language",
)
async def list_exams(
    principal: CurrentPrincipal,
    db: Db,
    locale: Locale,
    grade: Annotated[
        str | None, Query(max_length=8, description="Grade code, e.g. `9AF` or `NS4`.")
    ] = None,
    subject: Annotated[str | None, Query(max_length=80, description="Subject slug.")] = None,
    series: Annotated[Series | None, Query(description="Baccalauréat series.")] = None,
    exam_type: Annotated[ExamType | None, Query(description="Kind of paper.")] = None,
) -> ExamCatalogResponse:
    """Only published exams that have at least one question in `locale`."""
    params = {
        "locale": locale,
        "exam_id": None,
        "grade": grade,
        "subject": subject,
        "series": series,
        "exam_type": exam_type,
    }
    async with db.transaction(principal.user_id, read_only=True) as conn:
        rows = (await conn.execute(_EXAMS, params)).all()
    return ExamCatalogResponse(locale=locale, exams=[_summary(r) for r in rows])


@router.get(
    "/exams/{exam_id}",
    response_model=ExamSummary,
    responses=error_responses(401, 404, 422, 503),
    summary="One published exam (no questions)",
)
async def get_exam(
    exam_id: uuid.UUID, principal: CurrentPrincipal, db: Db, locale: Locale
) -> ExamSummary:
    """Metadata only. Questions are delivered when an attempt is started."""
    params = {
        "locale": locale,
        "exam_id": exam_id,
        "grade": None,
        "subject": None,
        "series": None,
        "exam_type": None,
    }
    async with db.transaction(principal.user_id, read_only=True) as conn:
        row = (await conn.execute(_EXAMS, params)).one_or_none()
    if row is None:
        raise _not_found()
    return _summary(row)


# --- attempts ----------------------------------------------------------------------
@router.post(
    "/exams/{exam_id}/attempts",
    response_model=StartAttemptResponse,
    responses=error_responses(401, 404, 422, 503),
    summary="Start (or resume) an attempt and receive the questions without keys",
)
async def start_attempt(
    exam_id: uuid.UUID, body: StartAttemptRequest, principal: CurrentPrincipal, db: Db
) -> StartAttemptResponse:
    """Timed attempts need a live connection and are bounded by `expires_at` (server clock).

    Starting a timed attempt while one is still open returns the open one
    (`resumed: true`): a learner cannot hold two clocks on the same exam.
    """
    async with db.transaction(principal.user_id) as conn:
        await ensure_learner_profile(conn, principal.user_id)
        result = (
            await conn.execute(
                _START, {"exam_id": exam_id, "locale": body.locale, "mode": body.mode}
            )
        ).scalar_one()
        if result["status"] not in ("started", "resumed"):
            raise _not_found()
        attempt = await _load_attempt(conn, uuid.UUID(result["attempt_id"]))
        questions = (
            await conn.execute(_QUESTIONS, {"exam_id": exam_id, "locale": attempt.locale})
        ).all()
        now = (await conn.execute(_NOW)).scalar_one()
    return StartAttemptResponse(
        attempt=attempt,
        resumed=result["status"] == "resumed",
        server_time=now,
        questions=[
            ExamQuestion(
                id=q.id,
                position=q.position,
                kind=q.kind,
                points=q.points,
                prompt=q.prompt,
                response_spec=q.response_spec,
            )
            for q in questions
        ],
    )


@router.post(
    "/exam-attempts/{attempt_id}/answers",
    response_model=SubmitAnswerResponse,
    responses=error_responses(401, 404, 409, 422, 503),
    summary="Submit one answer; the server decides whether it is correct",
)
async def submit_answer(
    attempt_id: uuid.UUID, body: SubmitAnswerRequest, principal: CurrentPrincipal, db: Db
) -> SubmitAnswerResponse:
    """Practice: the verdict, the key and the explanation come back, and the answer is final.

    Timed: the answer is recorded (it may be changed until the attempt is
    finished) and nothing is revealed. After `expires_at` the answer is refused
    with `409 attempt_expired`.
    """
    async with db.transaction(principal.user_id) as conn:
        result = (
            await conn.execute(
                _SUBMIT,
                {
                    "attempt_id": attempt_id,
                    "question_id": body.question_id,
                    "response": json.dumps(body.response),
                },
            )
        ).scalar_one()
    status = result["status"]
    if status in ("attempt_not_found", "question_not_found", "unauthenticated"):
        raise _not_found()
    if status == "invalid_response":
        raise ApiError(422, "validation_error", "The response does not fit this question.")
    if status == "attempt_expired":
        raise ApiError(409, "attempt_expired", "The time for this attempt is over.")
    if status == "attempt_closed":
        raise ApiError(409, "attempt_closed", "This attempt is already finished.")
    if status == "already_answered":
        raise ApiError(
            409, "already_answered", "This question was already answered in this practice attempt."
        )
    revealed = "answer_key" in result
    return SubmitAnswerResponse(
        feedback_available=revealed,
        is_correct=result.get("is_correct") if revealed else None,
        answer_key=result.get("answer_key"),
        explanation=result.get("explanation"),
    )


async def _detail(conn: AsyncConnection, attempt_id: uuid.UUID) -> AttemptDetailResponse:
    attempt = await _load_attempt(conn, attempt_id)
    items = (await conn.execute(_REVIEW, {"attempt_id": attempt_id})).scalar_one()
    now = (await conn.execute(_NOW)).scalar_one()
    return AttemptDetailResponse(
        attempt=attempt, server_time=now, items=[ReviewItem(**item) for item in (items or [])]
    )


@router.post(
    "/exam-attempts/{attempt_id}/finish",
    response_model=AttemptDetailResponse,
    responses=error_responses(401, 404, 422, 503),
    summary="Finish an attempt: the server scores it and reveals keys and explanations",
)
async def finish_attempt(
    attempt_id: uuid.UUID, principal: CurrentPrincipal, db: Db
) -> AttemptDetailResponse:
    """Safe to repeat: finishing a closed attempt returns the same result."""
    async with db.transaction(principal.user_id) as conn:
        result = (await conn.execute(_FINISH, {"attempt_id": attempt_id})).scalar_one()
        if result["status"] != "closed":
            raise _not_found()
        return await _detail(conn, attempt_id)


@router.get(
    "/exam-attempts",
    response_model=AttemptHistoryResponse,
    responses=error_responses(401, 404, 422, 503),
    summary="The signed-in learner's attempts, newest first",
)
async def list_attempts(
    principal: CurrentPrincipal,
    db: Db,
    exam_id: Annotated[uuid.UUID | None, Query(description="Only attempts of this exam.")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AttemptHistoryResponse:
    async with db.transaction(principal.user_id, read_only=True) as conn:
        rows = (await conn.execute(_ATTEMPTS, {"exam_id": exam_id, "limit": limit})).all()
    return AttemptHistoryResponse(attempts=[_attempt(r) for r in rows])


@router.get(
    "/exam-attempts/{attempt_id}",
    response_model=AttemptDetailResponse,
    responses=error_responses(401, 404, 422, 503),
    summary="One of the learner's own attempts, with what may be revealed so far",
)
async def get_attempt(
    attempt_id: uuid.UUID, principal: CurrentPrincipal, db: Db
) -> AttemptDetailResponse:
    """While a timed attempt is open, `answer_key` and `explanation` are null for every question."""
    async with db.transaction(principal.user_id, read_only=True) as conn:
        return await _detail(conn, attempt_id)
