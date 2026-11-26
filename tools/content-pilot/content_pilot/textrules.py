"""Plain-text rules shared by every string in the pilot (same spirit as the v1 content contract:
text only, never markup, no control or invisible characters)."""

from __future__ import annotations

import re
import unicodedata

NBSP = "\u00a0"  # allowed: keeps digit groups ("2 450") from breaking across lines

_ALLOWED_CONTROL = set()  # nothing: no tab, no newline inside a single text field

# Ranges refused: C0/C1 controls, zero-width and bidi-control characters, BOM, private use, replacement char.
_BAD_RANGES = (
    (0x0000, 0x001F),
    (0x007F, 0x009F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x2064),
    (0xE000, 0xF8FF),
    (0xFEFF, 0xFEFF),
    (0xFFFD, 0xFFFD),
)

_MARKUP = re.compile(r"</?[A-Za-z!][^>]*>?")
_ENTITY = re.compile(r"&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z]{2,8});")
_MD = re.compile(r"`|\*\*|__|\]\(|^\s{0,3}#{1,6}\s", re.M)
_URL = re.compile(r"https?://|www\.", re.I)
NUMBER = re.compile(r"\d+(?:\u00a0\d{3})*")


def _bad_char(ch: str) -> bool:
    c = ord(ch)
    return any(a <= c <= b for a, b in _BAD_RANGES)


def scan_text(text: str) -> list[tuple[str, str]]:
    """Return (code, message) for every violation found in one text field."""
    out: list[tuple[str, str]] = []
    if not text.strip():
        out.append(("text_empty", "empty or blank text"))
        return out
    bad = sorted({f"U+{ord(c):04X}" for c in text if _bad_char(c)})
    if bad:
        out.append(("invalid_character", f"control, invisible or replacement character(s): {', '.join(bad)}"))
    if _MARKUP.search(text):
        out.append(("markup", "HTML-like markup is not allowed (plain text only)"))
    if _ENTITY.search(text):
        out.append(("markup", "character entity (&...;) is not allowed"))
    if _MD.search(text):
        out.append(("markup", "Markdown-style formatting is not allowed (plain text only)"))
    if _URL.search(text):
        out.append(("url", "links and URLs are not allowed in lesson text"))
    if text != text.strip():
        out.append(("whitespace", "leading or trailing whitespace"))
    if "  " in text:
        out.append(("whitespace", "double space"))
    if unicodedata.normalize("NFC", text) != text:
        out.append(("not_nfc", "text is not Unicode NFC (accents stored decomposed)"))
    return out


def number_tokens(text: str) -> list[str]:
    """Numbers as written (digit groups joined by NBSP), used to compare fr/ht versions."""
    return sorted(NUMBER.findall(text))


MATH_SYMBOLS = "+−×÷=<>≤≥≠"


def number_sequence(text: str) -> list[int]:
    """Numbers as written, IN ORDER (NBSP digit groups joined). Order matters: 702 − 345 is not 345 − 702."""
    return [int(t.replace(NBSP, "")) for t in NUMBER.findall(text)]


def math_symbols(text: str) -> str:
    """The arithmetic and comparison signs of a text, in order, so `<` can never silently become `≥`."""
    return "".join(ch for ch in text if ch in MATH_SYMBOLS)
