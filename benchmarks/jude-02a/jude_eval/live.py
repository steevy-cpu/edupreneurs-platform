"""Optional live evaluation against a real provider — OFF, and hard to turn on by accident.

Nothing in Jude-02A runs this. It exists so that a later, authorised evaluation
uses the same cases and metrics instead of an ad-hoc script.

A live run is refused unless ALL of these hold:

1. the ``--live`` flag was given;
2. ``JUDE_EVAL_LIVE_AUTHORIZED`` is set to the exact phrase below;
3. a credential is in ``JUDE_EVAL_OPENROUTER_API_KEY`` — a variable used by
   nothing else, and it must differ from the application's own key;
4. one model is named, and ``config/published_prices.json`` has a price for it
   that was checked recently;
5. a hard spending cap in USD is given, above zero and at most ``MAX_CAP_USD``;
6. the person authorising is named (recorded in the run manifest).

The cap is enforced BEFORE each call: the worst case for that call (its whole
input plus the full output limit) must still fit, or the run stops. The key is
read from the environment only, never written anywhere, and the benchmark sends
only its own synthetic questions.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from edu_api.tutor.budget import MICROS_PER_USD, ModelPrice
from edu_api.tutor.providers.base import ModelProvider, ModelRequest, ModelResult, TokenUsage
from edu_api.tutor.providers.openai_compatible import OpenAICompatibleProvider
from edu_api.tutor.text import estimate_tokens
from jude_eval import CONFIG_DIR
from jude_eval.runner import RunStopped

AUTHORIZATION_ENV = "JUDE_EVAL_LIVE_AUTHORIZED"
AUTHORIZATION_PHRASE = "I authorize paid model calls for Jude evaluation"
CREDENTIAL_ENV = "JUDE_EVAL_OPENROUTER_API_KEY"
APPLICATION_KEY_ENV = "EDU_TUTOR_PROVIDER_API_KEY"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
#: No single evaluation run may be capped higher than this, whatever is asked for.
MAX_CAP_USD = 20.0
#: A published price older than this must be re-checked before money is spent on it.
MAX_PRICE_AGE_DAYS = 30
#: Sent with every live request: only providers that do not store prompts.
OPENROUTER_ROUTING: dict[str, object] = {
    "provider": {"data_collection": "deny", "zdr": True, "require_parameters": True}
}


class LiveRunRefused(Exception):
    """One or more conditions for a live run are not met. Lists all of them."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("live evaluation refused:\n- " + "\n- ".join(reasons))
        self.reasons = reasons


class SpendCapReached(RunStopped):
    pass


@dataclass(frozen=True)
class LiveAuthorization:
    model: str
    price: ModelPrice
    cap_micro: int
    authorized_by: str

    def manifest(self) -> dict[str, object]:
        """What is recorded about the authorisation. Never the credential."""
        return {
            "model": self.model,
            "price_version": self.price.price_version,
            "cap_usd": self.cap_micro / MICROS_PER_USD,
            "authorized_by": self.authorized_by,
        }


def load_published_price(
    model: str, *, today: date, path: Path | None = None
) -> tuple[ModelPrice | None, str]:
    """The published price of ``model`` and why it cannot be used, if it cannot."""
    document = json.loads((path or CONFIG_DIR / "published_prices.json").read_text("utf-8"))
    entry = next((m for m in document["openrouter"]["models"] if m["slug"] == model), None)
    if entry is None:
        return None, f"no published price recorded for model {model!r}"
    retrieved = date.fromisoformat(document["retrieved_on"])
    age = (today - retrieved).days
    if age > MAX_PRICE_AGE_DAYS:
        return None, (
            f"the recorded price for {model!r} was read {age} days ago; re-check it and "
            "update config/published_prices.json"
        )
    return (
        ModelPrice(
            f"openrouter-{document['retrieved_on']}",
            model,
            round(entry["input_usd_per_mtok"] * MICROS_PER_USD),
            round(entry["output_usd_per_mtok"] * MICROS_PER_USD),
        ),
        "",
    )


def authorize_live_run(
    *,
    live_flag: bool,
    model: str | None,
    max_spend_usd: float | None,
    authorized_by: str | None,
    env: Mapping[str, str] | None = None,
    today: date | None = None,
    prices_path: Path | None = None,
) -> LiveAuthorization:
    env = os.environ if env is None else env
    reasons: list[str] = []
    if not live_flag:
        reasons.append("the --live flag was not given")
    if env.get(AUTHORIZATION_ENV) != AUTHORIZATION_PHRASE:
        reasons.append(f"{AUTHORIZATION_ENV} is not set to the authorisation phrase")
    key = env.get(CREDENTIAL_ENV, "")
    if not key:
        reasons.append(f"no credential in {CREDENTIAL_ENV}")
    elif key == env.get(APPLICATION_KEY_ENV):
        reasons.append("the evaluation credential must not be the application's own key")
    price: ModelPrice | None = None
    if not model:
        reasons.append("no model was named (--model)")
    else:
        price, why = load_published_price(model, today=today or date.today(), path=prices_path)
        if price is None:
            reasons.append(why)
    if max_spend_usd is None or max_spend_usd <= 0:
        reasons.append("no hard spending cap was given (--max-spend-usd)")
    elif max_spend_usd > MAX_CAP_USD:
        reasons.append(f"the spending cap exceeds the ceiling of {MAX_CAP_USD:.2f} USD per run")
    if not authorized_by or not authorized_by.strip():
        reasons.append("the person authorising the run was not named (--authorized-by)")
    if reasons or price is None or model is None or max_spend_usd is None or not authorized_by:
        raise LiveRunRefused(reasons)
    return LiveAuthorization(
        model, price, round(max_spend_usd * MICROS_PER_USD), authorized_by.strip()
    )


class SpendGuard:
    """Counts money and refuses a call that could take the run over its cap."""

    def __init__(self, cap_micro: int) -> None:
        if cap_micro <= 0:
            raise ValueError("the cap must be positive")
        self.cap_micro = cap_micro
        self.spent_micro = 0
        self.calls = 0

    def check(self, worst_case_micro: int) -> None:
        if self.spent_micro + worst_case_micro > self.cap_micro:
            raise SpendCapReached(
                f"stopping: {self.spent_micro} micro-USD spent, the next call could cost "
                f"{worst_case_micro}, cap is {self.cap_micro}"
            )

    def record(self, micro: int) -> None:
        self.spent_micro += micro
        self.calls += 1


class GuardedProvider:
    """Wraps a provider so no call can start unless its worst case fits under the cap."""

    def __init__(self, inner: ModelProvider, price: ModelPrice, guard: SpendGuard) -> None:
        self._inner = inner
        self._price = price
        self._guard = guard
        self.name = inner.name

    async def complete(self, request: ModelRequest) -> ModelResult:
        worst = self._price.cost_micro(
            TokenUsage(
                sum(estimate_tokens(m.content) for m in request.messages),
                request.max_output_tokens,
            )
        )
        self._guard.check(worst)
        try:
            result = await self._inner.complete(request)
        except BaseException:
            # Unknown outcome: assume the provider billed the whole call.
            self._guard.record(worst)
            raise
        self._guard.record(self._price.cost_micro(result.usage))
        return result


def build_live_provider(
    authorization: LiveAuthorization,
    guard: SpendGuard,
    *,
    env: Mapping[str, str] | None = None,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 30.0,
) -> GuardedProvider:
    """An OpenRouter-backed provider under the spending guard. Tests pass ``client``."""
    env = os.environ if env is None else env
    client = client or httpx.AsyncClient(
        base_url=OPENROUTER_BASE_URL,
        headers={"Authorization": f"Bearer {env[CREDENTIAL_ENV]}"},
        timeout=timeout_s,
    )
    return GuardedProvider(
        OpenAICompatibleProvider(client, name="openrouter", extra_body=OPENROUTER_ROUTING),
        authorization.price,
        guard,
    )
