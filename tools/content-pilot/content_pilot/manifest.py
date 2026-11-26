"""Size estimates and an OPTIONAL deterministic, hash-verified preview manifest.

The manifest is a review/integrity aid for this pilot only. It is NOT a production pack format and must not be
consumed by the app, the API or the object store: Content-Delivery-00 defines the real manifest and signing.
It is unsigned: it detects accidental or careless change, not a determined attacker who can also rewrite it.

`verify_manifest` compares the WHOLE committed document (entry order, roles, locales, labels, totals, version) with
a canonical rebuild from disk, so altered metadata cannot pass just because the file hashes still match.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .checks import MANIFEST_NAME, inventory, load_descriptor
from .model import DEFAULT_LIMITS, LOCALES, PILOT_ID, Limits, expected_files, minified
from .safefs import ContentFileError, load_json_confined, loads_strict, read_confined

__all__ = ["LINKS_KBIT", "MANIFEST_NAME", "build_manifest", "render", "sizes", "verify_manifest"]

# Illustrative link speeds for the transfer-time column (assumptions, not measurements).
LINKS_KBIT = {"2G-like 32 kbit/s": 32, "slow 3G-like 128 kbit/s": 128}


def _gz(data: bytes) -> int:
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def _lesson_files(lesson: dict[str, Any]) -> dict[str, dict[str, str]]:
    """path -> {lesson_id, locale, role}, derived from the validated descriptor, never from the file system."""
    want = expected_files(lesson)
    meta: dict[str, dict[str, str]] = {}
    for kind in ("blocks", "questions"):
        for loc in LOCALES:
            meta[want[kind][loc]] = {"lesson_id": lesson["id"], "locale": loc, "role": kind}
    meta[want["verification"]] = {"lesson_id": lesson["id"], "locale": "all", "role": "verification"}
    return meta


def sizes(root: Path, limits: Limits | None = None) -> dict[str, Any]:
    """Per lesson and locale: delivery-shaped (minified UTF-8) bytes and gzip bytes, plus totals."""
    lim = limits or DEFAULT_LIMITS
    pilot = load_descriptor(root, lim)
    rows: list[dict[str, Any]] = []
    totals = {loc: {"bytes": 0, "gzip": 0} for loc in LOCALES}
    for lesson in pilot["lessons"]:
        want = expected_files(lesson)
        for loc in LOCALES:
            blocks = load_json_confined(root, want["blocks"][loc], lim.max_file_bytes)
            questions = load_json_confined(root, want["questions"][loc], lim.max_file_bytes)
            b, q = minified(blocks), minified(questions)
            both = minified({"blocks": blocks, "questions": questions})
            row = {
                "lesson": lesson["slug"],
                "locale": loc,
                "position": lesson["position"],
                "blocks_bytes": len(b),
                "questions_bytes": len(q),
                "unit_bytes": len(both),
                "unit_gzip_bytes": _gz(both),
                "block_count": len(blocks),
                "question_count": len(questions),
            }
            rows.append(row)
            totals[loc]["bytes"] += row["unit_bytes"]
            totals[loc]["gzip"] += row["unit_gzip_bytes"]
    transfer = {loc: {name: round(totals[loc]["gzip"] * 8 / (kbit * 1000), 1) for name, kbit in LINKS_KBIT.items()} for loc in LOCALES}
    return {
        "pilot_id": pilot["pilot_id"],
        "rows": rows,
        "totals": totals,
        "transfer_seconds_gzip": transfer,
        "basis": "minified UTF-8 JSON of blocks+questions per lesson; gzip level 9; transfer time ignores latency and HTTP overhead",
    }


def _expected_entries(root: Path, lim: Limits) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    pilot = load_descriptor(root, lim)
    meta: dict[str, dict[str, str]] = {"pilot.json": {"role": "descriptor"}}
    for lesson in pilot["lessons"]:
        meta.update(_lesson_files(lesson))
    return pilot, meta


def build_manifest(root: Path, limits: Limits | None = None) -> dict[str, Any]:
    """Canonical manifest: exactly the files the descriptor names, each read through the confined loader."""
    lim = limits or DEFAULT_LIMITS
    root = Path(root)
    _, meta = _expected_entries(root, lim)
    entries = []
    for rel in sorted(meta):
        try:
            data = read_confined(root, rel, lim.max_descriptor_bytes if rel == "pilot.json" else lim.max_file_bytes)
        except FileNotFoundError as exc:
            raise ContentFileError("file_missing", f"listed by the descriptor but missing on disk: {rel}") from exc
        entries.append({"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), **meta[rel]})
    core = {"pilot_id": PILOT_ID, "entries": entries}
    digest = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "manifest_version": "pilot-preview-0",
        "purpose": "Integrity preview for reviewers. NOT a production pack format; never served to the app.",
        "pilot_id": PILOT_ID,
        "entries": entries,
        "totals": {"files": len(entries), "bytes": sum(e["bytes"] for e in entries)},
        "manifest_sha256": digest,
    }


def render(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def verify_manifest(root: Path, limits: Limits | None = None) -> list[str]:
    """Compare the committed manifest with the files on disk. Returns human-readable problems (empty = verified)."""
    lim = limits or DEFAULT_LIMITS
    root = Path(root)
    try:
        committed = loads_strict(read_confined(root, MANIFEST_NAME, lim.max_descriptor_bytes), max_depth=lim.max_json_depth)
    except FileNotFoundError:
        return [f"{MANIFEST_NAME} is missing"]
    except ContentFileError as exc:
        return [f"{MANIFEST_NAME} is not valid JSON: {exc.message}" if exc.code == "json_invalid" else f"{MANIFEST_NAME}: {exc.message}"]
    if not isinstance(committed, dict) or not isinstance(committed.get("entries"), list) or not all(isinstance(e, dict) for e in committed["entries"]):
        return [f"{MANIFEST_NAME} must be an object with an 'entries' list of objects"]

    problems: list[str] = []
    paths = [e.get("path") for e in committed["entries"]]
    for path, n in sorted(Counter(map(str, paths)).items()):
        if n > 1:
            problems.append(f"manifest lists {path} {n} times")
    try:
        canonical = build_manifest(root, lim)
        stray, _ = inventory(root, load_descriptor(root, lim), lim)
    except ContentFileError as exc:
        return [*problems, exc.message]
    except OSError as exc:
        return [*problems, f"cannot read the pilot: {exc.strerror or exc}"]

    for f in stray:
        problems.append(f"on disk but not in the manifest or the pilot: {f.where} ({f.message})")
    want = {e["path"]: e for e in canonical["entries"]}
    got = {str(e.get("path")): e for e in committed["entries"]}
    for rel in sorted(set(want) - set(got)):
        problems.append(f"on disk but not in the manifest: {rel}")
    for rel in sorted(set(got) - set(want)):
        problems.append(f"listed but not part of the pilot (or missing on disk): {rel}")
    for rel in sorted(set(want) & set(got)):
        if got[rel].get("sha256") != want[rel]["sha256"]:
            problems.append(f"hash mismatch: {rel}")
        elif got[rel].get("bytes") != want[rel]["bytes"]:
            problems.append(f"size mismatch: {rel}")
        else:
            for field in sorted((set(want[rel]) | set(got[rel])) - {"path", "bytes", "sha256"}):
                if got[rel].get(field) != want[rel].get(field):
                    problems.append(f"metadata mismatch in {rel}: {field} is {got[rel].get(field)!r}, expected {want[rel].get(field)!r}")
    if not problems and committed != canonical:
        problems.append("the manifest differs from the canonical rebuild (entry order, totals, labels or version)")
    return problems
