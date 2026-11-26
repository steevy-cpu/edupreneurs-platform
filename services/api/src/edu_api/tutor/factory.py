"""Wiring: build a ``TutorService`` from settings and the pieces a deployment provides.

This is the ONLY place that turns configuration into a concrete provider, and
it refuses unsafe combinations instead of degrading quietly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from edu_api.tutor.budget import UsageStore
from edu_api.tutor.config import TutorSettings
from edu_api.tutor.content import LessonSource
from edu_api.tutor.errors import TutorConfigurationError
from edu_api.tutor.gateway import ModelGateway, RetryPolicy, Route
from edu_api.tutor.governance import (
    ConsentGate,
    DenyByDefaultConsent,
    DenyByDefaultEntitlements,
    EntitlementGate,
)
from edu_api.tutor.prompts import get_template
from edu_api.tutor.providers.base import ModelProvider, is_live_capable
from edu_api.tutor.providers.mock import MOCK_MODEL, DeterministicMockProvider
from edu_api.tutor.providers.openai_compatible import OpenAICompatibleProvider, https_origin
from edu_api.tutor.retrieval import Bm25Ranker, LessonRetriever, Ranker
from edu_api.tutor.safety import TEMPLATES_REVIEW_STATUS
from edu_api.tutor.service import TutorDependencies, TutorService


def require_live_authorization(settings: TutorSettings, provider: object, *, role: str) -> None:
    """The ONE gate for anything that can reach a real model endpoint.

    Applied to the provider built from settings and to every injected provider
    (primary and fallback) alike. A provider that declares ``live_capable`` is
    refused unless the owner has

    * authorised live provider calls, and
    * stated the spending limit configured on the provider's side — the only
      hard ceiling on what a third party can bill.
    """
    if not is_live_capable(provider):
        return
    if not settings.live_provider_calls_authorized:
        raise TutorConfigurationError(
            f"the {role} provider can reach a live model endpoint, but live provider calls "
            "are not authorised (EDU_TUTOR_LIVE_PROVIDER_CALLS_AUTHORIZED). Refusing it."
        )
    if settings.provider_side_monthly_limit_micro is None:
        raise TutorConfigurationError(
            f"the {role} provider bills by its own meter, which this server cannot bound. "
            "Set a spending limit on the provider's side and state it in "
            "EDU_TUTOR_PROVIDER_SIDE_MONTHLY_LIMIT_MICRO before any paid call."
        )
    if settings.provider_base_url is None:
        raise TutorConfigurationError("a live provider needs an approved provider_base_url")
    approved = https_origin(settings.provider_base_url)
    origin = getattr(provider, "origin", None)
    if origin != approved:
        raise TutorConfigurationError(
            f"the {role} provider is not bound to the approved model endpoint"
        )


def build_provider(
    settings: TutorSettings, *, http_client: httpx.AsyncClient | None = None
) -> ModelProvider:
    if settings.provider == "mock":
        if settings.model != MOCK_MODEL:
            raise TutorConfigurationError(
                f"the mock provider only serves {MOCK_MODEL!r}, not {settings.model!r}"
            )
        return DeterministicMockProvider()
    if not settings.live_provider_calls_authorized:
        raise TutorConfigurationError(
            "a live model provider is configured but live provider calls are not "
            "authorised (EDU_TUTOR_LIVE_PROVIDER_CALLS_AUTHORIZED). Refusing to build it."
        )
    if settings.provider_base_url is None or settings.provider_api_key is None:
        raise TutorConfigurationError("a live provider needs provider_base_url and an API key")
    approved = https_origin(settings.provider_base_url)
    if http_client is not None and (
        _origin_or_none(http_client.base_url) != approved or http_client.follow_redirects
    ):
        # An injected client is used as it is, so it must already point at the
        # approved endpoint, over https, without following redirects.
        raise TutorConfigurationError(
            "the injected HTTP client is not bound to the approved https model endpoint"
        )
    client = http_client or httpx.AsyncClient(
        base_url=settings.provider_base_url,
        headers={"Authorization": f"Bearer {settings.provider_api_key.get_secret_value()}"},
        timeout=settings.request_timeout_s,
        follow_redirects=False,
    )
    provider = OpenAICompatibleProvider(client)
    require_live_authorization(settings, provider, role="configured")
    return provider


def _origin_or_none(url: httpx.URL) -> tuple[str, int] | None:
    try:
        return https_origin(url)
    except TutorConfigurationError:
        return None


def require_student_facing_readiness(settings: TutorSettings) -> None:
    """Refuse to expose Jude to students while safeguarding review is outstanding.

    Whoever registers a student-facing route must call this first (see
    ``edu_api.tutor.router.build_student_facing_router``).
    """
    if not settings.safeguarding_review_completed:
        raise TutorConfigurationError(
            "Jude's safety phrases and fixed replies have not been reviewed by a "
            "child-safeguarding professional and native speakers "
            f"(status: {TEMPLATES_REVIEW_STATUS}). No student-facing route may be registered "
            "until the owner records that review (EDU_TUTOR_SAFEGUARDING_REVIEW_COMPLETED)."
        )


def build_tutor_service(
    settings: TutorSettings,
    *,
    lessons: LessonSource,
    usage: UsageStore,
    consent: ConsentGate | None = None,
    entitlements: EntitlementGate | None = None,
    provider: ModelProvider | None = None,
    fallback_provider: ModelProvider | None = None,
    ranker: Ranker | None = None,
    retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> TutorService:
    """Assemble the service. Omitted gates DENY; an omitted provider comes from settings."""
    provider = provider or build_provider(settings)
    require_live_authorization(settings, provider, role="primary")
    if fallback_provider is not None:
        require_live_authorization(settings, fallback_provider, role="fallback")
    primary = Route(
        provider, settings.model, settings.price_for(settings.model), settings.request_timeout_s
    )
    fallback: Route | None = None
    if settings.fallback_model is not None:
        fallback = Route(
            fallback_provider or provider,
            settings.fallback_model,
            settings.price_for(settings.fallback_model),
            settings.request_timeout_s,
        )
    gateway = ModelGateway(
        primary,
        retry=RetryPolicy(max_attempts=settings.max_attempts),
        fallback=fallback,
        allow_costlier_fallback=settings.allow_costlier_fallback,
        sleep=retry_sleep,
    )
    return TutorService(
        TutorDependencies(
            settings=settings,
            lessons=lessons,
            retriever=LessonRetriever(
                ranker or Bm25Ranker(),
                top_k=settings.retrieval_top_k,
                max_context_chars=settings.max_context_chars,
            ),
            template=get_template(settings.prompt_version),
            gateway=gateway,
            usage=usage,
            consent=consent or DenyByDefaultConsent(),
            entitlements=entitlements or DenyByDefaultEntitlements(),
            input_bound=settings.input_bound(),
        )
    )
