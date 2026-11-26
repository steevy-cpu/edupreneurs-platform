"""Corrections after independent QA #44: whole-claim boundaries, Euclidean division, coverage, controlled export.

Everything here runs on disposable copies of the pilot (`pilot_copy`) or on plain strings. The independent QA files
(`test_independent_verification_41.py`, `test_unit_notation_gate.py`) are kept byte-identical beside this one.
"""

import json

import pytest
from content_pilot.checks import _scan_math, math_coverage
from content_pilot.cli import main
from content_pilot.mathcheck import MAX_STATEMENTS, analyze, statements

from .conftest import L1, PILOT, REPO, edit_json


def holds(text):
    found, problems = statements(text)
    return [s.holds for s in found], problems


# --------------------------------------------------------------------------- 1. whole-claim boundaries
@pytest.mark.parametrize(
    "claim",
    [
        "1/2 = 2",
        "1/2 = 1/2",  # true, but unsupported: never "verified"
        "1,5 = 5",
        "1.5 = 5",
        "12 480,5 = 5",
        "3^2 = 2",
        "-4 = 4",
        "–4 = 4",  # en dash used as a minus
        "5 - 3 = 3",  # ASCII minus between numbers
        "3 x 4 = 4",
        "3 X 4 = 4",
        "2 * 3 = 3",
        "½ = 2",
        "50 % = 5",
        "√9 = 3",
        "3² = 2",
        "2·3 = 3",
        "2x = 6",
        "x2 = 2",
        "(1/2) + 1 = 1",
    ],
)
def test_unsupported_notation_is_reported_never_a_true_suffix(claim):
    verdicts, problems = holds(f"Vérifie : {claim}.")
    assert problems, claim
    assert not any(verdicts), (claim, verdicts)  # no isolated suffix is ever judged


@pytest.mark.parametrize("claim", ["1/2 = 2", "1,5 = 5", "3^2 = 2", "-4 = 4"])
def test_checks_turn_unsupported_notation_into_findings(claim):
    findings = _scan_math(f"Vérifie : {claim}", "x")
    assert [f.code for f in findings] == ["math_unparsed"]


@pytest.mark.parametrize(
    "text",
    [
        "Les nombres 1, 2, 3 et 4.",  # a list, no relation
        "vingt-deux et trente-trois",
        "La fraction 1/2 se lit un demi.",  # no relation: no claim to verify
        "- 3 + 4 = 7",  # a list bullet, then a plain true statement
        "Calcule : 3 + 4 = 7.",
        "3 + 4 × 2 = 11",
        "(3 + 4) × 2 = 14",
        "1 000 + 2 = 1 002 = 1 002",
        "5 > 3 > 1",
        "Page 3-5",
        "Phrase. 4 + 4 = 8. Autre phrase.",
    ],
)
def test_legitimate_text_is_not_flagged(text):
    verdicts, problems = holds(text)
    assert not problems, (text, problems)
    assert all(verdicts)


def test_supported_forms_keep_their_meaning():
    assert holds("2 + 3 × 4 = 14")[0] == [True]
    assert holds("2 + 3 × 4 = 20")[0] == [False]
    assert holds("(2 + 3) × 4 = 20")[0] == [True]
    assert holds("1 < 2 ≤ 2 ≠ 3")[0] == [True]
    assert holds("1 < 2 ≤ 1")[0] == [False]
    assert holds("12 480 ÷ 12 = 1 040")[0] == [True]


# --------------------------------------------------------------------------- 2. Euclidean division
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12 ÷ 4 = 3, reste 0", True),
        ("12 ÷ 4 = 3, reste 1", False),  # the ordinary equality is true; the remainder is wrong
        ("12 ÷ 4 = 3, rès 0", True),
        ("12 ÷ 4 = 3, rès 1", False),
        ("12 ÷ 4 = 3 reste 2", False),
        ("7 ÷ 3 = 2, reste 1", True),
        ("7 ÷ 3 = 2, rès 1", True),
        ("7 ÷ 3 = 2, reste 2", False),
        ("7 ÷ 3 = 1, reste 4", False),  # 7 = 3 × 1 + 4, but r ≥ b
        ("7 ÷ 3 = 3, reste 0", False),
        ("0 ÷ 5 = 0, reste 0", True),
        ("3 ÷ 5 = 0, reste 3", True),
        ("1 000 ÷ 7 = 142, reste 6", True),
        ("1 000 ÷ 7 = 142, reste 7", False),
        ("(6 + 6) ÷ (2 + 2) = 3, reste 0", True),
        ("(6 + 7) ÷ (2 + 2) = 3, reste 1", True),
        ("(6 + 7) ÷ (2 + 2) = 3, reste 0", False),
        ("7 ÷ 2 = 3, RESTE 1", True),
    ],
)
def test_euclidean_division_is_judged_as_a_whole(text, expected):
    verdicts, problems = holds(text)
    assert not problems, problems
    assert verdicts == [expected], text


@pytest.mark.parametrize(
    "text",
    [
        "12 = 3, reste 1",  # no division
        "1 + 8 ÷ 4 = 3, reste 1",  # more than one top-level operation
        "12 ÷ 4 ÷ 2 = 1, reste 0",
        "12 ÷ 4 = 1 < 3, reste 0",
        "÷ 4 = 3, reste 1",
    ],
)
def test_unsupported_remainder_shapes_are_reported(text):
    verdicts, problems = holds(text)
    assert problems and not any(verdicts), (text, verdicts, problems)


def test_euclid_needs_whole_numbers_and_positive_divisor():
    assert holds("(1 ÷ 2) ÷ 1 = 0, reste 0")[0] == [False]  # a is not a whole number
    assert holds("(2 − 5) ÷ 3 = 0, reste 0")[0] == [False]  # not a division of naturals
    assert holds("12 ÷ 0 = 3, reste 0")[0] == [False]  # a zero divisor is never a valid Euclidean division
    assert holds("12 ÷ (3 − 3) = 3, reste 0")[0] == [False]


@pytest.mark.parametrize(("locale", "intro", "word"), [("fr", "Vérifie le calcul.", "reste"), ("ht", "Tcheke kalkil la.", "rès")])
def test_strict_validation_rejects_wrong_remainder_in_both_languages(pilot_copy, locale, intro, word):
    edit_json(
        pilot_copy,
        f"{L1}/blocks.{locale}.json",
        lambda blocks: blocks[1].update(text=f"{intro} 12 ÷ 4 = 3, {word} 1"),
    )
    assert main(["validate", "--forbid-approvals", "--root", str(pilot_copy), "--repo-root", str(REPO)]) != 0


@pytest.mark.parametrize(("locale", "intro", "word"), [("fr", "Vérifie le calcul.", "reste"), ("ht", "Tcheke kalkil la.", "rès")])
def test_strict_validation_accepts_correct_remainders_in_both_languages(pilot_copy, locale, intro, word):
    for expr in ("12 ÷ 4 = 3, {w} 0", "13 ÷ 4 = 3, {w} 1"):
        edit_json(
            pilot_copy,
            f"{L1}/blocks.{locale}.json",
            lambda blocks, expr=expr: blocks[1].update(text=f"{intro} {expr.format(w=word)}"),
        )
        # The other locale still has its original text, so compare only the math findings on this one.
        findings = _scan_math(f"{intro} {expr.format(w=word)}", "x")
        assert findings == []


# --------------------------------------------------------------------------- 3. never silently skip
@pytest.mark.parametrize(
    "text",
    ["2 + 2 = 5 +", "+ 2 = 5", "2 + = 5", "(2 + 3 = 5", "2 + 3) = 5", "2 × × 3 = 6", "5 = 2 +"],
)
def test_incomplete_or_malformed_claims_are_problems(text):
    verdicts, problems = holds(text)
    assert problems and not any(verdicts), (text, verdicts, problems)


def test_fragments_without_both_operands_are_skipped_and_recorded():
    result = analyze("Donc = 1 000 en tout.")
    assert not result.problems and not result.statements
    assert [s.kind for s in result.skipped] == ["fragment"]


def test_statement_limit_is_a_finding_not_a_silent_stop():
    ok = "; ".join(["1=1"] * MAX_STATEMENTS)
    assert not analyze(ok).problems
    over = "; ".join(["1=1"] * MAX_STATEMENTS + ["1=2"])
    result = analyze(over)
    assert result.limit_reached and result.problems
    assert {f.code for f in _scan_math(over, "x")} == {"math_unparsed", "math_limit"}


def test_false_statement_before_the_limit_is_still_reported():
    text = "; ".join(["1=2"] + ["1=1"] * (MAX_STATEMENTS + 5))
    codes = {f.code for f in _scan_math(text, "x")}
    assert {"math_false", "math_limit"} <= codes


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("8 km = 8 000 m", "unit"),
        ("1 m = 100 cm, donc 7 m = 7 × 100 = 700 cm.", "unit"),
        ("3 480 = 3 milliers + 4 centaines", "named_unit"),
        ("Dividende = diviseur × quotient + reste", "named_unit"),
        ("Le signe < s'ouvre vers le plus grand", "fragment"),
    ],
)
def test_deliberate_skips_are_recorded(text, kind):
    result = analyze(text)
    assert not result.problems, result.problems
    assert kind in {s.kind for s in result.skipped}


def test_coverage_counts_what_was_checked_and_what_was_not():
    checked, skipped = math_coverage([{"key": "a", "type": "paragraph", "text": "2 + 2 = 4. 8 km = 8 000 m."}], "b")
    assert checked == 1
    assert skipped and all(len(item) == 3 for item in skipped)


def _guide_and_sheet(root, tmp_path):
    out = tmp_path.resolve() / "review"
    code = main(["review-pack", "--write", "--root", str(root), "--repo-root", str(REPO), "--review-dir", str(out)])
    assert code == 0
    return (out / "00-guide-de-relecture.md").read_text(), next(out.glob("lesson-01*.md")).read_text()


def test_export_never_claims_every_calculation_was_checked(pilot_copy, tmp_path):
    guide, sheet = _guide_and_sheet(pilot_copy, tmp_path)
    assert "chaque calcul des exemples" not in guide
    assert "n'interprète pas" in guide and "Calculs" in sheet


def test_skipped_unit_step_is_listed_on_the_sheet(pilot_copy, tmp_path):
    for locale in ("fr", "ht"):
        edit_json(
            pilot_copy,
            f"{L1}/blocks.{locale}.json",
            lambda blocks: next(b for b in blocks if b["type"] == "example")["steps"].append("8 km = 8 m"),
        )
    guide, sheet = _guide_and_sheet(pilot_copy, tmp_path)
    assert "8 km = 8 m" in sheet and "vérifiez-les à la main" in sheet
    assert "chaque calcul des exemples" not in guide


def test_unsupported_worked_step_blocks_the_export(pilot_copy, tmp_path):
    for locale in ("fr", "ht"):
        edit_json(
            pilot_copy,
            f"{L1}/blocks.{locale}.json",
            lambda blocks: next(b for b in blocks if b["type"] == "example")["steps"].append("1/2 = 2"),
        )
    out = tmp_path.resolve() / "review"
    assert main(["review-pack", "--write", "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)]) == 2
    assert not out.exists()


# --------------------------------------------------------------------------- 4. controlled export on malformed questions
MALFORMED = [
    ("explanation", None),
    ("explanation", []),
    ("explanation", "texte"),
    ("explanation", {"text": None}),
    ("prompt", None),
    ("prompt", {"text": 5}),
    ("answer_key", None),
    ("answer_key", {"correct_choice_id": None}),
    ("response_spec", None),
    ("response_spec", {"mode": "single", "choices": None}),
    ("response_spec", {"mode": "single", "choices": [None, 3]}),
]


@pytest.mark.parametrize("mode", ["--check", "--write"])
@pytest.mark.parametrize(("field", "value"), MALFORMED, ids=[f"{f}={json.dumps(v)}" for f, v in MALFORMED])
def test_malformed_question_field_is_a_controlled_error(pilot_copy, tmp_path, capsys, mode, field, value):
    edit_json(pilot_copy, f"{L1}/questions.ht.json", lambda questions: questions[0].update({field: value}))
    out = tmp_path.resolve() / "review"
    code = main(["review-pack", mode, "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)])
    err = capsys.readouterr().err
    assert code == 2 and "Traceback" not in err
    assert "review_input_invalid" in err and "lire-ecrire" in err
    assert not out.exists()


def test_failed_export_does_not_touch_existing_review_files(pilot_copy, tmp_path):
    out = tmp_path.resolve() / "review"
    assert main(["review-pack", "--write", "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)]) == 0
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    edit_json(pilot_copy, f"{L1}/questions.fr.json", lambda questions: questions[0].update(explanation=None))
    assert main(["review-pack", "--write", "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)]) == 2
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def test_validation_reports_the_field_and_skips_semantic_passes(pilot_copy, capsys):
    edit_json(pilot_copy, f"{L1}/questions.ht.json", lambda questions: questions[0].update(explanation=None))
    assert main(["validate", "--root", str(pilot_copy), "--repo-root", str(REPO)]) != 0
    out = capsys.readouterr()
    text = out.out + out.err
    assert "question_schema" in text and "explanation" in text and "Traceback" not in text
    assert "verification_skipped" in text


# --------------------------------------------------------------------------- nothing about the content changed
def test_every_lesson_language_is_still_an_unreviewed_draft():
    pilot = json.loads((PILOT / "pilot.json").read_text(encoding="utf-8"))
    records = [lesson["review"][loc] for lesson in pilot["lessons"] for loc in ("fr", "ht")]
    assert len(records) == 12
    assert all(r["status"] == "draft_unreviewed" and r["approvals"] == [] for r in records)
