from __future__ import annotations

from fastapi import APIRouter

from edu_api.deps import CurrentPrincipal, Db
from edu_api.errors import ApiError, error_responses
from edu_api.identity import MeResponse, ensure_learner_profile, load_profile

router = APIRouter(prefix="/v1", tags=["identity"])


@router.get(
    "/me",
    response_model=MeResponse,
    responses=error_responses(401, 503),
    summary="The signed-in learner's own profile",
)
async def get_me(principal: CurrentPrincipal, db: Db) -> MeResponse:
    """Returns the caller's profile. The profile row is created on first contact.

    The user id comes from the verified access token; there is no way to ask
    for someone else's profile.
    """
    async with db.transaction(principal.user_id, read_only=True) as conn:
        profile = await load_profile(conn, principal.user_id)
    if profile is None:
        async with db.transaction(principal.user_id) as conn:
            await ensure_learner_profile(conn, principal.user_id)
            profile = await load_profile(conn, principal.user_id)
    if profile is None:  # pragma: no cover - would mean RLS hides the caller's own row
        raise ApiError(500, "internal_error", "Unexpected server error.")
    return profile
