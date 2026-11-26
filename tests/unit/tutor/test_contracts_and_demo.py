"""Published contracts are generated from the code, and the demo runs offline."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from edu_api.tutor import contracts, demo, demo_content
from edu_api.tutor.errors import ALL_ERRORS

ROOT = Path(__file__).resolve().parents[3]
CONTENT_CONTRACTS = ROOT / "packages" / "contracts" / "content"


def test_contract_files_are_up_to_date() -> None:
    assert contracts.default_directory() == ROOT / "packages" / "contracts" / "tutor"
    assert contracts.main(["--check"]) == 0, (
        "packages/contracts/tutor is stale: run `uv run python -m edu_api.tutor.contracts`"
    )


def test_contract_schemas_are_valid_json_schema() -> None:
    for name, document in contracts.build_contracts().items():
        if name.endswith(".schema.json"):
            jsonschema.Draft202012Validator.check_schema(document)


def test_error_code_catalogue_lists_every_error_once() -> None:
    catalogue = contracts.build_contracts()["error-codes.json"]
    codes = [entry["code"] for entry in catalogue["errors"]]
    assert codes == [error.code for error in ALL_ERRORS]
    assert len(set(codes)) == len(codes)
    assert catalogue["prompt_versions"] == ["jude-tutor.v1"]


def test_synthetic_lessons_follow_the_real_content_contracts() -> None:
    blocks_schema = json.loads((CONTENT_CONTRACTS / "lesson-blocks.schema.json").read_text())
    question_schema = json.loads((CONTENT_CONTRACTS / "question-mcq.schema.json").read_text())
    for locale in ("fr", "ht"):
        jsonschema.validate(demo_content.raw_blocks(locale), blocks_schema)  # type: ignore[arg-type]
        for question in demo_content.raw_questions(locale):  # type: ignore[arg-type]
            columns = {k: v for k, v in question.items() if k not in ("question_key", "kind")}
            jsonschema.validate(columns, question_schema)
    fr, ht = demo_content.equations_fr(), demo_content.equations_ht()
    assert [b.key for b in fr.blocks] == [b.key for b in ht.blocks]
    assert fr.lesson_id == ht.lesson_id and fr.revision_id != ht.revision_id


async def test_the_demo_runs_end_to_end_without_a_network() -> None:
    output = "\n".join(await demo.run())
    assert "language=ht" in output and "grounding=lesson" in output
    assert "cites    : block 'balance'" in output
    assert "status   : insufficient_context | source=reviewed_template" in output
    assert "status   : safety_support | source=reviewed_template" in output
    assert "status   : declined | source=reviewed_template" in output
    assert "error    : tutor_daily_limit_reached (HTTP 429)" in output
    assert "correct? : False" in output
    ledger = output.split("=== Usage ledger")[1]
    assert ledger.count("outcome=answered") == 4
    assert "Pourquoi" not in ledger and "soustrait" not in ledger
