"""Learner-facing leaderboard API (read-only). Behind ``EDU_LEADERBOARD_ENABLED``.

PROVISIONAL CONTRACT. The learners are minors: there is no public or global
ranking. This router only ever returns the caller's own Gold and, for a caller
who explicitly opted in to a (synthetic) cohort, the caller's own rank there.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from edu_api.auth.verifier import Principal
from edu_api.deps import AppSettings, CurrentPrincipal, Db
from edu_api.errors import ApiError, error_responses
from edu_api.leaderboard import service
from edu_api.leaderboard.schemas import MyStanding

#: Ruling R-01: served, but kept out of the generated OpenAPI document until
#: the integrator extends the pinned path set. The contract is written down in
#: docs/overnight-2026-11-24/lanes/leaderboard.md.
INCLUDE_IN_SCHEMA = False

PERIOD_PATTERN = r"^(all|week|\d{4}-\d{2}-\d{2})$"


def require_leaderboard_enabled(settings: AppSettings) -> None:
    """Flag off = this route does not exist, exactly like any unknown path."""
    if not settings.leaderboard_enabled:
        raise ApiError(404, "not_found", "Not Found")


def leaderboard_principal(
    _enabled: Annotated[None, Depends(require_leaderboard_enabled)], principal: CurrentPrincipal
) -> Principal:
    # Parameter order matters: the flag is checked before the token.
    return principal


LeaderboardPrincipal = Annotated[Principal, Depends(leaderboard_principal)]

router = APIRouter(
    prefix="/v1/leaderboard", tags=["leaderboard"], include_in_schema=INCLUDE_IN_SCHEMA
)


@router.get(
    "/me",
    response_model=MyStanding,
    responses=error_responses(401, 404, 422, 503),
    summary="The signed-in learner's own Gold for a period and own rank in their cohort",
)
async def get_my_standing(
    principal: LeaderboardPrincipal,
    db: Db,
    period: Annotated[
        str,
        Query(
            pattern=PERIOD_PATTERN,
            max_length=10,
            description="`week` (current Haiti week), `all`, or the Monday of a past week.",
        ),
    ] = "week",
) -> MyStanding:
    """Never returns another learner's data. `cohort` is null unless the caller
    opted in; rank and size come from the latest snapshot (`computed_at`)."""
    return await service.my_standing(db, principal.user_id, period)
