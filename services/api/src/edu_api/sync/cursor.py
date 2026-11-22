"""Opaque pull cursor.

A cursor means "this account has applied every change up to version N".
It is encoded as URL-safe base64 of a tiny JSON document::

    {"v": 1, "a": "<account tag>", "n": N}

* ``a`` is the first 16 hex chars of SHA-256(user id). It lets the server
  notice a cursor that belongs to ANOTHER account (for example after an account
  switch on a shared phone) and force a clean restart instead of silently
  skipping changes.
* The cursor is NOT a credential and is not signed. Authorization comes from
  the access token and row-level security; a hand-edited cursor can only change
  which of the caller's OWN changes are returned.

Clients must treat the string as opaque and store whatever the server returns.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid

CURSOR_FORMAT_VERSION = 1
MAX_CURSOR_LENGTH = 200
_MAX_VERSION = 2**63 - 1


class InvalidCursor(Exception):
    pass


def _account_tag(user_id: uuid.UUID) -> str:
    return hashlib.sha256(user_id.bytes).hexdigest()[:16]


def encode_cursor(user_id: uuid.UUID, version: int) -> str:
    document = {"v": CURSOR_FORMAT_VERSION, "a": _account_tag(user_id), "n": version}
    raw = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(user_id: uuid.UUID, cursor: str) -> int:
    """Return the version in ``cursor`` or raise ``InvalidCursor``."""
    if not cursor or len(cursor) > MAX_CURSOR_LENGTH:
        raise InvalidCursor("length")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        document = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise InvalidCursor("encoding") from None
    if not isinstance(document, dict) or set(document) != {"v", "a", "n"}:
        raise InvalidCursor("shape")
    if document["v"] != CURSOR_FORMAT_VERSION:
        raise InvalidCursor("format_version")
    if document["a"] != _account_tag(user_id):
        raise InvalidCursor("other_account")
    version = document["n"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise InvalidCursor("version_type")
    if version < 0 or version > _MAX_VERSION:
        raise InvalidCursor("version_range")
    return version
