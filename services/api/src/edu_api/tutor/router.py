"""FastAPI router for Jude — NOT registered in ``edu_api.main``.

``build_tutor_router`` returns a router that a later, reviewed change can
include in the application. Until consent, entitlements, the usage schema and
the provider decision are approved, nothing imports this from ``main.py`` and
no student-facing route exists. Tests mount it on a throwaway application.

The learner is always ``principal.user_id`` from the verified access token.
The request body has no learner field and rejects unknown fields.
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends

from edu_api.deps import CurrentPrincipal
from edu_api.errors import ApiError, error_responses
from edu_api.tutor.config import TutorSettings
from edu_api.tutor.errors import TutorError
from edu_api.tutor.factory import require_student_facing_readiness
from edu_api.tutor.service import TutorService
from edu_api.tutor.types import TutorAvailability, TutorRequest, TutorResponse


def to_api_error(error: TutorError) -> ApiError:
    """A tutor failure in the API's one error shape, with its stable code."""
    headers = {"Retry-After": str(error.retry_after_s)} if error.retry_after_s else None
    return ApiError(error.http_status, error.code, error.message, headers=headers)


def build_student_facing_router(
    settings: TutorSettings, get_service: Callable[..., TutorService]
) -> APIRouter:
    """The ONLY entry point a production application may use to mount Jude.

    Raises ``TutorConfigurationError`` while the safeguarding review is
    outstanding. Nothing calls this yet.
    """
    require_student_facing_readiness(settings)
    return build_tutor_router(get_service)


def build_tutor_router(get_service: Callable[..., TutorService]) -> APIRouter:
    """The routes themselves, with no readiness check: for tests on a private app only."""
    router = APIRouter(prefix="/v1/jude", tags=["jude"])

    @router.post(
        "/requests",
        response_model=TutorResponse,
        responses=error_responses(401, 404, 409, 422, 503),
        summary="Ask Jude about one published lesson",
    )
    async def create_request(
        body: TutorRequest,
        principal: CurrentPrincipal,
        service: TutorService = Depends(get_service),
    ) -> TutorResponse:
        """A cited explanation grounded in the lesson, or a stable `tutor_*` error.

        Nothing the student writes is stored or logged.
        """
        try:
            return await service.answer(principal.user_id, body)
        except TutorError as exc:
            raise to_api_error(exc) from None

    @router.get(
        "/status",
        response_model=TutorAvailability,
        responses=error_responses(401, 503),
        summary="Whether the caller can use Jude right now",
    )
    async def get_status(
        principal: CurrentPrincipal,
        service: TutorService = Depends(get_service),
    ) -> TutorAvailability:
        return await service.availability(principal.user_id)

    return router
