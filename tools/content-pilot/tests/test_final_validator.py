"""Tests for the final validator corrections: exact arithmetic on displayed statements, bilingual duplication,
controlled review-export failure, evaluator bounds and handle-based filesystem access.

Only private temporary copies are edited. The independent tests of PR #38 are in `test_final_retest.py` (unchanged).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
from content_pilot import cli
from content_pilot.checks import validate
from content_pilot.mathcheck import MAX_DIGITS, MathError, statements, value_of
from content_pilot.model import DEFAULT_LIMITS, Limits
from content_pilot.review import build_review_pack
from content_pilot.safe_eval import EvalLimits, UnsafeExpression, safe_eval
from content_pilot.safefs import ContentFileError, open_dir_strict, read_confined, read_in_dir, scan_tree, write_text_atomic

from .conftest import L1, L2, L3, PILOT, REPO, edit_json

NB = " "


def run(root: Path, limits: Limits | None = None):
    return validate(root, repo_root=REPO, forbid_approvals=True, limits=limits)


def codes(root: Path, limits: Limits | None = None) -> set[str]:
    return {f.code for f in run(root, limits) if f.severity == "error"}


# ================================================================ the exact-arithmetic parser
@pytest.mark.parametrize(
    "text",
    [
        "36 × 10 = 360",
        "12 = 1 × 12 = 2 × 6 = 3 × 4",
        "(1 + 3 + 5) = 9",
        "2 + 3 × 4 = 14",
        "(2 + 3) × 4 = 20",
        "20 ÷ 4 = 5",
        "7 ≠ 8",
        f"6{NB}054 < 6{NB}540",
        "5 ≤ 5",
        "6 ≥ 5",
        "0 × 5 = 0",
        "17 = 5 × 3 + 2",
        f"4{NB}500 ÷ 10 = 450",
        "(10 − 4) ÷ 3 = 2",
        "10 ÷ 4 + 10 ÷ 4 = 5",  # exact rationals: 5/2 + 5/2
    ],
)
def test_true_statements_are_accepted(text):
    found, problems = statements(text)
    assert problems == [] and found and all(s.holds for s in found), (text, found)


@pytest.mark.parametrize(
    "text",
    [
        "36 × 10 = 3600",
        f"4{NB}501 ÷ 10 = 450",
        "10 ÷ 4 = 2",
        "10 ÷ 4 = 3",
        "2 + 3 × 4 = 20",
        f"6{NB}054 > 6{NB}540",
        "7 = 7 = 8",
        "3 − 5 = 2",
        "1 + 1 = 3",
        "9 ÷ 3 = 2, reste 3",  # remainder not smaller than the divisor
        "10 ÷ 3 = 3, reste 2",
        "10 ÷ 3 = 3, rès 3",
    ],
)
def test_false_statements_are_rejected(text):
    found, problems = statements(text)
    assert problems == [] and found and not all(s.holds for s in found), (text, found)


@pytest.mark.parametrize("text", ["10 ÷ 3 = 3, reste 1", "10 ÷ 3 = 3, rès 1", "47 ÷ 6 = 7, reste 5", "17 ÷ 5 = 3 reste 2"])
def test_euclidean_division_with_a_remainder_is_a_distinct_supported_form(text):
    found, problems = statements(text)
    assert problems == [] and [s.holds for s in found] == [True]


def test_euclidean_form_does_not_excuse_other_shapes():
    for text in ("10 ÷ 3 + 1 = 4, reste 0", "10 × 3 = 29, reste 1", "10 ÷ 3 ≤ 3, reste 1"):
        found, problems = statements(text)
        assert problems or not all(s.holds for s in found), text  # reported, or judged false: never judged true


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("5 × = 3", "ends where a number"),
        ("1 ÷ 0 = 1", "division by zero"),
        ("(1 + 2 = 3", "closing parenthesis"),
        ("1 + 2) = 3", "trailing"),
        ("1 2 = 3", "trailing"),
        ("(" * 14 + "1" + ")" * 14 + " = 1", "nested"),
        ("9" * (MAX_DIGITS + 1) + " + 1 = 2", "digits"),
        (" + ".join(["1"] * 60) + " = 60", "tokens"),
        ("1 + + 2 = 3", "unexpected"),
    ],
)
def test_malformed_arithmetic_is_reported_not_silently_accepted(text, fragment):
    found, problems = statements(text)
    assert [s for s in found if s.holds] == [] and any(fragment in p for p in problems), (text, problems)


def test_a_bare_malformed_expression_is_reported_too():
    _, problems = statements("Calcule : 5 × + 3")
    assert problems


@pytest.mark.parametrize(
    "text",
    [
        f"8 km = 8 × 1{NB}000 m = 8{NB}000 m",  # unit conversion is not an equality of numbers
        f"3{NB}480 = 3 milliers + 4 centaines + 8 dizaines",  # decomposition into named units
        f"1 km = 1{NB}000 m",
        "= 1 000",  # fragment next to prose
        "Il reste 8 quand on divise 24 par 8",  # no operator at all
    ],
)
def test_statements_next_to_units_or_words_are_not_interpreted_by_design(text):
    assert statements(text) == ([], [])


def test_whole_numbers_are_tokens_not_substrings():
    found, _ = statements("On a 36 × 10 = 360 donc 36 × 100 = 3600.")
    assert [s.text for s in found] == ["36 × 10 = 360", "36 × 100 = 3600"]
    found, _ = statements("36 × 10 = 3600")
    assert [s.text for s in found] == ["36 × 10 = 3600"] and not found[0].holds


def test_operand_order_and_operator_meaning_are_preserved():
    assert statements("702 − 345 = 357")[0][0].holds
    assert not statements("345 − 702 = 357")[0][0].holds
    assert statements("8 ÷ 2 = 4")[0][0].holds and not statements("2 ÷ 8 = 4")[0][0].holds
    assert not statements("2 + 3 × 4 = 20")[0][0].holds


def test_value_of_is_exact_not_floating_point():
    assert value_of(f"6{NB}200 ÷ 10") == 620
    assert value_of("10 ÷ 4") == Fraction(5, 2)
    assert value_of("1 ÷ 3 + 1 ÷ 3 + 1 ÷ 3") == 1  # floats would give 0.9999999999999999
    with pytest.raises(MathError):
        value_of("1 ÷ 0")
    with pytest.raises(MathError):
        value_of("1 +")


def test_the_number_of_statements_per_text_is_bounded():
    text = " ; ".join("1 + 1 = 2" for _ in range(2000))
    found, problems = statements(text)
    assert len(found) <= 400
    assert any("NOT checked" in p for p in problems)  # reaching the cap is reported, not silent


# ================================================================ displayed mathematics is verified in the lessons
def set_step(root: Path, example: str, index: int, text: str, locales=("fr", "ht"), lesson: str = L2) -> None:
    def edit(blocks):
        next(b for b in blocks if b["key"] == example)["steps"][index] = text

    for loc in locales:
        edit_json(root, f"{lesson}/blocks.{loc}.json", edit)


def test_a_false_displayed_equality_in_a_block_is_caught_in_either_language_alone(pilot_copy):
    for loc in ("fr", "ht"):
        set_step(pilot_copy, "exemple-addition", 0, "Unités : 8 + 5 = 12.", locales=(loc,))
        assert "math_false" in codes(pilot_copy), loc
        set_step(pilot_copy, "exemple-addition", 0, "Unités : 8 + 5 = 13. On écrit 3 et on retient 1.", locales=(loc,))


def test_a_false_equality_in_an_explanation_or_prompt_is_caught(pilot_copy):
    edit_json(pilot_copy, f"{L2}/questions.fr.json", lambda q: q[0]["explanation"].update(text="Unités : 6 + 8 = 15. Résultat : 834."))
    assert "math_false" in codes(pilot_copy)


def test_the_proof_record_cannot_excuse_a_false_displayed_statement(pilot_copy):
    set_step(pilot_copy, "exemple-addition", 3, "348 + 275 = 632")
    edit_json(
        pilot_copy, f"{L2}/verification.json", lambda v: v["examples"][0]["checks"][3].update(equals=632, expr="348 + 275 + 9", must_appear="348+275=632")
    )
    assert "math_false" in codes(pilot_copy)


def test_legitimate_euclidean_division_passes_and_a_wrong_remainder_fails(pilot_copy):
    set_step(
        pilot_copy, "exemple-division-1", 2, "17 = 5 × 3 + 2 : le quotient est 3 et le reste est 2. Aussi 17 ÷ 5 = 3, reste 2.", locales=("fr",), lesson=L3
    )
    set_step(pilot_copy, "exemple-division-1", 2, "17 = 5 × 3 + 2: kosyan an se 3 epi rès la se 2. Tou 17 ÷ 5 = 3, rès 2.", locales=("ht",), lesson=L3)
    assert not codes(pilot_copy)
    set_step(
        pilot_copy, "exemple-division-1", 2, "17 = 5 × 3 + 2 : le quotient est 3 et le reste est 2. Aussi 17 ÷ 5 = 3, reste 3.", locales=("fr",), lesson=L3
    )
    set_step(pilot_copy, "exemple-division-1", 2, "17 = 5 × 3 + 2: kosyan an se 3 epi rès la se 2. Tou 17 ÷ 5 = 3, rès 3.", locales=("ht",), lesson=L3)
    assert "math_false" in codes(pilot_copy)


def test_a_malformed_displayed_statement_is_reported(pilot_copy):
    set_step(pilot_copy, "exemple-addition", 0, "Unités : 8 + = 13.")
    assert "math_unparsed" in codes(pilot_copy)


def test_a_plain_choice_must_say_what_its_proof_says(pilot_copy):
    # the displayed claim becomes true while its proof (and key) still say it is false
    def fix(questions):
        wrong = next(c for c in questions[4]["response_spec"]["choices"] if c["id"] == "b")
        wrong["text"] = "280 + 260 = 540"

    for loc in ("fr", "ht"):
        edit_json(pilot_copy, f"{L2}/questions.{loc}.json", fix)
    assert codes(pilot_copy) & {"choice_binding", "duplicate_choice_text"}


@pytest.mark.parametrize("shown", ["136×10=360", "36×10=36", "6×10=360"])
def test_must_appear_must_match_complete_numbers(pilot_copy, shown):
    edit_json(
        pilot_copy,
        "lessons/04-multiplier-diviser-10-100-1000/verification.json",
        lambda v: next(e for e in v["examples"] if e["block"] == "exemple-multiplier")["checks"][0].update(must_appear=shown),
    )
    assert "example_not_shown" in codes(pilot_copy)


def test_exact_division_checks_need_a_zero_remainder_and_a_simple_shape(pilot_copy):
    L4 = "lessons/04-multiplier-diviser-10-100-1000"
    for expr in ("4501 // 10", "4500 // 0", "(4500) // 10", "4500 // 10 // 1"):
        edit_json(
            pilot_copy,
            f"{L4}/verification.json",
            lambda v, expr=expr: next(e for e in v["examples"] if e["block"] == "exemple-diviser")["checks"][0].update(expr=expr, equals=450),
        )
        assert "example_not_bound" in codes(pilot_copy), expr


def test_a_prompt_operation_that_is_not_an_exact_division_is_refused(pilot_copy):
    L4 = "lessons/04-multiplier-diviser-10-100-1000"
    for loc in ("fr", "ht"):
        edit_json(pilot_copy, f"{L4}/questions.{loc}.json", lambda q: q[1]["prompt"].update(text=q[1]["prompt"]["text"].replace(f"6{NB}200", f"6{NB}201")))
    edit_json(pilot_copy, f"{L4}/verification.json", lambda v: v["questions"]["divise-10"].update(prompt_math="6 201 ÷ 10", prompt_numbers=[6201, 10]))
    assert "prompt_binding" in codes(pilot_copy)


def test_every_displayed_statement_of_the_delivered_pilot_is_true_and_interpretable():
    total = 0
    for path in PILOT.rglob("*.json"):
        if path.name in ("pilot.json", "verification.json") or path.name.startswith("manifest"):
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        texts = []

        def walk(node, key=""):
            if isinstance(node, str) and key not in ("key", "type", "tone", "id", "correct_choice_id", "question_key"):
                texts.append(node)
            elif isinstance(node, dict):
                for k, v in node.items():
                    walk(v, k)
            elif isinstance(node, list):
                for v in node:
                    walk(v, key)

        walk(doc)
        for t in texts:
            found, problems = statements(t)
            total += len(found)
            if "questions" in path.name and "choices" not in t:  # distractor choices may be false on purpose
                assert problems == [], (path.name, t, problems)
    assert total > 100  # the scan really looked at the lessons


# ================================================================ bilingual duplication diagnostic
def test_one_copied_prose_field_is_flagged(pilot_copy):
    def copy_fr_paragraph(ht_blocks):
        fr = json.loads((pilot_copy / L1 / "blocks.fr.json").read_text(encoding="utf-8"))
        target = next(b for b in ht_blocks if b["key"] == "intro")
        target["text"] = next(b for b in fr if b["key"] == "intro")["text"]

    edit_json(pilot_copy, f"{L1}/blocks.ht.json", copy_fr_paragraph)
    assert "translation_duplicate" in codes(pilot_copy)


def test_the_diagnostic_names_what_it_cannot_do(pilot_copy):
    import shutil

    shutil.copyfile(pilot_copy / L1 / "questions.fr.json", pilot_copy / L1 / "questions.ht.json")
    msg = next(f.message for f in run(pilot_copy) if f.code == "translation_duplicate")
    assert "native-speaker" in msg and "cannot" in msg


def test_shared_notation_numerals_and_short_labels_are_not_flagged(pilot_copy):
    def share(blocks):
        block = next(b for b in blocks if b["key"] == "exemple-addition")
        block["steps"][3] = "348 + 275 = 623"  # already identical in both languages
        for b in blocks:
            if b["type"] == "heading":
                b["text"] = b["text"]

    edit_json(pilot_copy, f"{L2}/blocks.ht.json", share)
    assert "translation_duplicate" not in codes(pilot_copy)


def test_the_delivered_pilot_has_no_wholesale_duplication():
    assert "translation_duplicate" not in {f.code for f in validate(PILOT, repo_root=REPO)}


def test_duplicate_prose_is_flagged_even_when_digits_differ_in_formatting(pilot_copy):
    def copy_all(ht_questions):
        fr = json.loads((pilot_copy / L2 / "questions.fr.json").read_text(encoding="utf-8"))
        for h, f in zip(ht_questions, fr, strict=True):
            h["explanation"]["text"] = f["explanation"]["text"].upper()  # case changes do not hide it

    edit_json(pilot_copy, f"{L2}/questions.ht.json", copy_all)
    assert "translation_duplicate" in codes(pilot_copy)


# ================================================================ controlled review export
def test_missing_answer_key_is_a_controlled_error_naming_lesson_question_and_field(pilot_copy):
    edit_json(pilot_copy, f"{L1}/questions.fr.json", lambda q: q[2].pop("answer_key"))
    with pytest.raises(ContentFileError) as caught:
        build_review_pack(pilot_copy)
    msg = str(caught.value)
    assert caught.value.code == "review_input_invalid"
    assert "lire-ecrire-comparer-entiers" in msg and "comparer-deux-nombres" in msg and "answer_key" in msg


@pytest.mark.parametrize("field", ["prompt", "response_spec", "explanation", "question_key"])
def test_other_missing_fields_never_reach_the_exporter_as_a_keyerror(pilot_copy, field):
    edit_json(pilot_copy, f"{L2}/questions.ht.json", lambda q: q[1].pop(field))
    with pytest.raises(ContentFileError):
        build_review_pack(pilot_copy)


def test_a_block_without_text_is_a_controlled_error_too(pilot_copy):
    edit_json(pilot_copy, f"{L2}/blocks.ht.json", lambda b: b[1].pop("text"))
    with pytest.raises(ContentFileError):
        build_review_pack(pilot_copy)


def test_review_write_with_invalid_content_writes_nothing_and_exits_nonzero(pilot_copy, tmp_path, capsys):
    edit_json(pilot_copy, f"{L1}/questions.fr.json", lambda q: q[0].pop("answer_key"))
    out = tmp_path / "review"
    for mode in ("--write", "--check"):
        assert cli.main(["review-pack", mode, "--root", str(pilot_copy), "--review-dir", str(out)]) == 2
    assert not out.exists()
    assert "answer_key" in capsys.readouterr().err


def test_review_pack_uses_the_same_validation_as_validate(pilot_copy):
    set_step(pilot_copy, "exemple-addition", 0, "Unités : 8 + 5 = 12.")
    assert "math_false" in codes(pilot_copy)
    with pytest.raises(ContentFileError, match="math_false"):
        build_review_pack(pilot_copy)


# ================================================================ evaluator bounds
def test_sum_and_other_aggregates_obey_the_integer_limit():
    tiny = EvalLimits(max_bits=3)
    for bad in ("sum([4, 4])", "sum([7, 7])", "max(8, 1)", "gcd(8, 8)", "abs(8)", "sum([1, 2, 3, 4])"):
        with pytest.raises(UnsafeExpression, match=r"bits|integer"):
            safe_eval(bad, tiny)
    assert safe_eval("sum([1, 2, 3])", tiny) == 6  # 6 fits in 3 bits


def test_the_running_total_of_a_sum_is_bounded_not_only_the_final_value():
    # 4 + 4 overflows 3 bits at the first step even though the later "- 4" would bring the total back
    with pytest.raises(UnsafeExpression):
        safe_eval("sum([4, 4, -4])", EvalLimits(max_bits=3))


def test_aggregate_work_is_charged_to_the_step_budget():
    started = time.monotonic()
    with pytest.raises(UnsafeExpression, match="step budget"):
        safe_eval("sum([n for n in range(5000)])", EvalLimits(max_steps=1000))
    with pytest.raises(UnsafeExpression, match=r"step budget|longer"):
        safe_eval("len(sorted([n for n in range(5000)]))", EvalLimits(max_steps=1000, max_list=10_000))
    assert time.monotonic() - started < 1


def test_the_number_of_operands_is_bounded():
    many = ", ".join(["1"] * 65)
    for fn in ("max", "min", "gcd"):
        with pytest.raises(UnsafeExpression, match="arguments"):
            safe_eval(f"{fn}({many})")
    assert safe_eval(f"max({', '.join(['1'] * 64)})") == 1
    with pytest.raises(UnsafeExpression, match="arguments"):
        safe_eval("max(1, 2)", EvalLimits(max_operands=1))


def test_input_size_and_result_size_are_bounded_before_work():
    with pytest.raises(UnsafeExpression):
        safe_eval("sum([1, 2, 3, 4, 5, 6])", EvalLimits(max_list=5))
    with pytest.raises(UnsafeExpression):
        safe_eval("[n for n in range(100)]", EvalLimits(max_list=10))
    with pytest.raises(UnsafeExpression):
        safe_eval("range(10 ** 6)", EvalLimits(max_range=1000))
    with pytest.raises(UnsafeExpression):
        safe_eval("sum([2 ** 12] * 2)", EvalLimits())  # a list repeat is not arithmetic


def test_aggregates_reject_non_integers_and_empty_inputs():
    for bad in ("sum([[1], [2]])", "max([])", "min([])", "sum(3)", "len(3)", "sum([True, 1])", "sorted([[1]])"):
        with pytest.raises(UnsafeExpression):
            safe_eval(bad)


def test_aggregates_still_compute_correct_values_within_the_bounds():
    assert safe_eval("sum([n for n in range(1, 11)])") == 55
    assert safe_eval("max([3, 9, 4])") == 9
    assert safe_eval("min(7, 2, 5)") == 2
    assert safe_eval("sorted([3, 1, 2]) == [1, 2, 3]") is True
    assert safe_eval("gcd(12, 18)") == 6
    assert safe_eval("len([d for d in range(1, 13) if 12 % d == 0])") == 6


def test_hostile_verification_expressions_become_findings_before_exhaustion(pilot_copy):
    started = time.monotonic()
    for hostile in ("sum([n for n in range(100000)])", "max(" + ", ".join(["9"] * 100) + ")", "2 ** 12 ** 12", "sum([10 ** 30])"):
        edit_json(pilot_copy, f"{L2}/verification.json", lambda v, h=hostile: v["questions"]["calcul-mental"].update(compute=h))
        assert "verification_expression" in codes(pilot_copy), hostile
    assert time.monotonic() - started < 60


# ================================================================ handle-based filesystem access
class DirFdRecorder:
    def __init__(self, monkeypatch):
        self.calls: list[tuple[str, object]] = []
        real = os.open

        def wrapper(path, flags, mode=0o777, *, dir_fd=None):
            self.calls.append((os.fsdecode(path), dir_fd))
            return real(path, flags, mode, dir_fd=dir_fd)

        monkeypatch.setattr(os, "open", wrapper)


def test_confined_reads_open_each_component_relative_to_a_handle(pilot_copy, monkeypatch):
    rec = DirFdRecorder(monkeypatch)
    data = read_confined(pilot_copy, f"{L1}/blocks.fr.json", 1 << 20)
    assert data.startswith(b"[")
    names = [(n, fd is not None) for n, fd in rec.calls]
    assert names[0][1] is False  # the operator's root is opened once by its resolved path
    assert [n for n, relative in names[1:]] == ["lessons", "01-lire-ecrire-comparer-entiers", "blocks.fr.json"]
    assert all(relative for _, relative in names[1:])  # nothing below the root is ever re-resolved by name


def test_a_link_at_any_level_below_the_root_is_refused(pilot_copy, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "blocks.fr.json").write_text("[]")
    lessons = pilot_copy / "lessons"
    moved = tmp_path / "moved-lessons"
    lessons.rename(moved)
    lessons.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ContentFileError):
        read_confined(pilot_copy, f"{L1}/blocks.fr.json", 1 << 20)


def test_output_directories_fail_closed_when_any_ancestor_is_a_link(tmp_path):
    real = tmp_path / "real"
    (real / "sub").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ContentFileError):
        open_dir_strict(link / "sub")
    with pytest.raises(ContentFileError):
        write_text_atomic(link / "sub", "x.md", "text")
    with pytest.raises(ContentFileError):
        read_in_dir(link / "sub", "x.md", 100)
    assert not (real / "sub" / "x.md").exists()
    write_text_atomic(real / "sub", "x.md", "text")  # the real path works
    assert (real / "sub" / "x.md").read_text() == "text"


def test_review_check_mode_also_refuses_a_linked_ancestor(pilot_copy, tmp_path):
    real = tmp_path / "real"
    (real / "review").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    for mode in ("--check", "--write"):
        assert cli.main(["review-pack", mode, "--root", str(pilot_copy), "--review-dir", str(link / "review")]) == 2
    assert list((real / "review").iterdir()) == []


def test_review_pack_writes_into_a_real_directory_and_check_then_passes(tmp_path):
    out = tmp_path / "out"
    assert cli.main(["review-pack", "--write", "--root", str(PILOT), "--review-dir", str(out)]) == 0
    assert len(list(out.iterdir())) == 9
    assert cli.main(["review-pack", "--check", "--root", str(PILOT), "--review-dir", str(out)]) == 0
    (out / "answer-key-overview.md").write_text("stale")
    assert cli.main(["review-pack", "--check", "--root", str(PILOT), "--review-dir", str(out)]) == 1


def test_enumeration_stops_at_its_budget_instead_of_listing_everything(tmp_path):
    big = tmp_path / "big"
    big.mkdir()
    for i in range(300):
        (big / f"f{i:03}.json").write_text("[]")
    entries, stopped = scan_tree(big, max_entries=50, max_depth=4, max_bytes=1 << 20)
    assert stopped and "more than 50 entries" in stopped
    assert len(entries) == 50  # never more than the budget held in memory


def test_directories_and_links_count_against_the_entry_budget(tmp_path):
    root = tmp_path / "many"
    root.mkdir()
    for i in range(60):
        (root / f"d{i:02}").mkdir()
    entries, stopped = scan_tree(root, max_entries=40, max_depth=4, max_bytes=1 << 20)
    assert stopped and len(entries) == 40


def test_enumeration_depth_and_bytes_are_bounded(tmp_path):
    root = tmp_path / "deep"
    cur = root
    for i in range(8):
        cur = cur / f"d{i}"
    cur.mkdir(parents=True)
    _, stopped = scan_tree(root, max_entries=100, max_depth=3, max_bytes=1 << 20)
    assert stopped and "nested deeper" in stopped
    (tmp_path / "heavy").mkdir()
    (tmp_path / "heavy" / "a").write_bytes(b"x" * 500)
    _, stopped = scan_tree(tmp_path / "heavy", max_entries=100, max_depth=3, max_bytes=100)
    assert stopped and "bytes" in stopped


def test_validate_stops_on_a_directory_flood_without_reading_lessons(pilot_copy):
    flood = pilot_copy / "lessons" / "flood"
    flood.mkdir()
    for i in range(250):
        (flood / f"f{i}.json").write_text("[]")
    found = validate(pilot_copy, repo_root=REPO)
    assert "resource_limit" in {f.code for f in found}
    assert not any(f.code in ("math_false", "translation_numbers") for f in found)
    small = replace(DEFAULT_LIMITS, max_entries=10)
    assert "resource_limit" in {f.code for f in validate(PILOT, repo_root=REPO, limits=small)}


def test_empty_directories_do_not_hide_from_the_budget(pilot_copy):
    base = pilot_copy / "lessons"
    for i in range(DEFAULT_LIMITS.max_entries + 5):
        (base / f"e{i}").mkdir()
    assert "resource_limit" in {f.code for f in validate(pilot_copy, repo_root=REPO)}


def test_the_documented_threat_model_is_in_the_module_docstring():
    import content_pilot.safefs as m

    text = (m.__doc__ or "") + Path(m.__file__).read_text(encoding="utf-8")[:4000]
    assert re.search(r"trusted|operator", text)
