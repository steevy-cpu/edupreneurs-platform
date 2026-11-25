"""Validator for the four JSON columns of a practice question, per kind.

``validate_question(kind, document)`` takes
``{"prompt": ..., "response_spec": ..., "answer_key": ..., "explanation": ...}``
and returns a list of issues (empty = valid). ``mcq`` is format 1 and mirrors
``question-mcq.schema.json`` exactly; the three format-2 kinds mirror
``question-true-false``, ``question-numeric`` and ``question-short-text``.

SEMANTIC RULE (format-2 kinds)

    short_text.accepted_fits   every accepted answer is non-empty after
                               short-text-v1 normalisation and no longer than
                               response_spec.max_length code points
"""

from __future__ import annotations

import re
from typing import Any

from edu_api.content.formats import V2_QUESTION_KINDS
from edu_api.content.issues import Collector, Issue
from edu_api.content.scoring import NUMERIC_V1, SHORT_TEXT_V1, TRUE_FALSE_V1, normalise_short_text

_COLUMNS = ("prompt", "response_spec", "answer_key", "explanation")
_CHOICE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_DECIMAL = re.compile(r"-?(0|[1-9][0-9]{0,11})(\.[0-9]{1,6})?")
_NON_NEGATIVE_DECIMAL = re.compile(r"(0|[1-9][0-9]{0,11})(\.[0-9]{1,6})?")


def _text_object(c: Collector, value: Any, path: str, max_len: int) -> None:
    if c.obj(value, path, ("text",)):
        c.string(value["text"], f"{path}/text", max_len=max_len)


def _mcq(c: Collector, spec: Any, key: Any) -> None:
    if c.obj(spec, "/response_spec", ("choices",)) and c.array(
        spec["choices"], "/response_spec/choices", 2, 6
    ):
        for i, choice in enumerate(spec["choices"]):
            path = f"/response_spec/choices/{i}"
            if c.obj(choice, path, ("id", "text")):
                c.string(choice["id"], f"{path}/id", max_len=64, pattern=_CHOICE_ID)
                c.string(choice["text"], f"{path}/text", max_len=300)
    if c.obj(key, "/answer_key", ("correct_choice_id",)):
        c.string(
            key["correct_choice_id"],
            "/answer_key/correct_choice_id",
            max_len=64,
            pattern=_CHOICE_ID,
        )


def _true_false(c: Collector, spec: Any, key: Any) -> None:
    c.obj(spec, "/response_spec", ())
    if c.obj(key, "/answer_key", ("scoring_version", "correct")):
        c.const(key["scoring_version"], "/answer_key/scoring_version", TRUE_FALSE_V1)
        c.boolean(key["correct"], "/answer_key/correct")


def _numeric(c: Collector, spec: Any, key: Any) -> None:
    if c.obj(spec, "/response_spec", ("allow_fraction",), ("unit",)):
        c.boolean(spec["allow_fraction"], "/response_spec/allow_fraction")
        if "unit" in spec:
            c.string(spec["unit"], "/response_spec/unit", max_len=16, plain=True)
    if c.obj(key, "/answer_key", ("scoring_version", "value", "tolerance")):
        c.const(key["scoring_version"], "/answer_key/scoring_version", NUMERIC_V1)
        c.string(key["value"], "/answer_key/value", max_len=20, pattern=_DECIMAL)
        c.string(
            key["tolerance"], "/answer_key/tolerance", max_len=19, pattern=_NON_NEGATIVE_DECIMAL
        )


def _short_text(c: Collector, spec: Any, key: Any) -> None:
    if c.obj(spec, "/response_spec", ("max_length", "case_sensitive", "accent_sensitive")):
        c.integer(spec["max_length"], "/response_spec/max_length", 1, 80)
        c.boolean(spec["case_sensitive"], "/response_spec/case_sensitive")
        c.boolean(spec["accent_sensitive"], "/response_spec/accent_sensitive")
    if c.obj(key, "/answer_key", ("scoring_version", "accepted")):
        c.const(key["scoring_version"], "/answer_key/scoring_version", SHORT_TEXT_V1)
        accepted = key["accepted"]
        if c.array(accepted, "/answer_key/accepted", 1, 10):
            usable = True
            for i, answer in enumerate(accepted):
                usable &= c.string(answer, f"/answer_key/accepted/{i}", max_len=80, plain=True)
            if usable and len(set(accepted)) != len(accepted):
                c.schema("/answer_key/accepted", "items must be unique")


def _short_text_semantics(c: Collector, spec: dict[str, Any], key: dict[str, Any]) -> None:
    for i, answer in enumerate(key["accepted"]):
        normalised = normalise_short_text(
            answer,
            case_sensitive=spec["case_sensitive"],
            accent_sensitive=spec["accent_sensitive"],
        )
        if normalised == "" or len(answer) > spec["max_length"]:
            c.semantic(
                f"/answer_key/accepted/{i}",
                "short_text.accepted_fits",
                "accepted answer can never be typed",
            )


_KIND_CHECKS = {
    "mcq": _mcq,
    "true_false": _true_false,
    "numeric": _numeric,
    "short_text": _short_text,
}


def validate_question(kind: str, document: Any) -> list[Issue]:
    """Validate the four JSON columns of one question of the given kind."""
    if kind not in V2_QUESTION_KINDS:
        raise ValueError("unknown question kind")
    c = Collector()
    if not c.obj(document, "", _COLUMNS):
        return c.issues
    _text_object(c, document["prompt"], "/prompt", 1000)
    _text_object(c, document["explanation"], "/explanation", 2000)
    _KIND_CHECKS[kind](c, document["response_spec"], document["answer_key"])
    if not c.issues and kind == "short_text":
        _short_text_semantics(c, document["response_spec"], document["answer_key"])
    return c.issues
