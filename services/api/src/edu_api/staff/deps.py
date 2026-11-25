"""FastAPI dependencies for staff routes.

    from edu_api.staff.deps import StaffDb, StaffPrincipal, require_staff

    @router.post("/v1/staff/things", responses=error_responses(401, 403, 503))
    async def create_thing(
        staff: Annotated[StaffPrincipal, Depends(require_staff("editor", "admin"))],
        db: StaffDb,
    ) -> ...:
        async with db.transaction(staff.user_id) as conn:
            await conn.execute(text("SELECT staff.some_function(...)"))

What ``require_staff`` does, in order:

1. the access token is verified exactly as on the student side (401 otherwise);
2. if the staff side is not configured, 503 ``staff_unavailable``;
3. the caller's ACTIVE roles are read through the staff pool on every request
   (no caching: a revoked role stops working at once);
4. without one of the required roles the caller gets 403 ``forbidden`` and the
   refusal is written to the audit log as ``staff.access`` / ``denied`` in its
   own committed transaction — at most one event per actor per 60 seconds;
   further refusals in that window are counted, not stored.

This is the API's gate. It is not the only one: every ``staff.*`` database
function checks the role again with ``staff.require_role``.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import text

from edu_api.auth.verifier import Principal
from edu_api.db.session import Database
from edu_api.deps import CurrentPrincipal
from edu_api.errors import ApiError

#: Mirrors the CHECK constraint on ``app.staff_roles.role``.
STAFF_ROLES = frozenset({"editor", "reviewer", "publisher", "admin"})

#: What ops.audit_write accepts as a string value in audit details.
_AUDIT_TOKEN = re.compile(r"[A-Za-z0-9_.:/{}+-]{1,120}")

_ACTOR_ROLES = text("SELECT staff.actor_roles()")
#: Bounded in SQL: at most one persisted refusal per actor per 60-second window.
_AUDIT_DENIED = text("SELECT ops.audit_access_denied(CAST(:details AS jsonb))")


@dataclass(frozen=True)
class StaffPrincipal:
    """A verified caller who holds at least one of the roles the route asked for."""

    user_id: uuid.UUID
    roles: frozenset[str]
    principal: Principal


def get_staff_db(request: Request) -> Database:
    database: Database | None = getattr(request.app.state, "staff_db", None)
    if database is None:
        raise ApiError(
            503, "staff_unavailable", "Staff services are not enabled on this deployment."
        )
    return database


def _route_template(request: Request) -> str:
    """The route pattern (``/v1/staff/x/{id}``), never the raw URL.

    Built from the request path by putting each path parameter's name back in
    place of its value. Only requests that matched a route get here, so every
    other segment is fixed text from the route definition.
    """
    segments = request.url.path.split("/")
    for name, value in request.path_params.items():
        segments = ["{" + name + "}" if segment == str(value) else segment for segment in segments]
    template = "/".join(segments)
    return template if _AUDIT_TOKEN.fullmatch(template) else "unknown"


async def record_denial(
    request: Request,
    database: Database,
    actor_id: uuid.UUID,
    *,
    required: frozenset[str],
    check: str = "route",
) -> None:
    """Write (or, inside the 60-second window, only count) one refused request.
    Runs in its own transaction so that it survives the refusal itself.

    ``check`` says where the refusal came from: ``route`` (the role gate of the
    route, ``required_roles`` lists what it asked for) or ``function`` (the
    database function refused: wrong role, or not the author of the object).
    """
    details: dict[str, object] = {
        "method": request.method,
        "route": _route_template(request),
        "check": check,
    }
    if check == "route":
        details["required_roles"] = sorted(required) if required else ["any"]
    async with database.transaction(actor_id) as conn:
        await conn.execute(_AUDIT_DENIED, {"details": json.dumps(details)})


def require_staff(*roles: str) -> Callable[..., Awaitable[StaffPrincipal]]:
    """Dependency factory: the caller must hold one of ``roles`` (active).

    ``require_staff()`` with no argument accepts any active staff role.
    """
    unknown = set(roles) - STAFF_ROLES
    if unknown:
        raise ValueError(f"unknown staff role(s): {sorted(unknown)}")
    required = frozenset(roles)

    async def dependency(request: Request, principal: CurrentPrincipal) -> StaffPrincipal:
        database = get_staff_db(request)
        async with database.transaction(principal.user_id, read_only=True) as conn:
            held = frozenset((await conn.execute(_ACTOR_ROLES)).scalar_one())
        if not (held & required if required else held):
            await record_denial(request, database, principal.user_id, required=required)
            # The same answer for "not staff" and "staff without this role".
            raise ApiError(403, "forbidden", "You do not have access to this resource.")
        return StaffPrincipal(user_id=principal.user_id, roles=held, principal=principal)

    return dependency


StaffDb = Annotated[Database, Depends(get_staff_db)]
#: Any active staff role.
AnyStaff = Annotated[StaffPrincipal, Depends(require_staff())]
