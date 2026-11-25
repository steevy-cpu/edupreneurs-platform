"""Editorial workflow for staff: lessons, draft revisions, sources, review, packs.

Every route calls exactly one ``staff.*`` database function, which checks the
role again, writes, and records an audit event in the same transaction. The
editorial rules themselves are enforced by the integrity triggers of schema
``app``; this module only shapes requests and turns refusals into 4xx answers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from edu_api.errors import error_responses
from edu_api.staff.calls import as_jsonb, call_staff, staff_sql
from edu_api.staff.content import RevisionContent
from edu_api.staff.deps import AnyStaff, StaffDb, StaffPrincipal, require_staff

router = APIRouter()

Author = Annotated[StaffPrincipal, Depends(require_staff("editor", "admin"))]
Reviewer = Annotated[StaffPrincipal, Depends(require_staff("reviewer", "admin"))]
Builder = Annotated[StaffPrincipal, Depends(require_staff("editor", "publisher", "admin"))]
Publisher = Annotated[StaffPrincipal, Depends(require_staff("publisher", "admin"))]
Admin = Annotated[StaffPrincipal, Depends(require_staff("admin"))]

LocaleCode = Literal["fr", "ht"]
RevisionStatus = Literal["draft", "in_review", "approved", "rejected"]
RightsStatus = Literal["unverified", "cleared", "restricted", "blocked"]
ListLimit = Annotated[int, Query(ge=1, le=200, description="Maximum number of rows.")]

_STRICT = ConfigDict(extra="forbid")
_WRITE_ERRORS = error_responses(401, 403, 404, 409, 422, 503)
_READ_ERRORS = error_responses(401, 403, 404, 422, 503)


# --- response models -----------------------------------------------------------
class QuestionOut(BaseModel):
    id: uuid.UUID
    question_key: str
    position: int
    kind: str
    prompt: dict[str, Any]
    response_spec: dict[str, Any]
    answer_key: dict[str, Any]
    explanation: dict[str, Any]


class SourceRef(BaseModel):
    id: uuid.UUID
    source_title: str
    source_uri: str | None
    rights_status: RightsStatus


class ReviewOut(BaseModel):
    id: uuid.UUID
    reviewer_id: uuid.UUID
    verdict: Literal["approved", "rejected", "changes_requested"]
    notes: str | None
    reviewed_at: datetime


class RevisionSummary(BaseModel):
    id: uuid.UUID
    lesson_id: uuid.UUID
    revision: int
    locale: LocaleCode
    title: str
    status: RevisionStatus
    created_by: uuid.UUID
    created_at: datetime
    approved_by: uuid.UUID | None
    approved_at: datetime | None


class RevisionDetail(RevisionSummary):
    blocks: list[dict[str, Any]]
    questions: list[QuestionOut]
    sources: list[SourceRef]
    reviews: list[ReviewOut]


class RevisionList(BaseModel):
    revisions: list[RevisionSummary]


class SourceOut(SourceRef):
    rights_notes: str | None
    verified_at: datetime | None
    created_at: datetime


class SourceList(BaseModel):
    sources: list[SourceOut]


class PackItemOut(BaseModel):
    position: int
    lesson_revision_id: uuid.UUID
    lesson_id: uuid.UUID
    title: str


class PackReleaseOut(BaseModel):
    id: uuid.UUID
    pack_key: str
    locale: LocaleCode
    revision: int
    status: Literal["building", "ready", "active", "retired", "revoked"]
    is_current: bool = Field(description="True when learners currently get this release.")
    created_by: uuid.UUID | None
    created_at: datetime
    released_at: datetime | None
    manifest_sha256: str | None
    items: list[PackItemOut]


class PackReleaseList(BaseModel):
    releases: list[PackReleaseOut]


class PackSwitchOut(BaseModel):
    release: PackReleaseOut
    previous_release_id: uuid.UUID | None = Field(
        description="The release that was current before this action (now retired)."
    )


class LessonCreated(BaseModel):
    lesson_id: uuid.UUID


class SourceCreated(BaseModel):
    source_id: uuid.UUID


class ReviewRecorded(BaseModel):
    review_id: uuid.UUID
    revision: RevisionDetail


# --- request models ------------------------------------------------------------
class LessonIn(BaseModel):
    model_config = _STRICT
    unit_id: uuid.UUID
    slug: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{2,80}$")]


class RevisionIn(RevisionContent):
    locale: LocaleCode


class SourceIn(BaseModel):
    model_config = _STRICT
    source_title: Annotated[str, StringConstraints(min_length=1, max_length=240)]
    source_uri: (
        Annotated[str, StringConstraints(max_length=2000, pattern=r"^https?://\S+$")] | None
    ) = None


class SourceRightsIn(BaseModel):
    model_config = _STRICT
    rights_status: RightsStatus
    rights_notes: Annotated[str, StringConstraints(max_length=2000)] | None = None


class AttachSourceIn(BaseModel):
    model_config = _STRICT
    source_id: uuid.UUID


class ReviewIn(BaseModel):
    model_config = _STRICT
    verdict: Literal["approved", "rejected", "changes_requested"]
    notes: Annotated[str, StringConstraints(max_length=4000)] | None = None


class PackIn(BaseModel):
    model_config = _STRICT
    pack_key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{3,100}$")]
    locale: LocaleCode
    revision_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=500)]


# --- SQL -------------------------------------------------------------------------
_CREATE_LESSON = staff_sql("staff.create_lesson(:unit_id, :slug)")
_CREATE_REVISION = staff_sql(
    "staff.create_revision(:lesson_id, :locale, :title, CAST(:blocks AS jsonb), "
    "CAST(:questions AS jsonb))"
)
_UPDATE_REVISION = staff_sql(
    "staff.update_revision(:revision_id, :title, CAST(:blocks AS jsonb), "
    "CAST(:questions AS jsonb))::text"
)
_GET_REVISION = staff_sql("staff.get_revision(:revision_id)")
_LIST_REVISIONS = staff_sql("staff.list_revisions(:status, :mine, :limit)")
_CREATE_SOURCE = staff_sql("staff.create_source(:title, :uri)")
_SET_RIGHTS = staff_sql("staff.set_source_rights(:source_id, :status, :notes)::text")
_LIST_SOURCES = staff_sql("staff.list_sources(:limit)")
_ATTACH_SOURCE = staff_sql("staff.attach_source(:revision_id, :source_id)::text")
_DETACH_SOURCE = staff_sql("staff.detach_source(:revision_id, :source_id)::text")
_SUBMIT = staff_sql("staff.submit_revision(:revision_id)::text")
_REVIEW = staff_sql("staff.review_revision(:revision_id, :verdict, :notes)")
_BUILD_PACK = staff_sql("staff.build_pack(:pack_key, :locale, CAST(:revision_ids AS uuid[]))")
_RELEASE_PACK = staff_sql("staff.release_pack(:release_id)")
_ROLLBACK_PACK = staff_sql("staff.rollback_pack(:release_id)")
_GET_PACK = staff_sql("staff.get_pack_release(:release_id)")
_LIST_PACKS = staff_sql("staff.list_pack_releases(:pack_key, :locale, :limit)")


async def _revision(
    request: Request, db: StaffDb, staff: StaffPrincipal, revision_id: uuid.UUID
) -> RevisionDetail:
    row = await call_staff(
        request, db, staff, _GET_REVISION, {"revision_id": revision_id}, read_only=True
    )
    return RevisionDetail.model_validate(row)


async def _pack(
    request: Request, db: StaffDb, staff: StaffPrincipal, release_id: uuid.UUID
) -> PackReleaseOut:
    row = await call_staff(
        request, db, staff, _GET_PACK, {"release_id": release_id}, read_only=True
    )
    return PackReleaseOut.model_validate(row)


# --- lessons and revisions -----------------------------------------------------
@router.post(
    "/lessons",
    status_code=201,
    response_model=LessonCreated,
    responses=_WRITE_ERRORS,
    summary="Create an empty lesson at the end of a unit",
)
async def create_lesson(
    body: LessonIn, request: Request, staff: Author, db: StaffDb
) -> LessonCreated:
    """Role: editor or admin. The lesson is invisible to learners until one of its
    revisions is approved and released in a pack."""
    lesson_id = await call_staff(
        request, db, staff, _CREATE_LESSON, {"unit_id": body.unit_id, "slug": body.slug}
    )
    return LessonCreated(lesson_id=lesson_id)


@router.post(
    "/lessons/{lesson_id}/revisions",
    status_code=201,
    response_model=RevisionDetail,
    responses=_WRITE_ERRORS,
    summary="Create a draft revision of a lesson in one language",
)
async def create_revision(
    lesson_id: uuid.UUID, body: RevisionIn, request: Request, staff: Author, db: StaffDb
) -> RevisionDetail:
    """Role: editor or admin. The caller becomes the author. The revision number is
    the next one for that lesson and language."""
    revision_id = await call_staff(
        request,
        db,
        staff,
        _CREATE_REVISION,
        {
            "lesson_id": lesson_id,
            "locale": body.locale,
            "title": body.title,
            "blocks": as_jsonb(body.blocks_json()),
            "questions": as_jsonb(body.questions_json()),
        },
    )
    return await _revision(request, db, staff, revision_id)


@router.get(
    "/revisions",
    response_model=RevisionList,
    responses=_READ_ERRORS,
    summary="List revisions: drafts, the review queue, or everything",
)
async def list_revisions(
    request: Request,
    staff: AnyStaff,
    db: StaffDb,
    status: Annotated[
        RevisionStatus | None,
        Query(description="`draft` = drafts, `in_review` = the review queue. Omit for all."),
    ] = None,
    mine: Annotated[bool, Query(description="Only revisions written by the caller.")] = False,
    limit: ListLimit = 50,
) -> RevisionList:
    rows = await call_staff(
        request,
        db,
        staff,
        _LIST_REVISIONS,
        {"status": status, "mine": mine, "limit": limit},
        read_only=True,
    )
    return RevisionList(revisions=rows)


@router.get(
    "/revisions/{revision_id}",
    response_model=RevisionDetail,
    responses=_READ_ERRORS,
    summary="One revision with its questions, sources and reviews",
)
async def get_revision(
    revision_id: uuid.UUID, request: Request, staff: AnyStaff, db: StaffDb
) -> RevisionDetail:
    return await _revision(request, db, staff, revision_id)


@router.put(
    "/revisions/{revision_id}",
    response_model=RevisionDetail,
    responses=_WRITE_ERRORS,
    summary="Replace title, blocks and questions of a draft",
)
async def update_revision(
    revision_id: uuid.UUID, body: RevisionContent, request: Request, staff: Author, db: StaffDb
) -> RevisionDetail:
    """The author only (or an admin). A revision that is in review, reviewed,
    approved or published cannot be changed: 409."""
    await call_staff(
        request,
        db,
        staff,
        _UPDATE_REVISION,
        {
            "revision_id": revision_id,
            "title": body.title,
            "blocks": as_jsonb(body.blocks_json()),
            "questions": as_jsonb(body.questions_json()),
        },
    )
    return await _revision(request, db, staff, revision_id)


@router.post(
    "/revisions/{revision_id}/sources",
    response_model=RevisionDetail,
    responses=_WRITE_ERRORS,
    summary="Attach a registered source to a draft",
)
async def attach_source(
    revision_id: uuid.UUID, body: AttachSourceIn, request: Request, staff: Author, db: StaffDb
) -> RevisionDetail:
    await call_staff(
        request,
        db,
        staff,
        _ATTACH_SOURCE,
        {"revision_id": revision_id, "source_id": body.source_id},
    )
    return await _revision(request, db, staff, revision_id)


@router.delete(
    "/revisions/{revision_id}/sources/{source_id}",
    status_code=204,
    response_class=Response,
    responses=_WRITE_ERRORS,
    summary="Detach a source from a draft",
)
async def detach_source(
    revision_id: uuid.UUID, source_id: uuid.UUID, request: Request, staff: Author, db: StaffDb
) -> Response:
    await call_staff(
        request, db, staff, _DETACH_SOURCE, {"revision_id": revision_id, "source_id": source_id}
    )
    return Response(status_code=204)


@router.post(
    "/revisions/{revision_id}/submit",
    response_model=RevisionDetail,
    responses=_WRITE_ERRORS,
    summary="Send a draft to the review queue",
)
async def submit_revision(
    revision_id: uuid.UUID, request: Request, staff: Author, db: StaffDb
) -> RevisionDetail:
    """The author only (or an admin). Needs at least one attached source."""
    await call_staff(request, db, staff, _SUBMIT, {"revision_id": revision_id})
    return await _revision(request, db, staff, revision_id)


@router.post(
    "/revisions/{revision_id}/reviews",
    status_code=201,
    response_model=ReviewRecorded,
    responses=_WRITE_ERRORS,
    summary="Record a review: approve, reject, or request changes",
)
async def review_revision(
    revision_id: uuid.UUID, body: ReviewIn, request: Request, staff: Reviewer, db: StaffDb
) -> ReviewRecorded:
    """Role: reviewer or admin, and never the author of the revision (409
    `author_cannot_review`). `approved` approves the revision; `rejected` and
    `changes_requested` both close it — corrections need a new revision."""
    review_id = await call_staff(
        request,
        db,
        staff,
        _REVIEW,
        {"revision_id": revision_id, "verdict": body.verdict, "notes": body.notes},
    )
    return ReviewRecorded(
        review_id=review_id, revision=await _revision(request, db, staff, revision_id)
    )


# --- sources ---------------------------------------------------------------------
@router.post(
    "/sources",
    status_code=201,
    response_model=SourceCreated,
    responses=_WRITE_ERRORS,
    summary="Register a content source (rights start as unverified)",
)
async def create_source(
    body: SourceIn, request: Request, staff: Author, db: StaffDb
) -> SourceCreated:
    source_id = await call_staff(
        request, db, staff, _CREATE_SOURCE, {"title": body.source_title, "uri": body.source_uri}
    )
    return SourceCreated(source_id=source_id)


@router.get(
    "/sources",
    response_model=SourceList,
    responses=_READ_ERRORS,
    summary="List registered sources, newest first",
)
async def list_sources(
    request: Request, staff: AnyStaff, db: StaffDb, limit: ListLimit = 50
) -> SourceList:
    rows = await call_staff(request, db, staff, _LIST_SOURCES, {"limit": limit}, read_only=True)
    return SourceList(sources=rows)


@router.put(
    "/sources/{source_id}/rights",
    status_code=204,
    response_class=Response,
    responses=_WRITE_ERRORS,
    summary="Record the rights decision on a source",
)
async def set_source_rights(
    source_id: uuid.UUID, body: SourceRightsIn, request: Request, staff: Admin, db: StaffDb
) -> Response:
    """Role: admin only."""
    await call_staff(
        request,
        db,
        staff,
        _SET_RIGHTS,
        {"source_id": source_id, "status": body.rights_status, "notes": body.rights_notes},
    )
    return Response(status_code=204)


# --- packs -----------------------------------------------------------------------
@router.post(
    "/packs",
    status_code=201,
    response_model=PackReleaseOut,
    responses=_WRITE_ERRORS,
    summary="Build the next release of a pack from approved revisions",
)
async def build_pack(body: PackIn, request: Request, staff: Builder, db: StaffDb) -> PackReleaseOut:
    """Role: editor, publisher or admin. The release is finalised as `ready`; it
    reaches learners only when a publisher releases it."""
    release_id = await call_staff(
        request,
        db,
        staff,
        _BUILD_PACK,
        {"pack_key": body.pack_key, "locale": body.locale, "revision_ids": body.revision_ids},
    )
    return await _pack(request, db, staff, release_id)


@router.get(
    "/packs",
    response_model=PackReleaseList,
    responses=_READ_ERRORS,
    summary="List pack releases, newest first",
)
async def list_packs(
    request: Request,
    staff: AnyStaff,
    db: StaffDb,
    pack_key: Annotated[str | None, Query(pattern=r"^[a-z0-9_-]{3,100}$")] = None,
    locale: LocaleCode | None = None,
    limit: ListLimit = 50,
) -> PackReleaseList:
    rows = await call_staff(
        request,
        db,
        staff,
        _LIST_PACKS,
        {"pack_key": pack_key, "locale": locale, "limit": limit},
        read_only=True,
    )
    return PackReleaseList(releases=rows)


@router.post(
    "/packs/{release_id}/release",
    response_model=PackSwitchOut,
    responses=_WRITE_ERRORS,
    summary="Publish a ready release to learners",
)
async def release_pack(
    release_id: uuid.UUID, request: Request, staff: Publisher, db: StaffDb
) -> PackSwitchOut:
    """Role: publisher or admin. One action: activate the release, make it the
    current one, retire the release it replaces."""
    result = await call_staff(request, db, staff, _RELEASE_PACK, {"release_id": release_id})
    return PackSwitchOut(
        release=await _pack(request, db, staff, release_id),
        previous_release_id=result["previous_release_id"],
    )


@router.post(
    "/packs/{release_id}/rollback",
    response_model=PackSwitchOut,
    responses=_WRITE_ERRORS,
    summary="Go back to an earlier, retired release of the same pack",
)
async def rollback_pack(
    release_id: uuid.UUID, request: Request, staff: Publisher, db: StaffDb
) -> PackSwitchOut:
    """Role: publisher or admin. One action, the mirror image of a release."""
    result = await call_staff(request, db, staff, _ROLLBACK_PACK, {"release_id": release_id})
    return PackSwitchOut(
        release=await _pack(request, db, staff, release_id),
        previous_release_id=result["previous_release_id"],
    )
