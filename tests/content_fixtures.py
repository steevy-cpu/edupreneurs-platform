"""Helpers shared by the content-format-v2 tests: contract files, vectors, schema validators."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

CONTRACTS = Path(__file__).resolve().parents[1] / "packages" / "contracts" / "content"
VECTORS = CONTRACTS / "vectors"

BLOCK_SCHEMAS = {1: "lesson-blocks.schema.json", 2: "lesson-blocks.v2.schema.json"}
QUESTION_SCHEMAS = {
    "mcq": "question-mcq.schema.json",
    "true_false": "question-true-false.schema.json",
    "numeric": "question-numeric.schema.json",
    "short_text": "question-short-text.schema.json",
}


@cache
def load_schema(name: str) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema


@cache
def schema_validator(name: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(load_schema(name))


def schema_accepts(name: str, document: Any) -> bool:
    return schema_validator(name).is_valid(document)


@cache
def load_vectors(name: str) -> dict[str, Any]:
    suite: dict[str, Any] = json.loads((VECTORS / name).read_text(encoding="utf-8"))
    assert suite["vector_format"] == 1, name
    ids = [case["id"] for case in suite["cases"]]
    assert len(ids) == len(set(ids)), f"duplicate case ids in {name}"
    return suite


def cases(name: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = load_vectors(name)["cases"]
    return found


def math_document(source: str) -> list[dict[str, Any]]:
    """The wrapping prescribed by vectors/math-notation.json."""
    return [{"key": "m", "type": "math", "notation": "edu-math-1", "source": source, "alt": "x"}]
