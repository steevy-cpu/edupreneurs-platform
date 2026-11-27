"""Learner self-service routes (identity lane).

Every capability here is behind a setting that defaults to OFF. The routes are
always registered; while its flag is off a route answers the standard 404
``not_found`` — before authentication, validation or any database access.

Director ruling R-01 (overnight 2026-11-24): ``PATCH /v1/me`` is a new method on
an existing path and is part of the published contract. The NEW paths stay out
of the OpenAPI document on this branch behind ``INCLUDE_IN_SCHEMA``.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Request

from edu_api.account import service
from edu_api.account.schemas import (
    AccountExport,
    AccountRequests,
    DeletionRequestResponse,
    OnboardingResponse,
    OnboardingUpdate,
    ProfilePatch,
)
from edu_api.deps import CurrentPrincipal, Db
from edu_api.errors import ApiError, error_responses
from edu_api.identity import MeResponse

#: Ruling R-01: new paths (`/v1/me/onboarding`, `/v1/me/account-requests`,
#: `/v1/me/deletion-request`, `/v1/me/export`) are registered but kept out of the
#: OpenAPI document, so packages/contracts/openapi.json keeps the pinned path
#: set. Flipped once, at integration. Read when `build_router()` runs.
INCLUDE_IN_SCHEMA = False


def _require_flag(name: str) -> Callable[[Request], None]:
    """A dependency that hides a route (standard 404) while its setting is off."""

    def check(request: Request) -> None:
        if not getattr(request.app.state.settings, name):
            raise ApiError(404, "not_found", "Not Found")

    return check


def _profile_routes(router: APIRouter) -> None:
    @router.patch(
        "/me",
        response_model=MeResponse,
        responses=error_responses(401, 404, 422, 503),
        summary="Change the signed-in learner's own study settings",
    )
    async def patch_me(body: ProfilePatch, principal: CurrentPrincipal, db: Db) -> MeResponse:
        """Change any of `grade_code`, `preferred_locale`, `display_name`.

        Omitted fields are kept; unknown fields are rejected. The profile is
        always the caller's own (from the verified token). Returns the profile
        exactly as `GET /v1/me` does. Repeating the same request changes nothing.

        Answers 404 `not_found` while profile editing is switched off on the server.
        """
        return await service.update_profile(db, principal.user_id, body)


def _onboarding_routes(router: APIRouter) -> None:
    @router.get(
        "/me/onboarding",
        response_model=OnboardingResponse,
        responses=error_responses(401, 404, 503),
        summary="How far the signed-in learner is through onboarding",
    )
    async def get_onboarding(principal: CurrentPrincipal, db: Db) -> OnboardingResponse:
        """The caller's own onboarding state. Read-only.

        A learner whose work the server has already accepted is reported as
        `ready` even if no device ever sent an onboarding update.
        """
        return await service.get_onboarding(db, principal.user_id)

    @router.put(
        "/me/onboarding",
        response_model=OnboardingResponse,
        responses=error_responses(401, 404, 422, 503),
        summary="Record onboarding progress (idempotent, forward-only)",
    )
    async def put_onboarding(
        body: OnboardingUpdate, principal: CurrentPrincipal, db: Db
    ) -> OnboardingResponse:
        """Safe to retry and to replay late from an offline device.

        The state never moves backwards, versions keep their highest value and
        `tour_dismissed` stays true once set. A stale request returns 200 with
        the current (unchanged) state. Onboarding never deletes learning data.
        """
        return await service.advance_onboarding(db, principal.user_id, body)


def _lifecycle_routes(router: APIRouter) -> None:
    @router.get(
        "/me/account-requests",
        response_model=AccountRequests,
        responses=error_responses(401, 404, 503),
        summary="The signed-in learner's own deletion request and last export",
    )
    async def get_account_requests(principal: CurrentPrincipal, db: Db) -> AccountRequests:
        return await service.get_requests(db, principal.user_id)

    @router.post(
        "/me/deletion-request",
        response_model=DeletionRequestResponse,
        responses=error_responses(401, 404, 503),
        summary="Ask for the signed-in learner's own account to be deleted",
    )
    async def post_deletion_request(principal: CurrentPrincipal, db: Db) -> DeletionRequestResponse:
        """Records the request. **Nothing is deleted by this call** and the
        learner can keep using the app. Idempotent: while a request is open,
        asking again returns that same request. No deadline is promised."""
        return await service.request_deletion(db, principal.user_id)

    @router.delete(
        "/me/deletion-request",
        response_model=DeletionRequestResponse,
        responses=error_responses(401, 404, 503),
        summary="Withdraw the signed-in learner's open deletion request",
    )
    async def delete_deletion_request(
        principal: CurrentPrincipal, db: Db
    ) -> DeletionRequestResponse:
        """Idempotent: with no open request nothing changes and the most recent
        request (or `null`) is returned."""
        return await service.cancel_deletion(db, principal.user_id)

    @router.post(
        "/me/export",
        response_model=AccountExport,
        responses=error_responses(401, 404, 503),
        summary="Export the signed-in learner's own data",
    )
    async def post_export(principal: CurrentPrincipal, db: Db) -> AccountExport:
        """The caller's own profile, onboarding state, lesson progress and
        practice attempts. Bounded (see `limits` / `truncated`). Each call is
        recorded."""
        return await service.export_data(db, principal.user_id)


def build_router() -> APIRouter:
    """Three groups, each behind its own setting (checked per request)."""
    router = APIRouter(prefix="/v1", tags=["account"])

    profile = APIRouter(dependencies=[Depends(_require_flag("profile_edit_enabled"))])
    _profile_routes(profile)
    router.include_router(profile)

    onboarding = APIRouter(
        dependencies=[Depends(_require_flag("onboarding_enabled"))],
        include_in_schema=INCLUDE_IN_SCHEMA,
    )
    _onboarding_routes(onboarding)
    router.include_router(onboarding)

    lifecycle = APIRouter(
        dependencies=[Depends(_require_flag("account_lifecycle_enabled"))],
        include_in_schema=INCLUDE_IN_SCHEMA,
    )
    _lifecycle_routes(lifecycle)
    router.include_router(lifecycle)
    return router
