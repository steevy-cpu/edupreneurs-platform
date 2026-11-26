"""Command line: python -m content_pilot <command> [--root content/pilots/7af-math]

validate         check the pilot against the contracts and the pilot rules (exit 1 on any error)
sizes            print size estimates (delivery-shaped bytes and gzip)
manifest         build the deterministic preview manifest (--write to save, --check to compare)
verify-manifest  recompute hashes and compare them with the committed preview manifest
review-pack      generate the educator review package (--write to save, --check to compare)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import manifest as mf
from .checks import summarize, validate
from .model import find_repo_root
from .review import build_review_pack


def _default_root() -> Path:
    return find_repo_root(Path.cwd()) / "content" / "pilots" / "7af-math"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="content_pilot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["validate", "sizes", "manifest", "verify-manifest", "review-pack"])
    ap.add_argument("--root", type=Path, default=None, help="pilot directory (default: content/pilots/7af-math)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--repo-root", type=Path, default=None, help="repository root holding packages/contracts (default: auto-detect)")
    ap.add_argument("--forbid-approvals", action="store_true", help="fail if any lesson is marked approved")
    ap.add_argument("--review-dir", type=Path, default=None, help="review pack directory (default: docs/content-02a/review)")
    a = ap.parse_args(argv)
    root = (a.root or _default_root()).resolve()

    if a.command == "validate":
        findings = validate(root, repo_root=a.repo_root, forbid_approvals=a.forbid_approvals)
        errors, warnings = summarize(findings)
        if a.json:
            print(json.dumps([f.__dict__ for f in findings], ensure_ascii=False, indent=2))
        else:
            for f in findings:
                print(f)
            print(f"{'FAIL' if errors else 'OK'}: {errors} error(s), {warnings} warning(s)")
        return 1 if errors else 0

    if a.command == "sizes":
        s = mf.sizes(root)
        if a.json:
            print(json.dumps(s, ensure_ascii=False, indent=2))
            return 0
        print(f"{'lesson':36} {'loc':3} {'blocks':>7} {'quest.':>7} {'unit':>7} {'gzip':>6}")
        for r in s["rows"]:
            print(f"{r['lesson']:36} {r['locale']:3} {r['blocks_bytes']:>7} {r['questions_bytes']:>7} {r['unit_bytes']:>7} {r['unit_gzip_bytes']:>6}")
        for loc, t in s["totals"].items():
            print(f"TOTAL {loc}: {t['bytes']} bytes, {t['gzip']} gzip; transfer(gzip) {s['transfer_seconds_gzip'][loc]}")
        print(s["basis"])
        return 0

    if a.command == "manifest":
        text = mf.render(mf.build_manifest(root))
        target = root / mf.MANIFEST_NAME
        if a.write:
            target.write_text(text, encoding="utf-8")
            print(f"wrote {target}")
            return 0
        if a.check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                print(f"{mf.MANIFEST_NAME} is out of date: run `manifest --write`")
                return 1
            print(f"{mf.MANIFEST_NAME} is up to date")
            return 0
        sys.stdout.write(text)
        return 0

    if a.command == "verify-manifest":
        problems = mf.verify_manifest(root)
        for p in problems:
            print(p)
        print("FAIL" if problems else "OK: every file matches the preview manifest")
        return 1 if problems else 0

    # review-pack
    out_dir = (a.review_dir or find_repo_root(root) / "docs" / "content-02a" / "review").resolve()
    files = build_review_pack(root)
    stale = []
    for name, text in files.items():
        p = out_dir / name
        if a.write:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        elif a.check and (not p.exists() or p.read_text(encoding="utf-8") != text):
            stale.append(name)
    if a.write:
        print(f"wrote {len(files)} files to {out_dir}")
    elif a.check:
        for n in stale:
            print(f"out of date: {n}")
        print("FAIL" if stale else f"OK: review pack is up to date ({len(files)} files)")
        return 1 if stale else 0
    else:
        print("\n".join(sorted(files)))
    return 0
