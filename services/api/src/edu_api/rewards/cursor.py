"""Opaque cursor for the Gold ledger (newest first).

URL-safe base64 of a tiny JSON document::

    {"v": 2, "a": "<account tag>", "t": <microseconds>, "i": "<entry id>"}

meaning "I have seen every entry down to the one created at ``t`` with id
``i``; give me older ones". Both values belong to one of the caller's OWN
entries. The cursor deliberately carries nothing global (no table-wide
sequence number), so it reveals nothing about other learners' activity.

It is not a credential: authorization is the access token plus row-level
security, and a hand-edited cursor can only change which of the caller's own
entries are returned.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

CURSOR_FORMAT_VERSION = 2
MAX_CURSOR_LENGTH = 200
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_MICROS = int((datetime(9999, 1, 1, tzinfo=UTC) - _EPOCH).total_seconds()) * 1_000_000


class InvalidLedgerCursor(Exception):
    pass


def _account_tag(user_id: uuid.UUID) -> str:
    return hashlib.sha256(b"rewards-ledger:" + user_id.bytes).hexdigest()[:16]


def _micros(instant: datetime) -> int:
    delta = instant - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def encode_ledger_cursor(user_id: uuid.UUID, created_at: datetime, entry_id: uuid.UUID) -> str:
    document = {
        "v": CURSOR_FORMAT_VERSION,
        "a": _account_tag(user_id),
        "t": _micros(created_at),
        "i": str(entry_id),
    }
    raw = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_ledger_cursor(user_id: uuid.UUID, cursor: str) -> tuple[datetime, uuid.UUID]:
    """Return ``(created_at, entry_id)`` or raise ``InvalidLedgerCursor``."""
    if not cursor or len(cursor) > MAX_CURSOR_LENGTH:
        raise InvalidLedgerCursor("length")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        document = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise InvalidLedgerCursor("encoding") from None
    if not isinstance(document, dict) or set(document) != {"v", "a", "t", "i"}:
        raise InvalidLedgerCursor("shape")
    if document["v"] != CURSOR_FORMAT_VERSION:
        raise InvalidLedgerCursor("format_version")
    if document["a"] != _account_tag(user_id):
        raise InvalidLedgerCursor("other_account")
    micros = document["t"]
    if isinstance(micros, bool) or not isinstance(micros, int):
        raise InvalidLedgerCursor("instant_type")
    if micros < 0 or micros > _MAX_MICROS:
        raise InvalidLedgerCursor("instant_range")
    raw_id = document["i"]
    if not isinstance(raw_id, str):
        raise InvalidLedgerCursor("id_type")
    try:
        entry_id = uuid.UUID(raw_id)
    except ValueError:
        raise InvalidLedgerCursor("id_value") from None
    if str(entry_id) != raw_id:
        raise InvalidLedgerCursor("id_form")
    return _EPOCH + timedelta(microseconds=micros), entry_id
