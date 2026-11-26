"""Unit conversions require recorded coverage before a worked step can be called checked."""

import pytest
from content_pilot.cli import main
from content_pilot.mathcheck import statements

from .conftest import L1, REPO, edit_json


@pytest.mark.parametrize(("claim", "correct"), [("8 km = 8 m", False), ("1 m = 100 cm", True), ("1 kg = (2 + 3) g", False)])
def test_units_do_not_turn_magnitudes_into_a_verified_numeric_equality(claim, correct):
    judged, _ = statements(claim)
    for statement in judged:
        if statement.holds:
            assert correct and statement.text == claim


def test_unit_qualified_worked_step_has_truthful_review_status(pilot_copy, tmp_path):
    claim = "8 km = 8 m"

    def append_conversion(blocks):
        example = next(block for block in blocks if block["type"] == "example")
        example["steps"].append(claim)

    for locale in ("fr", "ht"):
        edit_json(pilot_copy, f"{L1}/blocks.{locale}.json", append_conversion)

    out = tmp_path.resolve() / "review"
    result = main(["review-pack", "--write", "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)])
    if result == 0:
        sheet = next(out.glob("lesson-01*.md")).read_text()
        guide = (out / "00-guide-de-relecture.md").read_text()
        assert not (claim in sheet and "chaque calcul des exemples" in guide), "Unchecked false unit conversion exported under the blanket verification claim"
