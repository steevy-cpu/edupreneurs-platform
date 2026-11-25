"""Database calls for the ``account`` routes.

Each function runs inside the caller's transaction (one per request, with the
verified actor set). All writes are performed by ``SECURITY DEFINER`` functions
in the ``account`` schema, which take the actor from the transaction and have
no user-id parameter.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

from edu_api.account.schemas import ProfilePatch
from edu_api.db.session import Database
from edu_api.errors import ApiError
from edu_api.identity import MeResponse, ensure_learner_profile, load_profile

_UPDATE_PROFILE = text("SELECT account.update_own_profile(:patch) AS outcome").bindparams(
    bindparam("patch", type_=JSONB)
)

_PROFILE_REJECTIONS: dict[str, tuple[str, str]] = {
    "grade_not_available": (
        "grade_not_available",
        "The requested grade does not exist or is not active.",
    ),
    "invalid_display_name": ("validation_error", "Request validation failed."),
}


async def _outcome(conn: AsyncConnection, statement: Any, params: dict[str, Any]) -> dict[str, Any]:
    outcome = (await conn.execute(statement, params)).scalar_one()
    if not isinstance(outcome, dict):  # pragma: no cover - the functions always return an object
        raise ApiError(500, "internal_error", "Unexpected server error.")
    return outcome


async def update_profile(db: Database, user_id: uuid.UUID, patch: ProfilePatch) -> MeResponse:
    changes = patch.changes()
    if not changes:
        raise ApiError(422, "empty_patch", "Send at least one profile field to change.")
    async with db.transaction(user_id) as conn:
        await ensure_learner_profile(conn, user_id)
        outcome = await _outcome(conn, _UPDATE_PROFILE, {"patch": changes})
        if outcome.get("status") != "ok":
            code, message = _PROFILE_REJECTIONS.get(
                str(outcome.get("code")), ("validation_error", "Request validation failed.")
            )
            # Raising rolls the transaction back; the function wrote nothing anyway.
            raise ApiError(422, code, message)
        profile = await load_profile(conn, user_id)
    if profile is None:  # pragma: no cover - would mean RLS hides the caller's own row
        raise ApiError(500, "internal_error", "Unexpected server error.")
    return profile
