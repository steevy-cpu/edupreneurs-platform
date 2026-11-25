"""Turning database refusals on the staff side into clean API errors.

Two sources of refusals exist, and both are deliberate:

* the ``staff.*`` workflow functions raise SQLSTATE class ``ED`` with a machine
  code as the message (``ED404`` / ``ED409`` / ``ED422``), or ``42501`` when the
  actor is not allowed;
* the integrity triggers in schema ``app`` — the enforcement of record for the
  editorial rules — raise ``P0001`` with a fixed English sentence.

Nothing from the database is passed to the client verbatim except the machine
codes of our own functions, which are checked against a strict pattern first.
"""

from __future__ import annotations

import re

from sqlalchemy.exc import DBAPIError

from edu_api.errors import ApiError

_CODE = re.compile(r"^[a-z][a-z0-9_]{2,59}$")

_ED_STATUS = {"ED404": 404, "ED409": 409, "ED422": 422}

_ED_MESSAGES = {
    404: "The requested object does not exist.",
    409: "This action is not possible in the current state.",
    422: "The submitted content is not acceptable.",
}

#: Messages of the triggers in supabase/migrations/20261121000200_integrity_guards.sql.
#: tests/unit/test_staff_errors.py fails if a trigger message is missing here.
TRIGGER_ERRORS: dict[str, tuple[int, str, str]] = {
    "Lesson revisions must be created as unapproved drafts": (
        409,
        "revision_must_start_as_draft",
        "A lesson revision starts as a draft.",
    ),
    "Approved/packed lesson revisions are immutable": (
        409,
        "revision_immutable",
        "An approved or published revision cannot be changed. Create a new revision.",
    ),
    "Lesson revision identity and authorship cannot be changed": (
        409,
        "revision_immutable",
        "The identity and authorship of a revision cannot be changed.",
    ),
    "Reviewed content cannot be modified; create a new revision": (
        409,
        "revision_already_reviewed",
        "A reviewed revision cannot be changed. Create a new revision.",
    ),
    "Approval requires the latest review to be an approval by an active, independent reviewer": (
        409,
        "approval_needs_independent_review",
        "Approval needs an approving review by an active reviewer who is not the author.",
    ),
    "Approval requires at least one source and all sources rights-cleared": (
        409,
        "sources_not_cleared",
        "Every source of the revision must be rights-cleared, and there must be at least one.",
    ),
    "Question cannot move to another lesson revision": (
        409,
        "revision_immutable",
        "A question belongs to one revision.",
    ),
    "Questions in reviewed/approved/packed lessons are immutable": (
        409,
        "revision_already_reviewed",
        "Questions of a reviewed or published revision cannot be changed.",
    ),
    "Reviewed source references cannot be modified": (
        409,
        "revision_already_reviewed",
        "Sources of a reviewed or published revision cannot be changed.",
    ),
    "Referenced sources cannot be deleted": (
        409,
        "source_in_use",
        "A source that content refers to cannot be deleted.",
    ),
    "Source identity used in reviewed material is immutable": (
        409,
        "source_in_use",
        "A source used by reviewed content cannot be renamed.",
    ),
    "Lesson revision does not exist": (
        404,
        "revision_not_found",
        "The requested object does not exist.",
    ),
    "Cannot review a finalized lesson revision": (
        409,
        "revision_immutable",
        "An approved or published revision cannot be reviewed again.",
    ),
    "Author cannot review own lesson": (
        409,
        "author_cannot_review",
        "The author of a revision cannot review it.",
    ),
    "Reviewer role required": (403, "forbidden", "You do not have access to this resource."),
    "Pack releases must be created in building state": (
        409,
        "pack_invalid_transition",
        "A pack release starts in the building state.",
    ),
    "Pack items cannot be moved; delete and re-add while the pack is building": (
        409,
        "pack_finalized",
        "Items of a pack cannot be moved.",
    ),
    "Cannot modify items of a finalized pack": (
        409,
        "pack_finalized",
        "A finalized pack cannot be changed.",
    ),
    "Pack items must be approved and match pack locale": (
        409,
        "pack_item_not_approved",
        "A pack can only contain approved revisions in the pack's language.",
    ),
    "Cannot remove finalized pack items": (
        409,
        "pack_finalized",
        "A finalized pack cannot be changed.",
    ),
    "Finalized packs must be retained or revoked": (
        409,
        "pack_finalized",
        "A finalized pack cannot be deleted.",
    ),
    "Pack release identity cannot be changed": (
        409,
        "pack_finalized",
        "The identity of a pack release cannot be changed.",
    ),
    "Finalized pack contents are immutable": (
        409,
        "pack_finalized",
        "A finalized pack cannot be changed.",
    ),
    "Cannot restore revoked pack": (
        409,
        "pack_invalid_transition",
        "A revoked pack cannot be restored.",
    ),
    "Invalid pack lifecycle transition": (
        409,
        "pack_invalid_transition",
        "This pack release cannot move to that state.",
    ),
    "Empty packs cannot be finalized": (409, "pack_empty", "A pack needs at least one lesson."),
    "Pack includes content with uncleared rights": (
        409,
        "sources_not_cleared",
        "The pack contains content whose sources are not rights-cleared.",
    ),
    "Switch current pointer before retiring/revoking pack": (
        409,
        "pack_invalid_transition",
        "The release learners currently get cannot be retired or revoked.",
    ),
    "Current pointer requires matching active pack": (
        409,
        "pack_invalid_transition",
        "Only an active release of the same pack can become current.",
    ),
    "Append-only records cannot be updated or deleted": (
        409,
        "record_append_only",
        "This record cannot be changed.",
    ),
}

_FORBIDDEN = "You do not have access to this resource."


def _sqlstate(exc: DBAPIError) -> str | None:
    value = getattr(exc.orig, "sqlstate", None)
    return value if isinstance(value, str) else None


def _message(exc: DBAPIError) -> str:
    """The primary PostgreSQL message (asyncpg's ``.message``), without driver noise."""
    seen: BaseException | None = exc.orig
    for _ in range(4):
        if seen is None:
            break
        message = getattr(seen, "message", None)
        if isinstance(message, str):
            return message
        seen = seen.__cause__
    return ""


def translate_db_error(exc: DBAPIError) -> ApiError | None:
    """An ``ApiError`` for a refusal we understand, else ``None`` (caller re-raises)."""
    sqlstate = _sqlstate(exc)
    if sqlstate is None:
        return None
    if sqlstate in _ED_STATUS:
        status = _ED_STATUS[sqlstate]
        code = _message(exc)
        if not _CODE.fullmatch(code):
            code = {404: "not_found", 409: "conflict", 422: "invalid_content"}[status]
        return ApiError(status, code, _ED_MESSAGES[status])
    if sqlstate == "42501":
        return ApiError(403, "forbidden", _FORBIDDEN)
    if sqlstate == "P0001":
        status, code, message = TRIGGER_ERRORS.get(
            _message(exc),
            (409, "editorial_rule_violation", "An editorial rule does not allow this."),
        )
        return ApiError(status, code, message)
    if sqlstate == "23505":
        return ApiError(409, "conflict", "The same object already exists.")
    if sqlstate == "23503":
        return ApiError(
            409, "reference_conflict", "A referenced object is missing or still in use."
        )
    if sqlstate in ("23514", "23502", "22023", "22P02", "22001"):
        return ApiError(422, "invalid_content", _ED_MESSAGES[422])
    return None
