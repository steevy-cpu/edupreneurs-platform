"""Size estimates and an OPTIONAL deterministic, hash-verified preview manifest.

The manifest is a review/integrity aid for this pilot only. It is NOT a production pack format and must not be
consumed by the app, the API or the object store: Content-Delivery-00 defines the real manifest and signing.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from .model import LOCALES, PILOT_ID, minified, read_json

MANIFEST_NAME = "manifest.preview.json"
# Illustrative link speeds for the transfer-time column (assumptions, not measurements).
LINKS_KBIT = {"2G-like 32 kbit/s": 32, "slow 3G-like 128 kbit/s": 128}


def _gz(data: bytes) -> int:
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def sizes(root: Path) -> dict[str, Any]:
    """Per lesson and locale: delivery-shaped (minified UTF-8) bytes and gzip bytes, plus totals."""
    pilot = read_json(root / "pilot.json")
    rows: list[dict[str, Any]] = []
    totals = {loc: {"bytes": 0, "gzip": 0} for loc in LOCALES}
    for lesson in pilot["lessons"]:
        for loc in LOCALES:
            blocks = read_json(root / lesson["files"]["blocks"][loc])
            questions = read_json(root / lesson["files"]["questions"][loc])
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


def _files(root: Path) -> list[Path]:
    out = [root / "pilot.json"]
    out += sorted((root / "lessons").rglob("*.json"))
    return out


def build_manifest(root: Path) -> dict[str, Any]:
    pilot = read_json(root / "pilot.json")
    by_file: dict[str, dict[str, str]] = {}
    for lesson in pilot["lessons"]:
        for kind in ("blocks", "questions"):
            for loc in LOCALES:
                by_file[lesson["files"][kind][loc]] = {"lesson_id": lesson["id"], "locale": loc, "role": kind}
        by_file[lesson["files"]["verification"]] = {"lesson_id": lesson["id"], "locale": "all", "role": "verification"}
    entries = []
    for p in _files(root):
        rel = p.relative_to(root).as_posix()
        data = p.read_bytes()
        meta = by_file.get(rel, {"role": "descriptor"} if rel == "pilot.json" else {"role": "unlisted"})
        entries.append({"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), **meta})
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


def verify_manifest(root: Path) -> list[str]:
    """Compare the committed manifest with the files on disk. Returns human-readable problems."""
    path = root / MANIFEST_NAME
    if not path.exists():
        return [f"{MANIFEST_NAME} is missing"]
    try:
        committed = read_json(path)
    except json.JSONDecodeError as exc:
        return [f"{MANIFEST_NAME} is not valid JSON: {exc}"]
    problems: list[str] = []
    listed = {e.get("path"): e for e in committed.get("entries", [])}
    actual = {p.relative_to(root).as_posix(): p for p in _files(root)}
    for rel in sorted(set(listed) - set(actual)):
        problems.append(f"listed but missing on disk: {rel}")
    for rel in sorted(set(actual) - set(listed)):
        problems.append(f"on disk but not in the manifest: {rel}")
    for rel in sorted(set(listed) & set(actual)):
        data = actual[rel].read_bytes()
        if hashlib.sha256(data).hexdigest() != listed[rel].get("sha256"):
            problems.append(f"hash mismatch: {rel}")
        elif len(data) != listed[rel].get("bytes"):
            problems.append(f"size mismatch: {rel}")
    if not problems:
        fresh = build_manifest(root)
        if fresh["manifest_sha256"] != committed.get("manifest_sha256"):
            problems.append("manifest_sha256 does not match its entries")
    return problems
