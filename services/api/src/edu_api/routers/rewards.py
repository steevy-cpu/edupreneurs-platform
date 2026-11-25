"""Learner-facing rewards API (read-only). Behind ``EDU_REWARDS_ENABLED``.

PROVISIONAL CONTRACT. The app may show Gold for work that has not synced yet,
but must label it "pending" and replace it with what these endpoints return
after the next sync. The server never accepts an amount from the device.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from edu_api.auth.verifier import Principal
from edu_api.deps import AppSettings, CurrentPrincipal, Db
from edu_api.errors import ApiError, error_responses
from edu_api.rewards import service
from edu_api.rewards.cursor import MAX_CURSOR_LENGTH
from edu_api.rewards.schemas import LedgerPage, RewardsSummary

#: The verified contract test pins the exact set of documented paths, and the
#: overnight rules forbid editing it in a lane. Until the integrator updates
#: that pin, these routes are served but kept out of the generated OpenAPI
#: document, so packages/contracts/openapi.json stays byte-identical to main.
#: The contract is written down in docs/overnight-2026-11-24/lanes/rewards.md.
INCLUDE_IN_SCHEMA = False


def require_rewards_enabled(settings: AppSettings) -> None:
    """Flag off = these routes do not exist, exactly like any unknown path."""
    if not settings.rewards_enabled:
        raise ApiError(404, "not_found", "Not Found")


def rewards_principal(
    _enabled: Annotated[None, Depends(require_rewards_enabled)], principal: CurrentPrincipal
) -> Principal:
    # Parameter order matters: the flag is checked before the token.
    return principal


RewardsPrincipal = Annotated[Principal, Depends(rewards_principal)]

router = APIRouter(prefix="/v1/rewards", tags=["rewards"], include_in_schema=INCLUDE_IN_SCHEMA)


@router.get(
    "/summary",
    response_model=RewardsSummary,
    responses=error_responses(401, 404, 503),
    summary="The signed-in learner's Gold balance, streak and achievements",
)
async def get_summary(principal: RewardsPrincipal, db: Db, settings: AppSettings) -> RewardsSummary:
    """Server-authoritative totals for the caller, plus the newest ledger entries.

    Before reading, accepted operations that were never examined (for example
    synced while rewards were switched off) are examined, bounded per request.
    """
    return await service.summary(
        db,
        principal.user_id,
        recent_limit=settings.rewards_recent_limit,
        reconcile_limit=settings.rewards_reconcile_limit,
    )


@router.get(
    "/ledger",
    response_model=LedgerPage,
    responses=error_responses(401, 404, 422, 503),
    summary="The signed-in learner's Gold ledger, newest first",
)
async def get_ledger(
    principal: RewardsPrincipal,
    db: Db,
    settings: AppSettings,
    cursor: Annotated[
        str | None,
        Query(
            max_length=MAX_CURSOR_LENGTH,
            description="`next_cursor` from the previous page. Omit for the newest entries.",
        ),
    ] = None,
    limit: Annotated[int | None, Query(ge=1, description="Page size.")] = None,
) -> LedgerPage:
    if limit is not None and limit > settings.rewards_ledger_max_limit:
        raise ApiError(
            422, "validation_error", f"limit must be <= {settings.rewards_ledger_max_limit}."
        )
    return await service.ledger_page(
        db, principal.user_id, cursor, limit=limit or settings.rewards_ledger_default_limit
    )
