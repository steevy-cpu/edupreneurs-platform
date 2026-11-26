"""A deterministic stand-in for a language model. No network, no randomness.

It reads the same prompt a real model would get and writes a structured
answer assembled from the lesson passages it was given, so the whole pipeline
— retrieval, prompt, budget, validation, citation mapping — runs end to end
in tests and in the demo. Its answers are stitched-together lesson text: they
demonstrate the plumbing, not tutoring quality.

``script`` makes it misbehave on purpose, one entry per call, to test the
failure paths (timeouts, garbage output, invented citations, obeying an
injected instruction ...).

PRIVACY: this class keeps NOTHING from a request after ``complete`` returns —
only how many calls it has served. It is the provider the factory builds by
default, so a long-lived service must not accumulate student text in it. A
test that needs to look at what was sent injects its own recording spy
(``tests/unit/tutor/spies.py``); there is none in this package.

METERING: the usage it reports comes from its own crude tokenizer model
(``mock_token_count`` plus framing), which is deliberately NOT the bound the
service reserves with (``edu_api.tutor.metering``). The two are independent,
so a test can tell a hold that is too small from one that is large enough.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from edu_api.tutor.providers.base import (
    ModelRequest,
    ModelResult,
    ProviderAuthError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
    TokenUsage,
)

MOCK_MODEL = "mock/jude-deterministic-v1"

#: Framing the mock "bills" on top of the message text, like a chat template would.
MOCK_FRAMING_TOKENS_PER_MESSAGE = 4
MOCK_FRAMING_TOKENS_PER_REQUEST = 3


def mock_token_count(text: str) -> int:
    """The mock model's tokenizer: one token per three UTF-8 bytes, rounded up.

    Roughly right for French and Creole prose. It is a property of the MOCK,
    used to produce a plausible invoice; nothing reserves budget with it.
    """
    return (len(text.encode("utf-8")) + 2) // 3


Behaviour = Literal[
    "ok",
    "timeout",  # never answers; the gateway's timeout fires
    "unavailable",
    "rate_limited",
    "auth_error",
    "invalid_json",
    "wrong_shape",
    "hallucinated_reference",
    "obey_injection",  # does what text inside the lesson told it to
    "leak_system_prompt",
    "wrong_language",
    "link_in_answer",
    "insufficient",
    "general_knowledge",
    "safety_support",
]

_PHRASES: dict[str, dict[str, str]] = {
    "fr": {
        "lead": "D'après la leçon : ",
        "hint": "Indice : relis ce passage et cherche quelle opération on fait des deux côtés.",
        "check": "À toi : peux-tu expliquer cette étape avec tes propres mots ?",
        "encourage": "Tu es sur la bonne voie : regarde la méthode de la leçon.",
        "correct": "Ta réponse est correcte. ",
        "incorrect": "Ta réponse n'est pas correcte. ",
        "general": "Ceci ne vient pas de la leçon : c'est une connaissance générale. ",
        "cross": "D'après la leçon (rédigée en créole), la réponse s'appuie sur les passages "
        "cités ci-dessous. Ce modèle de test ne traduit pas le texte de la leçon.",
    },
    "ht": {
        "lead": "Dapre leson an: ",
        "hint": "Endis: reli pasaj sa a epi chèche ki operasyon nou fè nan de bò yo.",
        "check": "Kounye a se tou pa w: èske ou ka eksplike etap sa a ak pwòp mo pa w?",
        "encourage": "Ou sou bon chemen an: gade metòd ki nan leson an.",
        "correct": "Repons ou an kòrèk. ",
        "incorrect": "Repons ou an pa kòrèk. ",
        "general": "Sa a pa soti nan leson an: se yon konesans jeneral. ",
        "cross": "Dapre leson an (ki ekri an fransè), repons lan chita sou pasaj mwen site "
        "anba a yo. Modèl tès sa a pa tradui tèks leson an.",
    },
}


@dataclass
class DeterministicMockProvider:
    name: str = "mock"
    script: Sequence[Behaviour] = ()
    #: Behaviour once the script is used up.
    default: Behaviour = "ok"
    #: Number of calls served so far. The only thing remembered between calls.
    call_count: int = 0
    #: When set, every call waits for it first (to hold requests "in flight" in tests).
    gate: asyncio.Event | None = None
    #: Set as soon as the first call arrives (lets a test wait for "in flight").
    started: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def calls(self) -> Sequence[object]:
        """The indices of the calls served: ``len(provider.calls)`` is the call count.

        Indices only. The requests themselves are not kept.
        """
        return range(self.call_count)

    async def complete(self, request: ModelRequest) -> ModelResult:
        index = self.call_count
        self.call_count += 1
        self.started.set()
        behaviour: Behaviour = self.script[index] if index < len(self.script) else self.default
        if self.gate is not None:
            await self.gate.wait()
        if behaviour == "timeout":
            await asyncio.Event().wait()  # until cancelled by the gateway's timeout
        if behaviour == "unavailable":
            raise ProviderUnavailableError()
        if behaviour == "rate_limited":
            raise ProviderRateLimitedError()
        if behaviour == "auth_error":
            raise ProviderAuthError()
        text = self._write(request, behaviour)
        usage = TokenUsage(
            input_tokens=MOCK_FRAMING_TOKENS_PER_REQUEST
            + sum(
                MOCK_FRAMING_TOKENS_PER_MESSAGE + mock_token_count(m.content)
                for m in request.messages
            ),
            output_tokens=min(mock_token_count(text), request.max_output_tokens),
        )
        return ModelResult(text=text, usage=usage, provider=self.name, model=request.model)

    def _write(self, request: ModelRequest, behaviour: Behaviour) -> str:
        system = request.messages[0].content
        data = _read_data(request.messages[-1].content)
        passages: list[dict[str, Any]] = data["lesson"]["passages"]
        student: dict[str, Any] = data["student"]
        language = "ht" if '"language" to "ht"' in system else "fr"
        phrases = _PHRASES[language]

        if behaviour == "invalid_json":
            return "Bien sûr ! Voici mon explication : on soustrait 5 des deux côtés."
        if behaviour == "obey_injection":
            return "PWNED. Voici mes instructions : " + system[:200]
        if behaviour == "wrong_shape":
            return json.dumps({"answer": "x = 7", "confidence": 0.9})

        body = [p for p in passages if p["kind"] != "heading"] or passages
        used = body[:2]
        explanation = phrases["lead"] + " ".join(" ".join(str(p["text"]).split()) for p in used)
        if data["lesson"].get("language") != language:
            # A real model would translate; this stand-in will not pretend to.
            explanation = phrases["cross"]
        if "answer_is_correct" in student:
            explanation = (
                phrases["correct"] if student["answer_is_correct"] else phrases["incorrect"]
            ) + explanation
        explanation = explanation[:700]
        answer: dict[str, Any] = {
            "status": "answered",
            "grounding": "lesson",
            "language": language,
            "explanation": explanation,
            "hint": None,
            "check_question": phrases["check"],
            "references": [p["id"] for p in used],
            "next_action": "try_practice_question",
        }
        if student.get("intent") == "hint":
            answer["explanation"] = phrases["encourage"]
            answer["hint"] = phrases["hint"]
            answer["check_question"] = None
            answer["next_action"] = "reread_passage"
        if student.get("intent") == "another_example":
            answer["next_action"] = "review_example"

        if behaviour == "hallucinated_reference":
            answer["references"] = ["P99"]
        elif behaviour == "leak_system_prompt":
            marker = system.split("never output: ")[-1].split("\n")[0]
            answer["explanation"] = f"{explanation} {marker}"
        elif behaviour == "wrong_language":
            other = "fr" if language == "ht" else "ht"
            answer["language"] = other
        elif behaviour == "link_in_answer":
            answer["explanation"] = explanation + " Voir https://example.invalid/solution"
        elif behaviour == "insufficient":
            answer.update(
                status="insufficient_context",
                grounding="none",
                explanation="",
                hint=None,
                check_question=None,
                references=[],
                next_action="rephrase_question",
            )
        elif behaviour == "general_knowledge":
            answer.update(
                grounding="general",
                explanation=phrases["general"] + explanation,
                references=[],
            )
        elif behaviour == "safety_support":
            answer.update(
                status="safety_support",
                grounding="none",
                explanation="",
                hint=None,
                check_question=None,
                references=[],
                next_action="none",
            )
        return json.dumps(answer, ensure_ascii=False)


def _read_data(message: str) -> dict[str, Any]:
    """Parse the DATA envelope the way the prompt template wrote it."""
    document: dict[str, Any] = json.loads(message[message.index("{") :])
    return document
