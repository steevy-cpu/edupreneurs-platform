"""Staff routes. Everything here lives under ``/v1/staff`` and needs a staff role."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from edu_api.errors import error_responses
from edu_api.staff.deps import AnyStaff

#: Director ruling R-01 (overnight 2026-11-24): new paths stay out of the OpenAPI
#: document on lane branches, so packages/contracts/openapi.json is unchanged.
#: The routes are registered either way. Flipped once, at integration.
INCLUDE_IN_SCHEMA = False

router = APIRouter(prefix="/v1/staff", tags=["staff"], include_in_schema=INCLUDE_IN_SCHEMA)


class StaffMeResponse(BaseModel):
    user_id: uuid.UUID
    #: Active roles, sorted: a subset of editor, reviewer, publisher, admin.
    roles: list[str]


@router.get(
    "/me",
    response_model=StaffMeResponse,
    responses=error_responses(401, 403, 503),
    summary="The signed-in staff member's active roles",
)
async def get_staff_me(staff: AnyStaff) -> StaffMeResponse:
    """Returns the caller's active staff roles.

    A signed-in account without an active staff role (every learner) gets 403,
    and the refusal is recorded in the audit log.
    """
    return StaffMeResponse(user_id=staff.user_id, roles=sorted(staff.roles))
