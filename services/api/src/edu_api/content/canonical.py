"""Canonical JSON for pack manifests and lesson objects (``edu-canon-json-1``).

WHY: a pack is identified by the SHA-256 of its manifest, and every lesson
object by the SHA-256 of its bytes. Two builds of the same content must
therefore produce the same bytes, on any machine, in any order of execution.

RULE ``edu-canon-json-1``
1. Text is Unicode NFC. Object keys are ASCII.
2. Numbers are integers. Floating-point numbers are not allowed (they have
   several valid spellings); booleans and null are.
3. Objects are written with their keys sorted (by code point; all keys are
   ASCII), arrays in their given order - the order of an array is part of the
   document and is fixed by the manifest specification.
4. No insignificant whitespace: separators are ``,`` and ``:``.
5. Strings use the shortest JSON escapes: ``\\"`` ``\\\\`` ``\\b`` ``\\f`` ``\\n``
   ``\\r`` ``\\t``, ``\\u00XX`` (lower-case hex) for the other characters below
   U+0020, and every other character written literally.
6. UTF-8, no byte-order mark, no trailing line break.

This is what ``JSON.stringify`` produces in JavaScript for an object whose keys
were inserted in sorted order, which keeps a phone implementation short.
It is the same serialisation as the sync digest rule ``mep-canon-1``
(``edu_api.sync.canonical``), applied to a whole document.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

CANON_JSON_VERSION = "edu-canon-json-1"


def _normalise(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.isascii():
                raise TypeError("canonical JSON object keys must be ASCII strings")
            out[key] = _normalise(item)
        return out
    if isinstance(value, list | tuple):
        return [_normalise(item) for item in value]
    raise TypeError(f"unsupported value in canonical JSON: {type(value).__name__}")


def canonical_json(document: Any) -> bytes:
    """The canonical bytes of ``document``. Raises ``TypeError`` for floats and odd keys."""
    return json.dumps(
        _normalise(document),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def is_canonical_json(data: bytes) -> bool:
    """True when ``data`` is exactly the canonical form of the document it encodes."""
    try:
        return canonical_json(json.loads(data.decode("utf-8"))) == data
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
        return False


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
