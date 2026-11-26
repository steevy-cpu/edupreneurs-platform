"""Validation of a content pilot directory. Every problem is a `Finding` with a stable code, so tests and
reviewers can refer to it. Nothing here touches a network, a database or the application."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .model import (
    LOCALES,
    MIN_QUESTIONS,
    REQUIRED_APPROVALS,
    SIZE_ERROR_BYTES,
    SIZE_WARN_BYTES,
    Finding,
    find_repo_root,
    minified,
    read_json,
    stable_id,
)
from .safe_eval import UnsafeExpression, safe_eval
from .textrules import NBSP, number_tokens, scan_text

TOOL_DIR = Path(__file__).resolve().parent.parent
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validator(schema_path: Path) -> Draft202012Validator:
    return Draft202012Validator(read_json(schema_path))


def _path(err: Any) -> str:
    return "/".join(str(p) for p in err.absolute_path) or "(root)"


def _strings(obj: Any, prefix: str = "") -> list[tuple[str, str]]:
    """All (path, text) string leaves, so text rules apply everywhere."""
    out: list[tuple[str, str]] = []
    if isinstance(obj, str):
        out.append((prefix, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out += _strings(v, f"{prefix}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _strings(v, f"{prefix}/{i}")
    return out


# Fields that hold identifiers, not prose.
_NON_PROSE = re.compile(r"/(key|type|tone|id|correct_choice_id|question_key)$")


def _text_findings(obj: Any, where: str) -> list[Finding]:
    out: list[Finding] = []
    for path, text in _strings(obj):
        if _NON_PROSE.search(path):
            continue
        for code, msg in scan_text(text):
            out.append(Finding(code, f"{where}{path}", msg))
    return out


def _plain(s: str) -> str:
    return re.sub(r"[\s\u00a0]+", "", s)


def validate(root: Path, *, repo_root: Path | None = None, forbid_approvals: bool = False) -> list[Finding]:
    root = Path(root)
    repo = repo_root or find_repo_root(root.resolve())
    findings: list[Finding] = []
    add = findings.append

    blocks_v = _validator(repo / "packages/contracts/content/lesson-blocks.schema.json")
    mcq_v = _validator(repo / "packages/contracts/content/question-mcq.schema.json")
    pilot_v = _validator(TOOL_DIR / "schemas/pilot.schema.json")

    pilot_path = root / "pilot.json"
    if not pilot_path.exists():
        return [Finding("pilot_missing", str(pilot_path), "pilot.json not found")]
    try:
        pilot = read_json(pilot_path)
    except json.JSONDecodeError as exc:
        return [Finding("json_invalid", "pilot.json", str(exc))]

    for err in pilot_v.iter_errors(pilot):
        add(Finding("pilot_schema", f"pilot.json:{_path(err)}", err.message))
    if findings:  # structure is unusable beyond this point
        return findings
    findings += _text_findings(
        {"unit": pilot["unit"]["titles"], "lessons": [{"titles": x["titles"], "objectives": x["objectives"]} for x in pilot["lessons"]]},
        "pilot.json",
    )

    source_ids = {s["id"] for s in pilot["sources"]}
    if len(source_ids) != len(pilot["sources"]):
        add(Finding("source_duplicate", "pilot.json:sources", "duplicate source id"))
    if pilot["unit"]["id"] != stable_id("unit", pilot["unit"]["slug"]):
        add(Finding("unstable_id", "pilot.json:unit.id", "unit id is not the deterministic uuid5 of its slug"))

    positions = [x["position"] for x in pilot["lessons"]]
    if positions != list(range(1, len(positions) + 1)):
        add(Finding("lesson_positions", "pilot.json:lessons", f"positions must be 1..n in order, got {positions}"))
    slugs = [x["slug"] for x in pilot["lessons"]]
    ids = [x["id"] for x in pilot["lessons"]]
    if len(set(slugs)) != len(slugs) or len(set(ids)) != len(ids):
        add(Finding("lesson_duplicate", "pilot.json:lessons", "duplicate lesson slug or id"))

    for lesson in pilot["lessons"]:
        findings += _validate_lesson(root, lesson, source_ids, blocks_v, mcq_v, forbid_approvals)
    return findings


def _validate_lesson(
    root: Path,
    lesson: dict[str, Any],
    source_ids: set[str],
    blocks_v: Draft202012Validator,
    mcq_v: Draft202012Validator,
    forbid_approvals: bool,
) -> list[Finding]:
    out: list[Finding] = []
    add = out.append
    slug = lesson["slug"]
    w = f"lesson:{slug}"

    if lesson["id"] != stable_id("lesson", slug):
        add(Finding("unstable_id", f"{w}:id", "lesson id is not the deterministic uuid5 of its slug"))
    for ref in lesson["curriculum_refs"]:
        if ref["source"] not in source_ids:
            add(Finding("unknown_source", f"{w}:curriculum_refs", f"source {ref['source']} is not in the source register"))

    # -- rights
    rights = lesson["rights"]
    if rights["third_party_material"]:
        add(Finding("rights_third_party", f"{w}:rights", "third-party material is not allowed in this pilot without an explicit rights record"))
    if rights["licence_status"] == "assigned" and not rights.get("licence"):
        add(Finding("rights_licence_missing", f"{w}:rights", "licence_status is 'assigned' but no licence is named"))
    if "licence" in rights and rights["licence_status"] != "assigned":
        add(Finding("rights_inconsistent", f"{w}:rights", "a licence is named but licence_status is not 'assigned'"))

    # -- review status
    for loc in LOCALES:
        rv = lesson["review"][loc]
        roles_done = {a["role"] for a in rv["approvals"]}
        if tuple(sorted(rv["required_approvals"])) != tuple(sorted(REQUIRED_APPROVALS)):
            add(Finding("review_requirements", f"{w}:review.{loc}", "every draft requires both a mathematics teacher and a native speaker"))
        if rv["status"] == "approved":
            if forbid_approvals:
                add(Finding("approval_forbidden", f"{w}:review.{loc}", "this pilot must not contain approvals before a human review"))
            missing = set(REQUIRED_APPROVALS) - roles_done
            if missing:
                add(Finding("approved_without_approvals", f"{w}:review.{loc}", f"status 'approved' but missing approvals: {sorted(missing)}"))
        elif roles_done:
            add(Finding("approvals_without_status", f"{w}:review.{loc}", "approvals are recorded but status is not 'approved'", "warning"))

    # -- files
    loaded: dict[str, dict[str, Any]] = {"blocks": {}, "questions": {}}
    for kind in ("blocks", "questions"):
        for loc in LOCALES:
            rel = lesson["files"][kind][loc]
            p = root / rel
            if not p.exists():
                note = " (missing translation)" if kind == "blocks" else ""
                add(Finding("file_missing", f"{w}:{rel}", f"{kind} file for locale {loc} is missing{note}"))
                continue
            try:
                loaded[kind][loc] = read_json(p)
            except json.JSONDecodeError as exc:
                add(Finding("json_invalid", f"{w}:{rel}", str(exc)))
    vrel = lesson["files"]["verification"]
    verification: dict[str, Any] | None = None
    if not (root / vrel).exists():
        add(Finding("file_missing", f"{w}:{vrel}", "verification file missing"))
    else:
        try:
            verification = read_json(root / vrel)
        except json.JSONDecodeError as exc:
            add(Finding("json_invalid", f"{w}:{vrel}", str(exc)))

    # -- lesson blocks: contract, uniqueness, text rules
    for loc, blocks in loaded["blocks"].items():
        where = f"{w}:blocks.{loc}"
        for err in blocks_v.iter_errors(blocks):
            add(Finding("blocks_schema", f"{where}:{_path(err)}", err.message))
        if isinstance(blocks, list):
            keys = [b.get("key") for b in blocks if isinstance(b, dict)]
            for k, n in Counter(keys).items():
                if n > 1:
                    add(Finding("duplicate_key", where, f"block key {k!r} appears {n} times"))
            if not any(isinstance(b, dict) and b.get("type") == "example" for b in blocks):
                add(Finding("no_worked_example", where, "a lesson needs at least one worked example"))
        out.extend(_text_findings(blocks, where))

    # -- language mapping of blocks
    fr_b, ht_b = loaded["blocks"].get("fr"), loaded["blocks"].get("ht")
    if isinstance(fr_b, list) and isinstance(ht_b, list) and all(isinstance(b, dict) for b in [*fr_b, *ht_b]):
        out += _compare_blocks(w, fr_b, ht_b)

    # -- questions
    for loc, questions in loaded["questions"].items():
        out += _validate_questions(w, loc, questions, mcq_v)
    fr_q, ht_q = loaded["questions"].get("fr"), loaded["questions"].get("ht")
    if isinstance(fr_q, list) and isinstance(ht_q, list) and all(isinstance(q, dict) for q in [*fr_q, *ht_q]):
        out += _compare_questions(w, fr_q, ht_q)

    # -- mathematical verification
    if verification is not None:
        out += _verify_math(w, verification, loaded)

    # -- size budget
    for loc in LOCALES:
        if loc in loaded["blocks"] and loc in loaded["questions"]:
            size = len(minified(loaded["blocks"][loc])) + len(minified(loaded["questions"][loc]))
            if size > SIZE_ERROR_BYTES:
                add(Finding("size_over_budget", f"{w}:{loc}", f"{size} bytes exceeds the {SIZE_ERROR_BYTES}-byte unit budget"))
            elif size > SIZE_WARN_BYTES:
                add(Finding("size_large", f"{w}:{loc}", f"{size} bytes is above the {SIZE_WARN_BYTES}-byte advisory size", "warning"))
    return out


def _compare_blocks(w: str, fr: list[Any], ht: list[Any]) -> list[Finding]:
    out: list[Finding] = []

    def sig(bs: list[Any]) -> list[tuple[Any, Any]]:
        return [(b.get("key"), b.get("type")) for b in bs]

    if sig(fr) != sig(ht):
        return [Finding("translation_structure", f"{w}:blocks", f"fr and ht blocks differ in keys/types/order: fr={sig(fr)} ht={sig(ht)}")]
    for a, b in zip(fr, ht, strict=True):
        key = a["key"]
        if a["type"] == "callout" and a.get("tone") != b.get("tone"):
            out.append(Finding("translation_structure", f"{w}:blocks/{key}", "callout tone differs between fr and ht"))
        if a["type"] == "example" and len(a.get("steps", [])) != len(b.get("steps", [])):
            out.append(Finding("translation_structure", f"{w}:blocks/{key}", "example has a different number of steps in fr and ht"))
        if number_tokens(json.dumps(a, ensure_ascii=False)) != number_tokens(json.dumps(b, ensure_ascii=False)):
            out.append(Finding("translation_numbers", f"{w}:blocks/{key}", "the numbers in fr and ht differ (a translation must not change the mathematics)"))
    return out


def _validate_questions(w: str, loc: str, questions: Any, mcq_v: Draft202012Validator) -> list[Finding]:
    out: list[Finding] = []
    where = f"{w}:questions.{loc}"
    if not isinstance(questions, list):
        return [Finding("questions_schema", where, "questions file must be a JSON array")]
    if len(questions) < MIN_QUESTIONS:
        out.append(Finding("question_count", where, f"{len(questions)} questions; the pilot requires at least {MIN_QUESTIONS}"))
    dicts = [q for q in questions if isinstance(q, dict)]
    for k, n in Counter(q.get("question_key") for q in dicts).items():
        if n > 1:
            out.append(Finding("duplicate_key", where, f"question key {k!r} appears {n} times"))
    if [q.get("position") for q in dicts] != list(range(1, len(dicts) + 1)):
        out.append(Finding("question_positions", where, "question positions must be 1..n in order"))
    for t, n in Counter(q.get("prompt", {}).get("text") if isinstance(q.get("prompt"), dict) else None for q in dicts).items():
        if n > 1:
            out.append(Finding("duplicate_prompt", where, f"identical prompt appears {n} times: {t!r}"))
    for q in questions:
        if not isinstance(q, dict):
            out.append(Finding("questions_schema", where, "each question must be an object"))
            continue
        qw = f"{where}/{q.get('question_key', '?')}"
        extra = set(q) - {"question_key", "position", "prompt", "response_spec", "answer_key", "explanation"}
        if extra:
            out.append(Finding("questions_schema", qw, f"unexpected field(s): {sorted(extra)}"))
        contract = {k: q[k] for k in ("prompt", "response_spec", "answer_key", "explanation") if k in q}
        for err in mcq_v.iter_errors(contract):
            out.append(Finding("question_schema", f"{qw}:{_path(err)}", err.message))
        spec = q.get("response_spec")
        chs = [c for c in (spec.get("choices", []) if isinstance(spec, dict) else []) if isinstance(c, dict)]
        ids = [c.get("id") for c in chs]
        texts = [_plain(str(c.get("text", ""))).lower() for c in chs]
        if len(set(ids)) != len(ids):
            out.append(Finding("duplicate_choice_id", qw, "choice ids must be unique"))
        if len(set(texts)) != len(texts):
            out.append(Finding("duplicate_choice_text", qw, "two choices have the same text"))
        ak = q.get("answer_key")
        correct = ak.get("correct_choice_id") if isinstance(ak, dict) else None
        if ids.count(correct) != 1:
            out.append(Finding("malformed_answer", qw, f"correct_choice_id {correct!r} must match exactly one choice id {ids}"))
        out.extend(_text_findings({k: q[k] for k in ("prompt", "response_spec", "explanation") if k in q}, qw))
    return out


def _compare_questions(w: str, fr: list[Any], ht: list[Any]) -> list[Finding]:
    out: list[Finding] = []
    if [q.get("question_key") for q in fr] != [q.get("question_key") for q in ht]:
        return [Finding("translation_structure", f"{w}:questions", "fr and ht questions differ in count or keys")]

    def choices(q: dict[str, Any]) -> list[dict[str, Any]]:
        spec = q.get("response_spec")
        return [c for c in (spec.get("choices", []) if isinstance(spec, dict) else []) if isinstance(c, dict)]

    for a, b in zip(fr, ht, strict=True):
        qk = a.get("question_key")
        if [c.get("id") for c in choices(a)] != [c.get("id") for c in choices(b)]:
            out.append(Finding("translation_structure", f"{w}:questions/{qk}", "choice ids/order differ between fr and ht"))
        if a.get("answer_key") != b.get("answer_key"):
            out.append(Finding("translation_answer_key", f"{w}:questions/{qk}", "the correct choice differs between fr and ht"))
        for part in ("prompt", "response_spec", "explanation"):
            if number_tokens(json.dumps(a.get(part), ensure_ascii=False)) != number_tokens(json.dumps(b.get(part), ensure_ascii=False)):
                out.append(Finding("translation_numbers", f"{w}:questions/{qk}/{part}", "the numbers in fr and ht differ"))
    return out


def _eval(expr: Any, where: str, out: list[Finding]) -> Any:
    if not isinstance(expr, str):
        out.append(Finding("verification_schema", where, "expression must be a string"))
        return None
    try:
        return safe_eval(expr)
    except (UnsafeExpression, ZeroDivisionError, TypeError, ValueError) as exc:
        out.append(Finding("verification_expression", where, f"cannot evaluate {expr!r}: {exc}"))
        return None


def _first_number(text: str) -> int | None:
    m = re.match(r"\s*(\d+(?:\u00a0\d{3})*)(?:\s|$)", text)
    return int(m.group(1).replace(NBSP, "")) if m else None


def _verify_value(qw: str, spec: dict[str, Any], q: dict[str, Any], choices: dict[str, Any], correct: Any, out: list[Finding]) -> None:
    computed = _eval(spec.get("compute"), qw, out)
    values = {cid: spec["choices"][cid] for cid in choices}
    hits = [cid for cid, v in values.items() if computed is not None and v == computed]
    if computed is not None and len(hits) != 1:
        out.append(Finding("answer_not_unique", qw, f"computed {computed!r}; {len(hits)} choices equal it (need exactly one)"))
    elif hits and hits[0] != correct:
        out.append(Finding("wrong_answer_key", qw, f"computed {computed!r} matches choice {hits[0]!r} but the key says {correct!r}"))
    if len({json.dumps(v) for v in values.values()}) != len(values):
        out.append(Finding("duplicate_choice_value", qw, "two choices carry the same value"))
    for cid, v in values.items():
        if isinstance(v, int) and not isinstance(v, bool):
            shown = _first_number(str(choices[cid].get("text", "")))
            if shown is not None and shown != v:
                out.append(Finding("choice_text_mismatch", f"{qw}/{cid}", f"choice shows {shown} but its verified value is {v}"))
    if isinstance(computed, int) and not isinstance(computed, bool):
        expl = q.get("explanation", {}).get("text", "")
        if computed not in {int(t.replace(NBSP, "")) for t in number_tokens(expl)}:
            out.append(Finding("explanation_missing_answer", qw, f"the explanation never states the verified answer {computed}"))


def _verify_truth(qw: str, spec: dict[str, Any], correct: Any, out: list[Finding]) -> None:
    truths = {cid: _eval(expr, f"{qw}/{cid}", out) for cid, expr in spec["choices"].items()}
    if not all(isinstance(t, bool) for t in truths.values()):
        if all(t is not None for t in truths.values()):
            out.append(Finding("verification_schema", qw, "every truth expression must evaluate to true or false"))
        return
    true_ids = [cid for cid, t in truths.items() if t is True]
    if len(true_ids) != 1:
        out.append(Finding("answer_not_unique", qw, f"{len(true_ids)} choices are true (need exactly one): {true_ids}"))
    elif true_ids[0] != correct:
        out.append(Finding("wrong_answer_key", qw, f"the true choice is {true_ids[0]!r} but the key says {correct!r}"))


def _verify_math(w: str, ver: dict[str, Any], loaded: dict[str, dict[str, Any]]) -> list[Finding]:
    out: list[Finding] = []
    qspecs = ver.get("questions")
    if not isinstance(qspecs, dict):
        return [Finding("verification_schema", f"{w}:verification", "'questions' object missing")]
    for loc, questions in loaded["questions"].items():
        if not isinstance(questions, list):
            continue
        qmap = {q.get("question_key"): q for q in questions if isinstance(q, dict)}
        for qk in qmap:
            if qk not in qspecs:
                out.append(Finding("unverified_question", f"{w}:questions.{loc}/{qk}", "no mathematical verification entry for this question"))
        for qk, spec in qspecs.items():
            qw = f"{w}:verify/{loc}/{qk}"
            q = qmap.get(qk)
            if q is None:
                out.append(Finding("verification_orphan", qw, "verification entry has no matching question"))
                continue
            spec_choices = q.get("response_spec", {}).get("choices", []) if isinstance(q.get("response_spec"), dict) else []
            choices = {c["id"]: c for c in spec_choices if isinstance(c, dict) and "id" in c}
            ak = q.get("answer_key")
            correct = ak.get("correct_choice_id") if isinstance(ak, dict) else None
            if set(spec.get("choices", {})) != set(choices):
                out.append(
                    Finding(
                        "verification_choices", qw, f"verification choices {sorted(spec.get('choices', {}))} do not match question choices {sorted(choices)}"
                    )
                )
                continue
            mode = spec.get("mode")
            if mode == "value":
                _verify_value(qw, spec, q, choices, correct, out)
            elif mode == "truth":
                _verify_truth(qw, spec, correct, out)
                for cid, expr in spec["choices"].items():
                    shown = {int(t.replace(NBSP, "")) for t in number_tokens(str(choices[cid].get("text", "")))}
                    used = {int(n) for n in re.findall(r"\d+", str(expr))}
                    if not shown <= used:
                        out.append(
                            Finding(
                                "choice_text_mismatch",
                                f"{qw}/{cid}",
                                f"the choice mentions {sorted(shown - used)} which its verification expression never uses",
                            )
                        )
            else:
                out.append(Finding("verification_schema", qw, f"unknown mode {mode!r}"))

    # worked examples: every example block must have checks; each result must be computed and shown
    examples = ver.get("examples", [])
    checked = {e.get("block") for e in examples if isinstance(e, dict)}
    for loc, blocks in loaded["blocks"].items():
        if not isinstance(blocks, list):
            continue
        by_key = {b.get("key"): b for b in blocks if isinstance(b, dict)}
        for b in by_key.values():
            if b.get("type") == "example" and b.get("key") not in checked:
                out.append(Finding("example_unverified", f"{w}:blocks.{loc}/{b.get('key')}", "worked example has no verification entry"))
        for e in examples:
            blk = by_key.get(e.get("block"))
            if blk is None or blk.get("type") != "example":
                out.append(Finding("verification_orphan", f"{w}:examples/{e.get('block')}", "no such example block"))
                continue
            text = _plain(" ".join(blk.get("steps", [])))
            for chk in e.get("checks", []):
                ew = f"{w}:examples/{e.get('block')}/{loc}"
                got = _eval(chk.get("expr"), ew, out)
                if got is not None and got != chk.get("equals"):
                    out.append(Finding("example_wrong", ew, f"{chk.get('expr')!r} evaluates to {got!r}, not {chk.get('equals')!r}"))
                if _plain(str(chk.get("must_appear", ""))) not in text:
                    out.append(Finding("example_not_shown", ew, f"the example does not show {chk.get('must_appear')!r}"))
    return out


def summarize(findings: list[Finding]) -> tuple[int, int]:
    return (sum(f.severity == "error" for f in findings), sum(f.severity == "warning" for f in findings))
