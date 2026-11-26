"""Independent review of the draft. Test data and expectations require no expression evaluation."""

import pytest
from jsonschema import Draft202012Validator

from content_pilot import manifest
from content_pilot.checks import TOOL_DIR, validate
from content_pilot.model import read_json
from content_pilot.safe_eval import UnsafeExpression, safe_eval

from .conftest import L1, L2, PILOT, REPO, edit_json


# Hand-solved in displayed order from the bilingual learner files. See FINAL_QA for derivations.
EXPECTED = ("cbabb", "bcbba", "bbbba", "bbcbb", "caabc", "bccca")
LESSONS = sorted((PILOT / "lessons").iterdir())


@pytest.mark.parametrize("locale", ["fr", "ht"])
@pytest.mark.parametrize("lesson", range(6), ids=lambda n: f"L{n + 1}")
@pytest.mark.parametrize("position", range(5), ids=lambda n: f"Q{n + 1}")
def test_independent_answer_choice(lesson, position, locale):
    question = read_json(LESSONS[lesson] / f"questions.{locale}.json")[position]
    assert question["position"] == position + 1
    assert question["answer_key"]["correct_choice_id"] == EXPECTED[lesson][position]


def errors(root):
    return [f for f in validate(root, repo_root=REPO, forbid_approvals=True) if f.severity == "error"]


def test_missing_verification_document_is_an_error(pilot_copy):
    (pilot_copy / L1 / "verification.json").write_text("null")
    assert errors(pilot_copy)


def test_wrong_verification_shape_is_a_finding(pilot_copy):
    (pilot_copy / L1 / "verification.json").write_text("[]")
    assert errors(pilot_copy)


def test_every_worked_example_has_at_least_one_check(pilot_copy):
    edit_json(pilot_copy, f"{L1}/verification.json", lambda doc: doc["examples"][0].update(checks=[]))
    assert errors(pilot_copy)


def test_comparison_direction_matches_visible_choice(pilot_copy):
    # Change one learner-facing mathematical symbol, preserving all digits and the proof file.
    def reverse(questions):
        choice = questions[2]["response_spec"]["choices"][0]
        assert "<" in choice["text"]
        choice["text"] = choice["text"].replace("<", "≥")

    edit_json(pilot_copy, f"{L1}/questions.ht.json", reverse)
    assert errors(pilot_copy)


def test_order_of_subtraction_survives_translation(pilot_copy):
    def transpose(questions):
        question = questions[1]["prompt"]
        assert "702 − 345" in question["text"]
        question["text"] = question["text"].replace("702 − 345", "345 − 702")

    edit_json(pilot_copy, f"{L2}/questions.ht.json", transpose)
    assert errors(pilot_copy)


def test_locales_have_distinct_files(pilot_copy):
    def reuse_french(descriptor):
        blocks = descriptor["lessons"][0]["files"]["blocks"]
        blocks["ht"] = blocks["fr"]

    edit_json(pilot_copy, "pilot.json", reuse_french)
    assert errors(pilot_copy)


def test_manifest_binds_locale_metadata(pilot_copy):
    def relabel(doc):
        entry = next(e for e in doc["entries"] if e.get("locale") == "fr")
        entry["locale"] = "ht"

    edit_json(pilot_copy, manifest.MANIFEST_NAME, relabel)
    assert manifest.verify_manifest(pilot_copy)


def test_duplicate_manifest_entries_rejected(pilot_copy):
    edit_json(pilot_copy, manifest.MANIFEST_NAME, lambda doc: doc["entries"].append(doc["entries"][0].copy()))
    assert manifest.verify_manifest(pilot_copy)


def test_duplicate_descriptor_json_members_rejected(pilot_copy):
    path = pilot_copy / "pilot.json"
    doc = path.read_text()
    path.write_text(doc.replace('"grade":', '"grade": "7AF", "grade":', 1))
    assert errors(pilot_copy)


def test_missing_source_is_rejected(pilot_copy):
    def unset_reference(descriptor):
        descriptor["lessons"][0]["curriculum_refs"][0]["source"] = "S99"

    edit_json(pilot_copy, "pilot.json", unset_reference)
    assert any(f.code == "unknown_source" for f in errors(pilot_copy))


def test_malformed_json_syntax_is_a_finding(pilot_copy):
    (pilot_copy / L1 / "questions.fr.json").write_text("[")
    assert any(f.code == "json_invalid" for f in errors(pilot_copy))


@pytest.mark.parametrize("kind", ["absolute", "parent"])
def test_file_reference_schema_requires_a_local_relative_name(kind):
    # Schema-only fixture. No filesystem operation uses this test value.
    descriptor = read_json(PILOT / "pilot.json")
    ref = "/synthetic/unused.json" if kind == "absolute" else "../unused.json"
    descriptor["lessons"][0]["files"]["verification"] = ref
    schema = read_json(TOOL_DIR / "schemas" / "pilot.schema.json")
    assert list(Draft202012Validator(schema).iter_errors(descriptor))


def test_arithmetic_multiplication_accepts_only_numbers():
    # Constant-sized, harmless input: the arithmetic operator has a sequence overload in Python.
    with pytest.raises(UnsafeExpression):
        safe_eval("[2] * 2")
