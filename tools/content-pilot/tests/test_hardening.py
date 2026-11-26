"""Regression tests for the correction round that followed independent QA (PR #34).

Everything here uses temporary copies of the pilot or schema-only fixtures. Nothing writes outside `tmp_path`, and the
"outside" files used to prove that nothing escapes the pilot root are created in `tmp_path` too.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import replace
from pathlib import Path

import pytest
from content_pilot import cli, manifest
from content_pilot.checks import validate
from content_pilot.model import DEFAULT_LIMITS, Limits, read_json
from content_pilot.review import build_review_pack
from content_pilot.safe_eval import EvalLimits, UnsafeExpression, safe_eval
from content_pilot.safefs import ContentFileError, check_relative, loads_strict, write_text_atomic

from .conftest import L1, L2, L3, L5, L6, PILOT, REPO, edit_json

LESSONS = sorted(p.name for p in (PILOT / "lessons").iterdir())


def run(root: Path, limits: Limits | None = None):
    return validate(root, repo_root=REPO, forbid_approvals=True, limits=limits)


def codes(root: Path, limits: Limits | None = None) -> set[str]:
    return {f.code for f in run(root, limits) if f.severity == "error"}


def load(rel: str):
    return read_json(PILOT / rel)


# ============================================================== missing or malformed mathematical verification
@pytest.mark.parametrize(
    ("label", "document"),
    [("null", None), ("list", []), ("string", "ok"), ("empty object", {}), ("empty questions", {"questions": {}, "examples": []})],
)
def test_verification_document_must_be_a_typed_object(pilot_copy, label, document):
    (pilot_copy / L1 / "verification.json").write_text(json.dumps(document))
    assert "verification_schema" in codes(pilot_copy), label


def test_example_with_no_checks_or_no_examples_is_not_a_green_lesson(pilot_copy):
    edit_json(pilot_copy, f"{L1}/verification.json", lambda v: v["examples"][0].update(checks=[]))
    assert "verification_schema" in codes(pilot_copy)
    edit_json(pilot_copy, f"{L1}/verification.json", lambda v: v.update(examples=[]))
    assert "verification_schema" in codes(pilot_copy)


@pytest.mark.parametrize("field", ["prompt_numbers", "choices", "mode"])
def test_every_required_verification_field_is_required(pilot_copy, field):
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["questions"]["addition-posee"].pop(field))
    assert "verification_schema" in codes(pilot_copy)


def test_unknown_verification_fields_and_wrong_types_are_refused(pilot_copy):
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["questions"]["addition-posee"].update(extra=1))
    assert "verification_schema" in codes(pilot_copy)
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["questions"]["addition-posee"].update(extra=None, compute=456))
    assert "verification_schema" in codes(pilot_copy)


def test_a_verified_example_listed_twice_is_refused(pilot_copy):
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["examples"].append(v["examples"][0]))
    assert "verification_schema" in codes(pilot_copy)


def test_unreadable_verification_file_is_a_finding_not_a_crash(pilot_copy):
    (pilot_copy / L1 / "verification.json").write_bytes(b"\xff\xfe\x00bad")
    assert "json_invalid" in codes(pilot_copy)


# ============================================================== reversed operands and changed signs
def test_reversed_operands_in_both_languages_still_disagree_with_the_verified_operation(pilot_copy):
    for loc in ("fr", "ht"):
        edit_json(pilot_copy, f"{L2}/questions.{loc}.json", lambda q: q[1]["prompt"].update(text="Calcule : 345 − 702"))
    assert "prompt_binding" in codes(pilot_copy)


def test_a_changed_operator_in_both_languages_is_caught(pilot_copy):
    for loc in ("fr", "ht"):
        edit_json(pilot_copy, f"{L2}/questions.{loc}.json", lambda q: q[0]["prompt"].update(text="Calcule : 456 − 378"))
    assert "prompt_binding" in codes(pilot_copy)


def test_a_prompt_with_an_arithmetic_sign_but_no_bound_operation_is_refused(pilot_copy):
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["questions"]["addition-posee"].pop("prompt_math"))
    assert "prompt_binding" in codes(pilot_copy)


def test_the_equality_a_prompt_states_must_be_true(pilot_copy):
    for loc in ("fr", "ht"):
        edit_json(pilot_copy, f"{L2}/questions.{loc}.json", lambda q: q[4]["prompt"].update(text=q[4]["prompt"]["text"].replace("= 280", "= 290")))
    edit_json(
        pilot_copy,
        f"{L2}/verification.json",
        lambda v: v["questions"]["verifier-soustraction"].update(prompt_math="540 − 260 = 290", prompt_numbers=[540, 260, 290]),
    )
    assert "prompt_binding" in codes(pilot_copy)


def test_comparison_sign_changed_in_a_translated_block_is_caught(pilot_copy):
    def flip(blocks):
        block = next(b for b in blocks if b["key"] == "exemple-comparer-2")
        assert any("<" in step for step in block["steps"])
        block["steps"] = [step.replace("<", ">") for step in block["steps"]]

    edit_json(pilot_copy, f"{L1}/blocks.ht.json", flip)
    assert any(f.code == "translation_numbers" and "signs" in f.message for f in run(pilot_copy))


def test_reversed_operands_in_a_translated_worked_example_are_caught(pilot_copy):
    def reverse(blocks):
        for b in blocks:
            if b["key"] == "exemple-soustraction":
                b["steps"][-1] = b["steps"][-1].replace("623 − 275", "275 − 623")

    edit_json(pilot_copy, f"{L2}/blocks.ht.json", reverse)
    assert {"translation_numbers", "example_not_shown"} <= codes(pilot_copy)


def test_example_line_must_be_the_checked_operation(pilot_copy):
    # same value, operands reversed: the displayed line is 8 + 5 = 13, the check says 5 + 8
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["examples"][0]["checks"][0].update(expr="5 + 8", equals=13))
    assert "example_not_bound" in codes(pilot_copy)


def test_choice_signs_and_numbers_are_bound_to_the_verified_claim(pilot_copy):
    def swap(questions):
        right = next(c for c in questions[4]["response_spec"]["choices"] if c["id"] == "a")
        right["text"] = "280 − 260 = 540"  # the correct choice now claims a subtraction

    for loc in ("fr", "ht"):
        edit_json(pilot_copy, f"{L2}/questions.{loc}.json", swap)
    assert "choice_binding" in codes(pilot_copy)


# ============================================================== locale-file substitution
@pytest.mark.parametrize("kind", ["blocks", "questions"])
def test_a_locale_must_use_its_own_named_file(pilot_copy, kind):
    edit_json(pilot_copy, "pilot.json", lambda d: d["lessons"][0]["files"][kind].update(ht=d["lessons"][0]["files"][kind]["fr"]))
    assert "pilot_schema" in codes(pilot_copy)


def test_a_file_reference_that_names_another_lesson_is_refused(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda d: d["lessons"][0]["files"]["blocks"].update(fr=d["lessons"][1]["files"]["blocks"]["fr"]))
    assert "file_reference" in codes(pilot_copy)


def test_manifest_and_sizes_refuse_swapped_files(pilot_copy):
    edit_json(pilot_copy, "pilot.json", lambda d: d["lessons"][0]["files"]["questions"].update(fr=d["lessons"][1]["files"]["questions"]["fr"]))
    with pytest.raises(ContentFileError):
        manifest.build_manifest(pilot_copy)
    with pytest.raises(ContentFileError):
        manifest.sizes(pilot_copy)


# ============================================================== descriptor path traversal, symlinks: nothing escapes
class Recorder:
    """Instrument the file operations of the tool, then assert that nothing under the 'outside' directory was touched.

    Recording stops as soon as `touched` is called, because resolving paths for the assertion uses the same functions.
    """

    def __init__(self, monkeypatch):
        self.paths: list[str] = []
        self.recording = True
        for name in ("open", "lstat", "scandir", "stat"):
            monkeypatch.setattr(os, name, self._wrap(getattr(os, name)))

    def _wrap(self, real):
        def wrapper(path, *a, **k):
            if self.recording and isinstance(path, (str, bytes, os.PathLike)):
                self.paths.append(os.fsdecode(path))
            return real(path, *a, **k)

        return wrapper

    def touched(self, outside: Path) -> list[str]:
        self.recording = False
        root = os.path.abspath(outside)  # literal comparison: a link inside the pilot is only inspected, never followed
        return [p for p in self.paths if os.path.abspath(p) == root or os.path.abspath(p).startswith(root + os.sep)]


@pytest.fixture()
def outside(tmp_path) -> Path:
    d = tmp_path / "outside-secret"
    d.mkdir()
    (d / "secret.json").write_text('{"secret": true}')
    return d


@pytest.mark.parametrize("kind", ["absolute", "parent", "backslash", "nul", "dot"])
def test_descriptor_paths_cannot_leave_the_pilot_root(pilot_copy, outside, monkeypatch, kind):
    target = {
        "absolute": str(outside / "secret.json"),
        "parent": "../outside-secret/secret.json",
        "backslash": "lessons\\..\\..\\outside-secret\\secret.json",
        "nul": "lessons/01-x\x00/../../outside-secret/secret.json",
        "dot": "./../outside-secret/secret.json",
    }[kind]
    edit_json(pilot_copy, "pilot.json", lambda d: d["lessons"][0]["files"].update(verification=target))
    rec = Recorder(monkeypatch)
    assert codes(pilot_copy) & {"pilot_schema", "file_reference"}
    with pytest.raises(ContentFileError):
        manifest.build_manifest(pilot_copy)
    assert rec.touched(outside) == []


def test_symlinked_lesson_file_is_refused_and_never_followed(pilot_copy, outside, monkeypatch):
    victim = pilot_copy / L1 / "blocks.fr.json"
    victim.unlink()
    victim.symlink_to(outside / "secret.json")
    rec = Recorder(monkeypatch)
    assert "file_unsafe" in codes(pilot_copy)
    assert manifest.verify_manifest(pilot_copy)
    with pytest.raises(ContentFileError):
        manifest.build_manifest(pilot_copy)
    assert rec.touched(outside) == []  # not even a stat: the link itself is inspected, its target never is


def test_symlinked_lesson_directory_is_refused_and_never_followed(pilot_copy, outside, monkeypatch):
    real = pilot_copy / L2
    moved = outside / "copy-of-lesson-2"
    real.rename(moved)
    real.symlink_to(moved, target_is_directory=True)
    rec = Recorder(monkeypatch)
    assert "file_unsafe" in codes(pilot_copy)
    with pytest.raises(ContentFileError):
        manifest.build_manifest(pilot_copy)
    rec.recording = False
    opened_behind_link = [p for p in rec.paths if p.startswith(str(moved)) and p.endswith(".json")]
    assert opened_behind_link == []


def test_symlinked_descriptor_is_refused(pilot_copy, outside):
    desc = pilot_copy / "pilot.json"
    other = outside / "pilot.json"
    other.write_text(desc.read_text())
    desc.unlink()
    desc.symlink_to(other)
    assert "file_unsafe" in codes(pilot_copy)


def test_non_regular_files_are_refused_without_blocking(pilot_copy):
    fifo = pilot_copy / L1 / "blocks.fr.json"
    fifo.unlink()
    os.mkfifo(fifo)
    assert stat.S_ISFIFO(os.lstat(fifo).st_mode)
    assert "file_unsafe" in codes(pilot_copy)


def test_unlisted_extra_files_and_links_are_reported(pilot_copy, outside):
    (pilot_copy / "lessons" / "extra.json").write_text("[]")
    (pilot_copy / "lessons" / "link.json").symlink_to(outside / "secret.json")
    found = {(f.code, f.where) for f in run(pilot_copy)}
    assert ("unexpected_file", "lessons/extra.json") in found
    assert ("file_unsafe", "lessons/link.json") in found


def test_review_pack_never_writes_through_an_existing_link(pilot_copy, tmp_path):
    out = tmp_path / "review"
    out.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    (out / "answer-key-overview.md").symlink_to(victim)
    assert cli.main(["review-pack", "--write", "--root", str(pilot_copy), "--review-dir", str(out)]) == 2
    assert victim.read_text() == "keep me"


def test_review_pack_refuses_a_linked_output_directory(pilot_copy, tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    link = tmp_path / "review-link"
    link.symlink_to(real, target_is_directory=True)
    assert cli.main(["review-pack", "--write", "--root", str(pilot_copy), "--review-dir", str(link)]) == 2
    assert list(real.iterdir()) == []


def test_review_pack_output_names_come_only_from_a_valid_descriptor(pilot_copy, tmp_path):
    edit_json(pilot_copy, "pilot.json", lambda d: d["lessons"][0].update(slug="../../escape"))
    out = tmp_path / "review"
    assert cli.main(["review-pack", "--write", "--root", str(pilot_copy), "--review-dir", str(out)]) == 2
    assert not (tmp_path / "escape").exists() and not out.exists()


def test_atomic_writer_refuses_links_and_unsafe_names(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    d = tmp_path / "d"
    d.mkdir()
    (d / "x.md").symlink_to(victim)
    with pytest.raises(ContentFileError):
        write_text_atomic(d, "x.md", "new")
    assert victim.read_text() == "keep me"
    with pytest.raises(ContentFileError):
        write_text_atomic(d, "../x.md", "new")


@pytest.mark.parametrize("bad", ["", "/abs", "../x", "a/../b", "a//b", "a/", "a\\b", "a\x00b", "./a", "é.json", "a" * 300])
def test_check_relative_rejects_everything_but_plain_relative_names(bad):
    with pytest.raises(ContentFileError):
        check_relative(bad)


# ============================================================== bounded resource consumption
def small(**kw) -> Limits:
    return replace(DEFAULT_LIMITS, **kw)


def test_oversized_files_are_refused_before_parsing(pilot_copy):
    assert "file_too_large" in {x.code for x in run(pilot_copy, small(max_file_bytes=1000))}


def test_oversized_descriptor_is_refused(pilot_copy):
    assert {x.code for x in run(pilot_copy, small(max_descriptor_bytes=1000))} == {"file_too_large"}


def test_too_many_files_or_bytes_stop_the_run_before_any_lesson_is_read(pilot_copy):
    assert "resource_limit" in {x.code for x in run(pilot_copy, small(max_files=5))}
    only = run(pilot_copy, small(max_total_bytes=1000))
    assert [x.code for x in only if x.severity == "error"] == ["resource_limit"]


def test_deeply_nested_json_is_a_finding_not_a_crash(pilot_copy):
    (pilot_copy / L1 / "questions.fr.json").write_text("[" * 5000 + "]" * 5000)
    assert "json_invalid" in codes(pilot_copy)
    (pilot_copy / L1 / "questions.fr.json").write_text("[" * 60 + "]" * 60)
    assert "json_invalid" in codes(pilot_copy)


@pytest.mark.parametrize("payload", [b"\xef\xbb\xbf[]", b"[NaN]", b"[Infinity]", b'{"a": 1, "a": 2}', b"[1" + b"0" * 5000 + b"]", b"\xc3("])
def test_strict_json_loader_rejects_ambiguous_documents(payload):
    with pytest.raises(ContentFileError):
        loads_strict(payload)


def test_duplicate_member_inside_a_lesson_file_is_rejected(pilot_copy):
    p = pilot_copy / L2 / "verification.json"
    p.write_text(p.read_text().replace('"examples":', '"examples": [], "examples":', 1))
    assert "json_duplicate_member" in codes(pilot_copy)


def test_evaluator_arithmetic_is_numeric_only():
    for bad in ("[2] * 2", "[1, 2] * 3", "(1, 2) + (3,)", "True + True", "1 + [2]", "-[1]", "2 ** [1]", "'ab' * 3", "2.5 + 1", "1 / 2"):
        with pytest.raises(UnsafeExpression):
            safe_eval(bad)


@pytest.mark.parametrize(
    ("limits", "expr", "fragment"),
    [
        (EvalLimits(max_nodes=10), "1 + 1 + 1 + 1 + 1 + 1", "syntax nodes"),
        (EvalLimits(max_depth=4), "-(-(-(-(-(-1)))))", "nested deeper"),
        (EvalLimits(max_bits=16), "300 * 300", "larger than"),
        (EvalLimits(max_bits=16), "2 ** 12", "exponent out of range"),
        (EvalLimits(max_list=5), "[1, 2, 3, 4, 5, 6]", "longer than"),
        (EvalLimits(max_range=50), "range(51)", "range too large"),
        (EvalLimits(max_chars=60), "1" + " " * 80 + "+ 1", "longer than"),
        (EvalLimits(max_steps=10), "len([a for a in range(5) if a < 9])", "step budget"),
    ],
    ids=["nodes", "depth", "bits", "pow-bits", "list", "range", "chars", "steps"],
)
def test_each_evaluator_limit_is_enforced_with_small_injected_limits(limits, expr, fragment):
    with pytest.raises(UnsafeExpression, match=fragment):
        safe_eval(expr, limits)


def test_small_injected_limits_still_allow_small_expressions():
    tiny = EvalLimits(max_chars=60, max_nodes=30, max_depth=12, max_steps=60, max_bits=16, max_list=5, max_range=50)
    assert safe_eval("1 + 2", tiny) == 3
    assert safe_eval("len([a for a in range(3)])", tiny) == 3


def test_evaluator_default_limits_stop_runaway_expressions():
    for bad in (
        "2 ** 200",
        "9 ** 12 * 9 ** 12 * 9 ** 12 * 9 ** 12",
        "sum([n for n in range(100000) if n % 2 == 0 and n % 3 == 0 and n % 7 == 0])",
        "1" + "+1" * 5000,
        "-" * 300 + "1",
        "x" * 1000,
    ):
        with pytest.raises(UnsafeExpression):
            safe_eval(bad)
    with pytest.raises(UnsafeExpression):
        safe_eval("(" * 200 + "1" + ")" * 200)


def test_a_hostile_expression_in_a_verification_file_becomes_a_finding(pilot_copy):
    edit_json(pilot_copy, f"{L2}/verification.json", lambda v: v["questions"]["calcul-mental"].update(compute="2 ** 12 ** 12"))
    assert "verification_expression" in codes(pilot_copy)


def test_the_step_budget_applies_to_real_verification_files(pilot_copy):
    lim = small(eval=EvalLimits(max_steps=40))
    assert "verification_expression" in {f.code for f in run(pilot_copy, lim)}


# ============================================================== manifest metadata
def edit_manifest(root: Path, fn) -> None:
    edit_json(root, manifest.MANIFEST_NAME, fn)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(manifest_version="pilot-preview-9"),
        lambda d: d.update(purpose="A production pack format"),
        lambda d: d["totals"].update(files=1),
        lambda d: d.update(extra="x"),
        lambda d: d["entries"].reverse(),
        lambda d: d["entries"][1].update(role="descriptor"),
        lambda d: d["entries"][1].update(lesson_id="00000000-0000-0000-0000-000000000000"),
        lambda d: d["entries"][1].update(note="added"),
        lambda d: d["entries"][1].pop("role"),
        lambda d: d.update(pilot_id="other"),
    ],
    ids=["version", "purpose", "totals", "extra-key", "order", "role", "lesson-id", "extra-entry-field", "missing-role", "pilot-id"],
)
def test_any_manifest_metadata_change_is_detected(pilot_copy, mutate):
    assert manifest.verify_manifest(pilot_copy) == []
    edit_manifest(pilot_copy, mutate)
    assert manifest.verify_manifest(pilot_copy)


def test_manifest_with_wrong_shape_is_reported_not_a_crash(pilot_copy):
    for doc in ([], "x", None, {"entries": "x"}, {"entries": [1]}):
        (pilot_copy / manifest.MANIFEST_NAME).write_text(json.dumps(doc))
        assert manifest.verify_manifest(pilot_copy)


def test_manifest_duplicate_json_member_is_reported(pilot_copy):
    p = pilot_copy / manifest.MANIFEST_NAME
    p.write_text(p.read_text().replace('"purpose":', '"purpose": "x", "purpose":', 1))
    assert manifest.verify_manifest(pilot_copy)


def test_manifest_lists_the_descriptor_named_files_exactly_once():
    committed = load(manifest.MANIFEST_NAME)
    paths = [e["path"] for e in committed["entries"]]
    assert len(paths) == len(set(paths)) == 1 + 6 * 5
    assert committed == manifest.build_manifest(PILOT)


# ============================================================== controlled exits
def test_cli_reports_hostile_input_with_a_status_not_a_traceback(pilot_copy, capsys):
    (pilot_copy / "pilot.json").write_bytes(b"\xff\xfe")
    assert cli.main(["validate", "--root", str(pilot_copy), "--repo-root", str(REPO)]) == 1
    assert "json_invalid" in capsys.readouterr().out
    assert cli.main(["manifest", "--root", str(pilot_copy)]) == 2
    assert cli.main(["sizes", "--root", str(pilot_copy)]) == 2
    assert cli.main(["review-pack", "--root", str(pilot_copy)]) == 2
    assert "error [" in capsys.readouterr().err


def test_cli_manifest_write_does_not_follow_a_link(pilot_copy, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    (pilot_copy / manifest.MANIFEST_NAME).unlink()
    (pilot_copy / manifest.MANIFEST_NAME).symlink_to(victim)
    assert cli.main(["manifest", "--write", "--root", str(pilot_copy)]) == 2
    assert victim.read_text() == "keep me"


# ============================================================== content corrections that QA asked for
def texts(path: str) -> str:
    return json.dumps(load(path), ensure_ascii=False)


def test_subtraction_warning_no_longer_teaches_to_reverse_the_order():
    for loc in ("fr", "ht"):
        warning = next(b for b in load(f"{L2}/blocks.{loc}.json") if b["key"] == "piege")["text"]
        assert "toujours le petit nombre" not in warning and "toujou wete ti nonb" not in warning
        assert "623 − 275" in warning and "275 − 623" in warning
        assert "0" in warning  # equal operands give zero
    fr = next(b for b in load(f"{L2}/blocks.fr.json") if b["key"] == "piege")["text"]
    assert "l'ordre" in fr


def test_multiples_and_divisors_state_their_domain():
    for loc in ("fr", "ht"):
        blocks = {b["key"]: b for b in load(f"{L5}/blocks.{loc}.json")}
        assert re.search(r"\b0, 4, 8", blocks["multiples"]["text"])  # 0 is a multiple of 4
        assert "0" in blocks["diviseurs"]["text"]  # a divisor is never 0
        warning = blocks["piege"]["text"]
        assert ("positif" in warning) or ("pozitif" in warning)
        assert not any("12 ÷ 5" in s for b in blocks.values() for s in b.get("steps", []))
    assert "toujours des diviseurs" not in next(b for b in load(f"{L5}/blocks.fr.json") if b["key"] == "piege")["text"].replace(
        "pour un nombre positif, 1 et le nombre lui-même sont toujours des diviseurs", ""
    )


def test_non_exact_division_is_written_as_an_identity_not_as_an_equality_with_a_quotient():
    for rel in (f"{L5}/questions.fr.json", f"{L5}/questions.ht.json", f"{L5}/blocks.fr.json", f"{L5}/blocks.ht.json"):
        assert not re.search(r"1[08] ÷ [34] = \d,", texts(rel)), rel


def test_yes_no_questions_now_ask_for_the_reasoning_and_have_no_bare_yes_choices():
    for rel, key in ((L5, "divisible-par-8"), (L6, "cahiers-en-paquets")):
        for loc in ("fr", "ht"):
            q = next(x for x in load(f"{rel}/questions.{loc}.json") if x["question_key"] == key)
            assert re.search(r"phrases? montre|raisons? permet|fraz ki montre|rezon ki pèmèt", q["prompt"]["text"]), (rel, loc)
            assert not re.search(r"^(Oui|Non|Wi)\b", "\n".join(c["text"] for c in q["response_spec"]["choices"]), re.M)


def test_last_lesson_question_no_longer_repeats_the_opening_scenario():
    for loc in ("fr", "ht"):
        intro = next(b for b in load(f"{L6}/blocks.{loc}.json") if b["key"] == "intro")["text"]
        q = next(x for x in load(f"{L6}/questions.{loc}.json") if x["question_key"] == "cahiers-en-paquets")
        assert q["prompt"]["text"] not in intro and "135" not in q["prompt"]["text"]


def test_distractors_of_the_division_identity_question_are_all_different():
    ver = load(f"{L3}/verification.json")["questions"]["egalite-division"]["choices"]
    right_hand = [entry["expr"].split("==")[1].strip() for entry in ver.values()]
    values = [eval(expr, {"__builtins__": {}}, {}) for expr in right_hand]  # trusted constants from this repository
    assert sorted(values) == sorted(set(values)) or values.count(29) == 1
    assert len({v for v in values if v != 29}) == 3


def test_correct_answers_are_spread_over_the_four_displayed_positions():
    positions = []
    for d in LESSONS:
        for q in load(f"lessons/{d}/questions.fr.json"):
            ids = [c["id"] for c in q["response_spec"]["choices"]]
            positions.append(ids.index(q["answer_key"]["correct_choice_id"]))
    assert len(positions) == 30
    counts = [positions.count(i) for i in range(4)]
    assert all(5 <= c <= 9 for c in counts), counts
    assert not any(positions[i] == positions[i + 1] == positions[i + 2] for i in range(len(positions) - 2))


def test_displayed_order_is_the_same_in_both_languages_and_choice_ids_are_opaque_and_stable():
    for d in LESSONS:
        fr, ht = load(f"lessons/{d}/questions.fr.json"), load(f"lessons/{d}/questions.ht.json")
        for a, b in zip(fr, ht, strict=True):
            assert [c["id"] for c in a["response_spec"]["choices"]] == [c["id"] for c in b["response_spec"]["choices"]]
            assert sorted(c["id"] for c in a["response_spec"]["choices"]) == list("abcd")


def test_review_sheets_label_choices_by_displayed_position():
    pack = build_review_pack(PILOT)
    sheet = pack["lesson-06-criteres-de-divisibilite.md"]
    q4 = sheet.split("**Q4 ·")[1].split("**Q5 ·")[0]
    lines = [ln for ln in q4.splitlines() if ln.startswith("- **")]
    assert [ln[4] for ln in lines] == list("ABCD")
    assert "← **réponse attendue**" in lines[3]  # affirmation-vraie: the correct choice is displayed last
    assert re.search(
        r"\| 6 \| Q4 \|.*\| \*\*D\*\* — 1 236 est divisible par 2, par 3 et par 4|\| 6 \| Q4 \|.*\| \*\*D\*\* — 1 236 est divisible par 2, par 3 et par 4",
        pack["answer-key-overview.md"],
    )


def test_choice_lengths_of_the_statement_question_are_comparable():
    q = next(x for x in load(f"{L6}/questions.fr.json") if x["question_key"] == "affirmation-vraie")
    lengths = [len(c["text"]) for c in q["response_spec"]["choices"]]
    assert max(lengths) <= 1.2 * min(lengths)


def test_every_lesson_remains_an_unreviewed_draft_and_nothing_is_approved():
    p = load("pilot.json")
    for lesson in p["lessons"]:
        for loc in ("fr", "ht"):
            assert lesson["review"][loc]["status"] == "draft_unreviewed" and lesson["review"][loc]["approvals"] == []
    assert "non approuvé" in p["proposal_status"]
