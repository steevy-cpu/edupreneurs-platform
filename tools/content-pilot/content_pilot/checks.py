"""Validation of a content pilot directory. Every problem is a `Finding` with a stable code, so tests and
reviewers can refer to it. Nothing here touches a network, a database or the application.

Trust model: the pilot directory is UNTRUSTED data. Every path is confined to the pilot root, symbolic links are
refused, sizes are bounded before parsing, and a lesson is only called valid when its mathematical verification
record is present, well-formed, complete, and bound to what the learner actually reads (prompt numbers and order,
arithmetic signs, choice text) in BOTH languages.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .mathcheck import MathError, statements, value_of
from .model import (
    DEFAULT_LIMITS,
    LOCALES,
    MIN_QUESTIONS,
    REQUIRED_APPROVALS,
    SIZE_ERROR_BYTES,
    SIZE_WARN_BYTES,
    TOOL_DIR,
    Finding,
    Limits,
    expected_files,
    find_repo_root,
    minified,
    read_json,
    stable_id,
)
from .safe_eval import UnsafeExpression, safe_eval
from .safefs import ContentFileError, load_json_confined, scan_tree
from .textrules import NBSP, math_symbols, number_sequence, scan_text

__all__ = ["TOOL_DIR", "summarize", "validate"]

MANIFEST_NAME = "manifest.preview.json"
_FAILED: Any = object()  # returned by `_load` when the file could not be read; a JSON `null` is NOT a failure (it is bad content)


@lru_cache(maxsize=16)
def _validator_for(schema_path: str) -> Draft202012Validator:
    return Draft202012Validator(read_json(Path(schema_path)))


def _validator(schema_path: Path) -> Draft202012Validator:
    return _validator_for(str(schema_path))  # a compiled validator holds no per-document state, so it is safe to reuse


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


def _prose(obj: Any) -> str:
    """All learner-visible text of a part, in document order, one field per line."""
    return "\n".join(t for p, t in _strings(obj) if not _NON_PROSE.search(p))


def _scan_math(text: Any, where: str) -> list[Finding]:
    """Every arithmetic statement the learner reads must be TRUE (exact arithmetic, see mathcheck.py)."""
    if not isinstance(text, str):
        return []
    found, problems = statements(text)
    out = [Finding("math_false", where, f"the displayed statement {st.text!r} is false ({st.detail})") for st in found if not st.holds]
    out += [Finding("math_unparsed", where, f"arithmetic that cannot be interpreted: {p}") for p in problems]
    return out


def _math_in(obj: Any, where: str) -> list[Finding]:
    out: list[Finding] = []
    for path, text in _strings(obj):
        if not _NON_PROSE.search(path):
            out += _scan_math(text, f"{where}{path}")
    return out


_LETTERS = re.compile(r"[^\W\d_]+", re.UNICODE)


def _prose_words(text: str) -> list[str]:
    """Letter-only lowercase words: digits, signs and punctuation (legitimately shared) are ignored."""
    return [w.casefold() for w in _LETTERS.findall(text)]


def _duplicate_prose(pairs: list[tuple[str, str, str]]) -> list[str]:
    """Labels of (label, fr_text, ht_text) pairs whose prose (4+ words) is identical in both languages."""
    same = []
    for label, fr, ht in pairs:
        words = _prose_words(fr)
        if len(words) >= 4 and words == _prose_words(ht):
            same.append(label)
    return same


def _plain(s: str) -> str:
    return re.sub(r"[\s ]+", "", s)


def _load(root: Path, rel: str, max_bytes: int, where: str, out: list[Finding], *, label: str = "file", note: str = "") -> Any:
    """Load one confined JSON file; any problem becomes a Finding and `_FAILED` is returned."""
    try:
        return load_json_confined(root, rel, max_bytes)
    except FileNotFoundError:
        out.append(Finding("file_missing", f"{where}:{rel}", f"{label} is missing{note}"))
    except ContentFileError as exc:
        out.append(Finding(exc.code, f"{where}:{rel}", exc.message))
    except OSError as exc:
        out.append(Finding("file_unsafe", f"{where}:{rel}", f"cannot be read: {exc.strerror or exc}"))
    return _FAILED


def inventory(root: Path, pilot: dict[str, Any], lim: Limits) -> tuple[list[Finding], bool]:
    """Enumerate the pilot directory by handle, never following a link, within a bounded budget. Returns findings and
    whether reading must stop."""
    expected = {"pilot.json", MANIFEST_NAME}
    for lesson in pilot["lessons"]:
        files = expected_files(lesson)
        expected |= {*files["blocks"].values(), *files["questions"].values(), files["verification"]}
    entries, stopped = scan_tree(Path(root), max_entries=lim.max_entries, max_depth=4, max_bytes=lim.max_total_bytes)
    out: list[Finding] = []
    for e in entries:
        if e.kind == "link":
            out.append(Finding("file_unsafe", e.rel, "symbolic links are not allowed inside a pilot directory"))
        elif e.kind == "other":
            out.append(Finding("file_unsafe", e.rel, "only regular files are allowed inside a pilot directory"))
        elif e.kind == "file" and e.rel not in expected:
            out.append(Finding("unexpected_file", e.rel, "file is not named by the pilot descriptor"))
    files_seen = sum(e.kind == "file" for e in entries)
    if stopped is None and files_seen > lim.max_files:
        stopped = f"{files_seen} files exceed the limit of {lim.max_files}"
    if stopped:
        out.append(Finding("resource_limit", ".", f"the pilot directory exceeds its limits ({stopped})"))
    return out, stopped is not None


def validate(root: Path, *, repo_root: Path | None = None, forbid_approvals: bool = False, limits: Limits | None = None) -> list[Finding]:
    lim = limits or DEFAULT_LIMITS
    root = Path(root)
    repo = repo_root or find_repo_root(root.resolve())
    findings: list[Finding] = []
    add = findings.append

    blocks_v = _validator(repo / "packages/contracts/content/lesson-blocks.schema.json")
    mcq_v = _validator(repo / "packages/contracts/content/question-mcq.schema.json")
    pilot_v = _validator(TOOL_DIR / "schemas/pilot.schema.json")
    verif_v = _validator(TOOL_DIR / "schemas/verification.schema.json")

    try:
        pilot = load_json_confined(root, "pilot.json", lim.max_descriptor_bytes, max_depth=lim.max_json_depth)
    except FileNotFoundError:
        return [Finding("pilot_missing", str(root / "pilot.json"), "pilot.json not found")]
    except ContentFileError as exc:
        return [Finding(exc.code, "pilot.json", exc.message)]

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

    inv, stop = inventory(root, pilot, lim)
    findings += inv
    if stop:
        return findings

    for lesson in pilot["lessons"]:
        findings += _validate_lesson(root, lesson, source_ids, blocks_v, mcq_v, verif_v, forbid_approvals, lim)
    return findings


def _validate_lesson(
    root: Path,
    lesson: dict[str, Any],
    source_ids: set[str],
    blocks_v: Draft202012Validator,
    mcq_v: Draft202012Validator,
    verif_v: Draft202012Validator,
    forbid_approvals: bool,
    lim: Limits,
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

    # -- file references: exactly the names derived from the lesson position and slug (so a locale can never reuse another file)
    want = expected_files(lesson)
    for kind in ("blocks", "questions"):
        for loc in LOCALES:
            if lesson["files"][kind][loc] != want[kind][loc]:
                add(Finding("file_reference", f"{w}:files.{kind}.{loc}", f"must be {want[kind][loc]!r}, got {lesson['files'][kind][loc]!r}"))
    if lesson["files"]["verification"] != want["verification"]:
        add(Finding("file_reference", f"{w}:files.verification", f"must be {want['verification']!r}, got {lesson['files']['verification']!r}"))
    if any(f.code == "file_reference" and f.where.startswith(w) for f in out):
        return out  # never read a file the descriptor names wrongly

    # -- files (bounded, confined, strict JSON)
    loaded: dict[str, dict[str, Any]] = {"blocks": {}, "questions": {}}
    for kind in ("blocks", "questions"):
        for loc in LOCALES:
            note = " (missing translation)" if kind == "blocks" else ""
            doc = _load(root, want[kind][loc], lim.max_file_bytes, w, out, label=f"{kind} file for locale {loc}", note=note)
            if doc is not _FAILED:
                loaded[kind][loc] = doc
    verification = _load(root, want["verification"], lim.max_file_bytes, w, out, label="verification file")

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
        out.extend(_math_in(blocks, where))

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

    # -- mathematical verification: REQUIRED, typed, then bound to what learners read
    if verification is not _FAILED:
        schema_errors = [Finding("verification_schema", f"{w}:verification:{_path(e)}", e.message) for e in verif_v.iter_errors(verification)]
        out += schema_errors
        if not schema_errors:
            out += _verify_math(w, verification, loaded, lim)

    # -- size budget
    for loc in LOCALES:
        if loc in loaded["blocks"] and loc in loaded["questions"]:
            size = len(minified(loaded["blocks"][loc])) + len(minified(loaded["questions"][loc]))
            if size > SIZE_ERROR_BYTES:
                add(Finding("size_over_budget", f"{w}:{loc}", f"{size} bytes exceeds the {SIZE_ERROR_BYTES}-byte unit budget"))
            elif size > SIZE_WARN_BYTES:
                add(Finding("size_large", f"{w}:{loc}", f"{size} bytes is above the {SIZE_WARN_BYTES}-byte advisory size", "warning"))
    return out


def _same_math(a: Any, b: Any) -> str | None:
    """None when two parallel texts carry the same numbers IN THE SAME ORDER and the same signs, else why not."""
    ta, tb = _prose(a), _prose(b)
    if number_sequence(ta) != number_sequence(tb):
        return "the numbers (or their order) differ between fr and ht"
    if math_symbols(ta) != math_symbols(tb):
        return f"the arithmetic/comparison signs differ between fr ({math_symbols(ta)!r}) and ht ({math_symbols(tb)!r})"
    return None


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
        why = _same_math(a, b)
        if why:
            out.append(Finding("translation_numbers", f"{w}:blocks/{key}", f"{why} (a translation must not change the mathematics)"))
    pairs = [(f"{a['key']}/{path}", ta, tb) for a, b in zip(fr, ht, strict=True) for (path, ta), (_, tb) in zip(_prose_items(a), _prose_items(b), strict=False)]
    out += _duplicate_finding(f"{w}:blocks", pairs)
    return out


def _prose_items(obj: Any) -> list[tuple[str, str]]:
    return [(p, t) for p, t in _strings(obj) if not _NON_PROSE.search(p)]


def _duplicate_finding(where: str, pairs: list[tuple[str, str, str]]) -> list[Finding]:
    """One finding per file when prose is identical in fr and ht. Diagnostic only: it cannot judge translation quality."""
    same = _duplicate_prose(pairs)
    if not same:
        return []
    return [
        Finding(
            "translation_duplicate",
            where,
            f"{len(same)} of {len(pairs)} fr/ht text fields have identical prose (first: {same[:3]}): the ht file may hold untranslated French. "
            "Numerals, formulas and symbols may be shared; this diagnostic does not and cannot assess translation quality, which needs a native-speaker review",
        )
    ]


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
        out.extend(_math_in({k: q[k] for k in ("prompt", "explanation") if k in q}, qw))
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
        for part in ("prompt", "explanation"):
            why = _same_math(a.get(part), b.get(part))
            if why:
                out.append(Finding("translation_numbers", f"{w}:questions/{qk}/{part}", why))
        for ca, cb in zip(choices(a), choices(b), strict=False):
            why = _same_math(ca.get("text"), cb.get("text"))
            if why:
                out.append(Finding("translation_numbers", f"{w}:questions/{qk}/choice-{ca.get('id')}", why))
    pairs: list[tuple[str, str, str]] = []
    for a, b in zip(fr, ht, strict=True):
        qk = str(a.get("question_key"))
        for part in ("prompt", "explanation"):
            pairs += [(f"{qk}/{part}", _prose(a.get(part)), _prose(b.get(part)))]
        pairs += [(f"{qk}/choice-{ca.get('id')}", str(ca.get("text", "")), str(cb.get("text", ""))) for ca, cb in zip(choices(a), choices(b), strict=False)]
    out += _duplicate_finding(f"{w}:questions", pairs)
    return out


# ---------------------------------------------------------------- mathematical verification


def _eval(expr: Any, where: str, out: list[Finding], lim: Limits) -> Any:
    if not isinstance(expr, str):
        out.append(Finding("verification_schema", where, "expression must be a string"))
        return None
    try:
        return safe_eval(expr, lim.eval)
    except (UnsafeExpression, ArithmeticError, TypeError, ValueError, RecursionError) as exc:
        out.append(Finding("verification_expression", where, f"cannot evaluate {expr!r}: {exc}"))
        return None


def _literals(expr: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", expr)]


def _is_subsequence(small: list[int], big: list[int]) -> bool:
    it = iter(big)
    return all(any(x == y for y in it) for x in small)


_TRANSLIT = str.maketrans({"−": "-", "×": "*", "÷": "//", " ": None, NBSP: None})
_PLAIN_EXPR = re.compile(r"^[0-9+\-*/=<>!\s]+$")
_OP_SYMBOL = (("==", "="), ("!=", "≠"), ("<=", "≤"), (">=", "≥"), ("//", "÷"), ("<", "<"), (">", ">"), ("+", "+"), ("-", "−"), ("*", "×"))


def _expr_symbols(expr: str) -> str:
    out, i = [], 0
    while i < len(expr):
        for op, sym in _OP_SYMBOL:
            if expr.startswith(op, i):
                out.append(sym)
                i += len(op)
                break
        else:
            i += 1
    return "".join(out)


def _bind_prompt(qw: str, spec: dict[str, Any], q: dict[str, Any], out: list[Finding], lim: Limits) -> None:
    """The prompt a learner reads must be the one that was verified: same numbers in the same order, same arithmetic."""
    prompt = q.get("prompt", {}).get("text", "") if isinstance(q.get("prompt"), dict) else ""
    shown = number_sequence(prompt)
    if shown != spec["prompt_numbers"]:
        out.append(
            Finding("prompt_binding", qw, f"the prompt shows the numbers {shown} in this order, but the verified question uses {spec['prompt_numbers']}")
        )
    math = spec.get("prompt_math")
    if any(ch in prompt for ch in "+−×÷") and math is None:
        out.append(Finding("prompt_binding", qw, "the prompt contains an arithmetic sign but the verification record has no prompt_math"))
    if math is not None:
        if math.replace(NBSP, " ") not in prompt.replace(NBSP, " "):
            out.append(Finding("prompt_binding", qw, f"the prompt does not contain the verified operation {math!r}"))
        grouped = re.sub(r"(?<=\d) (?=\d{3}(?!\d))", NBSP, math)  # "6 200" -> "6<NBSP>200", as the learner text writes it
        if "=" in math:  # the prompt states an equality: it must be TRUE
            found, problems = statements(grouped)
            if problems or not found or not all(st.holds for st in found):
                out.append(Finding("prompt_binding", qw, f"the statement {math!r} shown in the prompt is false or cannot be interpreted"))
        else:
            try:
                if value_of(grouped).denominator != 1:
                    out.append(Finding("prompt_binding", qw, f"{math!r} is not an exact division: ask for the quotient and the remainder explicitly"))
            except MathError as exc:
                out.append(Finding("prompt_binding", qw, f"{math!r} cannot be evaluated: {exc}"))
            if "compute" in spec and math.translate(_TRANSLIT) != spec["compute"].translate(_TRANSLIT):
                out.append(
                    Finding(
                        "prompt_binding",
                        qw,
                        f"the verified operation {math!r} is not the computed expression {spec['compute']!r} (operands or operator differ)",
                    )
                )


def _verify_value(qw: str, spec: dict[str, Any], q: dict[str, Any], choices: dict[str, Any], correct: Any, out: list[Finding], lim: Limits) -> None:
    computed = _eval(spec.get("compute"), qw, out, lim)
    values = {cid: spec["choices"][cid] for cid in choices}
    hits = [cid for cid, v in values.items() if computed is not None and v == computed]
    if computed is not None and len(hits) != 1:
        out.append(Finding("answer_not_unique", qw, f"computed {computed!r}; {len(hits)} choices equal it (need exactly one)"))
    elif hits and hits[0] != correct:
        out.append(Finding("wrong_answer_key", qw, f"computed {computed!r} matches choice {hits[0]!r} but the key says {correct!r}"))
    if len({str(v) for v in values.values()}) != len(values):
        out.append(Finding("duplicate_choice_value", qw, "two choices carry the same value"))
    for cid, v in values.items():
        shown = number_sequence(str(choices[cid].get("text", "")))
        if not shown or shown[0] != v:
            out.append(Finding("choice_text_mismatch", f"{qw}/{cid}", f"choice shows {shown[:1] or 'no number'} but its verified value is {v}"))
    if isinstance(computed, int) and not isinstance(computed, bool):
        expl = q.get("explanation", {}).get("text", "")
        if computed not in set(number_sequence(expl)):
            out.append(Finding("explanation_missing_answer", qw, f"the explanation never states the verified answer {computed}"))
    if spec.get("operands_in_proof") and isinstance(spec.get("compute"), str):
        missing = [n for n in spec["prompt_numbers"] if n not in _literals(spec["compute"])]
        if missing:
            out.append(Finding("prompt_binding", qw, f"prompt numbers {missing} never appear in the computed expression"))


def _verify_truth(qw: str, spec: dict[str, Any], choices: dict[str, Any], correct: Any, out: list[Finding], lim: Limits) -> None:
    truths = {cid: _eval(entry["expr"], f"{qw}/{cid}", out, lim) for cid, entry in spec["choices"].items()}
    if all(isinstance(t, bool) for t in truths.values()):
        true_ids = [cid for cid, t in truths.items() if t is True]
        if len(true_ids) != 1:
            out.append(Finding("answer_not_unique", qw, f"{len(true_ids)} choices are true (need exactly one): {true_ids}"))
        elif true_ids[0] != correct:
            out.append(Finding("wrong_answer_key", qw, f"the true choice is {true_ids[0]!r} but the key says {correct!r}"))
    elif all(t is not None for t in truths.values()):
        out.append(Finding("verification_schema", qw, "every truth expression must evaluate to true or false"))
    for cid, entry in spec["choices"].items():
        cw = f"{qw}/{cid}"
        text = str(choices[cid].get("text", ""))
        expr = entry["expr"]
        if number_sequence(text) != entry["numbers"]:
            out.append(
                Finding("choice_binding", cw, f"the choice shows the numbers {number_sequence(text)} but the verified claim declares {entry['numbers']}")
            )
        if math_symbols(text) != entry["symbols"]:
            out.append(Finding("choice_binding", cw, f"the choice shows the signs {math_symbols(text)!r} but the verified claim declares {entry['symbols']!r}"))
        if not _is_subsequence(entry["numbers"], _literals(expr)):
            out.append(Finding("choice_binding", cw, f"the declared numbers {entry['numbers']} are not used, in order, by the proof {expr!r}"))
        if _PLAIN_EXPR.match(expr) and (entry["symbols"] != _expr_symbols(expr) or entry["numbers"] != _literals(expr)):
            out.append(Finding("choice_binding", cw, f"the proof {expr!r} is a plain statement but does not match the declared numbers/signs"))
        if spec.get("operands_in_proof"):
            missing = [n for n in spec["prompt_numbers"] if n not in _literals(expr)]
            if missing:
                out.append(Finding("prompt_binding", cw, f"prompt numbers {missing} never appear in this choice's proof"))
        found, problems = statements(text)
        out += [Finding("math_unparsed", cw, f"arithmetic that cannot be interpreted: {p}") for p in problems]
        if _PLAIN_EXPR.match(expr) and found and isinstance(truths.get(cid), bool) and all(st.holds for st in found) != truths[cid]:
            out.append(
                Finding(
                    "choice_binding",
                    cw,
                    f"the displayed statement {text!r} is {'true' if all(st.holds for st in found) else 'false'} but its proof says {truths[cid]}",
                )
            )


def _verify_math(w: str, ver: dict[str, Any], loaded: dict[str, dict[str, Any]], lim: Limits) -> list[Finding]:
    out: list[Finding] = []
    qspecs = ver["questions"]
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
            if set(spec["choices"]) != set(choices):
                out.append(
                    Finding("verification_choices", qw, f"verification choices {sorted(spec['choices'])} do not match question choices {sorted(choices)}")
                )
                continue
            _bind_prompt(qw, spec, q, out, lim)
            if spec["mode"] == "value":
                _verify_value(qw, spec, q, choices, correct, out, lim)
            else:
                _verify_truth(qw, spec, choices, correct, out, lim)

    # worked examples: every example block must have at least one check; each result must be computed and shown
    examples = ver["examples"]
    names = [e["block"] for e in examples]
    for name, n in Counter(names).items():
        if n > 1:
            out.append(Finding("verification_schema", f"{w}:examples/{name}", "the example is verified more than once"))
    checked = set(names)
    for loc, blocks in loaded["blocks"].items():
        if not isinstance(blocks, list):
            continue
        by_key = {b.get("key"): b for b in blocks if isinstance(b, dict)}
        for b in by_key.values():
            if b.get("type") == "example" and b.get("key") not in checked:
                out.append(Finding("example_unverified", f"{w}:blocks.{loc}/{b.get('key')}", "worked example has no verification entry"))
        for e in examples:
            blk = by_key.get(e["block"])
            if blk is None or blk.get("type") != "example":
                out.append(Finding("verification_orphan", f"{w}:examples/{e['block']}", "no such example block"))
                continue
            text = _plain("¦".join(blk.get("steps", [])))  # a separator that is not a digit, so steps never run together
            ew = f"{w}:examples/{e['block']}/{loc}"
            for chk in e["checks"]:
                got = _eval(chk["expr"], ew, out, lim)
                if got is not None and got != chk["equals"]:
                    out.append(Finding("example_wrong", ew, f"{chk['expr']!r} evaluates to {got!r}, not {chk['equals']!r}"))
                shown = _plain(chk["must_appear"])
                if not re.search(rf"(?<![0-9]){re.escape(shown)}(?![0-9])", text):  # whole tokens, never a prefix of a longer number
                    out.append(Finding("example_not_shown", ew, f"the example does not show {chk['must_appear']!r} as complete numbers"))
                if "//" in chk["expr"] and "=" in chk["must_appear"]:
                    m = re.fullmatch(r"\s*(\d+)\s*//\s*(\d+)\s*", chk["expr"])
                    if not m or int(m.group(2)) == 0 or int(m.group(1)) % int(m.group(2)) != 0:
                        out.append(
                            Finding(
                                "example_not_bound",
                                ew,
                                f"{chk['expr']!r} is displayed as an exact division but is not one (non-zero remainder or unsupported form)",
                            )
                        )
                # the shown line must BE the checked operation: same operands, same order, same operator
                if "=" in chk["must_appear"] and isinstance(chk["equals"], int) and not isinstance(chk["equals"], bool) and _PLAIN_EXPR.match(chk["expr"]):
                    lhs = chk["expr"].translate(_TRANSLIT)
                    want = {f"{lhs}={chk['equals']}", f"{chk['equals']}={lhs}"}
                    if shown.translate(_TRANSLIT) not in want:
                        out.append(
                            Finding("example_not_bound", ew, f"the line {chk['must_appear']!r} is not the checked operation {chk['expr']!r} = {chk['equals']}")
                        )
    return out


def summarize(findings: list[Finding]) -> tuple[int, int]:
    return (sum(f.severity == "error" for f in findings), sum(f.severity == "warning" for f in findings))


def load_descriptor(root: Path, lim: Limits | None = None) -> dict[str, Any]:
    """The descriptor, read through the confined strict loader and checked against the schema AND the exact file
    names. Sizes, the manifest and the review pack use this, so none of them can be steered by a hostile descriptor."""
    lim = lim or DEFAULT_LIMITS
    doc = load_json_confined(Path(root), "pilot.json", lim.max_descriptor_bytes, max_depth=lim.max_json_depth)
    errors = [f"{_path(e)}: {e.message}" for e in _validator(TOOL_DIR / "schemas/pilot.schema.json").iter_errors(doc)]
    if not errors:
        for lesson in doc["lessons"]:
            want = expected_files(lesson)
            if lesson["files"] != want:
                errors.append(f"lesson {lesson['slug']}: file references must be exactly {want}")
    if errors:
        raise ContentFileError("pilot_schema", "; ".join(errors[:3]))
    return doc  # type: ignore[no-any-return]
