"""Deliberately damaged copies of the pilot: the validator must name each defect precisely."""

from __future__ import annotations

import json

import pytest
from content_pilot.checks import summarize, validate

from .conftest import L1, L2, L5, REPO, edit_json, replace_json


def codes(root, **kw):
    return {f.code for f in validate(root, repo_root=REPO, **kw) if f.severity == "error"}


def test_baseline_copy_is_clean(pilot_copy):
    assert codes(pilot_copy) == set()


# ---------------------------------------------------------------- block contract
def test_duplicate_block_key(pilot_copy):
    edit_json(pilot_copy, f"{L1}/blocks.fr.json", lambda b: b.append(dict(b[0])))
    assert "duplicate_key" in codes(pilot_copy)


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda b: b.__setitem__(1, {"key": "img", "type": "image", "src": "x.png"}), "blocks_schema"),
        (lambda b: b[1].update(text="x" * 4001), "blocks_schema"),
        (lambda b: b[1].update(extra="nope"), "blocks_schema"),
        (lambda b: b[0].update(key="Bad Key!"), "blocks_schema"),
        (lambda b: b[-2].update(tone="loud"), "blocks_schema"),
        (lambda b: b.clear(), "blocks_schema"),
    ],
)
def test_blocks_contract_violations(pilot_copy, mutate, expected):
    edit_json(pilot_copy, f"{L1}/blocks.fr.json", mutate)
    assert expected in codes(pilot_copy)


def test_lesson_without_worked_example(pilot_copy):
    replace_json(pilot_copy, f"{L1}/blocks.fr.json", lambda b: [x for x in b if x["type"] != "example"])
    assert "no_worked_example" in codes(pilot_copy)


# ---------------------------------------------------------------- translations
def test_missing_translation_file(pilot_copy):
    (pilot_copy / L1 / "blocks.ht.json").unlink()
    assert "file_missing" in codes(pilot_copy)


def test_missing_creole_questions(pilot_copy):
    (pilot_copy / L2 / "questions.ht.json").unlink()
    assert "file_missing" in codes(pilot_copy)


def test_creole_block_missing_or_reordered(pilot_copy):
    replace_json(pilot_copy, f"{L1}/blocks.ht.json", lambda b: b[:-1])
    assert "translation_structure" in codes(pilot_copy)


def test_translation_that_changes_a_number(pilot_copy):
    def change(b):
        for blk in b:
            if blk["key"] == "piege":
                blk["text"] = blk["text"].replace("2\u00a0000", "2\u00a0100")

    edit_json(pilot_copy, f"{L1}/blocks.ht.json", change)
    assert "translation_numbers" in codes(pilot_copy)


def test_callout_tone_differs_between_languages(pilot_copy):
    def retone(b):
        for x in b:
            if x["key"] == "piege":
                x["tone"] = "tip"

    edit_json(pilot_copy, f"{L1}/blocks.ht.json", retone)
    assert "translation_structure" in codes(pilot_copy)


def test_creole_answer_key_disagrees_with_french(pilot_copy):
    edit_json(pilot_copy, f"{L1}/questions.ht.json", lambda q: q[0]["answer_key"].update(correct_choice_id="a"))
    c = codes(pilot_copy)
    assert "translation_answer_key" in c and "wrong_answer_key" in c


# ---------------------------------------------------------------- malformed answers
@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda q: q[0]["answer_key"].update(correct_choice_id="z"), "malformed_answer"),
        (lambda q: q[0]["response_spec"]["choices"][1].update(id="a"), "duplicate_choice_id"),
        (lambda q: q[0]["response_spec"]["choices"][1].update(text=q[0]["response_spec"]["choices"][0]["text"]), "duplicate_choice_text"),
        (lambda q: q[0]["response_spec"].update(choices=q[0]["response_spec"]["choices"][:1]), "question_schema"),
        (lambda q: q[0].pop("explanation"), "question_schema"),
        (lambda q: q[0].update(surprise=1), "questions_schema"),
        (lambda q: q[0]["response_spec"]["choices"][0].update(id="bad id"), "question_schema"),
        (lambda q: q[1].update(position=9), "question_positions"),
        (lambda q: q[1]["prompt"].update(text=q[0]["prompt"]["text"]), "duplicate_prompt"),
    ],
)
def test_malformed_question_content(pilot_copy, mutate, expected):
    edit_json(pilot_copy, f"{L1}/questions.fr.json", mutate)
    assert expected in codes(pilot_copy)


def test_too_few_questions(pilot_copy):
    for loc in ("fr", "ht"):
        replace_json(pilot_copy, f"{L1}/questions.{loc}.json", lambda q: q[:-1])
    assert "question_count" in codes(pilot_copy)


def test_duplicate_question_key(pilot_copy):
    edit_json(pilot_copy, f"{L1}/questions.fr.json", lambda q: q[1].update(question_key=q[0]["question_key"]))
    assert "duplicate_key" in codes(pilot_copy)


# ---------------------------------------------------------------- mathematics
def test_wrong_answer_key_is_caught_by_recomputation(pilot_copy):
    # 456 + 378 = 834 is choice b; point both languages at a plausible wrong choice.
    for loc in ("fr", "ht"):
        edit_json(pilot_copy, f"{L2}/questions.{loc}.json", lambda q: q[0]["answer_key"].update(correct_choice_id="a"))
    assert "wrong_answer_key" in codes(pilot_copy)


def test_two_choices_with_the_same_verified_value(pilot_copy):
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["questions"]["addition-posee"]["choices"].update(a=834))
    c = codes(pilot_copy)
    assert "answer_not_unique" in c and "duplicate_choice_value" in c


def test_no_choice_matches_the_computed_answer(pilot_copy):
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["questions"]["addition-posee"].update(compute="456 + 379"))
    assert "answer_not_unique" in codes(pilot_copy)


def test_choice_text_disagrees_with_its_verified_value(pilot_copy):
    def swap(q):
        q[0]["response_spec"]["choices"][1]["text"] = "843"

    for loc in ("fr", "ht"):
        edit_json(pilot_copy, f"{L2}/questions.{loc}.json", swap)
    assert "choice_text_mismatch" in codes(pilot_copy)


def test_explanation_that_does_not_state_the_answer(pilot_copy):
    for loc in ("fr", "ht"):
        edit_json(pilot_copy, f"{L2}/questions.{loc}.json", lambda q: q[0]["explanation"].update(text="Résultat : 843. 6 + 8 = 14."))
    assert "explanation_missing_answer" in codes(pilot_copy)


def test_truth_choice_whose_text_mentions_a_number_its_check_never_uses(pilot_copy):
    edit_json(pilot_copy, f"{L5}/verification.json", lambda v: v["questions"]["divisible-par-8"]["choices"]["d"].update(expr="24 % 8 != 0"))
    assert "choice_binding" in codes(pilot_copy)


def test_two_true_choices_in_a_truth_question(pilot_copy):
    edit_json(pilot_copy, f"{L5}/verification.json", lambda v: v["questions"]["divisible-par-8"]["choices"]["b"].update(expr="24 % 8 == 0"))
    assert "answer_not_unique" in codes(pilot_copy)


def test_worked_example_with_wrong_arithmetic_is_caught(pilot_copy):
    def wrong(b):
        for blk in b:
            if blk["key"] == "exemple-addition":
                blk["steps"][-1] = "348 + 275 = 632"

    for loc in ("fr", "ht"):
        edit_json(pilot_copy, f"{L2}/blocks.{loc}.json", wrong)
    assert "example_not_shown" in codes(pilot_copy)


def test_verification_that_is_itself_wrong(pilot_copy):
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["examples"][0]["checks"][3].update(equals=632))
    assert "example_wrong" in codes(pilot_copy)


def test_question_without_verification_and_example_without_verification(pilot_copy):
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: (v["questions"].pop("calcul-mental"), v["examples"].pop()))
    c = codes(pilot_copy)
    assert "unverified_question" in c and "example_unverified" in c


def test_verification_entry_for_a_missing_question(pilot_copy):
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["questions"].update(ghost=v["questions"]["calcul-mental"]))
    assert "verification_orphan" in codes(pilot_copy)


def test_unsafe_or_broken_verification_expressions_are_refused(pilot_copy):
    for bad in ("__import__('os').system('true')", "open('x')", "(1).__class__", "2 ** 999", "1 / 0", "1 +"):
        edit_json(pilot_copy, f"{L2}/verification.json", lambda v, bad=bad: v["questions"]["calcul-mental"].update(compute=bad))
        assert "verification_expression" in codes(pilot_copy), bad


def test_verification_mode_and_choice_set_must_match(pilot_copy):
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["questions"]["calcul-mental"].update(mode="guess"))
    assert "verification_schema" in codes(pilot_copy)
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["questions"]["calcul-mental"].update(mode="value", choices={"a": 1, "b": 2}))
    assert "verification_choices" in codes(pilot_copy)


# ---------------------------------------------------------------- characters and markup
BAD_TEXT = [
    ("zero-width space", "Bonjour​ tout le monde", "invalid_character"),
    ("NUL", "Bonjour\x00 tout le monde", "invalid_character"),
    ("replacement char", "Bonjour � tout le monde", "invalid_character"),
    ("bidi override", "Bonjour ‮ tout le monde", "invalid_character"),
    ("BOM", "﻿Bonjour tout le monde", "invalid_character"),
    ("tab", "Bonjour\ttout le monde", "invalid_character"),
    ("newline", "Bonjour\ntout le monde", "invalid_character"),
    ("html tag", "Voici <b>du gras</b>", "markup"),
    ("unclosed tag", "Voici <script", "markup"),
    ("entity", "Tom &amp; Jerry", "markup"),
    ("markdown bold", "Voici **du gras**", "markup"),
    ("markdown code", "Voici `du code`", "markup"),
    ("markdown link", "[ici](x)", "markup"),
    ("url", "Va sur http://exemple.ht", "url"),
    ("leading space", " Bonjour tout le monde", "whitespace"),
    ("double space", "Bonjour  tout le monde", "whitespace"),
    ("decomposed accent", "Calcule éte", "not_nfc"),
    ("blank", "   ", "text_empty"),
]


@pytest.mark.parametrize(("label", "text", "expected"), BAD_TEXT, ids=[b[0] for b in BAD_TEXT])
def test_text_rules_in_lesson_blocks(pilot_copy, label, text, expected):
    edit_json(pilot_copy, f"{L1}/blocks.fr.json", lambda b: b[1].update(text=text))
    assert expected in codes(pilot_copy), label


@pytest.mark.parametrize(("label", "text", "expected"), BAD_TEXT[:4] + BAD_TEXT[7:10], ids=[b[0] for b in BAD_TEXT[:4] + BAD_TEXT[7:10]])
def test_text_rules_in_questions_and_choices(pilot_copy, label, text, expected):
    edit_json(pilot_copy, f"{L1}/questions.ht.json", lambda q: q[0]["prompt"].update(text=text))
    edit_json(pilot_copy, f"{L1}/questions.ht.json", lambda q: q[1]["response_spec"]["choices"][0].update(text=text))
    edit_json(pilot_copy, f"{L1}/questions.ht.json", lambda q: q[2]["explanation"].update(text=text))
    found = [f for f in validate(pilot_copy, repo_root=REPO) if f.code == expected]
    assert len(found) >= 3, label


def test_math_symbols_and_comparison_signs_are_not_mistaken_for_markup(pilot_copy):
    edit_json(pilot_copy, f"{L1}/blocks.fr.json", lambda b: b[1].update(text="Si 3 < 5 et 5 > 3, alors 3 × 4 − 2 ÷ 1 reste clair."))
    assert "markup" not in codes(pilot_copy)


# ---------------------------------------------------------------- rights and provenance
def test_third_party_material_is_refused(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0]["rights"].update(third_party_material=True))
    assert "rights_third_party" in codes(pilot_copy)


def test_rights_metadata_is_mandatory_and_consistent(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0].pop("rights"))
    assert "pilot_schema" in codes(pilot_copy)


def test_licence_without_assignment_and_assignment_without_licence(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0]["rights"].update(licence="CC-BY"))
    assert "rights_inconsistent" in codes(pilot_copy)
    edit_json(pilot_copy, "pilot.json", lambda p: (p["lessons"][0]["rights"].pop("licence"), p["lessons"][0]["rights"].update(licence_status="assigned")))
    assert "rights_licence_missing" in codes(pilot_copy)


def test_provenance_must_declare_original_authoring_with_no_third_party_derivation(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0]["provenance"].update(derived_from_third_party=True))
    assert "pilot_schema" in codes(pilot_copy)
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0]["rights"].update(origin="scanned_textbook"))
    assert "pilot_schema" in codes(pilot_copy)


def test_source_register_integrity(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0]["curriculum_refs"][0].update(source="S9"))
    assert "unknown_source" in codes(pilot_copy)
    edit_json(pilot_copy, "pilot.json", lambda p: p["sources"].append(dict(p["sources"][0])))
    assert "source_duplicate" in codes(pilot_copy)


def test_source_cannot_claim_a_licence_we_do_not_have(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda p: p["sources"][0].update(rights_status="cc_by"))
    assert "pilot_schema" in codes(pilot_copy)


def test_every_lesson_needs_a_curriculum_reference(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0].update(curriculum_refs=[]))
    assert "pilot_schema" in codes(pilot_copy)


# ---------------------------------------------------------------- identities
def test_unstable_ids_are_refused(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0].update(id="11111111-1111-4111-8111-111111111111"))
    assert "unstable_id" in codes(pilot_copy)
    edit_json(pilot_copy, "pilot.json", lambda p: p["unit"].update(id="22222222-2222-4222-8222-222222222222"))
    assert "unstable_id" in codes(pilot_copy)


def test_lesson_positions_and_duplicates(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][1].update(position=5))
    assert "lesson_positions" in codes(pilot_copy)
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][2].update(slug=p["lessons"][0]["slug"], id=p["lessons"][0]["id"]))
    assert "lesson_duplicate" in codes(pilot_copy)


# ---------------------------------------------------------------- review status
def test_approved_without_both_approvals_is_refused(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0]["review"]["fr"].update(status="approved"))
    assert "approved_without_approvals" in codes(pilot_copy)
    one = {"role": "mathematics_teacher", "name": "A. Enseignant", "date": "2026-12-01", "decision_ref": "feuille-signee-001"}
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0]["review"]["fr"].update(approvals=[one]))
    assert "approved_without_approvals" in codes(pilot_copy)


def test_a_properly_approved_lesson_passes_but_not_when_approvals_are_forbidden(pilot_copy):
    both = [
        {"role": "mathematics_teacher", "name": "A. Enseignant", "date": "2026-12-01", "decision_ref": "feuille-signee-001"},
        {"role": "native_speaker", "name": "B. Locuteur", "date": "2026-12-01", "decision_ref": "feuille-signee-001"},
    ]
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0]["review"]["fr"].update(status="approved", approvals=both))
    assert codes(pilot_copy) == set()
    assert "approval_forbidden" in codes(pilot_copy, forbid_approvals=True)


def test_approvals_recorded_but_status_not_approved_is_flagged(pilot_copy):
    one = {"role": "native_speaker", "name": "B. Locuteur", "date": "2026-12-01", "decision_ref": "x-001"}
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0]["review"]["ht"].update(approvals=[one]))
    findings = validate(pilot_copy, repo_root=REPO)
    assert any(f.code == "approvals_without_status" and f.severity == "warning" for f in findings)


def test_review_requirements_cannot_be_weakened(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0]["review"]["fr"].update(required_approvals=["mathematics_teacher"]))
    assert codes(pilot_copy) & {"pilot_schema", "review_requirements"}
    edit_json(pilot_copy, "pilot.json", lambda p: p["lessons"][0]["review"]["fr"].update(status="published"))
    assert "pilot_schema" in codes(pilot_copy)


# ---------------------------------------------------------------- files and size
def test_invalid_json_and_missing_files(pilot_copy):
    (pilot_copy / L1 / "blocks.fr.json").write_text("{ not json", encoding="utf-8")
    assert "json_invalid" in codes(pilot_copy)
    (pilot_copy / L1 / "verification.json").unlink()
    assert "file_missing" in codes(pilot_copy)


def test_missing_or_broken_pilot_descriptor(tmp_path):
    assert {f.code for f in validate(tmp_path, repo_root=REPO)} == {"pilot_missing"}
    (tmp_path / "pilot.json").write_text("[", encoding="utf-8")
    assert {f.code for f in validate(tmp_path, repo_root=REPO)} == {"json_invalid"}


def test_oversized_unit_is_refused_and_large_unit_is_warned(pilot_copy):
    def bloat(b, n):
        b[:] = [b[0], *[{"key": f"p{i}", "type": "paragraph", "text": "x" * 3000} for i in range(n)], b[-1]]

    edit_json(pilot_copy, f"{L1}/blocks.fr.json", lambda b: bloat(b, 7))
    assert "size_over_budget" in codes(pilot_copy)
    edit_json(pilot_copy, f"{L1}/blocks.fr.json", lambda b: bloat(b, 3))
    warns = [f.code for f in validate(pilot_copy, repo_root=REPO) if f.severity == "warning"]
    assert "size_large" in warns


def test_summarize_counts_errors_and_warnings(pilot_copy):
    (pilot_copy / L1 / "blocks.ht.json").unlink()
    errors, _ = summarize(validate(pilot_copy, repo_root=REPO))
    assert errors >= 1


def test_findings_are_actionable(pilot_copy):
    edit_json(pilot_copy, f"{L1}/blocks.fr.json", lambda b: b[1].update(text="Voici <b>gras</b>"))
    f = next(f for f in validate(pilot_copy, repo_root=REPO) if f.code == "markup")
    assert "lire-ecrire-comparer-entiers" in f.where and "blocks.fr" in f.where and "/1/text" in f.where
    assert json.dumps(f.message)
