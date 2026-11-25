from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from edu_api.deps import AppSettings, CurrentPrincipal, Db
from edu_api.errors import ApiError, error_responses
from edu_api.rewards.hook import award_after_accept
from edu_api.sync import service
from edu_api.sync.cursor import MAX_CURSOR_LENGTH
from edu_api.sync.schemas import PullResponse, PushRequest, PushResponse

router = APIRouter(prefix="/v1/sync", tags=["sync"])


@router.post(
    "/push",
    response_model=PushResponse,
    responses=error_responses(401, 413, 422, 503),
    summary="Upload offline operations (exactly-once)",
)
async def push(
    body: PushRequest, principal: CurrentPrincipal, db: Db, settings: AppSettings
) -> PushResponse:
    """Apply a small batch of offline operations for the signed-in learner.

    * Safe to retry: resend the SAME batch (same `op_id`s) until you receive a
      response. Already-applied operations come back with `replayed: true`.
    * HTTP 200 does not mean every operation was accepted — read each result.
    * The whole batch is one database transaction. On a 5xx nothing was applied.
    """
    return await service.push(
        db,
        principal.user_id,
        body,
        max_ops=settings.sync_max_ops,
        on_accepted=award_after_accept if settings.rewards_enabled else None,
    )


@router.get(
    "/pull",
    response_model=PullResponse,
    responses=error_responses(401, 410, 422, 503),
    summary="Download this account's changes after a cursor",
)
async def pull(
    principal: CurrentPrincipal,
    db: Db,
    settings: AppSettings,
    cursor: Annotated[
        str | None,
        Query(
            max_length=MAX_CURSOR_LENGTH,
            description="`next_cursor` from the previous pull. Omit for the first pull "
            "or after a 410 to replay from the beginning.",
        ),
    ] = None,
    limit: Annotated[int | None, Query(ge=1, description="Page size.")] = None,
) -> PullResponse:
    """Server-authoritative changes for the signed-in learner, oldest first."""
    if limit is not None and limit > settings.pull_max_limit:
        raise ApiError(422, "validation_error", f"limit must be <= {settings.pull_max_limit}.")
    return await service.pull(
        db, principal.user_id, cursor, limit=limit or settings.pull_default_limit
    )
