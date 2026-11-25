"""Learner self-service routes (identity lane).

Every capability here is behind a setting that defaults to OFF. A disabled
capability registers no route at all, so with every flag off the API — and its
OpenAPI document — is exactly what it was before this module existed.
"""

from __future__ import annotations

from fastapi import APIRouter

from edu_api.account import service
from edu_api.account.schemas import ProfilePatch
from edu_api.config import Settings
from edu_api.deps import CurrentPrincipal, Db
from edu_api.errors import error_responses
from edu_api.identity import MeResponse


def _profile_routes(router: APIRouter) -> None:
    @router.patch(
        "/me",
        response_model=MeResponse,
        responses=error_responses(401, 422, 503),
        summary="Change the signed-in learner's own study settings",
    )
    async def patch_me(body: ProfilePatch, principal: CurrentPrincipal, db: Db) -> MeResponse:
        """Change any of `grade_code`, `preferred_locale`, `display_name`.

        Omitted fields are kept; unknown fields are rejected. The profile is
        always the caller's own (from the verified token). Returns the profile
        exactly as `GET /v1/me` does. Repeating the same request changes nothing.
        """
        return await service.update_profile(db, principal.user_id, body)


def build_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["account"])
    if settings.profile_edit_enabled:
        _profile_routes(router)
    return router
