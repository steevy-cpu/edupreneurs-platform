"""Candidates the harness can run offline, and fault injection.

THREE KINDS — never confuse them in a report:

* ``mock``       Jude-01's deterministic mock, unchanged. It stitches lesson text
                 together. Its scores say the plumbing works, nothing about models.
* ``simulated``  Scripted behaviour profiles built on the mock ("always cites a
                 gold passage", "leaks the answer in a hint", "returns broken
                 JSON a quarter of the time"). They exist to prove each metric
                 can tell good behaviour from bad. They are NOT models and their
                 numbers predict nothing about any real model.
* ``live``       A real model behind an API. Never constructed here: see ``live.py``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from edu_api.tutor.budget import ModelPrice
from edu_api.tutor.providers.base import (
    ModelProvider,
    ModelRequest,
    ModelResult,
    ProviderAuthError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
    TokenUsage,
)
from edu_api.tutor.providers.mock import MOCK_MODEL, DeterministicMockProvider
from edu_api.tutor.retrieval import RetrievedContext
from edu_api.tutor.text import estimate_tokens
from jude_eval.dataset import Case, LessonPack

CandidateKind = Literal["mock", "simulated", "live"]


class VirtualClock:
    """Simulated time, so offline runs are deterministic and never sleep."""

    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class CaseAware(Protocol):
    def bind(self, case: Case, pack: LessonPack, context: RetrievedContext | None) -> None: ...


@dataclass(frozen=True)
class Candidate:
    name: str
    kind: CandidateKind
    model: str
    price: ModelPrice
    make_provider: Callable[[VirtualClock], ModelProvider]
    note: str = ""


def _fraction(*parts: str) -> float:
    """A stable pseudo-random number in [0, 1) from the given strings."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


@dataclass(frozen=True)
class Profile:
    """How a simulated candidate deviates from doing the expected thing."""

    name: str
    description: str
    broken_json_rate: float = 0.0
    invented_reference_rate: float = 0.0
    wrong_language_rate: float = 0.0
    #: Answers even when the case expects it to abstain, decline or flag safety.
    never_abstains: bool = False
    #: Writes the final result into every hint.
    leaks_hints: bool = False
    #: Does what text planted in the lesson tells it to.
    obeys_injection: bool = False
    drops_check_question_rate: float = 0.0
    time_to_first_token_s: float = 0.5
    output_tokens_per_s: float = 60.0
    input_micro_per_mtok: int = 200_000
    output_micro_per_mtok: int = 600_000

    @property
    def model(self) -> str:
        return f"sim/{self.name}"

    @property
    def price(self) -> ModelPrice:
        return ModelPrice(
            "synthetic-sim-1", self.model, self.input_micro_per_mtok, self.output_micro_per_mtok
        )


@dataclass
class SimulatedProvider:
    """The mock's answer, bent toward the expected result and then degraded by a profile."""

    profile: Profile
    clock: VirtualClock
    name: str = "simulated"
    _case: Case | None = None
    _pack: LessonPack | None = None
    _context: RetrievedContext | None = None
    _mock: DeterministicMockProvider = field(default_factory=DeterministicMockProvider)

    def bind(self, case: Case, pack: LessonPack, context: RetrievedContext | None) -> None:
        self._case, self._pack, self._context = case, pack, context

    def _roll(self, defect: str) -> float:
        return _fraction(self.profile.name, defect, self._case.id if self._case else "")

    async def complete(self, request: ModelRequest) -> ModelResult:
        base = await self._mock.complete(request)
        text = self._shape(base.text)
        usage = TokenUsage(
            base.usage.input_tokens, min(estimate_tokens(text), request.max_output_tokens)
        )
        self.clock.advance(
            self.profile.time_to_first_token_s
            + usage.output_tokens / self.profile.output_tokens_per_s
        )
        return ModelResult(text=text, usage=usage, provider=self.name, model=request.model)

    def _shape(self, raw: str) -> str:
        profile, case = self.profile, self._case
        answer: dict[str, Any] = json.loads(raw)
        expected = case.expect_model if case else None
        if case is not None and profile.obeys_injection and case.poison is not None:
            return "PWNED " + case.poison.text
        if expected is not None and expected.outcomes and not profile.never_abstains:
            status, _, grounding = expected.outcomes[0].partition("/")
            if status != "answered":
                answer.update(
                    status=status,
                    grounding="none",
                    explanation="",
                    hint=None,
                    check_question=None,
                    references=[],
                    next_action="none",
                )
            elif grounding == "general" and not expected.gold:
                answer.update(grounding="general", references=[])
        if expected is not None and expected.gold and self._context is not None:
            gold_ids = [p.id for p in self._context.passages if p.passage.ref.key in expected.gold]
            if gold_ids and answer.get("status") == "answered":
                answer["references"] = gold_ids[:2]
                answer["grounding"] = "lesson"
        if case is not None and case.intent == "hint" and profile.leaks_hints and self._pack:
            answer["hint"] = f"{answer.get('hint') or ''} {self._pack.final_answer_text}".strip()
        if self._roll("check") < profile.drops_check_question_rate:
            answer["check_question"] = None
        if self._roll("language") < profile.wrong_language_rate:
            answer["language"] = "fr" if answer.get("language") == "ht" else "ht"
        if self._roll("reference") < profile.invented_reference_rate:
            answer["references"] = ["P97"]
        text = json.dumps(answer, ensure_ascii=False)
        if self._roll("json") < profile.broken_json_rate:
            return text[: max(len(text) // 2, 1)]
        return text


PROFILES: tuple[Profile, ...] = (
    Profile(
        "reference",
        "Returns the expected status and cites a gold passage whenever one was retrieved. "
        "An upper bound for the automatic checks, not a model.",
    ),
    Profile(
        "sloppy-json",
        "Like reference, but a quarter of replies are cut off mid-object.",
        broken_json_rate=0.25,
    ),
    Profile(
        "citation-inventor",
        "Never abstains and cites a passage that does not exist in 30% of replies.",
        invented_reference_rate=0.30,
        never_abstains=True,
    ),
    Profile(
        "leaky-tutor",
        "Puts the final result in every hint and often forgets the check question.",
        leaks_hints=True,
        drops_check_question_rate=0.40,
    ),
    Profile(
        "obedient",
        "Follows instructions planted in lesson text; declares the wrong language 20% of the time.",
        obeys_injection=True,
        wrong_language_rate=0.20,
    ),
    Profile(
        "slow-costly",
        "Behaves like reference at five times the price and a third of the speed.",
        time_to_first_token_s=1.8,
        output_tokens_per_s=20.0,
        input_micro_per_mtok=1_000_000,
        output_micro_per_mtok=3_000_000,
    ),
)

MOCK_PRICE = ModelPrice("synthetic-2026-11", MOCK_MODEL, 500_000, 1_500_000)


def offline_candidates() -> list[Candidate]:
    candidates = [
        Candidate(
            name="mock (Jude-01)",
            kind="mock",
            model=MOCK_MODEL,
            price=MOCK_PRICE,
            make_provider=lambda clock: DeterministicMockProvider(),
            note="Stitches lesson text; never abstains; proves the plumbing only.",
        )
    ]
    for profile in PROFILES:
        candidates.append(
            Candidate(
                name=f"sim: {profile.name}",
                kind="simulated",
                model=profile.model,
                price=profile.price,
                make_provider=lambda clock, p=profile: SimulatedProvider(p, clock),  # type: ignore[misc]
                note=profile.description,
            )
        )
    return candidates


# --- fault injection ---------------------------------------------------------------------
Fault = Literal[
    "pass",
    "timeout",
    "unavailable",
    "rate_limited",
    "auth",
    "garbage",
    "truncate",
    "empty",
    "bad_reference",
    "wrong_language",
    "extra_field",
]
FAULTS: frozenset[str] = frozenset(Fault.__args__)  # type: ignore[attr-defined]


@dataclass
class FaultInjector:
    """Wraps ANY provider and makes its first calls fail the way real ones do.

    Transport faults raise the provider's typed errors; content faults take the
    wrapped provider's real answer and damage it. After the script is used up
    every call passes through.
    """

    inner: ModelProvider
    script: Sequence[str]
    calls: int = 0
    name: str = "fault-injector"

    def __post_init__(self) -> None:
        self.name = self.inner.name

    def bind(self, case: Case, pack: LessonPack, context: RetrievedContext | None) -> None:
        if hasattr(self.inner, "bind"):
            self.inner.bind(case, pack, context)

    async def complete(self, request: ModelRequest) -> ModelResult:
        fault = self.script[self.calls] if self.calls < len(self.script) else "pass"
        self.calls += 1
        if fault not in FAULTS:
            raise ValueError(f"unknown fault {fault!r}")
        if fault == "timeout":
            await asyncio.Event().wait()
        if fault == "unavailable":
            raise ProviderUnavailableError()
        if fault == "rate_limited":
            raise ProviderRateLimitedError()
        if fault == "auth":
            raise ProviderAuthError()
        result = await self.inner.complete(request)
        if fault == "pass":
            return result
        return ModelResult(
            text=_damage(result.text, fault),
            usage=result.usage,
            provider=result.provider,
            model=result.model,
        )


def _damage(text: str, fault: str) -> str:
    if fault == "garbage":
        return "Bien sûr ! Voici la réponse à ta question."
    if fault == "empty":
        return ""
    if fault == "truncate":
        return text[: max(len(text) // 2, 1)]
    try:
        answer: dict[str, Any] = json.loads(text)
    except ValueError:
        return text
    if fault == "bad_reference":
        answer["references"] = ["P97"]
    elif fault == "wrong_language":
        answer["language"] = "fr" if answer.get("language") == "ht" else "ht"
    elif fault == "extra_field":
        answer["confidence"] = 0.93
    return json.dumps(answer, ensure_ascii=False)
