"""Validation of what a model returned, before a student can see it.

A model's reply is untrusted input. It is accepted only if:

* it is one JSON object of exactly the expected shape;
* its language is the one that was asked for;
* every reference is a passage id the server issued for THIS request — the
  server then swaps ids for real lesson references, so a citation the student
  sees can only point at a passage that was really supplied;
* "grounded in the lesson" comes with at least one such reference;
* the text has no links, contact details, leaked instructions or claims that
  Jude contacted someone.

Anything else raises ``OutputRejected`` and is never shown.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from edu_api.tutor.gateway import OutputRejected
from edu_api.tutor.retrieval import RetrievedContext
from edu_api.tutor.safety import output_violations
from edu_api.tutor.text import normalize, words
from edu_api.tutor.types import Grounding, LessonReference, Locale, NextAction, ResponseStatus

MAX_EXPLANATION_CHARS = 1500
MAX_SHORT_FIELD_CHARS = 400

ModelNextAction = Literal[
    "none",
    "reread_passage",
    "review_example",
    "try_practice_question",
    "ask_follow_up",
    "rephrase_question",
]


class ModelAnswer(BaseModel):
    """The JSON object the output-format section of the prompt asks for."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["answered", "insufficient_context", "declined", "safety_support"]
    grounding: Literal["lesson", "general", "none"]
    language: Literal["fr", "ht"]
    explanation: str = Field(max_length=MAX_EXPLANATION_CHARS)
    hint: str | None = Field(default=None, max_length=MAX_SHORT_FIELD_CHARS)
    check_question: str | None = Field(default=None, max_length=MAX_SHORT_FIELD_CHARS)
    references: list[str] = Field(default_factory=list, max_length=12)
    next_action: ModelNextAction = "none"


@dataclass(frozen=True)
class ValidatedAnswer:
    status: ResponseStatus
    grounding: Grounding
    explanation: str
    hint: str | None
    check_question: str | None
    references: tuple[LessonReference, ...]
    next_action: NextAction


# Words that are common in one language and absent from the other (after accent folding).
_FRENCH_MARKERS = words(
    "les des est une dans pour que avec sont cette nous vous il elle on du au aux qui "
    "tu ton tes peux deux cotes donc"
)
_CREOLE_MARKERS = words(
    "yon nan ki pou ak yo li mwen nou lan gen kapab ka w fe leson bo epi kidonk paske "
    "menm oswa kounye"
)


def looks_like_other_language(text: str, expected: Locale) -> bool:
    """True only on strong evidence that ``text`` is in the other supported language.

    Short or ambiguous text passes: this catches a model that ignored the
    language instruction, it is not a language detector.
    """
    words = normalize(text).split()
    if len(words) < 8:
        return False
    french = sum(1 for w in words if w.strip(".,;:!?()'\"") in _FRENCH_MARKERS)
    creole = sum(1 for w in words if w.strip(".,;:!?()'\"") in _CREOLE_MARKERS)
    expected_hits, other_hits = (french, creole) if expected == "fr" else (creole, french)
    return other_hits >= 4 and other_hits >= 3 * max(expected_hits, 1)


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```") and text.endswith("```") and len(text) >= 6:
        inner = text[3:-3]
        if inner[:4].lower() == "json":
            inner = inner[4:]
        return inner.strip()
    return text


def validate_model_output(
    raw: str,
    *,
    context: RetrievedContext,
    expected_language: Locale,
    canary: str,
    allow_general: bool = True,
) -> ValidatedAnswer:
    """Parse and check a model reply, or raise ``OutputRejected`` with a reason code."""
    # The leak check runs on the raw text: a reply that is not even JSON can still leak.
    if canary and canary in raw:
        raise OutputRejected("system_prompt_leak")
    try:
        decoded = json.loads(_strip_code_fence(raw))
    except ValueError:
        raise OutputRejected("not_json") from None
    if not isinstance(decoded, dict):
        raise OutputRejected("not_an_object")
    try:
        answer = ModelAnswer.model_validate(decoded)
    except ValidationError:
        raise OutputRejected("wrong_shape") from None

    if answer.language != expected_language:
        raise OutputRejected("wrong_language")

    status = ResponseStatus(answer.status)
    if status is not ResponseStatus.ANSWERED:
        # The service replaces these with reviewed fixed messages; model text is dropped.
        return ValidatedAnswer(status, Grounding.NONE, "", None, None, (), NextAction.NONE)

    explanation = answer.explanation.strip()
    hint = (answer.hint or "").strip() or None
    check_question = (answer.check_question or "").strip() or None
    if not explanation:
        raise OutputRejected("empty_explanation")

    student_facing = "\n".join(part for part in (explanation, hint, check_question) if part)
    problems = output_violations(student_facing, canary=canary)
    if problems:
        raise OutputRejected(problems[0])
    if looks_like_other_language(student_facing, expected_language):
        raise OutputRejected("wrong_language")

    issued = context.by_id()
    unknown = [ref for ref in answer.references if ref not in issued]
    if unknown:
        raise OutputRejected("unknown_reference")
    references = tuple(dict.fromkeys(issued[ref].ref for ref in answer.references))

    grounding = Grounding(answer.grounding)
    if grounding is Grounding.NONE:
        raise OutputRejected("answered_without_grounding")
    if grounding is Grounding.LESSON and not references:
        raise OutputRejected("grounded_without_reference")
    if grounding is Grounding.GENERAL and not allow_general:
        raise OutputRejected("general_answer_not_allowed")

    return ValidatedAnswer(
        status=status,
        grounding=grounding,
        explanation=explanation,
        hint=hint,
        check_question=check_question,
        references=references,
        next_action=NextAction(answer.next_action),
    )
