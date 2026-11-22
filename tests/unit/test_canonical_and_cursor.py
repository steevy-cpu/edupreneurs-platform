"""Payload canonicalisation (mep-canon-1) and the opaque pull cursor."""

from __future__ import annotations

import base64
import json
import uuid

import pytest

from edu_api.sync.canonical import CANON_VERSION, canonical_bytes, payload_digest
from edu_api.sync.cursor import InvalidCursor, decode_cursor, encode_cursor
from edu_api.sync.schemas import OperationResult, SyncOperation
from edu_api.sync.service import _prepare
from tests.helpers import STUDENT_A, STUDENT_B

QUESTION = "D0000000-0000-4000-8000-000000000101"


def digest_of(raw_op: dict[str, object]) -> bytes:
    prepared = _prepare(SyncOperation.model_validate(raw_op))
    assert not isinstance(prepared, OperationResult), prepared
    return prepared.digest


def base_op() -> dict[str, object]:
    return {
        "op_id": "5b0b6b0e-5d1e-4c5e-9d57-0d6a1c1b2a01",
        "kind": "practice_answer",
        "payload": {"question_revision_id": QUESTION.lower(), "response": {"choice_id": "b"}},
    }


def test_canonical_bytes_are_exactly_specified() -> None:
    payload = {"question_revision_id": QUESTION.lower(), "response": {"choice_id": "b"}}
    assert canonical_bytes("practice_answer", payload) == (
        b'{"kind":"practice_answer","payload":{"question_revision_id":'
        b'"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}}'
    )
    assert CANON_VERSION == "mep-canon-1"


def test_key_order_does_not_change_the_digest() -> None:
    reordered = {
        "payload": {"response": {"choice_id": "b"}, "question_revision_id": QUESTION.lower()},
        "kind": "practice_answer",
        "op_id": "5b0b6b0e-5d1e-4c5e-9d57-0d6a1c1b2a01",
    }
    assert digest_of(reordered) == digest_of(base_op())


def test_uuid_spelling_does_not_change_the_digest() -> None:
    upper = base_op()
    upper["payload"] = {"question_revision_id": QUESTION, "response": {"choice_id": "b"}}
    no_hyphens = base_op()
    no_hyphens["payload"] = {
        "question_revision_id": QUESTION.replace("-", ""),
        "response": {"choice_id": "b"},
    }
    assert digest_of(upper) == digest_of(base_op()) == digest_of(no_hyphens)


def test_client_clock_and_op_id_are_not_part_of_the_digest() -> None:
    with_clock = {**base_op(), "client_recorded_at": "2026-11-21T10:00:00+00:00"}
    other_clock = {**base_op(), "client_recorded_at": "2031-01-01T00:00:00-05:00"}
    other_id = {**base_op(), "op_id": str(uuid.uuid4())}
    assert (
        digest_of(with_clock)
        == digest_of(other_clock)
        == digest_of(base_op())
        == digest_of(other_id)
    )


def test_a_different_answer_changes_the_digest() -> None:
    other = base_op()
    other["payload"] = {"question_revision_id": QUESTION.lower(), "response": {"choice_id": "a"}}
    assert digest_of(other) != digest_of(base_op())


def test_kind_is_part_of_the_digest() -> None:
    payload = {"lesson_revision_id": "c0000000-0000-4000-8000-000000000001"}
    assert payload_digest("lesson_completed", payload) != payload_digest("other_kind", payload)


def test_unicode_is_normalised_and_floats_are_refused() -> None:
    composed, decomposed = "é", "é"
    assert canonical_bytes("k", {"t": composed}) == canonical_bytes("k", {"t": decomposed})
    with pytest.raises(TypeError):
        canonical_bytes("k", {"score": 1.0})


@pytest.mark.parametrize(
    ("kind", "payload", "code"),
    [
        ("award_points", {"points": 1000}, "unsupported_kind"),
        ("practice_answer", {"question_revision_id": QUESTION}, "invalid_payload"),
        (
            "practice_answer",
            {"question_revision_id": "nope", "response": {"choice_id": "a"}},
            "invalid_payload",
        ),
        (
            "practice_answer",
            {"question_revision_id": QUESTION, "response": {"text": "7"}},
            "invalid_payload",
        ),
        (
            "practice_answer",
            {"question_revision_id": QUESTION, "response": {"choice_id": "a"}, "score": 1},
            "invalid_payload",
        ),
        (
            "practice_answer",
            {
                "question_revision_id": QUESTION,
                "response": {"choice_id": "a"},
                "learner_id": str(STUDENT_B),
            },
            "invalid_payload",
        ),
        (
            "practice_answer",
            {"question_revision_id": QUESTION, "response": {"choice_id": "x" * 65}},
            "invalid_payload",
        ),
        (
            "lesson_completed",
            {"lesson_revision_id": QUESTION, "completed_at": "2020-01-01T00:00:00Z"},
            "invalid_payload",
        ),
    ],
)
def test_bad_operations_are_rejected_individually(
    kind: str, payload: dict[str, object], code: str
) -> None:
    result = _prepare(
        SyncOperation.model_validate({"op_id": str(uuid.uuid4()), "kind": kind, "payload": payload})
    )
    assert isinstance(result, OperationResult)
    assert (result.status, result.code, result.replayed) == ("rejected", code, False)


# --- cursor ------------------------------------------------------------------------
def test_cursor_round_trip() -> None:
    for version in (0, 1, 42, 2**40):
        assert decode_cursor(STUDENT_A, encode_cursor(STUDENT_A, version)) == version


def test_cursor_of_another_account_is_refused() -> None:
    with pytest.raises(InvalidCursor):
        decode_cursor(STUDENT_A, encode_cursor(STUDENT_B, 5))


def _forge(document: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(document).encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "!!!",
        "not-base64-json",
        "x" * 500,
        _forge([1, 2, 3]),
        _forge({"v": 1, "n": 5}),
        _forge({"v": 2, "a": "0" * 16, "n": 5}),
        _forge({"v": 1, "a": "0" * 16, "n": 5, "extra": 1}),
    ],
)
def test_garbage_cursors_are_refused(cursor: str) -> None:
    with pytest.raises(InvalidCursor):
        decode_cursor(STUDENT_A, cursor)


@pytest.mark.parametrize("version", [-1, 2**63, "5", 1.5, True, None])
def test_cursor_version_must_be_a_sane_integer(version: object) -> None:
    good = json.loads(base64.urlsafe_b64decode(encode_cursor(STUDENT_A, 1) + "=="))
    with pytest.raises(InvalidCursor):
        decode_cursor(STUDENT_A, _forge({**good, "n": version}))
