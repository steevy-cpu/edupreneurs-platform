"""Word of the Day — staff workflow under ``/v1/staff/vocab``.

Every route goes through ``require_staff`` (token, staff pool, active role
read on each request, refusals audited) and then calls ONE ``vocab.*``
database function as ``edu_staff_login``. That function checks the role again,
writes the audit event in the same transaction, and the integrity triggers
enforce the rules that matter most whatever this file does: the reviewer is
never the author, nothing is approved without cleared rights, approved text
and opened days are immutable.

Roles (recorded choice, see docs/overnight-2026-11-24/lanes/vocab.md):
  write / submit, register a source ....... editor, admin
  review ................................... reviewer, admin
  rights, schedule, retire, run the fill ... publisher, admin
  read the queue and the calendar .......... any staff role
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from edu_api.db.session import Database
from edu_api.errors import ApiError, error_responses
from edu_api.staff.deps import AnyStaff, StaffDb, StaffPrincipal, require_staff
from edu_api.vocab.schemas import PartOfSpeech

logger = logging.getLogger("edu_api.staff_vocab")

#: Ruling R-01: new paths stay out of the generated contract on lane branches.
INCLUDE_IN_SCHEMA = False

router = APIRouter(prefix="/v1/staff/vocab", tags=["staff-vocab"])

Writer = Annotated[StaffPrincipal, Depends(require_staff("editor", "admin"))]
SourceWriter = Annotated[StaffPrincipal, Depends(require_staff("editor", "publisher", "admin"))]
Reviewer = Annotated[StaffPrincipal, Depends(require_staff("reviewer", "admin"))]
Publisher = Annotated[StaffPrincipal, Depends(require_staff("publisher", "admin"))]

_ERRORS = error_responses(401, 403, 404, 409, 422, 503)
_AUDIT_DENIED = text(
    "SELECT ops.audit_write('vocab.access', NULL, NULL, 'denied', CAST(:details AS jsonb))"
)


def _route(request: Request) -> str:
    path = getattr(request.scope.get("route"), "path", None)
    return path if isinstance(path, str) and len(path) <= 120 else "unknown"


@asynccontextmanager
async def staff_tx(
    db: Database, staff: StaffPrincipal, request: Request
) -> AsyncIterator[AsyncConnection]:
    """One staff transaction; database refusals become clean API errors.

    The messages passed through for 409 are the fixed sentences of the vocab
    integrity rules (they never contain a value). A refusal by the database
    (42501, e.g. "only the author can change this draft") is recorded as a
    ``denied`` audit event in its own committed transaction.
    """
    try:
        async with db.transaction(staff.user_id) as conn:
            yield conn
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        cause = getattr(exc.orig, "__cause__", None)
        message = getattr(cause, "message", None)
        rule = message if isinstance(message, str) and len(message) <= 200 else None
        if sqlstate == "42501":
            details = {"method": request.method, "route": _route(request), "reason": "rule"}
            async with db.transaction(staff.user_id) as conn:
                await conn.execute(_AUDIT_DENIED, {"details": json.dumps(details)})
            raise ApiError(403, "forbidden", "You do not have access to this resource.") from None
        if sqlstate == "P0002":
            raise ApiError(404, "vocab_not_found", rule or "Not found.") from None
        if sqlstate == "P0001":
            raise ApiError(
                409, "vocab_rule_violation", rule or "An editorial or schedule rule refused this."
            ) from None
        if sqlstate in ("23505", "23503"):
            raise ApiError(
                409, "vocab_conflict", "This conflicts with an existing record."
            ) from None
        if sqlstate == "23514":
            constraint = getattr(cause, "constraint_name", None)
            if constraint:  # a table CHECK: length, closed list, byte budget, size cap
                raise ApiError(
                    422,
                    "vocab_invalid_content",
                    "The content breaks a size or format limit.",
                    details=[{"constraint": str(constraint)}],
                ) from None
            raise ApiError(409, "vocab_rule_violation", rule or "A rule refused this.") from None
        if sqlstate in ("22023", "23502", "22P02"):
            raise ApiError(422, "validation_error", "Request validation failed.") from None
        raise


# --- request / response models ----------------------------------------------------
class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceIn(_Body):
    source_title: str = Field(min_length=1, max_length=240)
    source_uri: str | None = Field(default=None, min_length=1, max_length=500)
    licence: str = Field(min_length=1, max_length=120)
    rights_notes: str | None = Field(default=None, max_length=1000)


class RightsIn(_Body):
    rights_status: Literal["unverified", "cleared", "restricted", "blocked"]
    rights_notes: str | None = Field(default=None, max_length=1000)


class WordIn(_Body):
    slug: str = Field(pattern=r"^[a-z0-9-]{2,80}$")


class RevisionContent(_Body):
    term: str = Field(min_length=1, max_length=60)
    pronunciation: str | None = Field(default=None, min_length=1, max_length=80)
    part_of_speech: PartOfSpeech
    definition: str = Field(min_length=1, max_length=300)
    example: str = Field(min_length=1, max_length=240)
    gloss: str | None = Field(default=None, min_length=1, max_length=80)
    source_id: uuid.UUID


class RevisionIn(RevisionContent):
    locale: Literal["fr", "ht"]


class AudioIn(_Body):
    """Metadata of a recording that already exists in storage. No bytes are sent here."""

    object_key: str = Field(pattern=r"^[a-z0-9][a-z0-9/_.-]{2,119}$")
    byte_size: int = Field(ge=1, le=102_400)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: Literal["audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg"]
    duration_ms: int = Field(ge=1, le=15_000)
    source_id: uuid.UUID


class ReviewIn(_Body):
    verdict: Literal["approved", "rejected"]
    notes: str | None = Field(default=None, max_length=1000)


class ScheduleIn(_Body):
    word_id: uuid.UUID


class EnsureIn(_Body):
    from_date: date
    days: int = Field(ge=1, le=62)


class IdOut(BaseModel):
    id: uuid.UUID


class OkOut(BaseModel):
    ok: Literal[True] = True


class RowsOut(BaseModel):
    rows: int


class QueueItem(BaseModel):
    word_revision_id: uuid.UUID
    word_id: uuid.UUID
    slug: str
    locale: str
    revision: int
    term: str
    pronunciation: str | None
    part_of_speech: str
    definition: str
    example: str
    gloss: str | None
    source_id: uuid.UUID
    source_rights_status: str
    has_audio: bool
    created_by: uuid.UUID
    created_at: datetime


class QueueOut(BaseModel):
    items: list[QueueItem]


class CalendarItem(BaseModel):
    haiti_date: date
    locale: str
    word_id: uuid.UUID
    slug: str
    word_revision_id: uuid.UUID
    revision: int
    term: str
    assigned_via: str
    assigned_by: uuid.UUID | None
    assigned_at: datetime
    is_locked: bool


class CalendarOut(BaseModel):
    items: list[CalendarItem]


class AssignedItem(BaseModel):
    haiti_date: date
    locale: str
    word_id: uuid.UUID
    word_revision_id: uuid.UUID


class EnsureOut(BaseModel):
    created: list[AssignedItem]


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(row._mapping) for row in result.all()]


_CONTENT_ARGS = ":term, :pronunciation, :part_of_speech, :definition, :example, :gloss, :source_id"


# --- sources ----------------------------------------------------------------------
@router.post(
    "/sources",
    response_model=IdOut,
    responses=_ERRORS,
    summary="Register a source / licence record (rights start unverified)",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def register_source(
    body: SourceIn, staff: SourceWriter, db: StaffDb, request: Request
) -> IdOut:
    async with staff_tx(db, staff, request) as conn:
        new_id = (
            await conn.execute(
                text("SELECT vocab.register_source(:t, :u, :l, :n)"),
                {
                    "t": body.source_title,
                    "u": body.source_uri,
                    "l": body.licence,
                    "n": body.rights_notes,
                },
            )
        ).scalar_one()
    return IdOut(id=new_id)


@router.put(
    "/sources/{source_id}/rights",
    response_model=OkOut,
    responses=_ERRORS,
    summary="Record a rights decision for a source",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def set_source_rights(
    source_id: uuid.UUID, body: RightsIn, staff: Publisher, db: StaffDb, request: Request
) -> OkOut:
    async with staff_tx(db, staff, request) as conn:
        await conn.execute(
            text("SELECT vocab.set_source_rights(:id, :s, :n)"),
            {"id": source_id, "s": body.rights_status, "n": body.rights_notes},
        )
    return OkOut()


# --- words and drafts ---------------------------------------------------------------
@router.post(
    "/words",
    response_model=IdOut,
    responses=_ERRORS,
    summary="Create a word (identity only)",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def create_word(body: WordIn, staff: Writer, db: StaffDb, request: Request) -> IdOut:
    async with staff_tx(db, staff, request) as conn:
        new_id = (
            await conn.execute(text("SELECT vocab.create_word(:slug)"), {"slug": body.slug})
        ).scalar_one()
    return IdOut(id=new_id)


@router.post(
    "/words/{word_id}/revisions",
    response_model=IdOut,
    responses=_ERRORS,
    summary="Create a draft revision of a word in one language",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def create_draft(
    word_id: uuid.UUID, body: RevisionIn, staff: Writer, db: StaffDb, request: Request
) -> IdOut:
    async with staff_tx(db, staff, request) as conn:
        new_id = (
            await conn.execute(
                text(f"SELECT vocab.create_draft(:word_id, :locale, {_CONTENT_ARGS})"),
                {"word_id": word_id, **body.model_dump()},
            )
        ).scalar_one()
    return IdOut(id=new_id)


@router.put(
    "/revisions/{revision_id}",
    response_model=OkOut,
    responses=_ERRORS,
    summary="Edit your own draft",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def update_draft(
    revision_id: uuid.UUID, body: RevisionContent, staff: Writer, db: StaffDb, request: Request
) -> OkOut:
    async with staff_tx(db, staff, request) as conn:
        await conn.execute(
            text(f"SELECT vocab.update_draft(:revision_id, {_CONTENT_ARGS})"),
            {"revision_id": revision_id, **body.model_dump()},
        )
    return OkOut()


@router.put(
    "/revisions/{revision_id}/audio",
    response_model=IdOut,
    responses=_ERRORS,
    summary="Attach or replace recording metadata on your own draft",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def set_audio(
    revision_id: uuid.UUID, body: AudioIn, staff: Writer, db: StaffDb, request: Request
) -> IdOut:
    async with staff_tx(db, staff, request) as conn:
        new_id = (
            await conn.execute(
                text(
                    "SELECT vocab.set_audio(:revision_id, :object_key, :byte_size, "
                    "decode(:sha256, 'hex'), :mime_type, :duration_ms, :source_id)"
                ),
                {"revision_id": revision_id, **body.model_dump()},
            )
        ).scalar_one()
    return IdOut(id=new_id)


@router.delete(
    "/revisions/{revision_id}/audio",
    response_model=OkOut,
    responses=_ERRORS,
    summary="Remove recording metadata from your own draft",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def remove_audio(
    revision_id: uuid.UUID, staff: Writer, db: StaffDb, request: Request
) -> OkOut:
    async with staff_tx(db, staff, request) as conn:
        await conn.execute(text("SELECT vocab.remove_audio(:id)"), {"id": revision_id})
    return OkOut()


@router.post(
    "/revisions/{revision_id}/submit",
    response_model=OkOut,
    responses=_ERRORS,
    summary="Submit your own draft for review (content is frozen)",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def submit_revision(
    revision_id: uuid.UUID, staff: Writer, db: StaffDb, request: Request
) -> OkOut:
    async with staff_tx(db, staff, request) as conn:
        await conn.execute(text("SELECT vocab.submit_revision(:id)"), {"id": revision_id})
    return OkOut()


# --- review -------------------------------------------------------------------------
@router.post(
    "/revisions/{revision_id}/review",
    response_model=IdOut,
    responses=_ERRORS,
    summary="Approve or reject a submitted revision (never your own)",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def review_revision(
    revision_id: uuid.UUID, body: ReviewIn, staff: Reviewer, db: StaffDb, request: Request
) -> IdOut:
    async with staff_tx(db, staff, request) as conn:
        new_id = (
            await conn.execute(
                text("SELECT vocab.review_revision(:id, :verdict, :notes)"),
                {"id": revision_id, "verdict": body.verdict, "notes": body.notes},
            )
        ).scalar_one()
    return IdOut(id=new_id)


@router.get(
    "/review-queue",
    response_model=QueueOut,
    responses=_ERRORS,
    summary="Submitted revisions waiting for a verdict, oldest first",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def review_queue(staff: AnyStaff, db: StaffDb, request: Request) -> QueueOut:
    async with staff_tx(db, staff, request) as conn:
        rows = _rows(await conn.execute(text("SELECT * FROM vocab.review_queue()")))
    return QueueOut(items=[QueueItem(**row) for row in rows])


# --- schedule -----------------------------------------------------------------------
@router.put(
    "/schedule/{haiti_date}",
    response_model=RowsOut,
    responses=_ERRORS,
    summary="Put a word on a date that is not locked (replaces the date's word)",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def schedule_word(
    haiti_date: date, body: ScheduleIn, staff: Publisher, db: StaffDb, request: Request
) -> RowsOut:
    async with staff_tx(db, staff, request) as conn:
        written = (
            await conn.execute(
                text("SELECT vocab.schedule_word(:d, :w)"), {"d": haiti_date, "w": body.word_id}
            )
        ).scalar_one()
    return RowsOut(rows=written)


@router.delete(
    "/schedule/{haiti_date}",
    response_model=RowsOut,
    responses=_ERRORS,
    summary="Clear a date that is not locked",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def unschedule_date(
    haiti_date: date, staff: Publisher, db: StaffDb, request: Request
) -> RowsOut:
    async with staff_tx(db, staff, request) as conn:
        removed = (
            await conn.execute(text("SELECT vocab.unschedule_date(:d)"), {"d": haiti_date})
        ).scalar_one()
    return RowsOut(rows=removed)


@router.get(
    "/calendar",
    response_model=CalendarOut,
    responses=_ERRORS,
    summary="What is recorded for each date, and whether the date is locked",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def calendar(
    staff: AnyStaff,
    db: StaffDb,
    request: Request,
    from_date: Annotated[date, Query(description="First Haiti date of the window.")],
    days: Annotated[int, Query(ge=1, le=92)] = 31,
) -> CalendarOut:
    async with staff_tx(db, staff, request) as conn:
        rows = _rows(
            await conn.execute(
                text("SELECT * FROM vocab.calendar(:f, :n)"), {"f": from_date, "n": days}
            )
        )
    return CalendarOut(items=[CalendarItem(**row) for row in rows])


@router.post(
    "/schedule/ensure",
    response_model=EnsureOut,
    responses=_ERRORS,
    summary="Fill unassigned dates from the approved pool (idempotent)",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def ensure_assignments(
    body: EnsureIn, staff: Publisher, db: StaffDb, request: Request
) -> EnsureOut:
    async with staff_tx(db, staff, request) as conn:
        rows = _rows(
            await conn.execute(
                text("SELECT * FROM vocab.staff_ensure_assignments(:f, :n)"),
                {"f": body.from_date, "n": body.days},
            )
        )
    return EnsureOut(created=[AssignedItem(**row) for row in rows])


@router.post(
    "/words/{word_id}/retire",
    response_model=RowsOut,
    responses=_ERRORS,
    summary="Retire a word and free its unlocked future dates",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def retire_word(
    word_id: uuid.UUID, staff: Publisher, db: StaffDb, request: Request
) -> RowsOut:
    async with staff_tx(db, staff, request) as conn:
        removed = (
            await conn.execute(text("SELECT vocab.retire_word(:id)"), {"id": word_id})
        ).scalar_one()
    return RowsOut(rows=removed)
