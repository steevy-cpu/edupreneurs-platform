"""Check the upstream contracts with synthetic data and length-only sample twins."""

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1] / "packages" / "contracts" / "content"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    run = json.load(sys.stdin)
    manifest = Draft202012Validator(
        load(HERE / "manifest.schema.json"), format_checker=FormatChecker()
    )
    blocks = Draft202012Validator(load(CONTRACTS / "lesson-blocks.schema.json"))
    question = Draft202012Validator(load(CONTRACTS / "question-mcq.schema.json"))
    manifest.validate(run["manifest"])
    for packet in run["packets"]:
        blocks.validate(packet["target"]["blocks"])
        for item in packet["target"]["questions"]:
            question.validate(item)
    evidence = load(HERE / "sample-shapes.json")
    for section in evidence["blocks"]:
        blocks.validate(
            [
                {"key": b["key"], "type": b["type"], "text": "x" * b["text_length"]}
                for b in section["blocks"]
            ]
        )
    for s in evidence["question_lengths"]:
        question.validate(
            {
                "prompt": {"text": "x" * s["prompt"]},
                "response_spec": {
                    "choices": [
                        {"id": f"s{i}", "text": "x" * n} for i, n in enumerate(s["choices"])
                    ]
                },
                "answer_key": {"correct_choice_id": "s0"},
                "explanation": {"text": "x" * s["explanation"]},
            }
        )
    print(
        "Validated field and question shape twins:",
        len(evidence["blocks"]),
        len(evidence["question_lengths"]),
    )


if __name__ == "__main__":
    main()
