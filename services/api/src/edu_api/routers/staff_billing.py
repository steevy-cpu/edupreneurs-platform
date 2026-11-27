"""Staff entitlement routes: grant, revoke, list a learner's grants (role ``admin``).

Everything goes through the staff pool (``edu_staff_login``), which holds no
table privilege in ``billing``: each route calls ONE audited ``SECURITY DEFINER``
function, and that function checks the role again in the database.

There is no route for prices, plans, orders or provider messages.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from edu_api.billing.schemas import EntitlementScope
from edu_api.billing.staff_schemas import (
    StaffGrantItem,
    StaffGrantRequest,
    StaffGrantResponse,
    StaffLearnerGrantsResponse,
    StaffRevokeRequest,
    StaffRevokeResponse,
)
from edu_api.errors import ApiError, error_responses
from edu_api.routers.entitlements import billing_unavailable, require_entitlements_enabled
from edu_api.staff.deps import StaffDb, StaffPrincipal, require_staff

#: Director ruling R-01 (see routers/entitlements.py). Flipped once, at integration.
INCLUDE_IN_SCHEMA = False

BillingAdmin = Annotated[StaffPrincipal, Depends(require_staff("admin"))]

_GRANT = text(
    "SELECT billing.staff_grant_entitlement("
    ":learner_id, :scope_kind, :scope_id, :duration_days, :source, :reason_code, :idempotency_key)"
)
_REVOKE = text("SELECT billing.staff_revoke_entitlement(:entitlement_id, :reason_code)")
_LIST = text("SELECT billing.staff_list_entitlements(:learner_id)")


def _as_dict(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _refusal(exc: DBAPIError) -> ApiError | None:
    """Translate the SQLSTATEs the billing staff functions raise on purpose."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "42501":
        # the role was revoked between the API check and the call, or a self-grant
        return ApiError(403, "forbidden", "You do not have access to this resource.")
    if sqlstate == "22023":
        return ApiError(
            422, "invalid_entitlement_request", "The learner, scope or period is not valid."
        )
    if sqlstate == "P0002":
        return ApiError(404, "entitlement_not_found", "No such entitlement.")
    return billing_unavailable(exc)


def build_router() -> APIRouter:
    """Built by the application factory so that ``INCLUDE_IN_SCHEMA`` is read then."""
    router = APIRouter(
        prefix="/v1/staff/billing",
        tags=["staff-billing"],
        dependencies=[Depends(require_entitlements_enabled)],
    )

    @router.post(
        "/grants",
        response_model=StaffGrantResponse,
        responses=error_responses(401, 403, 404, 409, 422, 503),
        summary="Grant an entitlement to a learner (admin; idempotent; audited)",
        include_in_schema=INCLUDE_IN_SCHEMA,
    )
    async def grant_entitlement(
        body: StaffGrantRequest, staff: BillingAdmin, db: StaffDb
    ) -> StaffGrantResponse:
        """Creates ONE grant per `idempotency_key`.

        * Repeating the same request returns the original grant (`replayed: true`).
        * Reusing a key for a different learner, scope, source or duration is
          refused with 409 and changes nothing; the refusal is audited.
        * The grant starts now (server clock) and lasts `duration_days` times 24 hours.
          It cannot be a `purchase`, and an admin cannot grant to themselves.
        """
        try:
            async with db.transaction(staff.user_id) as conn:
                outcome = _as_dict(
                    (
                        await conn.execute(
                            _GRANT,
                            {
                                "learner_id": body.learner_id,
                                "scope_kind": body.scope.kind,
                                "scope_id": body.scope.id,
                                "duration_days": body.duration_days,
                                "source": body.source,
                                "reason_code": body.reason_code,
                                "idempotency_key": body.idempotency_key,
                            },
                        )
                    ).scalar_one()
                )
        except DBAPIError as exc:
            refusal = _refusal(exc)
            if refusal is not None:
                raise refusal from None
            raise
        # Raised AFTER the transaction committed, so the 'denied' audit row stays.
        if outcome["status"] != "granted":
            raise ApiError(
                409,
                "idempotency_key_conflict",
                "This idempotency key was already used for a different grant.",
            )
        return StaffGrantResponse(
            entitlement_id=outcome["entitlement_id"],
            replayed=outcome["replayed"],
            starts_at=outcome["starts_at"],
            ends_at=outcome["ends_at"],
        )

    @router.post(
        "/grants/{entitlement_id}/revoke",
        response_model=StaffRevokeResponse,
        responses=error_responses(401, 403, 404, 422, 503),
        summary="Revoke one grant (admin; idempotent; audited)",
        include_in_schema=INCLUDE_IN_SCHEMA,
    )
    async def revoke_entitlement(
        entitlement_id: uuid.UUID, body: StaffRevokeRequest, staff: BillingAdmin, db: StaffDb
    ) -> StaffRevokeResponse:
        """Records a revocation for the grant. The grant row itself is never
        edited; revoking twice returns the first revocation (`replayed: true`).
        The learner's other grants are not affected."""
        try:
            async with db.transaction(staff.user_id) as conn:
                outcome = _as_dict(
                    (
                        await conn.execute(
                            _REVOKE,
                            {"entitlement_id": entitlement_id, "reason_code": body.reason_code},
                        )
                    ).scalar_one()
                )
        except DBAPIError as exc:
            refusal = _refusal(exc)
            if refusal is not None:
                raise refusal from None
            raise
        return StaffRevokeResponse(
            entitlement_id=outcome["entitlement_id"],
            replayed=outcome["replayed"],
            revoked_at=outcome["revoked_at"],
        )

    @router.get(
        "/learners/{learner_id}/grants",
        response_model=StaffLearnerGrantsResponse,
        responses=error_responses(401, 403, 404, 422, 503),
        summary="Every grant of one learner, with its state (admin; audited)",
        include_in_schema=INCLUDE_IN_SCHEMA,
    )
    async def list_learner_grants(
        learner_id: uuid.UUID, staff: BillingAdmin, db: StaffDb
    ) -> StaffLearnerGrantsResponse:
        """All grants of the learner, oldest first. An unknown learner id gives
        an empty list. Each read is recorded in the audit log."""
        try:
            async with db.transaction(staff.user_id) as conn:
                rows = _as_dict(
                    (await conn.execute(_LIST, {"learner_id": learner_id})).scalar_one()
                )
        except DBAPIError as exc:
            refusal = _refusal(exc)
            if refusal is not None:
                raise refusal from None
            raise
        return StaffLearnerGrantsResponse(
            learner_id=learner_id,
            grants=[
                StaffGrantItem(
                    id=row["id"],
                    scope=EntitlementScope(kind=row["scope_kind"], id=row["scope_id"]),
                    starts_at=row["starts_at"],
                    ends_at=row["ends_at"],
                    source=row["source"],
                    state=row["state"],
                    order_id=row["order_id"],
                    granted_by=row["granted_by"],
                    created_at=row["created_at"],
                    revoked_at=row["revoked_at"],
                    revocation_reason=row["revocation_reason"],
                )
                for row in rows
            ],
        )

    return router
