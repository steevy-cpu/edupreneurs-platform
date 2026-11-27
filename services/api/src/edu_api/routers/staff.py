"""Staff routes. Everything here lives under ``/v1/staff`` and needs a staff role."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from edu_api.errors import error_responses
from edu_api.routers import staff_editorial, staff_roles
from edu_api.staff.deps import AnyStaff

#: Director ruling R-01 (overnight 2026-11-24): new paths stay out of the OpenAPI
#: document on lane branches, so packages/contracts/openapi.json is unchanged.
#: The routes are registered either way. Flipped once, at integration.
INCLUDE_IN_SCHEMA = False

_me = APIRouter()


class StaffMeResponse(BaseModel):
    user_id: uuid.UUID
    #: Active roles, sorted: a subset of editor, reviewer, publisher, admin.
    roles: list[str]


@_me.get(
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


def build_router(include_in_schema: bool | None = None) -> APIRouter:
    """The whole staff side under ``/v1/staff``. ``include_in_schema`` defaults to
    the module constant; tests pass ``True`` to check the documented contract."""
    documented = INCLUDE_IN_SCHEMA if include_in_schema is None else include_in_schema
    staff_router = APIRouter(prefix="/v1/staff", tags=["staff"], include_in_schema=documented)
    staff_router.include_router(_me)
    staff_router.include_router(staff_editorial.router)
    staff_router.include_router(staff_roles.router)
    return staff_router


router = build_router()
