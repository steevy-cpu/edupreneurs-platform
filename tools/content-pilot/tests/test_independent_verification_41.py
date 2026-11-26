"""Independent mathematical and CLI checks on #41. Only temporary pilot copies are edited."""

from fractions import Fraction

import pytest
from content_pilot.cli import main
from content_pilot.mathcheck import MAX_STATEMENTS, MathError, statements, value_of

from .conftest import L1, REPO, edit_json


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("(1 008 − 2 × (3 + 1)) ÷ 4", Fraction(250)),
        ("2 − 3 × 4", Fraction(-10)),
        ("(2 − 7) ÷ 3", Fraction(-5, 3)),
        ("1 ÷ (2 + 4) + 1 ÷ 3", Fraction(1, 2)),
        ("(0 − 3) × (0 − 4)", Fraction(12)),
        ("72 ÷ (6 ÷ 2)", Fraction(24)),
        ("72 ÷ 6 ÷ 2", Fraction(6)),
    ],
)
def test_exact_value_independent_oracle(expression, expected):
    assert value_of(expression) == expected


@pytest.mark.parametrize(
    ("display", "expected"),
    [
        ("1 002 − 2 = (200 × 5) = 1 000", True),
        ("1 002 − 2 = 1 000 = 100", False),
        ("2 − 7 < 0 − 1 < 0", True),
        ("2 − 7 > 0 − 1", False),
        ("1 ÷ 3 + 1 ÷ 6 = 1 ÷ 2", True),
        ("1 ÷ 3 + 1 ÷ 6 = 2 ÷ 3", False),
        ("7 ÷ 3 = 2, reste 1", True),
        ("7 ÷ 3 = 2, rès 2", False),
        ("12 ÷ 4 = 3, reste 0", True),
        ("12 ÷ 4 = 3, reste 1", False),
        ("12 ÷ 4 = 3, rès 1", False),
    ],
)
def test_judge_the_complete_claim(display, expected):
    found, problems = statements(display)
    assert not problems
    assert [s.holds for s in found] == [expected]


@pytest.mark.parametrize(
    "display",
    [
        "1/2 = 2",  # unsupported slash; the denominator alone satisfies the equality
        "1,5 = 5",  # French decimal comma
        "3^2 = 2",
        "-4 = 4",  # ASCII minus
        "3÷(2−2)=0",
        "2 × × 3 = 6",
        "2 + 2 = 5 +",
        "1 + = 1",
        "1" * 19 + " = 1",
        "(" * 15 + "1" + ")" * 15 + " = 1",
        " + ".join(["1"] * 41) + " = 41",
    ],
)
def test_invalid_or_unsupported_claim_is_never_verified(display):
    found, problems = statements(display)
    assert problems or any(not s.holds for s in found), (display, found)


@pytest.mark.parametrize("expression", ["1 ÷ (9 − 9)", "(5 + 1", "6 − − 2", "1/2"])
def test_exact_value_rejects_malformed_input(expression):
    with pytest.raises(MathError):
        value_of(expression)


@pytest.mark.parametrize(
    "display",
    [
        "12 ÷ 4 = 3, reste 1",
        "1/2 = 2",
        "2 + 2 = 5 +",
        "; ".join(["1=1"] * MAX_STATEMENTS + ["1=2"]),
        "1 + (2 × 5) = 12",  # control: within the advertised grammar, objectively false
    ],
    ids=["wrong-remainder", "partial-equation", "dangling-operator", "unread-tail", "supported-false"],
)
def test_strict_cli_rejects_bad_lesson_prose(pilot_copy, display):
    for locale, introduction in (("fr", "Vérifie le calcul."), ("ht", "Tcheke kalkil la.")):
        edit_json(pilot_copy, f"{L1}/blocks.{locale}.json", lambda blocks: blocks[1].update(text=f"{introduction} {display}"))
    assert main(["validate", "--forbid-approvals", "--root", str(pilot_copy), "--repo-root", str(REPO)]) != 0


def test_new_output_respects_private_tree_boundary(tmp_path, pilot_copy):
    # Both the output directory and its alias are inside pytest's private temporary tree.
    target = tmp_path / "owned"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    out = alias / "review"
    for flag in ("--write", "--check"):
        assert main(["review-pack", flag, "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)]) != 0
        assert list(target.iterdir()) == []


@pytest.mark.parametrize("mode", ["--check", "--write"])
def test_null_explanation_is_a_controlled_export_error(pilot_copy, tmp_path, capsys, mode):
    edit_json(pilot_copy, f"{L1}/questions.ht.json", lambda questions: questions[0].update(explanation=None))
    out = tmp_path / "review"
    assert main(["review-pack", mode, "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)]) == 2
    assert "explanation" in capsys.readouterr().err
    assert not out.exists()


def test_new_worked_step_is_not_exported_as_checked(pilot_copy, tmp_path):
    for locale in ("fr", "ht"):

        def add_step(blocks):
            example = next(block for block in blocks if block["type"] == "example")
            example["steps"].append("1/2 = 2")

        edit_json(pilot_copy, f"{L1}/blocks.{locale}.json", add_step)

    out = tmp_path.resolve() / "review"
    code = main(["review-pack", "--write", "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)])
    if code == 0:
        sheet = next(out.glob("lesson-01*.md")).read_text()
        guide = (out / "00-guide-de-relecture.md").read_text()
        assert not ("1/2 = 2" in sheet and "chaque calcul des exemples" in guide), "False worked step exported under the global arithmetic-check claim"
