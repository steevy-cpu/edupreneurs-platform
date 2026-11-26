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
from edu_api.tutor.providers.base import ModelProvider
from edu_api.tutor.providers.mock import MOCK_MODEL, DeterministicMockProvider
from edu_api.tutor.providers.openai_compatible import OpenAICompatibleProvider
from edu_api.tutor.retrieval import Bm25Ranker, LessonRetriever, Ranker
from edu_api.tutor.service import TutorDependencies, TutorService


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
    if not settings.provider_base_url.startswith("https://"):
        raise TutorConfigurationError("provider_base_url must use https")
    client = http_client or httpx.AsyncClient(
        base_url=settings.provider_base_url,
        headers={"Authorization": f"Bearer {settings.provider_api_key.get_secret_value()}"},
        timeout=settings.request_timeout_s,
    )
    return OpenAICompatibleProvider(client)


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
        )
    )
