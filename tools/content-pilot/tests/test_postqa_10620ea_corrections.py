"""Corrections after the independent retest of 10620ea: whitelisted boundaries, complete remainders, coverage, IDs.

Strings and disposable pilot copies only. The independent file `test_postqa44_independent.py` is kept unchanged.
"""

import pytest
from content_pilot.checks import _scan_math
from content_pilot.cli import main
from content_pilot.mathcheck import analyze

from .conftest import L1, REPO, edit_json

NB = " "


def verdicts(text):
    a = analyze(text)
    return [s.holds for s in a.statements], a.problems, [s.kind for s in a.skipped]


# ------------------------------------------------------------------ 1. no Unicode or alternate notation yields a suffix
@pytest.mark.parametrize(
    "claim",
    [
        "2 ⋅ 3 = 3",  # dot operator
        "2 ∙ 4 = 4",  # bullet operator
        "2 ∗ 3 = 3",  # asterisk operator
        "6 ∕ 3 = 3",  # division slash
        "6 ⁄ 3 = 3",  # fraction slash
        "1 ＋ 2 = 2",  # fullwidth plus
        "5 － 3 = 3",  # fullwidth hyphen-minus
        "—4 = 4",  # em dash
        "‒4 = 4",  # figure dash
        "5 ‐ 3 = 3",  # Unicode hyphen
        "1 234 = 234",  # narrow no-break space
        "1 234 = 234",  # thin space
        "1 234 = 234",  # figure space
        "1​234 = 234",  # zero-width space
        "1⁠234 = 234",  # word joiner
        "1﻿234 = 234",  # zero-width no-break space
        "１２ = 2",  # fullwidth digits
        "١٢ = 2",  # Arabic-Indic digits
        "2³ = 3",  # superscript
        "⅓ = 3",  # vulgar fraction
        "√16 = 16",
        "±4 = 4",
        "90° = 90",
        "5 € = 5",
        "$5 = 5",
        "1 ＝ 1",  # fullwidth equals between equal numbers: still not accepted
        "2 ＜ 1",
    ],
)
def test_alternate_notation_is_never_a_verified_statement(claim):
    holds, problems, skipped = verdicts(f"Vérifie : {claim}.")
    assert not any(holds), (claim, holds)
    assert problems or skipped, claim  # never silent


@pytest.mark.parametrize("claim", ["2 ⋅ 3 = 3", "1 234 = 234", "1 ＋ 2 = 2", "—4 = 4", "１２ = 2", "1​234 = 234"])
def test_alternate_notation_fails_validation(claim):
    assert {f.code for f in _scan_math(f"Vérifie : {claim}", "x")} == {"math_unparsed"}


@pytest.mark.parametrize(
    "text",
    [
        "Calcule : 3 + 4 = 7.",
        "« 3 + 4 = 7 »",
        "(3 + 4 = 7)",
        "Donc 3 + 4 = 7, puis 7 − 2 = 5 ; enfin 5 × 2 = 10 !",
        "Est-ce que 3 + 4 = 7 ?",
        "3 + 4 = 7 → 7 est impair",
        "(voir aussi 3 + 4 = 7)",
        "Le résultat (3 + 4 = 7) est impair",
        f"12{NB}480 ÷ 12 = 1{NB}040",
        "- 3 + 4 = 7\n- 5 − 2 = 3",
        "L'égalité 2 × 3 = 6 est vraie",
    ],
)
def test_ordinary_punctuation_and_prose_are_valid_boundaries(text):
    holds, problems, _ = verdicts(text)
    assert not problems and holds and all(holds), (text, holds, problems)


# ------------------------------------------------------------------ 2. remainders are complete or reported
@pytest.mark.parametrize(
    "claim",
    [
        "12 ÷ 4 = 3, reste 0,5",
        "12 ÷ 4 = 3, reste 0.5",
        "7 ÷ 3 = 2, rès 1.5",
        "7 ÷ 3 = 2, rès 1,0",
        "12 ÷ 4 = 3, rès -1",
        "12 ÷ 4 = 3, reste −1",
        "12 ÷ 4 = 3, reste",
        "12 ÷ 4 = 3, reste.",
        "12 ÷ 4 = 3, reste 0 + 1",
        "12 ÷ 4 = 3, reste 0 × 5",
        "12 ÷ 4 = 3, reste (0)",
        "12 ÷ 4 = 3, reste 0x",
        "12 ÷ 4 = 3, reste 1/2",
        "12 ÷ 4 = 3, reste zéro",
        "12 ÷ 4 = 3, RESTE 0,5",
        "12 ÷ 4 = 3 rès 0 1",
    ],
)
def test_malformed_remainder_is_reported_and_the_plain_equality_is_not_used(claim):
    holds, problems, _ = verdicts(claim)
    assert problems, claim
    assert not any(holds), (claim, holds)


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("12 ÷ 4 = 3, reste 0.", True),
        ("12 ÷ 4 = 3, reste 0", True),
        ("12 ÷ 4 = 3, reste 0 ; puis on continue", True),
        ("13 ÷ 4 = 3, reste 1, donc 13 n'est pas un multiple de 4.", True),
        ("13 ÷ 4 = 3, rès 1 paske 13 = 4 × 3 + 1.", True),
        ("(13 ÷ 4 = 3, reste 1)", True),
        ("13 ÷ 4 = 3, reste 1 !", True),
        (f"1{NB}000 ÷ 7 = 142, reste 6.", True),
        ("13 ÷ 4 = 3, reste 2.", False),
        ("12 ÷ 4 = 3, reste 1.", False),
    ],
)
def test_complete_remainders_keep_working(claim, expected):
    holds, problems, _ = verdicts(claim)
    assert not problems, (claim, problems)
    assert holds[0] is expected


@pytest.mark.parametrize("claim", ["(2 + 3 = 5", "2 + 3) = 5", "((2 + 3 = 5)", "(2 + 3 = 5))"])
def test_unmatched_parentheses_stay_malformed(claim):
    holds, problems, _ = verdicts(claim)
    assert problems and not any(holds), (claim, holds)


def test_prose_dash_next_to_a_number_is_reported_not_guessed():
    # Conservative by design: a dash touching a number may be a minus, so the statement is reported, never judged.
    holds, problems, _ = verdicts("Le total — par exemple 3 + 4 = 7 — est petit.")
    assert problems and not any(holds)


def test_word_starting_with_the_keyword_is_not_a_remainder():
    holds, problems, _ = verdicts("12 ÷ 4 = 3, restera à vérifier")
    assert holds == [True] and not problems


# ------------------------------------------------------------------ 3. unsupported relations reach the reviewer
@pytest.mark.parametrize("claim", ["1 ≈ 200", "3 ≃ 4", "2 ≡ 5", "1 ∼ 9", "7 ≅ 8", "1 ≪ 2", "3 ∝ 4"])
def test_unsupported_relation_is_listed_for_manual_review(claim):
    a = analyze(f"On note {claim} ici.")
    assert not a.statements and not a.problems
    assert [s.kind for s in a.skipped] == ["unsupported_relation"]
    assert claim in a.skipped[0].text


def test_unsupported_relation_appears_on_both_language_sheets(pilot_copy, tmp_path):
    for locale in ("fr", "ht"):
        edit_json(
            pilot_copy,
            f"{L1}/blocks.{locale}.json",
            lambda blocks: next(b for b in blocks if b["type"] == "example")["steps"].append("1 ≈ 200"),
        )
    out = tmp_path.resolve() / "review"
    assert main(["review-pack", "--write", "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)]) == 0
    sheet = next(out.glob("lesson-01*.md")).read_text()
    lines = [line for line in sheet.splitlines() if "1 ≈ 200" in line and "que l'outil ne lit pas" in line]
    assert any("fr/blocs" in line for line in lines) and any("ht/blocs" in line for line in lines), lines


def test_false_step_in_alternate_notation_blocks_the_export(pilot_copy, tmp_path):
    for locale in ("fr", "ht"):
        edit_json(
            pilot_copy,
            f"{L1}/blocks.{locale}.json",
            lambda blocks: next(b for b in blocks if b["type"] == "example")["steps"].append("2 ⋅ 3 = 3"),
        )
    out = tmp_path.resolve() / "review"
    assert main(["review-pack", "--write", "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)]) == 2
    assert not out.exists()


# ------------------------------------------------------------------ 4. malformed identifiers fail cleanly
BAD = [[], {}, 5, 1.5, True, None, ["a"], {"id": "a"}]


@pytest.mark.parametrize("mode", ["--check", "--write"])
@pytest.mark.parametrize("bad", BAD, ids=[repr(b) for b in BAD])
def test_mistyped_choice_id_is_a_controlled_field_error(pilot_copy, tmp_path, capsys, mode, bad):
    edit_json(pilot_copy, f"{L1}/questions.ht.json", lambda qs: qs[0]["response_spec"]["choices"][0].update(id=bad))
    out = tmp_path.resolve() / "review"
    assert main(["review-pack", mode, "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err and "internal_error" not in err  # reported by validation, not by the last-resort guard
    assert "question_schema" in err and "choices" in err
    assert not out.exists()


@pytest.mark.parametrize("mode", ["--check", "--write"])
@pytest.mark.parametrize("bad", BAD, ids=[repr(b) for b in BAD])
def test_mistyped_correct_choice_id_is_a_controlled_field_error(pilot_copy, tmp_path, capsys, mode, bad):
    edit_json(pilot_copy, f"{L1}/questions.fr.json", lambda qs: qs[1]["answer_key"].update(correct_choice_id=bad))
    out = tmp_path.resolve() / "review"
    assert main(["review-pack", mode, "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err and "internal_error" not in err
    assert not out.exists()


@pytest.mark.parametrize("bad", BAD, ids=[repr(b) for b in BAD])
def test_mistyped_ids_do_not_crash_validation(pilot_copy, capsys, bad):
    edit_json(pilot_copy, f"{L1}/questions.ht.json", lambda qs: qs[0]["response_spec"]["choices"][0].update(id=bad))
    assert main(["validate", "--root", str(pilot_copy), "--repo-root", str(REPO)]) != 0
    out = capsys.readouterr()
    assert "Traceback" not in out.out + out.err


def test_failed_export_leaves_existing_review_files_untouched(pilot_copy, tmp_path):
    out = tmp_path.resolve() / "review"
    args = ["review-pack", "--write", "--root", str(pilot_copy), "--repo-root", str(REPO), "--review-dir", str(out)]
    assert main(args) == 0
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    edit_json(pilot_copy, f"{L1}/questions.ht.json", lambda qs: qs[0]["response_spec"]["choices"][0].update(id=[]))
    assert main(args) == 2
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def test_last_resort_guard_reports_instead_of_crashing(monkeypatch, capsys):
    import content_pilot.cli as cli

    def boom(argv):
        raise TypeError("unhashable type: 'list'")

    monkeypatch.setattr(cli, "_main", boom)
    assert cli.main(["validate"]) == 2
    err = capsys.readouterr().err
    assert "internal_error" in err and "Traceback" not in err
