"""Provider adapters and the gateway: timeouts, retries, fallback, metering, cancellation."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from edu_api.tutor.budget import ModelPrice
from edu_api.tutor.config import TutorSettings
from edu_api.tutor.errors import TutorConfigurationError
from edu_api.tutor.factory import build_provider
from edu_api.tutor.gateway import Attempt, ModelGateway, OutputRejected, RetryPolicy, Route
from edu_api.tutor.providers.base import (
    ChatMessage,
    ModelRequest,
    ModelResult,
    ProviderAuthError,
    ProviderBadResponseError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    TokenUsage,
)
from edu_api.tutor.providers.mock import MOCK_MODEL, Behaviour, DeterministicMockProvider
from edu_api.tutor.providers.openai_compatible import OpenAICompatibleProvider

from .conftest import make_settings, no_sleep

CHEAP = ModelPrice("test-v1", "cheap", 100_000, 200_000)
PRICEY = ModelPrice("test-v1", "pricey", 900_000, 2_000_000)

DATA = 'DATA\n{"lesson":{"language":"fr","passages":[{"id":"P1","kind":"paragraph","text":"t"}]},"student":{"intent":"ask_question","message":"m"}}'


def request_for(route: Route) -> ModelRequest:
    return ModelRequest(
        messages=(ChatMessage("system", 'Set "language" to "fr".'), ChatMessage("user", DATA)),
        model=route.model,
        max_output_tokens=200,
    )


def route(provider: Any, price: ModelPrice = CHEAP, timeout_s: float = 0.05) -> Route:
    return Route(provider, price.model, price, timeout_s)


def mock(*script: Behaviour, name: str = "mock") -> DeterministicMockProvider:
    return DeterministicMockProvider(name=name, script=script)


def accept(result: ModelResult) -> str:
    return result.text


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


async def test_success_on_the_first_try_makes_one_call_and_meters_it() -> None:
    provider = mock()
    attempts: list[Attempt] = []
    result = await ModelGateway(route(provider), sleep=no_sleep).run(request_for, accept, attempts)
    assert result.failure is None and result.value
    assert len(provider.calls) == 1
    assert [(a.outcome, a.usage_unknown) for a in attempts] == [("ok", False)]
    assert attempts[0].usage is not None and attempts[0].usage.input_tokens > 0


async def test_timeout_is_retried_with_backoff_then_succeeds() -> None:
    provider = mock("timeout", "ok")
    sleeps = Sleeps()
    attempts: list[Attempt] = []
    gateway = ModelGateway(
        route(provider), retry=RetryPolicy(max_attempts=3, base_delay_s=0.5), sleep=sleeps
    )
    result = await gateway.run(request_for, accept, attempts)
    assert result.failure is None
    assert [a.outcome for a in attempts] == ["timeout", "ok"]
    assert attempts[0].usage is None and attempts[0].usage_unknown  # may have been billed
    assert sleeps.delays == [0.5]


async def test_retries_are_bounded() -> None:
    provider = mock("timeout", "timeout", "timeout", "ok")
    attempts: list[Attempt] = []
    gateway = ModelGateway(route(provider), retry=RetryPolicy(max_attempts=2), sleep=no_sleep)
    result = await gateway.run(request_for, accept, attempts)
    assert (result.value, result.failure) == (None, "timeout")
    assert len(provider.calls) == 2 == gateway.max_calls


def test_backoff_grows_and_is_capped() -> None:
    policy = RetryPolicy(max_attempts=4, base_delay_s=0.5, max_delay_s=1.5)
    assert [policy.delay(n) for n in (2, 3, 4)] == [0.5, 1.0, 1.5]
    with pytest.raises(TutorConfigurationError):
        RetryPolicy(max_attempts=9)


async def test_an_auth_error_is_not_retried() -> None:
    provider = mock("auth_error", "ok")
    attempts: list[Attempt] = []
    gateway = ModelGateway(route(provider), retry=RetryPolicy(max_attempts=3), sleep=no_sleep)
    result = await gateway.run(request_for, accept, attempts)
    assert result.failure == "auth" and len(provider.calls) == 1
    assert attempts[0].usage_unknown is False  # rejected before any work: nothing to charge


async def test_rate_limiting_is_retried_and_not_charged() -> None:
    provider = mock("rate_limited", "ok")
    attempts: list[Attempt] = []
    result = await ModelGateway(route(provider), sleep=no_sleep).run(request_for, accept, attempts)
    assert result.failure is None
    assert (attempts[0].outcome, attempts[0].usage, attempts[0].usage_unknown) == (
        "rate_limited",
        None,
        False,
    )


async def test_rejected_output_is_retried_and_its_tokens_are_still_counted() -> None:
    provider = mock("ok", "ok")
    seen: list[str] = []

    def picky(result: ModelResult) -> str:
        seen.append(result.text)
        if len(seen) == 1:
            raise OutputRejected("not_json")
        return result.text

    attempts: list[Attempt] = []
    result = await ModelGateway(route(provider), sleep=no_sleep).run(request_for, picky, attempts)
    assert result.failure is None
    assert [(a.outcome, a.detail) for a in attempts] == [
        ("output_rejected", "not_json"),
        ("ok", ""),
    ]
    assert attempts[0].usage is not None  # the provider billed for the unusable answer


async def test_no_fallback_happens_unless_one_was_configured() -> None:
    primary = mock("unavailable", "unavailable")
    attempts: list[Attempt] = []
    result = await ModelGateway(route(primary), sleep=no_sleep).run(request_for, accept, attempts)
    assert result.failure == "unavailable"
    assert {a.provider for a in attempts} == {"mock"}


async def test_configured_fallback_is_used_once_after_the_primary_is_exhausted() -> None:
    primary, backup = mock("unavailable", "unavailable"), mock(name="backup")
    attempts: list[Attempt] = []
    gateway = ModelGateway(route(primary, PRICEY), fallback=route(backup, CHEAP), sleep=no_sleep)
    result = await gateway.run(request_for, accept, attempts)
    assert result.failure is None
    assert [(a.provider, a.model, a.outcome) for a in attempts] == [
        ("mock", "pricey", "unavailable"),
        ("mock", "pricey", "unavailable"),
        ("backup", "cheap", "ok"),
    ]
    assert gateway.max_calls == 3


async def test_fallback_is_tried_straight_away_when_retrying_the_primary_cannot_help() -> None:
    primary, backup = mock("auth_error"), mock(name="backup")
    attempts: list[Attempt] = []
    gateway = ModelGateway(route(primary, PRICEY), fallback=route(backup, CHEAP), sleep=no_sleep)
    await gateway.run(request_for, accept, attempts)
    assert [a.provider for a in attempts] == ["mock", "backup"]


def test_a_costlier_fallback_is_refused_unless_explicitly_allowed() -> None:
    with pytest.raises(TutorConfigurationError, match="costs more"):
        ModelGateway(route(mock(), CHEAP), fallback=route(mock(), PRICEY))
    ModelGateway(route(mock(), CHEAP), fallback=route(mock(), PRICEY), allow_costlier_fallback=True)


def test_a_route_must_use_the_price_of_its_own_model() -> None:
    with pytest.raises(TutorConfigurationError):
        Route(mock(), "some-other-model", CHEAP, 1.0)


def test_worst_case_cost_covers_every_call_the_gateway_may_make() -> None:
    gateway = ModelGateway(
        route(mock(), PRICEY), retry=RetryPolicy(max_attempts=2), fallback=route(mock(), CHEAP)
    )
    usage = TokenUsage(1_000, 500)
    assert gateway.worst_case_micro(input_tokens=1_000, max_output_tokens=500) == (
        2 * PRICEY.cost_micro(usage) + CHEAP.cost_micro(usage)
    )


async def test_cancellation_stops_the_call_and_records_the_attempt() -> None:
    provider = mock("timeout")
    attempts: list[Attempt] = []
    gateway = ModelGateway(route(provider, timeout_s=30), sleep=no_sleep)
    task = asyncio.create_task(gateway.run(request_for, accept, attempts))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [(a.outcome, a.usage_unknown) for a in attempts] == [("cancelled", True)]


async def test_an_adapter_crash_is_contained_and_its_text_is_not_kept() -> None:
    class Crashing:
        name = "crashing"

        async def complete(self, request: ModelRequest) -> ModelResult:
            raise RuntimeError("secret prompt: " + request.messages[1].content)

    attempts: list[Attempt] = []
    result = await ModelGateway(route(Crashing()), sleep=no_sleep).run(
        request_for, accept, attempts
    )
    assert result.failure == "provider_crashed"
    assert len(attempts) == 1 and attempts[0].usage_unknown
    assert "secret prompt" not in repr(attempts)


# --- configuration: no live provider without explicit authorisation -------------------------
def test_defaults_are_the_safe_ones() -> None:
    settings = TutorSettings(_env_file=None)
    assert settings.enabled is False
    assert settings.provider == "mock"
    assert settings.live_provider_calls_authorized is False
    assert settings.model == MOCK_MODEL
    assert settings.fallback_model is None and settings.allow_costlier_fallback is False
    assert isinstance(build_provider(settings), DeterministicMockProvider)


def test_a_live_provider_is_refused_without_explicit_authorisation() -> None:
    live = {
        "provider": "openai_compatible",
        "model": "vendor/some-model",
        "provider_base_url": "https://provider.invalid/api/v1",
        "provider_api_key": "sk-test-not-a-real-key",
        "prices": [
            {
                "price_version": "p1",
                "model": "vendor/some-model",
                "input_micro_per_mtok": 1,
                "output_micro_per_mtok": 1,
            }
        ],
    }
    with pytest.raises(TutorConfigurationError, match="not authorised"):
        build_provider(make_settings(**live))
    with pytest.raises(TutorConfigurationError, match="https"):
        build_provider(
            make_settings(
                **{**live, "provider_base_url": "http://provider.invalid"},
                live_provider_calls_authorized=True,
            )
        )
    with pytest.raises(TutorConfigurationError, match="API key"):
        build_provider(
            make_settings(**{**live, "provider_api_key": None}, live_provider_calls_authorized=True)
        )


def test_settings_reject_a_model_without_a_price_and_a_too_short_reservation() -> None:
    with pytest.raises(ValueError, match="no price configured"):
        make_settings(model="vendor/unpriced")
    with pytest.raises(ValueError, match="no price configured"):
        make_settings(fallback_model="vendor/unpriced")
    with pytest.raises(ValueError, match="reservation_ttl_s"):
        make_settings(request_timeout_s=60, max_attempts=2, reservation_ttl_s=120)


def test_the_api_key_never_appears_in_a_settings_dump() -> None:
    settings = make_settings(provider_api_key="sk-test-not-a-real-key")
    assert "sk-test-not-a-real-key" not in repr(settings)
    assert "sk-test-not-a-real-key" not in settings.model_dump_json()


# --- OpenAI-compatible adapter, driven only through an in-memory transport ------------------
def adapter(handler: Any) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://provider.invalid/api/v1",
        headers={"Authorization": "Bearer sk-test-not-a-real-key"},
    )
    return OpenAICompatibleProvider(client)


REQUEST = ModelRequest(
    messages=(ChatMessage("system", "rules"), ChatMessage("user", "data")),
    model="vendor/some-model",
    max_output_tokens=321,
    temperature=0.1,
)


async def test_adapter_sends_a_bounded_json_request_and_reads_usage() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"status":"answered"}'}}],
                "usage": {"prompt_tokens": 812, "completion_tokens": 97},
            },
        )

    result = await adapter(handler).complete(REQUEST)
    assert captured["url"] == "https://provider.invalid/api/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-test-not-a-real-key"
    assert captured["body"] == {
        "model": "vendor/some-model",
        "messages": [{"role": "system", "content": "rules"}, {"role": "user", "content": "data"}],
        "max_tokens": 321,
        "temperature": 0.1,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    assert result.text == '{"status":"answered"}'
    assert result.usage == TokenUsage(812, 97)
    assert (result.provider, result.model) == ("openrouter", "vendor/some-model")


@pytest.mark.parametrize(
    ("status", "error", "retryable", "usage_unknown"),
    [
        (401, ProviderAuthError, False, False),
        (403, ProviderAuthError, False, False),
        (429, ProviderRateLimitedError, True, False),
        (400, ProviderRejectedError, False, False),
        (408, ProviderTimeoutError, True, True),
        (504, ProviderTimeoutError, True, True),
        (500, ProviderUnavailableError, True, True),
        (503, ProviderUnavailableError, True, True),
    ],
)
async def test_adapter_maps_http_failures_to_typed_errors(
    status: int, error: type[ProviderError], retryable: bool, usage_unknown: bool
) -> None:
    secret_body = {"error": {"message": "echo of the prompt: data"}}
    with pytest.raises(error) as caught:
        await adapter(lambda request: httpx.Response(status, json=secret_body)).complete(REQUEST)
    assert (caught.value.retryable, caught.value.usage_unknown) == (retryable, usage_unknown)
    assert "echo of the prompt" not in str(caught.value)  # provider text is never carried along


async def test_adapter_maps_transport_failures() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderTimeoutError):
        await adapter(timeout).complete(REQUEST)
    with pytest.raises(ProviderUnavailableError):
        await adapter(refused).complete(REQUEST)


@pytest.mark.parametrize(
    "body",
    [
        {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        {"choices": [{"message": {"content": "x"}}]},  # no usage: cost unknown
        {
            "choices": [{"message": {"content": None}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
        {
            "choices": [{"message": {"content": "x"}}],
            "usage": {"prompt_tokens": -5, "completion_tokens": 1},
        },
        "not an object",
    ],
)
async def test_adapter_rejects_responses_it_cannot_meter(body: Any) -> None:
    with pytest.raises(ProviderBadResponseError) as caught:
        await adapter(lambda request: httpx.Response(200, json=body)).complete(REQUEST)
    assert caught.value.usage_unknown
