"""Authoring helpers: write the pilot's JSON from compact Python definitions.

This module is NOT part of the validator. The validator only reads the committed JSON, so a mistake here is
caught exactly like a mistake in a hand-edited file. French and Haitian Creole texts are written separately
(the Creole is never produced by a function applied to the French).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

NBSP = "\u00a0"
_GROUP = re.compile(r"(?<=\d) (?=\d{3}(?!\d))")


def nb(text: str) -> str:
    """Join digit groups with a no-break space so '2 450' never wraps in the middle of a number."""
    prev = None
    while prev != text:
        prev = text
        text = _GROUP.sub(NBSP, text)
    return text


def fmt(n: int) -> str:
    return nb(f"{n:,}".replace(",", " "))


def H(key: str, text: str) -> dict[str, Any]:
    return {"key": key, "type": "heading", "text": nb(text)}


def P(key: str, text: str) -> dict[str, Any]:
    return {"key": key, "type": "paragraph", "text": nb(text)}


def EX(key: str, title: str, steps: list[str]) -> dict[str, Any]:
    return {"key": key, "type": "example", "title": nb(title), "steps": [nb(s) for s in steps]}


def CO(key: str, tone: str, text: str) -> dict[str, Any]:
    return {"key": key, "type": "callout", "tone": tone, "text": nb(text)}


@dataclass
class C:
    """One answer choice. `value` is the verified value (mode 'value'); `expr` a true/false claim (mode 'truth')."""

    value: Any = None
    expr: str | None = None
    fr: str | None = None
    ht: str | None = None


@dataclass
class Q:
    key: str
    mode: str  # 'value' | 'truth'
    correct: str
    prompt: dict[str, str]
    explanation: dict[str, str]
    choices: list[C]
    compute: str | None = None


@dataclass
class ExampleCheck:
    block: str
    checks: list[dict[str, Any]]


@dataclass
class Lesson:
    slug: str
    position: int
    titles: dict[str, str]
    objectives: dict[str, list[str]]
    refs: list[dict[str, str]]
    blocks: dict[str, list[dict[str, Any]]]
    questions: list[Q]
    examples: list[ExampleCheck] = field(default_factory=list)


def choice_text(c: C, loc: str) -> str:
    label = getattr(c, loc)
    if label is not None:
        return nb(label)
    if isinstance(c.value, int) and not isinstance(c.value, bool):
        return fmt(c.value)
    raise ValueError(f"choice needs an explicit {loc} label: {c}")


def question_files(lesson: Lesson, loc: str) -> list[dict[str, Any]]:
    out = []
    for i, q in enumerate(lesson.questions, start=1):
        ids = [chr(ord("a") + k) for k in range(len(q.choices))]
        out.append(
            {
                "question_key": q.key,
                "position": i,
                "prompt": {"text": nb(q.prompt[loc])},
                "response_spec": {"choices": [{"id": cid, "text": choice_text(c, loc)} for cid, c in zip(ids, q.choices, strict=True)]},
                "answer_key": {"correct_choice_id": q.correct},
                "explanation": {"text": nb(q.explanation[loc])},
            }
        )
    return out


def verification_file(lesson: Lesson) -> dict[str, Any]:
    qs: dict[str, Any] = {}
    for q in lesson.questions:
        ids = [chr(ord("a") + k) for k in range(len(q.choices))]
        if q.mode == "value":
            qs[q.key] = {"mode": "value", "compute": q.compute, "choices": {cid: c.value for cid, c in zip(ids, q.choices, strict=True)}}
        else:
            qs[q.key] = {"mode": "truth", "choices": {cid: c.expr for cid, c in zip(ids, q.choices, strict=True)}}
    return {"questions": qs, "examples": [{"block": e.block, "checks": e.checks} for e in lesson.examples]}
