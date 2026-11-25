"""Opaque paging cursor for the learner's own notification list.

The list is newest first; a cursor means "continue below this row". It is
URL-safe base64 of a tiny JSON document::

    {"v": 1, "a": "<account tag>", "t": <available_at, microseconds>, "s": <seq>}

Like the sync cursor it is NOT a credential and is not signed: authorization
comes from the access token and row-level security, so a hand-edited cursor can
only change which of the caller's OWN rows are returned. The account tag makes
a cursor from another account (a shared phone) fail cleanly.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

CURSOR_FORMAT_VERSION = 1
MAX_CURSOR_LENGTH = 200
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)
#: 0001-01-01 .. 9999-12-31 in microseconds since the epoch.
_MIN_MICROS = -62_135_596_800_000_000
_MAX_MICROS = 253_402_300_799_999_999
_MAX_SEQ = 2**63 - 1


class InvalidCursor(Exception):
    pass


def _account_tag(user_id: uuid.UUID) -> str:
    return hashlib.sha256(b"notify:" + user_id.bytes).hexdigest()[:16]


def encode_cursor(user_id: uuid.UUID, available_at: datetime, seq: int) -> str:
    micros = (available_at.astimezone(UTC) - _EPOCH) // _MICROSECOND
    document = {"v": CURSOR_FORMAT_VERSION, "a": _account_tag(user_id), "t": micros, "s": seq}
    raw = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _integer(value: object, low: int, high: int, reason: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InvalidCursor(reason)
    return value


def decode_cursor(user_id: uuid.UUID, cursor: str) -> tuple[datetime, int]:
    """Return ``(available_at, seq)`` from ``cursor`` or raise ``InvalidCursor``."""
    if not cursor or len(cursor) > MAX_CURSOR_LENGTH:
        raise InvalidCursor("length")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        document = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise InvalidCursor("encoding") from None
    if not isinstance(document, dict) or set(document) != {"v", "a", "t", "s"}:
        raise InvalidCursor("shape")
    if document["v"] != CURSOR_FORMAT_VERSION:
        raise InvalidCursor("format_version")
    if document["a"] != _account_tag(user_id):
        raise InvalidCursor("other_account")
    micros = _integer(document["t"], _MIN_MICROS, _MAX_MICROS, "time")
    seq = _integer(document["s"], 1, _MAX_SEQ, "seq")
    return _EPOCH + micros * _MICROSECOND, seq
