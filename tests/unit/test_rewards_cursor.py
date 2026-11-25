"""The opaque ledger cursor (pure logic; no database)."""

from __future__ import annotations

import base64
import json

import pytest

from edu_api.rewards.cursor import (
    MAX_CURSOR_LENGTH,
    InvalidLedgerCursor,
    decode_ledger_cursor,
    encode_ledger_cursor,
)
from edu_api.sync.cursor import encode_cursor
from tests.helpers import STUDENT_A, STUDENT_B


def _raw(document: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(document).encode()).decode().rstrip("=")


@pytest.mark.parametrize("seq", [1, 2, 41, 2**40, 2**63 - 1])
def test_round_trip(seq: int) -> None:
    cursor = encode_ledger_cursor(STUDENT_A, seq)
    assert len(cursor) <= MAX_CURSOR_LENGTH
    assert decode_ledger_cursor(STUDENT_A, cursor) == seq


def test_cursor_is_bound_to_the_account() -> None:
    with pytest.raises(InvalidLedgerCursor, match="other_account"):
        decode_ledger_cursor(STUDENT_B, encode_ledger_cursor(STUDENT_A, 7))


def test_a_sync_pull_cursor_is_not_a_ledger_cursor() -> None:
    with pytest.raises(InvalidLedgerCursor):
        decode_ledger_cursor(STUDENT_A, encode_cursor(STUDENT_A, 7))


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "x" * (MAX_CURSOR_LENGTH + 1),
        "not base64 !!",
        _raw([1, 2, 3]),
        _raw({"v": 1, "s": 5}),
        _raw({"v": 1, "a": "0" * 16, "s": 5, "extra": 1}),
    ],
)
def test_malformed_cursors(cursor: str) -> None:
    with pytest.raises(InvalidLedgerCursor):
        decode_ledger_cursor(STUDENT_A, cursor)


@pytest.mark.parametrize("seq", [0, -1, 2**63, True, "5", 1.5, None])
def test_bad_sequences(seq: object) -> None:
    good = encode_ledger_cursor(STUDENT_A, 5)
    document = json.loads(base64.urlsafe_b64decode(good + "=" * (-len(good) % 4)))
    document["s"] = seq
    with pytest.raises(InvalidLedgerCursor):
        decode_ledger_cursor(STUDENT_A, _raw(document))


def test_unknown_format_version() -> None:
    good = encode_ledger_cursor(STUDENT_A, 5)
    document = json.loads(base64.urlsafe_b64decode(good + "=" * (-len(good) % 4)))
    document["v"] = 2
    with pytest.raises(InvalidLedgerCursor, match="format_version"):
        decode_ledger_cursor(STUDENT_A, _raw(document))
