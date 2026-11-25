"""Content format versions and the negotiation rule for old mobile builds.

A *content format* is a small integer. Format 1 is what every build shipped so
far understands: blocks ``heading``, ``paragraph``, ``example``, ``callout`` and
question kind ``mcq``. Format 2 adds blocks ``math``, ``image``, ``list``,
``table``, ``audio`` and question kinds ``true_false``, ``numeric``,
``short_text``.

THE RULE (normative text: docs/overnight-2026-11-24/lanes/content.md)

1. Every lesson revision has a *required format*: the smallest format whose
   contract accepts all its blocks and question kinds (:func:`required_format`).
2. Every pack release declares exactly one ``content_format``; it may only
   contain revisions whose required format is not higher. A format-1 pack
   therefore never contains a format-2 block or question.
3. A client declares the formats it can render in the request header
   ``Edu-Content-Formats`` (comma-separated integers, e.g. ``1,2``). A missing,
   empty or malformed header means ``{1}``: an old build never sent it.
4. The server offers the highest format that both sides know
   (:func:`negotiate`). When there is none, the content is simply absent for
   that client. A format-2 body is never sent to a format-1 client and is never
   "downgraded" on the fly: reviewers approved the lesson as a whole.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

#: Formats this code base knows how to validate, oldest first.
SUPPORTED_FORMATS: tuple[int, ...] = (1, 2)
#: What a client that sends no header is assumed to understand.
DEFAULT_CLIENT_FORMATS: frozenset[int] = frozenset({1})
#: Request header in which a client declares the formats it can render.
CLIENT_FORMATS_HEADER = "Edu-Content-Formats"

V1_BLOCK_TYPES: frozenset[str] = frozenset({"heading", "paragraph", "example", "callout"})
V2_BLOCK_TYPES: frozenset[str] = V1_BLOCK_TYPES | {"math", "image", "list", "table", "audio"}
V1_QUESTION_KINDS: frozenset[str] = frozenset({"mcq"})
V2_QUESTION_KINDS: frozenset[str] = V1_QUESTION_KINDS | {"true_false", "numeric", "short_text"}

_HEADER_TOKEN = re.compile(r"[1-9][0-9]{0,2}")
_MAX_HEADER_TOKENS = 8


def required_format(blocks: Sequence[Mapping[str, Any]], question_kinds: Iterable[str] = ()) -> int:
    """Smallest content format able to carry these blocks and question kinds.

    Raises ``ValueError`` for a block type or question kind no format knows.
    """
    needed = 1
    for block in blocks:
        block_type = block.get("type") if isinstance(block, Mapping) else None
        if not isinstance(block_type, str):  # a list, a number, missing: never a TypeError
            raise ValueError("unknown block type")
        if block_type in V1_BLOCK_TYPES:
            continue
        if block_type in V2_BLOCK_TYPES:
            needed = 2
        else:
            raise ValueError("unknown block type")
    for kind in question_kinds:
        if not isinstance(kind, str):
            raise ValueError("unknown question kind")
        if kind in V1_QUESTION_KINDS:
            continue
        if kind in V2_QUESTION_KINDS:
            needed = 2
        else:
            raise ValueError("unknown question kind")
    return needed


def parse_client_formats(header_value: str | None) -> frozenset[int]:
    """Formats declared by a client; ``{1}`` when the header is absent or malformed.

    Failing towards the oldest format is the safe direction: the worst case is
    that a new build is offered older content, never the reverse.
    """
    if header_value is None:
        return DEFAULT_CLIENT_FORMATS
    tokens = [token.strip(" \t") for token in header_value.split(",")]
    if not 1 <= len(tokens) <= _MAX_HEADER_TOKENS:
        return DEFAULT_CLIENT_FORMATS
    if not all(_HEADER_TOKEN.fullmatch(token) for token in tokens):
        return DEFAULT_CLIENT_FORMATS
    return frozenset(int(token) for token in tokens)


def negotiate(client_formats: Iterable[int], available_formats: Iterable[int]) -> int | None:
    """Highest format both the client and the available content share, or ``None``."""
    usable = set(client_formats) & set(available_formats) & set(SUPPORTED_FORMATS)
    return max(usable) if usable else None
