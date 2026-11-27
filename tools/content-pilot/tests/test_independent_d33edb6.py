"""Independent worked-step boundaries after d33edb6. All changed lessons are disposable copies."""

import pytest
from content_pilot.cli import main
from content_pilot.mathcheck import analyze

from .conftest import L1, edit_json
from .test_postqa44_independent import review_args, sheet_coverage


@pytest.mark.parametrize("text", ["Calcule : 3 = 3.", "Tcheke : 3 = 3.", "12 ÷ 4 = 3, reste 0.", "(6 + 6) ÷ 3 = 4."])
def test_prose_and_supported_division(text):
    result = analyze(text)
    assert [s.holds for s in result.statements] == [True]
    assert not result.problems and not result.skipped


@pytest.mark.parametrize("text", ["6 : 3 = 3", "(6 + 6) : (3) = 3", ".5 = 5", ",5 = 5", "1’234 = 234", "6 ÷ 3 = 3", "7 ÷ 3 = 2, rès 1/2"])
def test_incorrect_or_unread_claim_never_gets_a_verified_suffix(text):
    result = analyze(text)
    assert not any(s.holds for s in result.statements), (text, result)
    assert result.problems or result.skipped or result.statements


@pytest.mark.parametrize("text", ["6 : 3 = 3", ".5 = 5", "6 ÷ 3 = 3"])
def test_bilingual_worked_example_is_blocked_or_flagged_without_inflating_count(pilot_copy, tmp_path, text):
    out = tmp_path.resolve() / "review"
    assert main(review_args(pilot_copy, out, "--write")) == 0
    before, _ = sheet_coverage(out)

    def add_step(blocks):
        example = next(block for block in blocks if block["type"] == "example")
        example["steps"].append(text)

    for locale in ("fr", "ht"):
        edit_json(pilot_copy, f"{L1}/blocks.{locale}.json", add_step)

    result = main(review_args(pilot_copy, out, "--write"))
    if result == 0:
        after, section = sheet_coverage(out)
        rows = [line for line in section.splitlines() if text in line]
        assert before == after and all(any(f"{loc}/blocs" in row for row in rows) for loc in ("fr", "ht")), (text, before, after, rows)
    else:
        assert result == 2
