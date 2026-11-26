"""Independent checks with synthetic data. The enclosing fixture disables sockets."""

import gc
import weakref

import httpx
import pytest

from edu_api.tutor.factory import build_provider, build_tutor_service
from edu_api.tutor.providers.base import ChatMessage, ModelRequest, ProviderError
from edu_api.tutor.providers.openai_compatible import OpenAICompatibleProvider
from edu_api.tutor.safety import ScreenAction, screen_student_message
from tests.unit.tutor.conftest import LEARNER_A, ask, build_harness, make_settings

REQUEST = ModelRequest((ChatMessage("user", "Addition"),), "synthetic", 50)


async def test_factory_mock_drops_completed_request() -> None:
    provider = build_provider(make_settings())
    harness = build_harness()
    # Observe a real service request without retaining a reference ourselves.
    observed = []

    class Observer:
        name = provider.name

        async def complete(self, request):
            observed.append(weakref.ref(request))
            return await provider.complete(request)

    svc = build_tutor_service(
        harness.settings,
        lessons=harness.lessons,
        usage=harness.usage,
        consent=harness.consent,
        entitlements=harness.entitlements,
        provider=Observer(),
    )
    await svc.answer(LEARNER_A, ask())
    gc.collect()
    assert len(observed) == 1
    assert observed[0]() is None, "factory mock retained the completed provider request"


@pytest.mark.parametrize("counter", [True, 1.5])
async def test_adapter_refuses_noninteger_usage(counter) -> None:
    response = {
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": counter, "completion_tokens": 2},
    }
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    async with httpx.AsyncClient(
        base_url="https://provider.invalid", transport=transport
    ) as client:
        with pytest.raises(ProviderError):
            await OpenAICompatibleProvider(client).complete(REQUEST)


async def test_redirect_status_is_never_a_completion() -> None:
    response = {
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }
    transport = httpx.MockTransport(lambda _: httpx.Response(302, json=response))
    async with httpx.AsyncClient(
        base_url="https://provider.invalid", transport=transport
    ) as client:
        with pytest.raises(ProviderError):
            await OpenAICompatibleProvider(client).complete(REQUEST)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Dans le roman, le narrateur dit « je suis en danger ». Quel est le sujet ?",
            ScreenAction.ALLOW,
        ),
        ("Je ne me sens pas en sécurité chez moi.", ScreenAction.SAFETY_SUPPORT),
    ],
)
def test_synthetic_safeguarding_triage_examples(text, expected) -> None:
    assert screen_student_message(text).action is expected


async def test_unnecessary_self_identification_stays_out_of_provider_data() -> None:
    harness = build_harness()
    await harness.service.answer(
        LEARNER_A, ask(message="Je m'appelle Élève-Exemple. Pourquoi soustraire 5 des deux côtés ?")
    )
    assert len(harness.provider.calls) == 1
    assert all(
        "Élève-Exemple" not in message.content for message in harness.provider.calls[0].messages
    )


async def test_client_cancelled_during_settlement_keeps_its_single_charge(monkeypatch):
    import asyncio

    harness = build_harness()
    started, resume, done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    settle = harness.usage.settle

    async def delayed(reservation, outcome):
        started.set()
        await resume.wait()
        await settle(reservation, outcome)
        done.set()

    monkeypatch.setattr(harness.usage, "settle", delayed)
    task = asyncio.create_task(harness.service.answer(LEARNER_A, ask()))
    try:
        async with asyncio.timeout(5):
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            resume.set()
            await done.wait()
    finally:
        resume.set()
    records = harness.usage.records()
    assert len(records) == 1 and records[0].status == "settled"
    assert records[0].attempts == 1 and records[0].spent_micro > 0


def test_live_capable_dependency_needs_the_authorization_gate():
    from edu_api.tutor.errors import TutorConfigurationError

    harness = build_harness()
    with pytest.raises(TutorConfigurationError):
        build_tutor_service(
            harness.settings,
            lessons=harness.lessons,
            usage=harness.usage,
            consent=harness.consent,
            entitlements=harness.entitlements,
            provider=OpenAICompatibleProvider(
                httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
            ),
        )


async def test_injected_http_client_must_match_approved_https_origin():
    from pydantic import SecretStr

    from edu_api.tutor.errors import TutorConfigurationError

    settings = make_settings(
        provider="openai_compatible",
        live_provider_calls_authorized=True,
        provider_base_url="https://approved.invalid",
        provider_api_key=SecretStr("synthetic"),
    )
    async with httpx.AsyncClient(
        base_url="http://different.invalid",
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
    ) as client:
        with pytest.raises(TutorConfigurationError):
            build_provider(settings, http_client=client)
