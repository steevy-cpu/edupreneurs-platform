"""Validator for lesson bodies (``app.lesson_revisions.blocks``), formats 1 and 2.

``validate_blocks(document, content_format)`` returns a list of
:class:`~edu_api.content.issues.Issue`; an empty list means valid.

SEMANTIC RULES (format 2 only; codes are stable and shared with the phone)

    keys.unique          every block key appears once in the lesson
    math.*               the edu-math-1 grammar (see math_notation.py)
    table.row_width      every row has exactly as many cells as there are columns
    table.width_budget   readable on a 320 dp screen without horizontal scrolling:
                         for each column take its longest unbreakable word (cells
                         and header, split on U+0020, counted in code points);
                         the sum over the columns must be <= 36 - 2 * columns
                         (32 / 30 / 28 for 2 / 3 / 4 columns)
    audio.transcript     every transcript block key exists in this lesson and
                         names a text-bearing block (not audio, not image)
    assets.consistent    the same sha256 always comes with the same mime, bytes
                         and intrinsic size
    assets.image_budget  distinct images of one lesson (including pre-rendered
                         formulas) weigh at most 1 000 000 bytes together

WHERE 36 - 2n COMES FROM: 320 dp screen, 16 dp page margin on each side leaves
288 dp; each column needs 16 dp of cell padding; a 14 sp glyph is budgeted at
8 dp. floor((288 - 16 n) / 8) = 36 - 2 n characters that can never be broken.
Cell text wraps at spaces; a word is never split and the table never scrolls
sideways.
"""

from __future__ import annotations

import re
from typing import Any

from edu_api.content.formats import SUPPORTED_FORMATS, V1_BLOCK_TYPES, V2_BLOCK_TYPES
from edu_api.content.issues import Collector, Issue
from edu_api.content.math_notation import MAX_SOURCE_LENGTH, NOTATION, check_math_source

MAX_BLOCKS = 200
MAX_IMAGE_BYTES = 200_000
MAX_IMAGE_SIDE = 1600
MAX_AUDIO_BYTES = 2_000_000
MAX_AUDIO_MS = 600_000
MAX_LESSON_IMAGE_BYTES = 1_000_000
IMAGE_MIMES = frozenset({"image/webp", "image/png", "image/jpeg"})
AUDIO_MIMES = frozenset({"audio/mp4", "audio/mpeg"})
TEXT_BEARING_TYPES = V2_BLOCK_TYPES - {"audio", "image"}

_KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MATH_CHARSET = re.compile(r"[A-Za-z0-9 +*/=<>()\[\]|,.;:!'^_{}\\%\u00c0-\u017f-]+")


def table_width_budget(columns: int) -> int:
    return 36 - 2 * columns


def _key(c: Collector, block: dict[str, Any], path: str) -> None:
    if "key" in block:
        c.string(block["key"], f"{path}/key", max_len=64, pattern=_KEY, no_control=True)


def _image_asset(c: Collector, value: Any, path: str) -> None:
    if not c.obj(value, path, ("sha256", "mime", "bytes", "width", "height")):
        return
    c.string(value["sha256"], f"{path}/sha256", min_len=64, max_len=64, pattern=_SHA256)
    c.enum(value["mime"], f"{path}/mime", IMAGE_MIMES)
    c.integer(value["bytes"], f"{path}/bytes", 1, MAX_IMAGE_BYTES)
    c.integer(value["width"], f"{path}/width", 1, MAX_IMAGE_SIDE)
    c.integer(value["height"], f"{path}/height", 1, MAX_IMAGE_SIDE)


def _audio_asset(c: Collector, value: Any, path: str) -> None:
    if not c.obj(value, path, ("sha256", "mime", "bytes")):
        return
    c.string(value["sha256"], f"{path}/sha256", min_len=64, max_len=64, pattern=_SHA256)
    c.enum(value["mime"], f"{path}/mime", AUDIO_MIMES)
    c.integer(value["bytes"], f"{path}/bytes", 1, MAX_AUDIO_BYTES)


def _heading(c: Collector, b: dict[str, Any], p: str) -> None:
    if c.obj(b, p, ("key", "type", "text")):
        c.string(b["text"], f"{p}/text", max_len=200)


def _paragraph(c: Collector, b: dict[str, Any], p: str) -> None:
    if c.obj(b, p, ("key", "type", "text")):
        c.string(b["text"], f"{p}/text", max_len=4000)


def _example(c: Collector, b: dict[str, Any], p: str) -> None:
    if not c.obj(b, p, ("key", "type", "steps"), ("title",)):
        return
    if "title" in b:
        c.string(b["title"], f"{p}/title", max_len=200)
    if c.array(b["steps"], f"{p}/steps", 1, 20):
        for i, step in enumerate(b["steps"]):
            c.string(step, f"{p}/steps/{i}", max_len=500)


def _callout(c: Collector, b: dict[str, Any], p: str) -> None:
    if c.obj(b, p, ("key", "type", "tone", "text")):
        c.enum(b["tone"], f"{p}/tone", ("tip", "warning", "remember"))
        c.string(b["text"], f"{p}/text", max_len=4000)


def _math(c: Collector, b: dict[str, Any], p: str) -> None:
    if not c.obj(b, p, ("key", "type", "notation", "source", "alt"), ("asset",)):
        return
    c.const(b["notation"], f"{p}/notation", NOTATION)
    c.string(
        b["source"],
        f"{p}/source",
        max_len=MAX_SOURCE_LENGTH,
        pattern=_MATH_CHARSET,
        plain=True,  # no control character, no tag opener (bare or inside \\text{})
    )
    c.string(b["alt"], f"{p}/alt", max_len=300, plain=True)
    if "asset" in b:
        _image_asset(c, b["asset"], f"{p}/asset")


def _image(c: Collector, b: dict[str, Any], p: str) -> None:
    if not c.obj(b, p, ("key", "type", "asset", "alt"), ("caption",)):
        return
    _image_asset(c, b["asset"], f"{p}/asset")
    c.string(b["alt"], f"{p}/alt", max_len=300, plain=True)
    if "caption" in b:
        c.string(b["caption"], f"{p}/caption", max_len=200, plain=True)


def _list(c: Collector, b: dict[str, Any], p: str) -> None:
    if not c.obj(b, p, ("key", "type", "style", "items")):
        return
    c.enum(b["style"], f"{p}/style", ("bullet", "number"))
    if c.array(b["items"], f"{p}/items", 1, 30):
        for i, item in enumerate(b["items"]):
            c.string(item, f"{p}/items/{i}", max_len=500, plain=True)


def _table(c: Collector, b: dict[str, Any], p: str) -> None:
    if not c.obj(b, p, ("key", "type", "caption", "columns", "rows"), ("row_headers",)):
        return
    c.string(b["caption"], f"{p}/caption", max_len=200, plain=True)
    if c.array(b["columns"], f"{p}/columns", 2, 4):
        for i, cell in enumerate(b["columns"]):
            c.string(cell, f"{p}/columns/{i}", max_len=24, plain=True)
    if "row_headers" in b:
        c.boolean(b["row_headers"], f"{p}/row_headers")
    if c.array(b["rows"], f"{p}/rows", 1, 20):
        for r, row in enumerate(b["rows"]):
            if c.array(row, f"{p}/rows/{r}", 2, 4):
                for i, cell in enumerate(row):
                    c.string(cell, f"{p}/rows/{r}/{i}", min_len=0, max_len=80, plain=True)


def _audio(c: Collector, b: dict[str, Any], p: str) -> None:
    if not c.obj(b, p, ("key", "type", "asset", "duration_ms", "title", "transcript")):
        return
    _audio_asset(c, b["asset"], f"{p}/asset")
    c.integer(b["duration_ms"], f"{p}/duration_ms", 1, MAX_AUDIO_MS)
    c.string(b["title"], f"{p}/title", max_len=200, plain=True)
    transcript = b["transcript"]
    if not c.obj(transcript, f"{p}/transcript", ("block_keys",)):
        return
    keys = transcript["block_keys"]
    if c.array(keys, f"{p}/transcript/block_keys", 1, 20):
        usable = True
        for i, key in enumerate(keys):
            usable &= c.string(
                key,
                f"{p}/transcript/block_keys/{i}",
                max_len=64,
                pattern=_KEY,
                no_control=True,
            )
        if usable and len(set(keys)) != len(keys):
            c.schema(f"{p}/transcript/block_keys", "items must be unique")


_BLOCK_CHECKS = {
    "heading": _heading,
    "paragraph": _paragraph,
    "example": _example,
    "callout": _callout,
    "math": _math,
    "image": _image,
    "list": _list,
    "table": _table,
    "audio": _audio,
}


def _structure(c: Collector, document: Any, content_format: int) -> None:
    if not c.array(document, "", 1, MAX_BLOCKS):
        return
    allowed = V1_BLOCK_TYPES if content_format == 1 else V2_BLOCK_TYPES
    for index, block in enumerate(document):
        path = f"/{index}"
        if not isinstance(block, dict):
            c.schema(path, "must be an object")
            continue
        block_type = block.get("type")
        if not isinstance(block_type, str) or block_type not in allowed:
            c.schema(f"{path}/type", f"is not a block type of content format {content_format}")
            continue
        _BLOCK_CHECKS[block_type](c, block, path)
        _key(c, block, path)


def _longest_word(text: str) -> int:
    return max((len(word) for word in text.split(" ")), default=0)


def _table_semantics(c: Collector, block: dict[str, Any], path: str) -> None:
    columns: list[str] = block["columns"]
    rows: list[list[str]] = block["rows"]
    if any(len(row) != len(columns) for row in rows):
        c.semantic(path, "table.row_width", "every row needs one cell per column")
        return
    needed = 0
    for index, header in enumerate(columns):
        needed += max(_longest_word(header), *(_longest_word(row[index]) for row in rows))
    if needed > table_width_budget(len(columns)):
        c.semantic(path, "table.width_budget", "too wide for a 320 dp screen")


def _semantics(c: Collector, document: list[dict[str, Any]]) -> None:
    types_by_key: dict[str, str] = {}
    for index, block in enumerate(document):
        key: str = block["key"]
        if key in types_by_key:
            c.semantic(f"/{index}/key", "keys.unique", "block key is used more than once")
        else:
            types_by_key[key] = block["type"]

    assets: dict[str, dict[str, Any]] = {}
    image_bytes = 0
    for index, block in enumerate(document):
        path = f"/{index}"
        block_type = block["type"]
        if block_type == "math":
            code = check_math_source(block["source"])
            if code is not None:
                c.semantic(f"{path}/source", code, "not valid edu-math-1")
        elif block_type == "table":
            _table_semantics(c, block, path)
        elif block_type == "audio":
            for position, key in enumerate(block["transcript"]["block_keys"]):
                if types_by_key.get(key) not in TEXT_BEARING_TYPES:
                    c.semantic(
                        f"{path}/transcript/block_keys/{position}",
                        "audio.transcript",
                        "must name a text-bearing block of this lesson",
                    )
        asset = block.get("asset")
        if asset is None:
            continue
        known = assets.get(asset["sha256"])
        if known is None:
            assets[asset["sha256"]] = asset
            if block_type != "audio":
                image_bytes += asset["bytes"]
        elif known != asset:
            c.semantic(f"{path}/asset", "assets.consistent", "same hash with different metadata")
    if image_bytes > MAX_LESSON_IMAGE_BYTES:
        c.semantic("", "assets.image_budget", "images of this lesson are too heavy together")


def validate_blocks(document: Any, content_format: int) -> list[Issue]:
    """Validate a lesson body against content format 1 or 2."""
    if content_format not in SUPPORTED_FORMATS:
        raise ValueError("unsupported content format")
    collector = Collector()
    _structure(collector, document, content_format)
    if not collector.issues and content_format >= 2:
        _semantics(collector, document)
    return collector.issues


def asset_references(document: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Distinct assets referenced by a VALID lesson body, keyed by sha256.

    Each value is the asset object plus ``kind`` (``image`` or ``audio``).
    """
    found: dict[str, dict[str, Any]] = {}
    for block in document:
        asset = block.get("asset")
        if isinstance(asset, dict):
            kind = "audio" if block.get("type") == "audio" else "image"
            found.setdefault(asset["sha256"], {**asset, "kind": kind})
    return found
