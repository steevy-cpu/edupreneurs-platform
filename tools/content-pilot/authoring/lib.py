"""Authoring helpers: write the pilot's JSON from compact Python definitions.

This module is NOT part of the validator. The validator only reads the committed JSON, so a mistake here is
caught exactly like a mistake in a hand-edited file. French and Haitian Creole texts are written separately
(the Creole is never produced by a function applied to the French).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from content_pilot.textrules import math_symbols, number_sequence

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
    # Displayed position (1-4) of the correct choice. Choice ids stay stable opaque ids (a, b, c, d in AUTHORING order);
    # only the order shown to the learner changes, so answers are spread over the four positions instead of clustering.
    place: int | None = None
    # The arithmetic operation the prompt displays (required whenever the prompt contains + − × ÷), e.g. "702 − 345".
    math: str | None = None


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


def _ids(q: Q) -> list[str]:
    return [chr(ord("a") + k) for k in range(len(q.choices))]


def displayed(q: Q) -> list[tuple[str, C]]:
    """(id, choice) in the order shown to the learner: the correct one moved to `place`, the others keep their order."""
    pairs = list(zip(_ids(q), q.choices, strict=True))
    if q.place is None:
        return pairs
    right = next(p for p in pairs if p[0] == q.correct)
    rest = [p for p in pairs if p[0] != q.correct]
    rest.insert(q.place - 1, right)
    return rest


def question_files(lesson: Lesson, loc: str) -> list[dict[str, Any]]:
    out = []
    for i, q in enumerate(lesson.questions, start=1):
        out.append(
            {
                "question_key": q.key,
                "position": i,
                "prompt": {"text": nb(q.prompt[loc])},
                "response_spec": {"choices": [{"id": cid, "text": choice_text(c, loc)} for cid, c in displayed(q)]},
                "answer_key": {"correct_choice_id": q.correct},
                "explanation": {"text": nb(q.explanation[loc])},
            }
        )
    return out


def _literals(expr: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", expr)]


def verification_file(lesson: Lesson) -> dict[str, Any]:
    """The proof record. It pins what the learner reads (prompt numbers in order, the displayed operation, each
    choice's numbers and signs) to what was verified, so the validator can detect a changed translation."""
    qs: dict[str, Any] = {}
    for q in lesson.questions:
        ids = _ids(q)
        prompt = nb(q.prompt["fr"])
        numbers = number_sequence(prompt)
        entry: dict[str, Any] = {"mode": q.mode}
        if q.mode == "value":
            entry["compute"] = q.compute
        entry["prompt_numbers"] = numbers
        if any(ch in prompt for ch in "+−×÷") and q.math is None:
            raise ValueError(f"{q.key}: the prompt shows an arithmetic sign, so `math=` is required")
        if q.math is not None:
            entry["prompt_math"] = q.math
        exprs = [q.compute] if q.mode == "value" else [c.expr for c in q.choices]
        if numbers and all(all(n in _literals(str(e)) for n in numbers) for e in exprs):
            entry["operands_in_proof"] = True
        if q.mode == "value":
            entry["choices"] = {cid: c.value for cid, c in zip(ids, q.choices, strict=True)}
        else:
            entry["choices"] = {
                cid: {"expr": c.expr, "numbers": number_sequence(choice_text(c, "fr")), "symbols": math_symbols(choice_text(c, "fr"))}
                for cid, c in zip(ids, q.choices, strict=True)
            }
        qs[q.key] = entry
    return {"questions": qs, "examples": [{"block": e.block, "checks": e.checks} for e in lesson.examples]}
