"""The opaque ledger cursor (pure logic; no database)."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime

import pytest

from edu_api.rewards.cursor import (
    MAX_CURSOR_LENGTH,
    InvalidLedgerCursor,
    decode_ledger_cursor,
    encode_ledger_cursor,
)
from edu_api.sync.cursor import encode_cursor
from tests.helpers import STUDENT_A, STUDENT_B

ENTRY = uuid.UUID("0b0f5c0e-2f0e-4c57-9a0e-3d5f3f6f2a11")
WHEN = datetime(2026, 11, 24, 23, 59, 59, 999999, tzinfo=UTC)


def _raw(document: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(document).encode()).decode().rstrip("=")


def _document(cursor: str) -> dict[str, object]:
    document: dict[str, object] = json.loads(
        base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
    )
    return document


@pytest.mark.parametrize(
    "when",
    [
        WHEN,
        datetime(1970, 1, 1, tzinfo=UTC),
        datetime(2026, 3, 8, 5, 0, 0, 1, tzinfo=UTC),
        datetime(2099, 12, 31, 23, 59, 59, 123456, tzinfo=UTC),
    ],
)
def test_round_trip_is_exact_to_the_microsecond(when: datetime) -> None:
    cursor = encode_ledger_cursor(STUDENT_A, when, ENTRY)
    assert len(cursor) <= MAX_CURSOR_LENGTH
    assert decode_ledger_cursor(STUDENT_A, cursor) == (when, ENTRY)


def test_the_cursor_holds_only_the_callers_own_entry_position() -> None:
    """Security review L3: nothing global (no table-wide sequence) is exposed."""
    document = _document(encode_ledger_cursor(STUDENT_A, WHEN, ENTRY))
    assert set(document) == {"v", "a", "t", "i"}
    assert document["i"] == str(ENTRY) and document["v"] == 2
    assert str(STUDENT_A) not in json.dumps(document)


def test_cursor_is_bound_to_the_account() -> None:
    with pytest.raises(InvalidLedgerCursor, match="other_account"):
        decode_ledger_cursor(STUDENT_B, encode_ledger_cursor(STUDENT_A, WHEN, ENTRY))


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
        _raw({"v": 2, "t": 5, "i": str(ENTRY)}),
        _raw({"v": 2, "a": "0" * 16, "t": 5, "i": str(ENTRY), "extra": 1}),
        _raw({"v": 1, "a": "0" * 16, "s": 5}),
    ],
)
def test_malformed_cursors(cursor: str) -> None:
    with pytest.raises(InvalidLedgerCursor):
        decode_ledger_cursor(STUDENT_A, cursor)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("t", -1),
        ("t", 10**30),
        ("t", True),
        ("t", "5"),
        ("t", 1.5),
        ("t", None),
        ("i", 5),
        ("i", None),
        ("i", "not-a-uuid"),
        ("i", "0B0F5C0E-2F0E-4C57-9A0E-3D5F3F6F2A11"),
        ("i", "0b0f5c0e2f0e4c579a0e3d5f3f6f2a11"),
        ("v", 1),
        ("v", 3),
    ],
)
def test_bad_field_values(field: str, value: object) -> None:
    document = _document(encode_ledger_cursor(STUDENT_A, WHEN, ENTRY))
    document[field] = value
    with pytest.raises(InvalidLedgerCursor):
        decode_ledger_cursor(STUDENT_A, _raw(document))
