"""Canonical manifests, the pack builder, the local-directory storage adapter and
the verifier - including the golden test and corrupted-object rejection.

No database is needed: every pack here is built from vectors/pack-manifest.json.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from edu_api.content.canonical import canonical_json, is_canonical_json, sha256_hex
from edu_api.content.pack import (
    BuiltPack,
    PackBuildError,
    PackIntegrityError,
    asset_object_key,
    build_pack,
    lesson_object_key,
    pack_input_from_json,
    png_size,
    size_report,
    sniff_mime,
    validate_manifest,
    verify_pack,
    write_pack,
)
from edu_api.content.storage import LocalDirectoryStorage, StorageError, check_key
from tests.content_fixtures import (
    BLOCK_SCHEMAS,
    QUESTION_SCHEMAS,
    VECTORS,
    cases,
    schema_accepts,
)
from tests.unit.test_content_v2_vectors import _mutations

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ID = "v2-pack-three-lessons"
#: Pinned here as well as in the vector file: changing the manifest format, the
#: canonical form or the builder's ordering must be a deliberate, visible act.
GOLDEN_SHA256 = "f76f7ed37cb3bec1b0ca5bfaa36eda19a70ed0984806013637135b110a4580cf"


def assets_of(case: dict[str, Any]) -> dict[str, bytes]:
    return {name: base64.b64decode(data) for name, data in case["input"]["assets_base64"].items()}


def build(case: dict[str, Any]) -> BuiltPack:
    return build_pack(pack_input_from_json(case["input"]), assets_of(case))


def case_by_id(case_id: str) -> dict[str, Any]:
    return next(case for case in cases("pack-manifest.json") if case["id"] == case_id)


@pytest.fixture
def golden() -> BuiltPack:
    return build(case_by_id(GOLDEN_ID))


def stored(tmp_path: Path, built: BuiltPack) -> LocalDirectoryStorage:
    storage = LocalDirectoryStorage(tmp_path / "pack")
    write_pack(storage, built)
    return storage


# ------------------------------------------------------------------ canonical form
def test_canonical_json_is_exactly_specified() -> None:
    document = {
        "b": [3, 1, 2],
        "a": {"z": None, "y": True},
        "t": 'e\u0301 "q" \\ \n\t\u0001 \u2028',
    }
    assert canonical_json(document) == (
        b'{"a":{"y":true,"z":null},"b":[3,1,2],"t":"\xc3\xa9 \\"q\\" \\\\ \\n\\t\\u0001 \xe2\x80\xa8"}'
    )
    assert is_canonical_json(canonical_json(document))
    for not_canonical in (b'{"a": 1}', b'{"b":1,"a":2}', b'{"a":1}\n', b'{"a":1.0}', b"\xff", b""):
        assert not is_canonical_json(not_canonical), not_canonical
    # NFD text is not canonical; the canonical form of it is NFC.
    assert not is_canonical_json('"e\u0301"'.encode())
    for unsupported in (1.5, {"k": 0.1}, {1: "x"}, {"cl\u00e9": 1}, {"s": {1, 2}}, float("nan")):
        with pytest.raises(TypeError):
            canonical_json(unsupported)


# ------------------------------------------------------------------ golden vectors
@pytest.mark.parametrize("case", [pytest.param(c, id=c["id"]) for c in cases("pack-manifest.json")])
def test_pack_manifest_vectors(case: dict[str, Any]) -> None:
    expected = case["expect"]
    if "error" in expected:
        with pytest.raises(PackBuildError) as refused:
            build(case)
        assert refused.value.code == expected["error"]
        return
    built = build(case)
    # Byte-identical manifest, and the recorded hash and size really are those of the bytes.
    assert built.manifest_bytes == expected["manifest_utf8"].encode("utf-8")
    assert (
        hashlib.sha256(expected["manifest_utf8"].encode("utf-8")).hexdigest()
        == (expected["manifest_sha256"])
    )
    assert (built.manifest_sha256, len(built.manifest_bytes), built.manifest_key) == (
        expected["manifest_sha256"],
        expected["manifest_bytes"],
        expected["manifest_key"],
    )
    assert [
        {"key": key, "sha256": sha256_hex(data), "bytes": len(data)}
        for key, data in sorted(built.objects.items())
    ] == expected["objects"]
    assert built.total_bytes == expected["total_bytes"]
    # An independent re-serialisation of the golden text gives the same bytes.
    reparsed = json.loads(expected["manifest_utf8"])
    assert (
        json.dumps(reparsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        == expected["manifest_utf8"]
    )
    assert validate_manifest(reparsed) == []
    assert schema_accepts("pack-manifest.v1.schema.json", reparsed)


def test_the_golden_manifest_hash_is_pinned(golden: BuiltPack) -> None:
    assert golden.manifest_sha256 == GOLDEN_SHA256
    assert case_by_id(GOLDEN_ID)["expect"]["manifest_sha256"] == GOLDEN_SHA256


def test_manifest_content_is_true_and_complete(golden: BuiltPack) -> None:
    manifest = golden.manifest
    assert [lesson["position"] for lesson in manifest["lessons"]] == [1, 2, 3]
    assert [lesson["content_format"] for lesson in manifest["lessons"]] == [2, 1, 2]
    assert manifest["content_format"] == 2
    for lesson in manifest["lessons"]:
        blob = golden.objects[lesson["object_key"]]
        assert lesson["object_key"] == lesson_object_key(lesson["sha256"])
        assert (sha256_hex(blob), len(blob)) == (lesson["sha256"], lesson["bytes"])
        assert is_canonical_json(blob)
        body = json.loads(blob)
        assert schema_accepts("pack-lesson.v1.schema.json", body)
        assert schema_accepts(BLOCK_SCHEMAS[body["content_format"]], body["blocks"])
        assert [q["id"] for q in body["questions"]] == [q["id"] for q in lesson["questions"]]
        for question in body["questions"]:
            columns = {
                k: question[k] for k in ("prompt", "response_spec", "answer_key", "explanation")
            }
            assert schema_accepts(QUESTION_SCHEMAS[question["kind"]], columns)
    assert [asset["sha256"] for asset in manifest["assets"]] == sorted(
        asset["sha256"] for asset in manifest["assets"]
    )
    for asset in manifest["assets"]:
        data = golden.objects[asset["object_key"]]
        assert asset["object_key"] == asset_object_key(asset["sha256"])
        assert (sha256_hex(data), len(data), sniff_mime(data)) == (
            asset["sha256"],
            asset["bytes"],
            asset["mime"],
        )
        assert asset["required"] is (asset["kind"] == "image")
    # The image used by lessons 1 and 3 is listed, stored and counted once.
    shared = set(manifest["lessons"][0]["assets"]) & set(manifest["lessons"][2]["assets"])
    assert len(shared) == 1 and len(manifest["assets"]) == 3
    totals = manifest["totals"]
    assert totals == {
        "lessons": 3,
        "questions": 5,
        "assets": 3,
        "lesson_bytes": sum(lesson["bytes"] for lesson in manifest["lessons"]),
        "required_asset_bytes": sum(a["bytes"] for a in manifest["assets"] if a["required"]),
        "optional_asset_bytes": sum(a["bytes"] for a in manifest["assets"] if not a["required"]),
    }
    assert golden.total_bytes == len(golden.manifest_bytes) + sum(
        totals[name] for name in ("lesson_bytes", "required_asset_bytes", "optional_asset_bytes")
    )
    assert len(golden.objects) == 6 and len(size_report(golden)) == 6
    # Nothing in a manifest depends on when or where it was built.
    for forbidden in ("created_at", "built_at", "timestamp", "host"):
        assert forbidden not in golden.manifest_bytes.decode()


def _shuffled(rng: random.Random, value: Any) -> Any:
    """Same JSON document, object keys inserted in a different order."""
    if isinstance(value, dict):
        names = list(value)
        rng.shuffle(names)
        return {name: _shuffled(rng, value[name]) for name in names}
    if isinstance(value, list):
        return [_shuffled(rng, item) for item in value]
    return value


def test_identical_input_gives_byte_identical_output(golden: BuiltPack) -> None:
    case = case_by_id(GOLDEN_ID)
    rng = random.Random(7)  # noqa: S311 - deterministic test data, not security
    for _ in range(25):
        variant = _shuffled(rng, copy.deepcopy(case))
        rng.shuffle(variant["input"]["lessons"])  # the order lessons are handed over in
        for lesson in variant["input"]["lessons"]:
            rng.shuffle(lesson["questions"])
        built = build(variant)
        assert built.manifest_bytes == golden.manifest_bytes
        assert built.objects == golden.objects
    # NFD and NFC spellings of the same text are the same content.
    decomposed = copy.deepcopy(case)
    for lesson in decomposed["input"]["lessons"]:
        for block in lesson["blocks"]:
            if block["type"] == "paragraph":
                block["text"] = block["text"].replace("\u00e9", "e\u0301")
    assert build(decomposed).manifest_bytes == golden.manifest_bytes


def test_a_different_python_process_builds_the_same_bytes(tmp_path: Path) -> None:
    """Through the command line, with a different hash seed: build, then verify."""
    case = case_by_id(GOLDEN_ID)
    description = tmp_path / "pack.json"
    description.write_text(json.dumps(case["input"]), encoding="utf-8")
    out = tmp_path / "out"
    script = str(ROOT / "scripts" / "build_pack.py")
    env = {"PYTHONHASHSEED": "12345", "PATH": "/usr/bin:/bin"}
    built = subprocess.run(  # noqa: S603 - fixed arguments, our own script
        [sys.executable, script, "build-file", "--input", str(description), "--out", str(out)],
        capture_output=True, text=True, check=False, env=env, cwd=tmp_path,
    )  # fmt: skip
    assert built.returncode == 0, built.stderr
    assert f"manifest sha256  {GOLDEN_SHA256}" in built.stdout
    manifest_key = case["expect"]["manifest_key"]
    assert (out / manifest_key).read_bytes() == case["expect"]["manifest_utf8"].encode("utf-8")

    def verify(*extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - fixed arguments, our own script
            [sys.executable, script, "verify", "--dir", str(out), "--manifest-key", manifest_key, *extra],
            capture_output=True, text=True, check=False, env=env, cwd=tmp_path,
        )  # fmt: skip

    ok = verify("--sha256", GOLDEN_SHA256)
    assert ok.returncode == 0 and "pack is intact: 3 lessons, 5 questions, 3 assets" in ok.stdout
    wrong = verify("--sha256", "0" * 64)
    assert wrong.returncode == 1 and "manifest.hash" in wrong.stderr
    # Corrupt one stored asset on disk: the command fails and names the object.
    asset = case["expect"]["objects"][0]
    target = out / asset["key"]
    target.write_bytes(target.read_bytes()[:-1] + b"\x00")
    corrupted = verify("--sha256", GOLDEN_SHA256)
    assert corrupted.returncode == 1
    assert (
        "pack is NOT intact: object.hash" in corrupted.stderr and asset["key"] in corrupted.stderr
    )
    assert "intact:" not in corrupted.stdout


# ------------------------------------------------------------------ storage adapter
def test_local_storage_round_trip_and_immutability(tmp_path: Path) -> None:
    storage = LocalDirectoryStorage(tmp_path / "store")
    assert not storage.exists("assets/sha256/ab/abc")
    storage.put("assets/sha256/ab/abc", b"one")
    assert storage.exists("assets/sha256/ab/abc") and storage.get("assets/sha256/ab/abc") == b"one"
    storage.put("assets/sha256/ab/abc", b"one")  # same bytes again: harmless
    with pytest.raises(StorageError, match="different content"):
        storage.put("assets/sha256/ab/abc", b"two")
    assert storage.get("assets/sha256/ab/abc") == b"one"
    with pytest.raises(StorageError, match="not found"):
        storage.get("assets/sha256/ab/missing")
    # No temporary file is left behind.
    assert sorted(p.name for p in (tmp_path / "store" / "assets/sha256/ab").iterdir()) == ["abc"]


@pytest.mark.parametrize(
    "key",
    ["../outside", "/etc/passwd", "a/../../b", "a//b", "a/./b", "", ".hidden", "a/.hidden",
     "A/upper", "a b", "a\\b", "a/b/", "a\x00b", "x" * 301, "~/x", "a/..", ".."],
)  # fmt: skip
def test_local_storage_refuses_keys_that_could_leave_the_directory(
    tmp_path: Path, key: str
) -> None:
    storage = LocalDirectoryStorage(tmp_path / "store")
    for operation in (
        lambda: storage.put(key, b"x"),
        lambda: storage.get(key),
        lambda: storage.exists(key),
    ):
        with pytest.raises(StorageError, match="invalid object key"):
            operation()
    assert not (tmp_path / "outside").exists() and list((tmp_path / "store").iterdir()) == []
    assert check_key("packs/math-9af/fr/1/manifest.json") == "packs/math-9af/fr/1/manifest.json"


def test_local_storage_refuses_a_symlink_that_escapes(tmp_path: Path) -> None:
    storage = LocalDirectoryStorage(tmp_path / "store")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "store" / "link").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(StorageError, match="invalid object key"):
        storage.put("link/file", b"x")
    assert list((tmp_path / "elsewhere").iterdir()) == []


# ------------------------------------------------------------------ write + verify
def test_write_then_verify_and_rebuild_is_idempotent(tmp_path: Path, golden: BuiltPack) -> None:
    storage = stored(tmp_path, golden)
    manifest = verify_pack(storage, golden.manifest_key, golden.manifest_sha256)
    assert manifest == golden.manifest
    write_pack(storage, golden)  # an interrupted build can simply be run again
    files = sorted(
        p.relative_to(tmp_path / "pack").as_posix()
        for p in (tmp_path / "pack").rglob("*")
        if p.is_file()
    )
    assert files == sorted([golden.manifest_key, *golden.objects])
    assert sum((tmp_path / "pack" / name).stat().st_size for name in files) == golden.total_bytes


def _corrupt(path: Path, how: str) -> None:
    data = path.read_bytes()
    if how == "flip":
        path.write_bytes(data[:10] + bytes([data[10] ^ 0x01]) + data[11:])
    elif how == "truncate":
        path.write_bytes(data[:-1])
    elif how == "append":
        path.write_bytes(data + b" ")
    elif how == "empty":
        path.write_bytes(b"")
    else:
        path.unlink()


@pytest.mark.parametrize("how", ["flip", "truncate", "append", "empty", "delete"])
def test_every_corrupted_or_missing_object_is_rejected(
    tmp_path: Path, golden: BuiltPack, how: str
) -> None:
    """One damaged object at a time, for EVERY object of the pack."""
    expected_code = {"flip": "object.hash", "delete": "object.missing"}.get(how, "object.size")
    for index, key in enumerate(sorted(golden.objects)):
        storage = stored(tmp_path / f"{how}-{index}", golden)
        _corrupt(storage.root / key, how)
        with pytest.raises(PackIntegrityError) as rejected:
            verify_pack(storage, golden.manifest_key, golden.manifest_sha256)
        assert (rejected.value.code, rejected.value.key) == (expected_code, key)


def test_a_tampered_manifest_is_rejected(tmp_path: Path, golden: BuiltPack) -> None:
    storage = stored(tmp_path, golden)
    path = storage.root / golden.manifest_key
    original = path.read_bytes()

    def rejected_with(data: bytes, expected_sha256: str | None) -> str:
        path.write_bytes(data)
        with pytest.raises(PackIntegrityError) as rejected:
            verify_pack(storage, golden.manifest_key, expected_sha256)
        return rejected.value.code

    # With the hash the server recorded, ANY change to the manifest is caught first.
    assert (
        rejected_with(original.replace(b'"revision":2', b'"revision":3'), golden.manifest_sha256)
        == "manifest.hash"
    )
    assert rejected_with(original + b"\n", golden.manifest_sha256) == "manifest.hash"
    # Without a trusted hash the verifier still refuses what it can detect by itself.
    assert rejected_with(original + b"\n", None) == "manifest.not_canonical"
    assert (
        rejected_with(json.dumps(json.loads(original), indent=1).encode(), None)
        == "manifest.not_canonical"
    )
    assert rejected_with(b"not json", None) == "manifest.not_canonical"
    retitled = json.loads(original)
    retitled["lessons"][0]["title"] = "Autre titre"
    assert rejected_with(canonical_json(retitled), None) == "lesson.mismatch"
    extra = json.loads(original)
    extra["signature"] = "x"
    assert rejected_with(canonical_json(extra), None) == "manifest.structure"
    lower = json.loads(original)
    lower["content_format"] = 1
    assert rejected_with(canonical_json(lower), None) == "manifest.structure"
    dropped = json.loads(original)
    dropped["assets"].pop()
    assert rejected_with(canonical_json(dropped), None) in {"lesson.mismatch", "manifest.structure"}
    moved = json.loads(original)
    moved["pack"]["revision"] = 9
    assert rejected_with(canonical_json(moved), None) == "manifest.key"
    path.write_bytes(original)
    assert verify_pack(storage, golden.manifest_key, golden.manifest_sha256) == golden.manifest
    path.unlink()
    with pytest.raises(PackIntegrityError, match=r"object\.missing"):
        verify_pack(storage, golden.manifest_key, golden.manifest_sha256)


def test_a_consistently_rewritten_lesson_is_still_caught_by_the_manifest_hash(
    tmp_path: Path, golden: BuiltPack
) -> None:
    """An attacker who rewrites a lesson AND fixes the manifest to match it produces
    a self-consistent pack. Only the manifest hash the server recorded detects that."""
    storage = stored(tmp_path, golden)
    manifest = json.loads(golden.manifest_bytes)
    entry = manifest["lessons"][1]
    lesson = json.loads(golden.objects[entry["object_key"]])
    lesson["questions"][0]["answer_key"]["correct_choice_id"] = "a"
    forged = canonical_json(lesson)
    entry["sha256"], entry["bytes"] = sha256_hex(forged), len(forged)
    entry["object_key"] = lesson_object_key(entry["sha256"])
    manifest["totals"]["lesson_bytes"] = sum(item["bytes"] for item in manifest["lessons"])
    storage.put(entry["object_key"], forged)
    (storage.root / golden.manifest_key).write_bytes(canonical_json(manifest))
    assert (
        verify_pack(storage, golden.manifest_key, None)["lessons"][1]["sha256"] == entry["sha256"]
    )
    with pytest.raises(PackIntegrityError, match=r"manifest\.hash"):
        verify_pack(storage, golden.manifest_key, golden.manifest_sha256)


def test_optional_audio_may_be_absent_only_when_allowed(tmp_path: Path, golden: BuiltPack) -> None:
    storage = stored(tmp_path, golden)
    audio = next(asset for asset in golden.manifest["assets"] if asset["kind"] == "audio")
    image = next(asset for asset in golden.manifest["assets"] if asset["kind"] == "image")
    (storage.root / audio["object_key"]).unlink()
    with pytest.raises(PackIntegrityError, match=r"object\.missing"):
        verify_pack(storage, golden.manifest_key, golden.manifest_sha256)
    verify_pack(storage, golden.manifest_key, golden.manifest_sha256, require_optional=False)
    # A present-but-damaged audio file is rejected even when audio is optional.
    (storage.root / audio["object_key"]).write_bytes(b"x" * audio["bytes"])
    with pytest.raises(PackIntegrityError, match=r"object\.hash"):
        verify_pack(storage, golden.manifest_key, golden.manifest_sha256, require_optional=False)
    (storage.root / audio["object_key"]).unlink()
    (storage.root / image["object_key"]).unlink()
    with pytest.raises(PackIntegrityError, match=r"object\.missing"):
        verify_pack(storage, golden.manifest_key, golden.manifest_sha256, require_optional=False)


def test_nothing_is_written_when_the_build_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "out"
    for case in cases("pack-manifest.json"):
        if "error" in case["expect"]:
            with pytest.raises(PackBuildError):
                write_pack(LocalDirectoryStorage(out), build(case))
    assert [p for p in out.rglob("*") if p.is_file()] == []


def test_assets_must_be_attached_when_the_database_view_is_given() -> None:
    case = case_by_id(GOLDEN_ID)
    pack, files = pack_input_from_json(case["input"]), assets_of(case)
    recorded: dict[str, dict[str, dict[str, Any]]] = {}
    for lesson in case["input"]["lessons"]:
        for block in lesson["blocks"]:
            if "asset" in block:
                recorded.setdefault(lesson["revision_id"], {})[block["asset"]["sha256"]] = dict(
                    block["asset"]
                )
    assert build_pack(pack, files, recorded).manifest_sha256 == GOLDEN_SHA256
    one_revision, one_asset = next((r, s) for r, assets in recorded.items() for s in assets)
    missing = copy.deepcopy(recorded)
    del missing[one_revision][one_asset]
    with pytest.raises(PackBuildError) as refused:
        build_pack(pack, files, missing)
    assert refused.value.code == "asset.not_attached"
    different = copy.deepcopy(recorded)
    different[one_revision][one_asset]["bytes"] += 1
    with pytest.raises(PackBuildError) as refused:
        build_pack(pack, files, different)
    assert refused.value.code == "asset.metadata"


# ------------------------------------------------------------------ small pieces
def test_file_signatures() -> None:
    assert sniff_mime(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8) == "image/png"
    assert sniff_mime(b"\xff\xd8\xff\xe0" + b"\x00" * 8) == "image/jpeg"
    assert sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert sniff_mime(b"\x00\x00\x00\x18ftypM4A ") == "audio/mp4"
    assert (
        sniff_mime(b"ID3\x04\x00") == "audio/mpeg"
        and sniff_mime(b"\xff\xfb\x90\x00") == "audio/mpeg"
    )
    for other in (
        b"",
        b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        b"<!doctype html>",
        b"GIF89a",
        b"%PDF-1.7",
        b"RIFF\x00\x00\x00\x00WAVEfmt ",
    ):
        assert sniff_mime(other) is None, other
    png = next(v for v in assets_of(case_by_id(GOLDEN_ID)).values() if sniff_mime(v) == "image/png")
    assert png_size(png) in {(16, 9), (8, 8)} and png_size(b"\xff\xd8\xff") is None


def test_manifest_validator_and_json_schema_agree_on_damaged_manifests(golden: BuiltPack) -> None:
    rng = random.Random(99)  # noqa: S311 - deterministic test data, not security
    rejected = 0
    for _ in range(2000):
        document = _mutations(rng, golden.manifest)
        valid = validate_manifest(document) == []
        assert valid == schema_accepts("pack-manifest.v1.schema.json", document), document
        rejected += not valid
    assert rejected > 500


def test_the_vector_file_is_listed() -> None:
    assert (VECTORS / "pack-manifest.json").is_file()
