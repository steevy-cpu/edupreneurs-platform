"""Reference scoring for question kinds ``true_false``, ``numeric``, ``short_text``.

STATUS: reference implementation and contract only. These functions are NOT
called by ``app.sync_apply_operation``; the server still rejects every kind
other than ``mcq`` with ``unsupported_question_kind``. They exist so that the
future server rule and the phone's offline feedback are written against the
same vectors (``packages/contracts/content/vectors/scoring.json``).

Every rule is versioned. A change in normalisation, tolerance handling or
matching needs a NEW version string, because stored attempts record the
version that scored them (``practice_attempts.scoring_version``).

All functions are total: malformed input never raises, it yields
``invalid_response``. Scores are the integers 0 and 1; there is no floating
point anywhere in this module.

true-false-v1
    response ``{"value": <boolean>}``; score 1 when it equals
    ``answer_key.correct``. Anything that is not exactly that shape is
    ``invalid_response`` / ``not_a_boolean`` (the JSON strings "true"/"false"
    and the numbers 0/1 are NOT booleans).

numeric-v1
    response ``{"text": <string of 1..32 code points>}``. Steps:
    1. delete every U+0009, U+0020, U+00A0, U+2009, U+202F (so "1 000" is 1000);
    2. replace U+2212 (minus sign) by "-";
    3. a decimal is ``[+-]? digits{1,12} ( [.,] digits{1,6} )?``;
       when ``response_spec.allow_fraction`` is true a fraction
       ``[+-]? digits{1,12} / digits{1,12}`` with a non-zero denominator is
       also a number; nothing else is (``not_a_number``): no exponent, no
       leading or trailing separator, no thousands separators other than the
       spaces of step 1;
    4. compare EXACTLY (rational arithmetic):
       correct when ``|response - value| <= tolerance``.

short-text-v1
    response ``{"text": <string of 1..200 code points>}``; longer than
    ``response_spec.max_length`` code points is ``too_long``. Normalisation of
    the response and of each accepted answer:
    1. Unicode NFC;
    2. U+2019, U+2018, U+02BC become U+0027 (apostrophe);
    3. each run of U+0009, U+000A, U+000D, U+0020, U+00A0, U+2009, U+202F
       becomes one U+0020; leading and trailing spaces are removed;
    4. unless ``case_sensitive``: Unicode default lower-casing
       (locale-independent);
    5. unless ``accent_sensitive``: U+0153 to "oe", U+0152 to "OE", U+00E6 to
       "ae", U+00C6 to "AE"; then NFD, delete U+0300..U+036F, then NFC.
    An empty result is ``empty``. Correct when the normalised response equals
    one normalised accepted answer, code point for code point.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

TRUE_FALSE_V1 = "true-false-v1"
NUMERIC_V1 = "numeric-v1"
SHORT_TEXT_V1 = "short-text-v1"
SCORING_VERSIONS: dict[str, str] = {
    "true_false": TRUE_FALSE_V1,
    "numeric": NUMERIC_V1,
    "short_text": SHORT_TEXT_V1,
}

NUMERIC_RESPONSE_MAX = 32
SHORT_TEXT_RESPONSE_MAX = 200

_NUMERIC_SPACES = str.maketrans("", "", "\u0009\u0020\u00a0\u2009\u202f")
_DECIMAL = re.compile(r"([+-]?)([0-9]{1,12})(?:[.,]([0-9]{1,6}))?")
_FRACTION = re.compile(r"([+-]?)([0-9]{1,12})/([0-9]{1,12})")
_KEY_DECIMAL = re.compile(r"(-?)(0|[1-9][0-9]{0,11})(?:\.([0-9]{1,6}))?")
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'"})
_TEXT_SPACES = re.compile("[\u0009\u000a\u000d\u0020\u00a0\u2009\u202f]+")
_LIGATURES = str.maketrans({"\u0153": "oe", "\u0152": "OE", "\u00e6": "ae", "\u00c6": "AE"})
_COMBINING = re.compile("[\u0300-\u036f]")


@dataclass(frozen=True)
class ScoreResult:
    """Outcome of scoring one response.

    ``status == "scored"``: ``score`` is 0 or 1 and ``is_correct`` matches it.
    ``status == "invalid_response"``: nothing is scored; ``code`` says why.
    """

    status: Literal["scored", "invalid_response"]
    scoring_version: str
    score: int | None = None
    is_correct: bool | None = None
    code: str | None = None


def _scored(version: str, correct: bool) -> ScoreResult:
    return ScoreResult("scored", version, score=1 if correct else 0, is_correct=correct)


def _invalid(version: str, code: str) -> ScoreResult:
    return ScoreResult("invalid_response", version, code=code)


def _only_key(response: Any, name: str) -> Any:
    """The value of ``response[name]`` when ``response`` is exactly ``{name: ...}``."""
    if not isinstance(response, dict) or set(response) != {name}:
        return None
    return response[name]


# --- true_false ---------------------------------------------------------------------
def score_true_false(answer_key: Mapping[str, Any], response: Any) -> ScoreResult:
    value = _only_key(response, "value")
    if not isinstance(value, bool):
        return _invalid(TRUE_FALSE_V1, "not_a_boolean")
    return _scored(TRUE_FALSE_V1, value is answer_key["correct"])


# --- numeric ------------------------------------------------------------------------
def _decimal(sign: str, integer: str, fraction: str | None) -> Fraction:
    digits = fraction or ""
    magnitude = Fraction(int(integer + digits), 10 ** len(digits))
    return -magnitude if sign == "-" else magnitude


def parse_key_decimal(text: str) -> Fraction:
    """Exact value of a canonical decimal string of an answer key (value or tolerance)."""
    match = _KEY_DECIMAL.fullmatch(text)
    if match is None:
        raise ValueError("not a canonical decimal")
    return _decimal(match[1], match[2], match[3])


def parse_numeric_response(text: str, *, allow_fraction: bool) -> Fraction | None:
    """Exact value of what the learner typed under ``numeric-v1``, or ``None``."""
    cleaned = text.translate(_NUMERIC_SPACES).replace("\u2212", "-")
    match = _DECIMAL.fullmatch(cleaned)
    if match is not None:
        return _decimal(match[1], match[2], match[3])
    if allow_fraction:
        match = _FRACTION.fullmatch(cleaned)
        if match is not None and int(match[3]) != 0:
            magnitude = Fraction(int(match[2]), int(match[3]))
            return -magnitude if match[1] == "-" else magnitude
    return None


def score_numeric(
    response_spec: Mapping[str, Any], answer_key: Mapping[str, Any], response: Any
) -> ScoreResult:
    text = _only_key(response, "text")
    if not isinstance(text, str) or not 1 <= len(text) <= NUMERIC_RESPONSE_MAX:
        return _invalid(NUMERIC_V1, "not_a_number")
    value = parse_numeric_response(text, allow_fraction=response_spec["allow_fraction"] is True)
    if value is None:
        return _invalid(NUMERIC_V1, "not_a_number")
    expected = parse_key_decimal(answer_key["value"])
    tolerance = parse_key_decimal(answer_key["tolerance"])
    return _scored(NUMERIC_V1, abs(value - expected) <= tolerance)


# --- short_text ---------------------------------------------------------------------
def normalise_short_text(text: str, *, case_sensitive: bool, accent_sensitive: bool) -> str:
    out = unicodedata.normalize("NFC", text).translate(_APOSTROPHES)
    out = _TEXT_SPACES.sub(" ", out).strip(" ")
    if not case_sensitive:
        out = out.lower()
    if not accent_sensitive:
        out = unicodedata.normalize("NFD", out.translate(_LIGATURES))
        out = unicodedata.normalize("NFC", _COMBINING.sub("", out))
    return out


def score_short_text(
    response_spec: Mapping[str, Any], answer_key: Mapping[str, Any], response: Any
) -> ScoreResult:
    text = _only_key(response, "text")
    if not isinstance(text, str) or not 1 <= len(text) <= SHORT_TEXT_RESPONSE_MAX:
        return _invalid(SHORT_TEXT_V1, "not_text")
    if len(text) > response_spec["max_length"]:
        return _invalid(SHORT_TEXT_V1, "too_long")
    case_sensitive = response_spec["case_sensitive"] is True
    accent_sensitive = response_spec["accent_sensitive"] is True
    given = normalise_short_text(
        text, case_sensitive=case_sensitive, accent_sensitive=accent_sensitive
    )
    if given == "":
        return _invalid(SHORT_TEXT_V1, "empty")
    accepted = {
        normalise_short_text(
            answer, case_sensitive=case_sensitive, accent_sensitive=accent_sensitive
        )
        for answer in answer_key["accepted"]
    }
    return _scored(SHORT_TEXT_V1, given in accepted)


def score(
    kind: str, response_spec: Mapping[str, Any], answer_key: Mapping[str, Any], response: Any
) -> ScoreResult:
    """Score ``response`` for a VALID question of the given kind (validate it first)."""
    if kind == "true_false":
        return score_true_false(answer_key, response)
    if kind == "numeric":
        return score_numeric(response_spec, answer_key, response)
    if kind == "short_text":
        return score_short_text(response_spec, answer_key, response)
    raise ValueError("no reference scoring rule for this question kind")
