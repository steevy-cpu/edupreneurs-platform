"""Additional independent checks for Content-02A after PR #37. Only private copies are edited."""

import shutil

import pytest
from content_pilot.checks import validate
from content_pilot.cli import main
from content_pilot.safe_eval import EvalLimits, UnsafeExpression, safe_eval

from .conftest import L1, REPO, edit_json

L4 = "lessons/04-multiplier-diviser-10-100-1000"


def errors(root):
    return [f for f in validate(root, repo_root=REPO, forbid_approvals=True) if f.severity == "error"]


def edit_first_step(root, example, before, after):
    def revise(blocks):
        block = next(b for b in blocks if b["key"] == example)
        assert block["steps"][0] == before
        block["steps"][0] = after

    for locale in ("fr", "ht"):
        edit_json(root, f"{L4}/blocks.{locale}.json", revise)


def test_displayed_result_is_a_whole_number_token(pilot_copy):
    edit_first_step(pilot_copy, "exemple-multiplier", "36 × 10 = 360", "36 × 10 = 3600")
    assert errors(pilot_copy)


def test_division_equality_requires_zero_remainder(pilot_copy):
    edit_first_step(pilot_copy, "exemple-diviser", "4 500 ÷ 10 = 450", "4 501 ÷ 10 = 450")

    def revise(verification):
        example = next(e for e in verification["examples"] if e["block"] == "exemple-diviser")
        example["checks"][0].update(expr="4501 // 10", equals=450, must_appear="4501÷10=450")

    edit_json(pilot_copy, f"{L4}/verification.json", revise)
    assert errors(pilot_copy)


@pytest.mark.parametrize("kind", ["blocks", "questions"])
def test_complete_duplicate_locale_prose_is_flagged(pilot_copy, kind):
    folder = pilot_copy / L1
    shutil.copyfile(folder / f"{kind}.fr.json", folder / f"{kind}.ht.json")
    findings = validate(pilot_copy, repo_root=REPO, forbid_approvals=True)
    assert findings, "A whole prose-bearing file is byte-identical in both locales"


def test_review_export_reports_incomplete_question(pilot_copy, tmp_path, capsys):
    edit_json(pilot_copy, f"{L1}/questions.fr.json", lambda questions: questions[0].pop("answer_key"))
    code = main(["review-pack", "--root", str(pilot_copy), "--review-dir", str(tmp_path / "review"), "--check"])
    assert code in (1, 2)
    assert "answer_key" in "".join(capsys.readouterr())


def test_sum_obeys_same_integer_limit_as_addition():
    with pytest.raises(UnsafeExpression):
        safe_eval("sum([4, 4])", EvalLimits(max_bits=3))


def test_numeric_prefix_control_corrected_back_to_valid(pilot_copy):
    edit_first_step(pilot_copy, "exemple-multiplier", "36 × 10 = 360", "36 × 10 = 3600")
    edit_first_step(pilot_copy, "exemple-multiplier", "36 × 10 = 3600", "36 × 10 = 360")
    assert not errors(pilot_copy)
