"""Write (or check) the JSON Schemas in ``packages/contracts/tutor``.

    uv run python -m edu_api.tutor.contracts           # rewrite the files
    uv run python -m edu_api.tutor.contracts --check   # fail if they are stale

The schemas are generated from the Pydantic models, so the contract a client
reads can never drift from what the server validates.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from edu_api.tutor.errors import ALL_ERRORS
from edu_api.tutor.prompts import known_versions
from edu_api.tutor.types import TutorAvailability, TutorRequest, TutorResponse
from edu_api.tutor.validation import ModelAnswer

_BASE_ID = "https://contracts.mon-edupreneur.local/tutor/"


def _schema(model: type[Any], name: str, title: str) -> dict[str, Any]:
    schema: dict[str, Any] = model.model_json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _BASE_ID + name,
        **schema,
        "title": title,
    }


def build_contracts() -> dict[str, dict[str, Any]]:
    return {
        "tutor-request.schema.json": _schema(
            TutorRequest, "tutor-request.schema.json", "Jude request (tutor contract v1)"
        ),
        "tutor-response.schema.json": _schema(
            TutorResponse, "tutor-response.schema.json", "Jude response (tutor contract v1)"
        ),
        "tutor-availability.schema.json": _schema(
            TutorAvailability, "tutor-availability.schema.json", "Jude availability probe"
        ),
        "model-answer.schema.json": _schema(
            ModelAnswer,
            "model-answer.schema.json",
            "Structured output a model must return (internal, not sent to clients)",
        ),
        "error-codes.json": {
            "description": "Stable error codes of the tutor, in the API's standard error shape.",
            "prompt_versions": list(known_versions()),
            "errors": [
                {
                    "code": error.code,
                    "http_status": error.http_status,
                    "message": error.message,
                    "retry_after_s": error.retry_after_s,
                }
                for error in ALL_ERRORS
            ],
        },
    }


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def default_directory() -> Path:
    return Path(__file__).resolve().parents[5] / "packages" / "contracts" / "tutor"


def main(argv: list[str]) -> int:
    directory = default_directory()
    check = "--check" in argv
    stale: list[str] = []
    for name, document in build_contracts().items():
        path = directory / name
        text = render(document)
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if stale:
        sys.stderr.write(f"stale tutor contracts: {', '.join(stale)}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
