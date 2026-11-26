"""The committed pilot is valid, complete, consistent in both languages and mathematically correct."""

from __future__ import annotations

import json
import re
import uuid

from content_pilot import manifest as mf
from content_pilot.checks import summarize, validate
from content_pilot.model import LOCALES, PILOT_NAMESPACE, SIZE_ERROR_BYTES, stable_id
from content_pilot.review import build_review_pack
from content_pilot.textrules import number_tokens
from jsonschema import Draft202012Validator

from .conftest import PILOT, REPO


def load(rel: str):
    return json.loads((PILOT / rel).read_text(encoding="utf-8"))


def pilot():
    return load("pilot.json")


def test_pilot_validates_with_no_errors_and_no_warnings():
    findings = validate(PILOT, repo_root=REPO, forbid_approvals=True)
    assert summarize(findings) == (0, 0), [str(f) for f in findings]


def test_shape_six_lessons_two_languages_five_questions_each():
    p = pilot()
    assert p["grade"] == "7AF" and p["locales"] == ["fr", "ht"]
    assert 4 <= len(p["lessons"]) <= 6
    for lesson in p["lessons"]:
        for loc in LOCALES:
            assert len(load(lesson["files"]["questions"][loc])) == 5


def test_lesson_json_validates_against_the_repository_contracts_independently():
    """Do not trust the tool alone: re-validate with jsonschema straight from packages/contracts."""
    blocks_v = Draft202012Validator(json.loads((REPO / "packages/contracts/content/lesson-blocks.schema.json").read_text()))
    mcq_v = Draft202012Validator(json.loads((REPO / "packages/contracts/content/question-mcq.schema.json").read_text()))
    for lesson in pilot()["lessons"]:
        for loc in LOCALES:
            assert list(blocks_v.iter_errors(load(lesson["files"]["blocks"][loc]))) == []
            for q in load(lesson["files"]["questions"][loc]):
                contract = {k: q[k] for k in ("prompt", "response_spec", "answer_key", "explanation")}
                assert list(mcq_v.iter_errors(contract)) == [], q["question_key"]


def test_every_question_has_exactly_one_correct_choice_in_both_languages():
    for lesson in pilot()["lessons"]:
        for loc in LOCALES:
            for q in load(lesson["files"]["questions"][loc]):
                ids = [c["id"] for c in q["response_spec"]["choices"]]
                assert len(ids) == len(set(ids)) >= 2
                assert ids.count(q["answer_key"]["correct_choice_id"]) == 1


def test_answers_are_recomputed_by_an_independent_evaluator():
    """A second, deliberately different implementation (restricted eval) must agree with the committed keys."""
    safe = {"max": max, "min": min, "len": len, "range": range, "sum": sum}
    checked = 0
    for lesson in pilot()["lessons"]:
        ver = load(lesson["files"]["verification"])
        qs = {q["question_key"]: q for q in load(lesson["files"]["questions"]["fr"])}
        for key, spec in ver["questions"].items():
            correct = qs[key]["answer_key"]["correct_choice_id"]
            if spec["mode"] == "value":
                got = eval(spec["compute"], {"__builtins__": {}}, dict(safe))
                matches = [cid for cid, v in spec["choices"].items() if v == got]
            else:
                matches = [cid for cid, expr in spec["choices"].items() if eval(expr, {"__builtins__": {}}, dict(safe)) is True]
            assert matches == [correct], f"{lesson['slug']}/{key}: computed {matches}, key {correct}"
            checked += 1
    assert checked == 30


def test_every_worked_example_is_verified():
    for lesson in pilot()["lessons"]:
        ver = load(lesson["files"]["verification"])
        for loc in LOCALES:
            example_keys = {b["key"] for b in load(lesson["files"]["blocks"][loc]) if b["type"] == "example"}
            assert example_keys and example_keys == {e["block"] for e in ver["examples"]}, lesson["slug"]


def test_french_and_creole_share_structure_keys_and_numbers():
    for lesson in pilot()["lessons"]:
        fr, ht = (load(lesson["files"]["blocks"][loc]) for loc in LOCALES)
        assert [(b["key"], b["type"]) for b in fr] == [(b["key"], b["type"]) for b in ht]
        for a, b in zip(fr, ht, strict=True):
            assert number_tokens(json.dumps(a, ensure_ascii=False)) == number_tokens(json.dumps(b, ensure_ascii=False)), (lesson["slug"], a["key"])
        qf, qh = (load(lesson["files"]["questions"][loc]) for loc in LOCALES)
        assert [q["question_key"] for q in qf] == [q["question_key"] for q in qh]
        assert [q["answer_key"] for q in qf] == [q["answer_key"] for q in qh]


def test_creole_is_not_a_copy_of_the_french():
    """Independent drafts: the prose differs (only digits/symbols may coincide)."""
    for lesson in pilot()["lessons"]:
        fr, ht = (load(lesson["files"]["blocks"][loc]) for loc in LOCALES)
        same = [a["key"] for a, b in zip(fr, ht, strict=True) if a.get("text") and a.get("text") == b.get("text")]
        assert same == [], f"{lesson['slug']}: identical text in {same}"


def test_identities_are_stable_deterministic_uuid5_and_unique():
    p = pilot()
    assert p["unit"]["id"] == str(uuid.uuid5(PILOT_NAMESPACE, "7af-math-pilot/unit/nombres-entiers-naturels"))
    ids = [le["id"] for le in p["lessons"]]
    assert len(set(ids)) == len(ids)
    for le in p["lessons"]:
        assert le["id"] == stable_id("lesson", le["slug"])
        uuid.UUID(le["id"])


def test_nothing_is_described_as_approved_and_every_draft_requires_both_reviewers():
    p = pilot()
    assert not re.search(r"(?<!non )approuvé par|approved by", json.dumps(p, ensure_ascii=False).lower())
    for le in p["lessons"]:
        for loc in LOCALES:
            rv = le["review"][loc]
            assert rv["status"] == "draft_unreviewed" and rv["approvals"] == []
            assert sorted(rv["required_approvals"]) == ["mathematics_teacher", "native_speaker"]
        assert le["rights"]["third_party_material"] is False and le["rights"]["licence_status"] == "unassigned_owner_decision"
        assert le["provenance"]["derived_from_third_party"] is False


def test_every_curriculum_reference_points_to_the_source_register_and_is_honest_about_gaps():
    p = pilot()
    ids = {s["id"] for s in p["sources"]}
    relations = set()
    for le in p["lessons"]:
        for r in le["curriculum_refs"]:
            assert r["source"] in ids
            relations.add(r["relation"])
    assert "partial" in relations  # the pilot never claims full alignment everywhere
    assert any(s["verification"] == "not_located" for s in p["sources"])
    assert all(s["rights_status"] != "assigned" for s in p["sources"])


def test_units_are_small_for_old_phones_and_slow_links():
    s = mf.sizes(PILOT)
    for row in s["rows"]:
        assert row["unit_bytes"] < 8 * 1024 < SIZE_ERROR_BYTES, row
        assert row["unit_gzip_bytes"] < row["unit_bytes"]
    for loc in LOCALES:
        assert s["totals"][loc]["bytes"] < 64 * 1024  # the whole pilot, one language


def test_sizes_are_deterministic():
    assert mf.sizes(PILOT) == mf.sizes(PILOT)


def test_preview_manifest_is_committed_current_and_deterministic():
    assert mf.verify_manifest(PILOT) == []
    assert mf.render(mf.build_manifest(PILOT)) == mf.render(mf.build_manifest(PILOT))
    assert (PILOT / mf.MANIFEST_NAME).read_text(encoding="utf-8") == mf.render(mf.build_manifest(PILOT))
    m = mf.build_manifest(PILOT)
    assert "NOT a production pack format" in m["purpose"]
    assert all(len(e["sha256"]) == 64 for e in m["entries"])
    assert not any("timestamp" in k or "date" in k for k in m)  # no clock in the manifest


def test_review_pack_is_committed_and_current():
    out = REPO / "docs" / "content-02a" / "review"
    for name, text in build_review_pack(PILOT).items():
        assert (out / name).read_text(encoding="utf-8") == text, f"{name} is stale: run review-pack --write"


def test_review_sheets_cover_every_block_and_question_and_approve_nothing():
    files = build_review_pack(PILOT)
    for le in pilot()["lessons"]:
        sheet = files[f"lesson-{le['position']:02d}-{le['slug']}.md"]
        for loc in LOCALES:
            for b in load(le["files"]["blocks"][loc]):
                assert f"`{b['key']}`" in sheet
            for q in load(le["files"]["questions"][loc]):
                assert f"`{q['question_key']}`" in sheet
        assert "non approuvé" in sheet and "[x]" not in sheet.lower() and "☑" not in sheet
        assert sheet.count("réponse attendue") >= 10  # 5 questions × 2 languages
    assert all("approuvé le" not in t.lower() for t in files.values())
