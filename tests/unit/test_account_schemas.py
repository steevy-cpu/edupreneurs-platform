"""Pure validation logic of the account routes (no database, no network)."""

from __future__ import annotations

import unicodedata

import pytest
from pydantic import ValidationError

from edu_api.account.schemas import (
    DISPLAY_NAME_MAX_CHARS,
    ProfilePatch,
    normalise_display_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ti Zwazo", "Ti Zwazo"),
        ("  Ti Zwazo \t", "Ti Zwazo"),
        ("\u00a0Ti\u3000", "Ti"),  # Unicode spaces are trimmed too
        ("Ele\u0300v", "Elèv"),  # decomposed input is stored composed (NFC)
        ("Élève d'essai n° 7", "Élève d'essai n° 7"),
        ("x" * DISPLAY_NAME_MAX_CHARS, "x" * DISPLAY_NAME_MAX_CHARS),
        ("  " + "e\u0301" * DISPLAY_NAME_MAX_CHARS + "  ", "é" * DISPLAY_NAME_MAX_CHARS),
    ],
)
def test_display_name_is_trimmed_and_normalised(raw: str, expected: str) -> None:
    assert normalise_display_name(raw) == expected
    assert unicodedata.is_normalized("NFC", normalise_display_name(raw))


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "\t\n",
        "x" * (DISPLAY_NAME_MAX_CHARS + 1),
        "x" * 10_000,
        "line one\nline two",
        "carriage\rreturn",
        "tab\tinside",
        "nul\x00byte",
        "escape\x1b[31m",
        "del\x7f",
        "c1\u0085control",
        "line\u2028separator",
        "paragraph\u2029separator",
        "lone\ud800surrogate",
    ],
)
def test_display_name_rejections_never_echo_the_value(raw: str) -> None:
    with pytest.raises(ValueError) as caught:
        normalise_display_name(raw)
    message = str(caught.value)
    assert message.startswith("display_name must")
    if raw.strip():
        assert raw.strip() not in message


def test_patch_reports_only_the_fields_that_were_sent() -> None:
    assert ProfilePatch.model_validate({}).changes() == {}
    assert ProfilePatch.model_validate({"display_name": None}).changes() == {"display_name": None}
    assert ProfilePatch.model_validate({"grade_code": "9AF"}).changes() == {"grade_code": "9AF"}
    full = ProfilePatch.model_validate(
        {"display_name": " A ", "preferred_locale": "ht", "grade_code": "NS4"}
    )
    assert full.changes() == {"display_name": "A", "grade_code": "NS4", "preferred_locale": "ht"}


@pytest.mark.parametrize(
    "body",
    [
        {"grade_code": None},
        {"preferred_locale": None},
        {"preferred_locale": "en"},
        {"preferred_locale": "FR"},
        {"grade_code": "9af"},
        {"grade_code": "9"},
        {"grade_code": "TOOLONG123"},
        {"grade_code": "9AF'; --"},
        {"grade_code": 9},
        {"display_name": 7},
        {"display_name": ["a"]},
        {"user_id": "a0000000-0000-4000-8000-000000000002"},
        {"grade_id": "b0000000-0000-4000-8000-000000000001"},
        {"created_at": "2020-01-01T00:00:00Z"},
        {"role": "admin"},
        {"display_name": "ok", "is_staff": True},
    ],
)
def test_patch_is_strict(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProfilePatch.model_validate(body)
