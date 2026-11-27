"""Independent Content-02A retest. Every modified input and export lives in a pytest fixture."""

import re

import pytest
from content_pilot.cli import main
from content_pilot.mathcheck import MAX_STATEMENTS, analyze

from .conftest import L1, REPO, edit_json


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("1 ÷ 3 + 1 ÷ 6 = 1 ÷ 2", True),
        ("(2 − 9) × (1 − 4) = 21 > 20", True),
        ("(2 − 9) × (1 − 4) = 21 < 20", False),
        ("5 ÷ 2 = 2", False),
        ("(6 + 7) ÷ 4 = 3, reste 1", True),
        ("(6 + 7) ÷ 4 = 3, rès 2", False),
        ("12 ÷ 4 = 3, reste 0.", True),
    ],
)
def test_whole_claim_controls(claim, expected):
    a = analyze(claim)
    assert not a.problems and not a.skipped
    assert [s.holds for s in a.statements] == [expected]


@pytest.mark.parametrize(
    "claim",
    [
        "2 ⋅ 3 = 3",
        "1\u202f234 = 234",
        "2 ∙ 4 = 4",
        "1 ＋ 2 = 2",
        "—4 = 4",
        "1/2 = 2",
        "1,25 = 25",
        "12 ÷ 4 = 3, reste 0,5",
        "7 ÷ 3 = 2, rès 1.5",
        "12 ÷ 4 = 3, rès -1",
        "12 ÷ 4 = 3, reste",
        "12 ÷ 4 = 3, reste 0 + 1",
        "2 + 2 = 4 +",
        "3 ÷ (2 − 2) = 0",
        "1 ≈ 200",
        "1 ＝ 2",
        "1 kg = 2 g",
        "9" * 19 + " = 1",
    ],
)
def test_no_verified_part_or_silent_omission(claim):
    a = analyze(claim)
    assert not any(st.holds for st in a.statements), (claim, a)
    assert a.problems or a.skipped or any(not st.holds for st in a.statements), (claim, a)


def test_excess_statement_has_visible_limit():
    claims = ["1=1"] * MAX_STATEMENTS + ["2=1"]
    a = analyze("; ".join(claims))
    assert a.limit_reached and a.problems
    assert len(a.statements) <= MAX_STATEMENTS


def review_args(root, out, mode):
    return ["review-pack", mode, "--root", str(root), "--repo-root", str(REPO), "--review-dir", str(out)]


def sheet_coverage(out):
    sheet = next(out.glob("lesson-01*.md")).read_text()
    section = sheet.split("Calculs : ce que l'outil", 1)[1].split("\n## ", 1)[0]
    count = re.search(r"recalculé exactement \*\*(\d+)\*\*", section)
    assert count, section
    return int(count.group(1)), section


@pytest.mark.parametrize("claim", ["2 ⋅ 3 = 3", "12 ÷ 4 = 3, reste 0,5", "1 ≈ 200", "8 km = 8 m"])
def test_worked_step_export_has_honest_per_lesson_coverage(pilot_copy, tmp_path, claim):
    out = tmp_path.resolve() / "review"
    assert main(review_args(pilot_copy, out, "--write")) == 0
    before, _ = sheet_coverage(out)

    def add_worked_step(blocks):
        example = next(b for b in blocks if b["type"] == "example")
        example["steps"].append(claim)

    for locale in ("fr", "ht"):
        edit_json(pilot_copy, f"{L1}/blocks.{locale}.json", add_worked_step)
    status = main(review_args(pilot_copy, out, "--write"))
    if status == 0:
        after, coverage = sheet_coverage(out)
        marked = [line for line in coverage.splitlines() if claim in line]
        assert after == before and all(any(f"{loc}/blocs" in line for line in marked) for loc in ("fr", "ht")), (claim, before, after, marked)
    else:
        assert status == 2


@pytest.mark.parametrize("mode", ["--check", "--write"])
@pytest.mark.parametrize("bad_id", [[], {}], ids=["array", "object"])
def test_mistyped_choice_identifier_returns_controlled_error(pilot_copy, tmp_path, mode, bad_id):
    def damage(qs):
        qs[0]["response_spec"]["choices"][0]["id"] = bad_id

    edit_json(pilot_copy, f"{L1}/questions.ht.json", damage)
    out = tmp_path.resolve() / "review"
    assert main(review_args(pilot_copy, out, mode)) == 2
    assert not out.exists()


@pytest.mark.parametrize("field", ["explanation", "answer_key"])
def test_missing_question_field_is_controlled(pilot_copy, tmp_path, field):
    edit_json(pilot_copy, f"{L1}/questions.fr.json", lambda qs: qs[0].pop(field))
    assert main(review_args(pilot_copy, tmp_path.resolve() / "review", "--write")) == 2


def test_whole_french_file_in_creole_slot_is_an_error(pilot_copy, capsys):
    lesson = pilot_copy / L1
    (lesson / "blocks.ht.json").write_bytes((lesson / "blocks.fr.json").read_bytes())
    assert main(["validate", "--forbid-approvals", "--repo-root", str(REPO), "--root", str(pilot_copy)]) != 0
    assert "translation_duplicate" in capsys.readouterr().out


def test_review_directory_link_rejected_for_both_modes(pilot_copy, tmp_path):
    destination = tmp_path.resolve() / "owned"
    destination.mkdir()
    link = tmp_path.resolve() / "alias"
    link.symlink_to(destination, target_is_directory=True)
    for mode in ("--write", "--check"):
        assert main(review_args(pilot_copy, link / "out", mode)) != 0
        assert not list(destination.iterdir())
