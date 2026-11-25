"""``GET /v1/entitlements`` — the caller's own entitlement status (read-only).

Mounted only when ``EDU_ENTITLEMENTS_ENABLED`` is true (default: off). There is
no route here, in any environment, that creates, extends or revokes a grant, and
none that receives a payment-provider message.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response
from sqlalchemy.exc import DBAPIError

from edu_api.billing.schemas import EntitlementsResponse
from edu_api.billing.service import load_active_entitlements
from edu_api.config import Settings
from edu_api.deps import CurrentPrincipal, Db
from edu_api.errors import ApiError, error_responses

logger = logging.getLogger("edu_api.billing")

#: SQLSTATE classes meaning "the billing schema itself cannot be used":
#: 42 (insufficient privilege, undefined table/column) and 3F (invalid schema).
#: Connection-level failures are left to the global handler (dependency_unavailable).
_BILLING_UNUSABLE_SQLSTATE_CLASSES = ("42", "3F")


def build_router(settings: Settings) -> APIRouter:
    """The entitlements router; empty (no route at all) while the flag is off."""
    router = APIRouter(prefix="/v1", tags=["entitlements"])
    if not settings.entitlements_enabled:
        return router

    @router.get(
        "/entitlements",
        response_model=EntitlementsResponse,
        responses=error_responses(401, 503),
        summary="The signed-in learner's own active entitlement grants",
    )
    async def get_entitlements(
        principal: CurrentPrincipal, db: Db, response: Response
    ) -> EntitlementsResponse:
        """The caller's grants that are active now, and the server's clock.

        * The learner is taken from the verified access token; nobody else's
          grants can be requested.
        * This endpoint reports status. It does not lock anything: free lessons
          stay available whatever it returns, and when it is unavailable (503).
        * Nothing a client sends can create or extend a grant.
        """
        try:
            async with db.transaction(principal.user_id, read_only=True) as conn:
                result = await load_active_entitlements(conn, principal.user_id)
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if isinstance(sqlstate, str) and sqlstate[:2] in _BILLING_UNUSABLE_SQLSTATE_CLASSES:
                logger.error("billing schema unusable: sqlstate=%s", sqlstate)
                raise ApiError(
                    503,
                    "entitlements_unavailable",
                    "Entitlement status is temporarily unavailable. Free content is not affected.",
                    headers={"Retry-After": "30"},
                ) from None
            raise
        response.headers["Cache-Control"] = "private, no-store"
        return result

    return router
