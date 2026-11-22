"""Canonical form and digest of a sync operation ("mep-canon-1").

WHY: the server remembers each ``op_id`` together with a SHA-256 digest of what
was submitted. On a retry, "same op_id + same digest" means *the same logical
operation* (return the stored result) and "same op_id + different digest" means
*op_id reuse* (conflict). For that to be reliable, two byte-wise different
JSON encodings of the same operation — different key order, whitespace, UUID
letter case — must produce the same digest.

RULE ``mep-canon-1``
1. Validate the operation against its typed schema first. Unknown fields are
   rejected, so nothing un-modelled can enter the digest.
2. Build the object ``{"kind": <kind>, "payload": <validated payload>}`` where
   UUIDs are lower-case hyphenated strings and text is Unicode NFC.
3. Serialise as JSON with keys sorted, no insignificant whitespace
   (separators ``,`` and ``:``), non-ASCII characters written literally, UTF-8.
4. SHA-256 of those bytes.

NOT part of the digest:
* ``op_id`` — it is the lookup key, not content;
* ``client_recorded_at`` — untrusted display metadata; a client that re-reads
  its clock on retry must not turn an honest retry into a conflict;
* the learner — taken from the verified token, never from the request.

Changing this rule requires a new version string: stored receipts record the
version that produced their digest (``sync_receipts.canon_version``).
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

CANON_VERSION = "mep-canon-1"


def _normalise(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {unicodedata.normalize("NFC", str(k)): _normalise(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_normalise(v) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    # Floats have several valid JSON spellings; no current payload uses them.
    raise TypeError(f"Unsupported value in canonical payload: {type(value).__name__}")


def canonical_bytes(kind: str, payload: dict[str, Any]) -> bytes:
    document = {"kind": kind, "payload": _normalise(payload)}
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def payload_digest(kind: str, payload: dict[str, Any]) -> bytes:
    return hashlib.sha256(canonical_bytes(kind, payload)).digest()
