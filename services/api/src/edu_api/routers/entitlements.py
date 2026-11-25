"""``GET /v1/entitlements`` — the caller's own entitlement status (read-only).

Always registered; answers the standard 404 while ``EDU_ENTITLEMENTS_ENABLED``
is off (the default), exactly like a path that does not exist. There is no
route here, in any environment, that creates, extends or revokes a grant, and
none that receives a payment-provider message.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.exc import DBAPIError

from edu_api.billing.schemas import EntitlementsResponse
from edu_api.billing.service import load_active_entitlements
from edu_api.deps import CurrentPrincipal, Db
from edu_api.errors import ApiError, error_responses

logger = logging.getLogger("edu_api.billing")

#: Director ruling R-01: new paths stay out of the generated OpenAPI document on
#: lane branches (the baseline contract test pins the exact path set). Flipped to
#: True once, at integration. The contract is in
#: docs/overnight-2026-11-24/lanes/entitlements.md.
INCLUDE_IN_SCHEMA = False

#: SQLSTATE classes meaning "the billing schema itself cannot be used":
#: 42 (insufficient privilege, undefined table/column) and 3F (invalid schema).
#: Connection-level failures are left to the global handler (dependency_unavailable).
_BILLING_UNUSABLE_SQLSTATE_CLASSES = ("42", "3F")


def require_entitlements_enabled(request: Request) -> None:
    """With the flag off these routes behave like paths that do not exist.

    A router-level dependency, so it runs before authentication: the answer is
    the same 404 with or without a token.
    """
    if not request.app.state.settings.entitlements_enabled:
        raise ApiError(404, "not_found", "Not Found")


def billing_unavailable(exc: DBAPIError) -> ApiError | None:
    """The 503 to return when the billing schema itself is unusable, else None."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if isinstance(sqlstate, str) and sqlstate[:2] in _BILLING_UNUSABLE_SQLSTATE_CLASSES:
        logger.error("billing schema unusable: sqlstate=%s", sqlstate)
        return ApiError(
            503,
            "entitlements_unavailable",
            "Entitlement status is temporarily unavailable. Free content is not affected.",
            headers={"Retry-After": "30"},
        )
    return None


def build_router() -> APIRouter:
    """Built by the application factory so that ``INCLUDE_IN_SCHEMA`` is read then."""
    router = APIRouter(
        prefix="/v1", tags=["entitlements"], dependencies=[Depends(require_entitlements_enabled)]
    )

    @router.get(
        "/entitlements",
        response_model=EntitlementsResponse,
        responses=error_responses(401, 404, 503),
        summary="The signed-in learner's own active entitlement grants",
        include_in_schema=INCLUDE_IN_SCHEMA,
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
        * 404 while the feature is switched off.
        """
        try:
            async with db.transaction(principal.user_id, read_only=True) as conn:
                result = await load_active_entitlements(conn, principal.user_id)
        except DBAPIError as exc:
            unavailable = billing_unavailable(exc)
            if unavailable is not None:
                raise unavailable from None
            raise
        response.headers["Cache-Control"] = "private, no-store"
        return result

    return router
