"""The staff request models accept and refuse exactly what the published
content schemas (packages/contracts/content/*.schema.json) accept and refuse."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from edu_api.staff.content import McqQuestion, RevisionContent

CONTRACTS = Path(__file__).resolve().parents[2] / "packages" / "contracts" / "content"
BLOCKS_SCHEMA = Draft202012Validator(
    json.loads((CONTRACTS / "lesson-blocks.schema.json").read_text())
)
MCQ_SCHEMA = Draft202012Validator(json.loads((CONTRACTS / "question-mcq.schema.json").read_text()))

GOOD_BLOCKS: list[dict[str, Any]] = [
    {"key": "t", "type": "heading", "text": "Titre"},
    {"key": "p", "type": "paragraph", "text": "Texte."},
    {"key": "e", "type": "example", "title": "Exemple", "steps": ["a", "b"]},
    {"key": "e2", "type": "example", "steps": ["a"]},
    {"key": "c", "type": "callout", "tone": "remember", "text": "Note."},
]
GOOD_QUESTION: dict[str, Any] = {
    "prompt": {"text": "?"},
    "response_spec": {"choices": [{"id": "a", "text": "1"}, {"id": "b", "text": "2"}]},
    "answer_key": {"correct_choice_id": "b"},
    "explanation": {"text": "."},
}


def model_accepts_blocks(blocks: Any) -> bool:
    try:
        RevisionContent.model_validate({"title": "t", "blocks": blocks})
    except ValidationError:
        return False
    return True


def model_accepts_question(question: Any) -> bool:
    if not isinstance(question, dict):
        return False
    try:
        McqQuestion.model_validate({"question_key": "q1", "kind": "mcq", **question})
    except ValidationError:
        return False
    return True


def blocks_with(index: int, **changes: Any) -> list[dict[str, Any]]:
    blocks = copy.deepcopy(GOOD_BLOCKS)
    blocks[index].update(changes)
    return blocks


def blocks_without(index: int, field: str) -> list[dict[str, Any]]:
    blocks = copy.deepcopy(GOOD_BLOCKS)
    del blocks[index][field]
    return blocks


BLOCK_VECTORS: list[Any] = [
    GOOD_BLOCKS,
    [GOOD_BLOCKS[0]],
    [],
    {"not": "an array"},
    [{**GOOD_BLOCKS[1], "key": f"p{n}"} for n in range(200)],
    [{**GOOD_BLOCKS[1], "key": f"p{n}"} for n in range(201)],
    blocks_with(0, text=""),
    blocks_with(0, text="x" * 200),
    blocks_with(0, text="x" * 201),
    blocks_with(1, text="x" * 4000),
    blocks_with(1, text="x" * 4001),
    blocks_with(1, text=5),
    blocks_with(1, type="html"),
    blocks_with(1, key="Bad Key"),
    blocks_with(1, key=""),
    blocks_with(1, key="-starts-with-dash"),
    blocks_with(1, key="a" * 64),
    blocks_with(1, key="a" * 65),
    blocks_with(1, extra="field"),
    blocks_with(1, html="<b>x</b>"),
    blocks_with(2, steps=[]),
    blocks_with(2, steps=["x"] * 20),
    blocks_with(2, steps=["x"] * 21),
    blocks_with(2, steps=["x" * 500]),
    blocks_with(2, steps=["x" * 501]),
    blocks_with(2, steps=[""]),
    blocks_with(2, steps="abc"),
    blocks_with(2, title=""),
    blocks_with(2, title=None),
    blocks_with(2, title="x" * 201),
    blocks_with(4, tone="shout"),
    blocks_with(4, tone=None),
    blocks_without(0, "text"),
    blocks_without(1, "key"),
    blocks_without(2, "steps"),
    blocks_without(4, "tone"),
    blocks_without(4, "type"),
    [*GOOD_BLOCKS, "a string"],
    [*GOOD_BLOCKS, None],
]


def question_with(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    question = copy.deepcopy(GOOD_QUESTION)
    target: Any = question
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    return question


QUESTION_VECTORS: list[Any] = [
    GOOD_QUESTION,
    question_with(("prompt", "text"), ""),
    question_with(("prompt", "text"), "x" * 1000),
    question_with(("prompt", "text"), "x" * 1001),
    question_with(("prompt", "html"), "<b>"),
    question_with(("prompt",), "text"),
    question_with(("explanation", "text"), "x" * 2000),
    question_with(("explanation", "text"), "x" * 2001),
    question_with(("explanation", "extra"), 1),
    question_with(("response_spec", "choices"), []),
    question_with(("response_spec", "choices"), [{"id": "b", "text": "1"}]),
    question_with(("response_spec", "choices"), [{"id": c, "text": "1"} for c in "abcdef"]),
    question_with(("response_spec", "choices"), [{"id": c, "text": "1"} for c in "abcdefg"]),
    question_with(
        ("response_spec", "choices"), [{"id": "a b", "text": "1"}, {"id": "b", "text": "2"}]
    ),
    question_with(
        ("response_spec", "choices"), [{"id": "a", "text": ""}, {"id": "b", "text": "2"}]
    ),
    question_with(
        ("response_spec", "choices"), [{"id": "a", "text": "x" * 301}, {"id": "b", "text": "2"}]
    ),
    question_with(
        ("response_spec", "choices"),
        [{"id": "a", "text": "1", "correct": True}, {"id": "b", "text": "2"}],
    ),
    question_with(("response_spec", "shuffle"), True),
    question_with(("answer_key", "correct_choice_id"), ""),
    question_with(("answer_key", "correct_choice_id"), "b" * 65),
    question_with(("answer_key", "score"), 1),
    question_with(("answer_key",), {}),
    question_with(("unknown",), 1),
    {k: v for k, v in GOOD_QUESTION.items() if k != "explanation"},
    {k: v for k, v in GOOD_QUESTION.items() if k != "answer_key"},
]


@pytest.mark.parametrize("blocks", BLOCK_VECTORS)
def test_blocks_model_agrees_with_the_published_schema(blocks: Any) -> None:
    assert model_accepts_blocks(blocks) == BLOCKS_SCHEMA.is_valid(blocks)


@pytest.mark.parametrize("question", QUESTION_VECTORS)
def test_question_model_agrees_with_the_published_schema(question: Any) -> None:
    assert model_accepts_question(question) == MCQ_SCHEMA.is_valid(question)


def test_the_vectors_cover_both_outcomes() -> None:
    block_results = {BLOCKS_SCHEMA.is_valid(v) for v in BLOCK_VECTORS}
    question_results = {MCQ_SCHEMA.is_valid(v) for v in QUESTION_VECTORS}
    assert block_results == {True, False} and question_results == {True, False}
    assert sum(BLOCKS_SCHEMA.is_valid(v) for v in BLOCK_VECTORS) >= 8


def test_rules_beyond_the_schema() -> None:
    """Stricter than the schema on purpose: these make a lesson unusable."""
    duplicate_block_keys = [GOOD_BLOCKS[0], {**GOOD_BLOCKS[1], "key": "t"}]
    assert BLOCKS_SCHEMA.is_valid(duplicate_block_keys) and not model_accepts_blocks(
        duplicate_block_keys
    )

    wrong_answer = question_with(("answer_key", "correct_choice_id"), "z")
    assert MCQ_SCHEMA.is_valid(wrong_answer) and not model_accepts_question(wrong_answer)
    twin_choices = question_with(
        ("response_spec", "choices"), [{"id": "b", "text": "1"}, {"id": "b", "text": "2"}]
    )
    assert MCQ_SCHEMA.is_valid(twin_choices) and not model_accepts_question(twin_choices)

    question = {"question_key": "q1", "kind": "mcq", **GOOD_QUESTION}
    with pytest.raises(ValidationError, match="question keys must be unique"):
        RevisionContent.model_validate(
            {"title": "t", "blocks": GOOD_BLOCKS, "questions": [question, question]}
        )
    with pytest.raises(ValidationError):
        RevisionContent.model_validate(
            {"title": "t", "blocks": GOOD_BLOCKS, "questions": [question] * 51}
        )
    with pytest.raises(ValidationError):
        McqQuestion.model_validate({**question, "kind": "numeric"})
    with pytest.raises(ValidationError):
        McqQuestion.model_validate({**question, "question_key": "Bad Key"})


def test_stored_json_is_exactly_what_the_contract_describes() -> None:
    question = {"question_key": "q1", "kind": "mcq", **GOOD_QUESTION}
    content = RevisionContent.model_validate(
        {"title": "t", "blocks": GOOD_BLOCKS, "questions": [question]}
    )
    assert content.blocks_json() == GOOD_BLOCKS, "an absent optional title is not stored as null"
    assert BLOCKS_SCHEMA.is_valid(content.blocks_json())
    stored = content.questions_json()[0]
    assert MCQ_SCHEMA.is_valid({k: stored[k] for k in GOOD_QUESTION})


# --- control characters (review finding L-B2-1): stricter than the schema on purpose ---
@pytest.mark.parametrize(
    "bad", ["\u0000", "\u0001", "\u0008", "\u000b", "\u000c", "\u001f", "\u007f", "\u009f"]
)
def test_control_characters_are_refused_in_every_text(bad: str) -> None:
    text = f"a{bad}b"
    assert not model_accepts_blocks(blocks_with(0, text=text))
    assert not model_accepts_blocks(blocks_with(1, text=text))
    assert not model_accepts_blocks(blocks_with(2, title=text))
    assert not model_accepts_blocks(blocks_with(2, steps=["ok", text]))
    assert not model_accepts_blocks(blocks_with(4, text=text))
    with pytest.raises(ValidationError):
        RevisionContent.model_validate({"title": text, "blocks": GOOD_BLOCKS})
    for path in (("prompt", "text"), ("explanation", "text")):
        question = copy.deepcopy(GOOD_QUESTION)
        question[path[0]][path[1]] = text
        assert not model_accepts_question(question)
    question = copy.deepcopy(GOOD_QUESTION)
    question["response_spec"]["choices"][0]["text"] = text
    assert not model_accepts_question(question)


@pytest.mark.parametrize("fine", ["a\tb", "a\nb", "é — €", "a\u200bb"])
def test_tab_line_feed_and_ordinary_unicode_are_accepted(fine: str) -> None:
    assert model_accepts_blocks(blocks_with(1, text=fine))
    question = copy.deepcopy(GOOD_QUESTION)
    question["prompt"]["text"] = fine
    assert model_accepts_question(question)


# --- line endings: CRLF and CR become LF in multi-line text; single-line fields refuse them ---
@pytest.mark.parametrize(
    ("raw", "stored"), [("a\r\nb", "a\nb"), ("a\rb", "a\nb"), ("a\r\n\rb", "a\n\nb")]
)
def test_crlf_and_lone_cr_become_lf_in_multi_line_text(raw: str, stored: str) -> None:
    content = RevisionContent.model_validate(
        {
            "title": "t",
            "blocks": [{"key": "p", "type": "paragraph", "text": raw}],
            "questions": [
                {
                    "question_key": "q1",
                    "prompt": {"text": raw},
                    "response_spec": {
                        "choices": [{"id": "a", "text": raw}, {"id": "b", "text": "2"}]
                    },
                    "answer_key": {"correct_choice_id": "b"},
                    "explanation": {"text": raw},
                }
            ],
        }
    )
    assert content.blocks_json()[0]["text"] == stored
    question = content.questions_json()[0]
    assert question["prompt"]["text"] == stored
    assert question["explanation"]["text"] == stored
    assert question["response_spec"]["choices"][0]["text"] == stored


def test_a_control_character_next_to_a_carriage_return_is_still_refused() -> None:
    assert not model_accepts_blocks(blocks_with(1, text="a\r\n\u0000b"))


@pytest.mark.parametrize("bad", ["a\rb", "a\nb", "a\r\nb", "a\tb", "a\u0000b"])
def test_titles_are_single_line(bad: str) -> None:
    assert not model_accepts_blocks(blocks_with(0, text=bad))
    assert not model_accepts_blocks(blocks_with(2, title=bad))
    with pytest.raises(ValidationError):
        RevisionContent.model_validate({"title": bad, "blocks": GOOD_BLOCKS})
