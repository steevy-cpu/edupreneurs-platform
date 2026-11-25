"""Opaque cursor for the Gold ledger (newest first).

Same idea as the sync pull cursor: URL-safe base64 of a tiny JSON document
``{"v": 1, "a": "<account tag>", "s": <sequence>}`` meaning "I have seen every
entry down to sequence ``s``; give me older ones". It is not a credential:
authorization is the access token plus row-level security, and a hand-edited
cursor can only change which of the caller's OWN entries are returned.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid

CURSOR_FORMAT_VERSION = 1
MAX_CURSOR_LENGTH = 200
_MAX_SEQ = 2**63 - 1


class InvalidLedgerCursor(Exception):
    pass


def _account_tag(user_id: uuid.UUID) -> str:
    return hashlib.sha256(b"rewards-ledger:" + user_id.bytes).hexdigest()[:16]


def encode_ledger_cursor(user_id: uuid.UUID, seq: int) -> str:
    document = {"v": CURSOR_FORMAT_VERSION, "a": _account_tag(user_id), "s": seq}
    raw = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_ledger_cursor(user_id: uuid.UUID, cursor: str) -> int:
    """Return the sequence in ``cursor`` or raise ``InvalidLedgerCursor``."""
    if not cursor or len(cursor) > MAX_CURSOR_LENGTH:
        raise InvalidLedgerCursor("length")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        document = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise InvalidLedgerCursor("encoding") from None
    if not isinstance(document, dict) or set(document) != {"v", "a", "s"}:
        raise InvalidLedgerCursor("shape")
    if document["v"] != CURSOR_FORMAT_VERSION:
        raise InvalidLedgerCursor("format_version")
    if document["a"] != _account_tag(user_id):
        raise InvalidLedgerCursor("other_account")
    seq = document["s"]
    if isinstance(seq, bool) or not isinstance(seq, int):
        raise InvalidLedgerCursor("sequence_type")
    if seq < 1 or seq > _MAX_SEQ:
        raise InvalidLedgerCursor("sequence_range")
    return seq
