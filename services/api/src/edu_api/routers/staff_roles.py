"""Administration of staff roles. Admin only; every change is audited."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from edu_api.errors import error_responses
from edu_api.staff.calls import call_staff, staff_sql
from edu_api.staff.deps import StaffDb, StaffPrincipal, require_staff

router = APIRouter()

Admin = Annotated[StaffPrincipal, Depends(require_staff("admin"))]
RoleName = Literal["editor", "reviewer", "publisher", "admin"]

_GRANT = staff_sql("staff.grant_role(:user_id, :role)")
_REVOKE = staff_sql("staff.revoke_role(:user_id, :role)")
_LIST = staff_sql("staff.list_role_assignments(:limit)")


class RoleAssignment(BaseModel):
    user_id: uuid.UUID
    role: RoleName
    is_active: bool
    granted_by: uuid.UUID | None
    granted_at: datetime


class RoleAssignmentList(BaseModel):
    assignments: list[RoleAssignment]


class RoleChange(BaseModel):
    user_id: uuid.UUID
    role: RoleName
    is_active: bool
    changed: bool = Field(description="False when the role already was in that state.")


@router.get(
    "/roles",
    response_model=RoleAssignmentList,
    responses=error_responses(401, 403, 422, 503),
    summary="Every staff role assignment, active or not",
)
async def list_roles(
    request: Request,
    staff: Admin,
    db: StaffDb,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> RoleAssignmentList:
    rows = await call_staff(request, db, staff, _LIST, {"limit": limit}, read_only=True)
    return RoleAssignmentList(assignments=rows)


@router.put(
    "/users/{user_id}/roles/{role}",
    response_model=RoleChange,
    responses=error_responses(401, 403, 404, 409, 422, 503),
    summary="Give a staff role to an account",
)
async def grant_role(
    user_id: uuid.UUID, role: RoleName, request: Request, staff: Admin, db: StaffDb
) -> RoleChange:
    """Role: admin. Nobody can give a role to themselves (403)."""
    changed = await call_staff(request, db, staff, _GRANT, {"user_id": user_id, "role": role})
    return RoleChange(user_id=user_id, role=role, is_active=True, changed=changed)


@router.delete(
    "/users/{user_id}/roles/{role}",
    response_model=RoleChange,
    responses=error_responses(401, 403, 404, 409, 422, 503),
    summary="Take a staff role away from an account",
)
async def revoke_role(
    user_id: uuid.UUID, role: RoleName, request: Request, staff: Admin, db: StaffDb
) -> RoleChange:
    """Role: admin. The last active admin cannot be revoked (409 `last_admin`).
    The role stops working on the account's very next request."""
    changed = await call_staff(request, db, staff, _REVOKE, {"user_id": user_id, "role": role})
    return RoleChange(user_id=user_id, role=role, is_active=False, changed=changed)
