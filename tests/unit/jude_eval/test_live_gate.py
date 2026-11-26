"""Live evaluation is off by default and cannot overspend. No test here touches a network."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from typing import Any

import httpx
import pytest
from jude_eval import BENCH_ROOT, live
from jude_eval.candidates import Candidate
from jude_eval.dataset import build_cases, load_packs
from jude_eval.runner import RunStopped, run_model_layer

from edu_api.tutor.budget import ModelPrice
from edu_api.tutor.providers.base import ChatMessage, ModelRequest, ProviderUnavailableError
from edu_api.tutor.providers.mock import DeterministicMockProvider
from edu_api.tutor.providers.openai_compatible import OpenAICompatibleProvider

MODEL = "mistralai/mistral-small-3.2-24b-instruct"
TODAY = date(2026, 11, 27)
FAKE_KEY = "test-not-a-real-credential"


def complete_env(**overrides: str) -> dict[str, str]:
    env = {live.AUTHORIZATION_ENV: live.AUTHORIZATION_PHRASE, live.CREDENTIAL_ENV: FAKE_KEY}
    env.update(overrides)
    return env


def authorize(**overrides: Any) -> live.LiveAuthorization:
    options: dict[str, Any] = {
        "live_flag": True,
        "model": MODEL,
        "max_spend_usd": 2.0,
        "authorized_by": "Owner Name",
        "env": complete_env(),
        "today": TODAY,
    }
    options.update(overrides)
    return live.authorize_live_run(**options)


def test_with_nothing_set_every_condition_is_reported() -> None:
    with pytest.raises(live.LiveRunRefused) as refused:
        live.authorize_live_run(
            live_flag=False, model=None, max_spend_usd=None, authorized_by=None, env={}, today=TODAY
        )
    assert len(refused.value.reasons) == 6


def test_a_fully_authorised_run_is_accepted_and_records_no_credential() -> None:
    authorization = authorize()
    assert authorization.cap_micro == 2_000_000 and authorization.model == MODEL
    assert authorization.price.input_micro_per_mtok == 75_000
    assert authorization.price.output_micro_per_mtok == 200_000
    manifest = json.dumps(authorization.manifest())
    assert FAKE_KEY not in manifest and "Owner Name" in manifest


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"live_flag": False}, "--live flag"),
        ({"env": complete_env(**{live.AUTHORIZATION_ENV: "yes"})}, "authorisation phrase"),
        ({"env": {live.AUTHORIZATION_ENV: live.AUTHORIZATION_PHRASE}}, "no credential"),
        (
            {"env": complete_env(**{live.APPLICATION_KEY_ENV: FAKE_KEY})},
            "must not be the application's own key",
        ),
        ({"model": None}, "no model was named"),
        ({"model": "vendor/unknown-model"}, "no published price"),
        ({"max_spend_usd": None}, "no hard spending cap"),
        ({"max_spend_usd": 0}, "no hard spending cap"),
        ({"max_spend_usd": live.MAX_CAP_USD + 0.01}, "exceeds the ceiling"),
        ({"authorized_by": "  "}, "was not named"),
        ({"today": date(2027, 2, 1)}, "re-check it"),
    ],
)
def test_each_missing_condition_alone_refuses_the_run(
    overrides: dict[str, Any], reason: str
) -> None:
    with pytest.raises(live.LiveRunRefused) as refused:
        authorize(**overrides)
    assert len(refused.value.reasons) == 1 and reason in refused.value.reasons[0]


def test_the_command_line_refuses_by_default_and_spends_nothing() -> None:
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"}
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(BENCH_ROOT / "evaluate.py"), "live", "--model", MODEL],
        capture_output=True,
        text=True,
        env={**env, "PYTHONPATH": ":".join(sys.path)},
        check=False,
    )
    assert done.returncode == 2
    assert "live evaluation refused" in done.stderr and "--live flag" in done.stderr


# --- the spending cap ---------------------------------------------------------------------
PRICE = ModelPrice("p", "m", 1_000_000, 2_000_000)
REQUEST = ModelRequest(
    (
        ChatMessage("system", 'Set "language" to "fr".' + "x" * 2977),
        ChatMessage(
            "user",
            'DATA\n{"lesson":{"language":"fr","passages":[{"id":"P1","kind":"paragraph","text":"t"}]},"student":{"intent":"ask_question","message":"m"}}',
        ),
    ),
    "m",
    max_output_tokens=500,
)


async def test_a_call_that_could_exceed_the_cap_never_starts() -> None:
    inner = DeterministicMockProvider()
    guard = live.SpendGuard(cap_micro=3_000)
    provider = live.GuardedProvider(inner, PRICE, guard)
    await provider.complete(REQUEST)  # worst case ~2,050 fits under 3,000
    assert guard.calls == 1 and 0 < guard.spent_micro < 2_050
    with pytest.raises(live.SpendCapReached):
        await provider.complete(REQUEST)  # spent + worst case would pass the cap
    assert len(inner.calls) == 1  # the second request was never sent
    assert guard.spent_micro <= guard.cap_micro


async def test_a_failed_call_is_charged_at_its_worst_case() -> None:
    class Failing:
        name = "failing"

        async def complete(self, request: ModelRequest) -> Any:
            raise ProviderUnavailableError()

    guard = live.SpendGuard(cap_micro=10_000)
    with pytest.raises(ProviderUnavailableError):
        await live.GuardedProvider(Failing(), PRICE, guard).complete(REQUEST)  # type: ignore[arg-type]
    assert guard.spent_micro > 2_000


async def test_the_runner_stops_when_the_cap_is_reached_and_stays_under_it() -> None:
    packs = load_packs()
    cases = [c for c in build_cases(packs) if "model" in c.layers][:40]
    guard = live.SpendGuard(cap_micro=6_000)
    provider = live.GuardedProvider(DeterministicMockProvider(), PRICE, guard)
    candidate = Candidate("capped", "mock", "m", PRICE, lambda clock: provider)
    with pytest.raises(RunStopped):
        await run_model_layer(candidate, cases, packs, provider=provider)
    assert 0 < guard.calls < 40 and guard.spent_micro <= 6_000
    with pytest.raises(ValueError):
        live.SpendGuard(0)


async def test_a_live_provider_asks_only_for_providers_that_keep_no_data() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"status":"declined"}'}}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 40},
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=live.OPENROUTER_BASE_URL,
        headers={"Authorization": f"Bearer {FAKE_KEY}"},
    )
    authorization = authorize()
    guard = live.SpendGuard(authorization.cap_micro)
    provider = live.build_live_provider(authorization, guard, env=complete_env(), client=client)
    await provider.complete(ModelRequest(REQUEST.messages, MODEL, 500))
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["body"]["model"] == MODEL and seen["body"]["max_tokens"] == 500
    assert seen["body"]["provider"] == {
        "data_collection": "deny",
        "zdr": True,
        "require_parameters": True,
    }
    # 900 in, 40 out at 0.075 / 0.20 USD per million tokens, rounded up per direction.
    assert guard.spent_micro == 68 + 8


def test_the_adapter_cannot_have_its_own_fields_overridden() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ValueError, match="may not set"):
        OpenAICompatibleProvider(client, extra_body={"model": "something-expensive"})
    with pytest.raises(ValueError, match="may not set"):
        OpenAICompatibleProvider(client, extra_body={"max_tokens": 100000})


def test_no_credential_is_committed_anywhere_in_the_benchmark() -> None:
    for path in BENCH_ROOT.rglob("*"):
        if path.is_file() and path.suffix in {
            ".py",
            ".json",
            ".jsonl",
            ".md",
            ".env",
            ".yaml",
            ".yml",
            ".sh",
            ".example",
        }:
            text = path.read_text(encoding="utf-8")
            assert "sk-or-" not in text and "sk-ant-" not in text, path
            assert "rpa_" not in text and "hf_" + "A" not in text, path
    assert not list(BENCH_ROOT.rglob(".env"))
