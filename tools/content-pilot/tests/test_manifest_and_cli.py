from __future__ import annotations

import json
import shutil

from content_pilot import manifest as mf
from content_pilot.cli import main

from .conftest import L1, PILOT, REPO


def test_manifest_detects_tampering_additions_and_deletions(pilot_copy):
    assert mf.verify_manifest(pilot_copy) == []
    p = pilot_copy / L1 / "blocks.fr.json"
    p.write_text(p.read_text(encoding="utf-8").replace("Un stade", "Un stade."), encoding="utf-8")
    assert any("hash mismatch" in x and "blocks.fr.json" in x for x in mf.verify_manifest(pilot_copy))
    (pilot_copy / "lessons" / "extra.json").write_text("[]", encoding="utf-8")
    assert any("not in the manifest" in x for x in mf.verify_manifest(pilot_copy))
    (pilot_copy / L1 / "questions.ht.json").unlink()
    assert any("missing on disk" in x for x in mf.verify_manifest(pilot_copy))


def test_manifest_digest_changes_when_any_byte_changes(pilot_copy):
    before = mf.build_manifest(pilot_copy)["manifest_sha256"]
    f = pilot_copy / L1 / "verification.json"
    f.write_text(f.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert mf.build_manifest(pilot_copy)["manifest_sha256"] != before


def test_missing_or_corrupt_manifest_is_reported(pilot_copy):
    (pilot_copy / mf.MANIFEST_NAME).write_text("not json", encoding="utf-8")
    assert any("not valid JSON" in x for x in mf.verify_manifest(pilot_copy))
    (pilot_copy / mf.MANIFEST_NAME).unlink()
    assert any("missing" in x for x in mf.verify_manifest(pilot_copy))


def test_manifest_independent_of_checkout_location(tmp_path):
    other = tmp_path / "elsewhere" / "deep"
    shutil.copytree(PILOT, other)
    assert mf.render(mf.build_manifest(other)) == mf.render(mf.build_manifest(PILOT))


def test_sizes_report_shape():
    s = mf.sizes(PILOT)
    assert len(s["rows"]) == 12 and set(s["totals"]) == {"fr", "ht"}
    assert "ignores latency" in s["basis"]


def test_cli_validate_ok_and_json(capsys):
    assert main(["validate", "--root", str(PILOT), "--forbid-approvals"]) == 0
    assert "OK: 0 error(s), 0 warning(s)" in capsys.readouterr().out
    assert main(["validate", "--root", str(PILOT), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_cli_validate_fails_with_exit_1_on_bad_content(pilot_copy, capsys):
    (pilot_copy / L1 / "blocks.ht.json").unlink()
    assert main(["validate", "--root", str(pilot_copy), "--repo-root", str(REPO)]) == 1
    out = capsys.readouterr().out
    assert "file_missing" in out and "FAIL" in out


def test_cli_manifest_and_review_pack_checks(pilot_copy, tmp_path, capsys):
    assert main(["manifest", "--root", str(pilot_copy), "--check"]) == 0
    assert main(["verify-manifest", "--root", str(pilot_copy)]) == 0
    f = pilot_copy / L1 / "blocks.fr.json"
    f.write_text(f.read_text(encoding="utf-8").replace("Un stade", "Un grand stade"), encoding="utf-8")
    assert main(["manifest", "--root", str(pilot_copy), "--check"]) == 1
    assert main(["verify-manifest", "--root", str(pilot_copy)]) == 1
    rd = tmp_path / "review"
    assert main(["review-pack", "--root", str(pilot_copy), "--review-dir", str(rd), "--repo-root", str(REPO), "--write"]) == 0
    assert main(["review-pack", "--root", str(pilot_copy), "--review-dir", str(rd), "--check"]) == 0
    (rd / "answer-key-overview.md").write_text("x", encoding="utf-8")
    assert main(["review-pack", "--root", str(pilot_copy), "--review-dir", str(rd), "--check"]) == 1
    capsys.readouterr()


def test_cli_sizes(capsys):
    assert main(["sizes", "--root", str(PILOT)]) == 0
    assert "TOTAL fr" in capsys.readouterr().out
