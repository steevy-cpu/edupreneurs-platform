"""Build and verify a content pack in a LOCAL DIRECTORY (no cloud storage, no upload).

    # from the local database: one pack release, with asset files named by their sha256
    uv run python scripts/build_pack.py build --release-id <uuid> --assets-dir <dir> --out <dir>

    # from a JSON description (the "input" of a case in vectors/pack-manifest.json)
    uv run python scripts/build_pack.py build-file --input <pack.json> --out <dir>

    # check a pack directory end to end; exit code 1 when anything is corrupt
    uv run python scripts/build_pack.py verify --dir <dir> --manifest-key <key> [--sha256 <hex>]

What `build` does: reads the release, its lesson revisions, questions and
attached assets (read-only), validates every lesson against the content-format
contracts, checks every asset file against its recorded hash, size and type,
writes the lesson objects, the assets and the canonical manifest to the output
directory, then reads everything back and verifies it. It prints the size of
each lesson and the manifest's SHA-256.

What it does NOT do: it never writes to the database, never marks a release
ready, and never contacts any other machine. Recording the manifest hash is a
separate, audited staff action (`content.record_release_manifest`); the values
to pass to it are printed at the end.

SAFETY: like every script here, it refuses a database that is not on this
machine (127.0.0.1 / localhost).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import gzip
import json
import sys
import uuid
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlsplit

from edu_api.content.formats import SUPPORTED_FORMATS, required_format
from edu_api.content.pack import (
    BuiltPack,
    PackBuildError,
    PackInput,
    PackIntegrityError,
    PackLesson,
    PackQuestion,
    build_pack,
    pack_input_from_json,
    size_report,
    verify_pack,
    write_pack,
)
from edu_api.content.storage import LocalDirectoryStorage, StorageError
from local_stack import LOCAL_HOSTS, read_env_file

MAX_ASSET_FILE_BYTES = 2_000_000

_RELEASE = """
    SELECT r.id, r.pack_key, r.locale, r.revision, r.status
    FROM app.pack_releases r WHERE r.id = $1
"""
_LESSONS = """
    SELECT pi.position, lr.id AS revision_id, lr.lesson_id, lr.revision, lr.title, lr.blocks
    FROM app.pack_items pi
    JOIN app.lesson_revisions lr ON lr.id = pi.lesson_revision_id
    WHERE pi.pack_release_id = $1
    ORDER BY pi.position
"""
_QUESTIONS = """
    SELECT q.lesson_revision_id, q.id, q.question_key, q.position, q.kind,
           q.prompt, q.response_spec, q.answer_key, q.explanation
    FROM app.question_revisions q
    JOIN app.pack_items pi ON pi.lesson_revision_id = q.lesson_revision_id
    WHERE pi.pack_release_id = $1
    ORDER BY q.lesson_revision_id, q.position
"""
_ATTACHED = """
    SELECT ra.lesson_revision_id, encode(a.sha256, 'hex') AS sha256, a.mime, a.bytes,
           a.width, a.height
    FROM content.revision_assets ra
    JOIN content.assets a ON a.sha256 = ra.asset_sha256
    JOIN app.pack_items pi ON pi.lesson_revision_id = ra.lesson_revision_id
    WHERE pi.pack_release_id = $1
"""

Attached = dict[str, dict[str, dict[str, Any]]]


def _fail(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


async def load_pack_input(
    conn: Any, release_id: uuid.UUID, content_format: int | None = None
) -> tuple[PackInput, Attached]:
    """Read one pack release from the database (any asyncpg connection, read-only use).

    ``content_format`` defaults to the smallest format able to carry the content.
    Returns the builder's input and what the database recorded about attached assets.
    """
    release = await conn.fetchrow(_RELEASE, release_id)
    if release is None:
        raise PackBuildError("pack.identity", "unknown pack release")
    questions: dict[uuid.UUID, list[PackQuestion]] = {}
    for row in await conn.fetch(_QUESTIONS, release_id):
        questions.setdefault(row["lesson_revision_id"], []).append(
            PackQuestion(
                id=str(row["id"]),
                question_key=row["question_key"],
                position=row["position"],
                kind=row["kind"],
                prompt=json.loads(row["prompt"]),
                response_spec=json.loads(row["response_spec"]),
                answer_key=json.loads(row["answer_key"]),
                explanation=json.loads(row["explanation"]),
            )
        )
    lessons = tuple(
        PackLesson(
            position=row["position"],
            lesson_id=str(row["lesson_id"]),
            revision_id=str(row["revision_id"]),
            revision=row["revision"],
            title=row["title"],
            blocks=json.loads(row["blocks"]),
            questions=tuple(questions.get(row["revision_id"], ())),
        )
        for row in await conn.fetch(_LESSONS, release_id)
    )
    attached: Attached = {}
    for row in await conn.fetch(_ATTACHED, release_id):
        recorded: dict[str, Any] = {"mime": row["mime"], "bytes": row["bytes"]}
        if row["width"] is not None:
            recorded |= {"width": row["width"], "height": row["height"]}
        attached.setdefault(str(row["lesson_revision_id"]), {})[row["sha256"]] = recorded
    if content_format is None:
        try:
            content_format = max(
                (
                    required_format(lesson.blocks, [q.kind for q in lesson.questions])
                    for lesson in lessons
                ),
                default=1,
            )
        except ValueError as error:
            raise PackBuildError("lesson.blocks", str(error)) from None
    pack = PackInput(
        release_id=str(release["id"]),
        pack_key=release["pack_key"],
        locale=release["locale"],
        revision=release["revision"],
        content_format=content_format,
        lessons=lessons,
    )
    return pack, attached


def read_asset_files(directory: Path | None) -> dict[str, bytes]:
    """Files of ``directory`` whose name (without extension) is a 64-hex sha256."""
    files: dict[str, bytes] = {}
    if directory is None:
        return files
    if not directory.is_dir():
        _fail(f"assets directory not found: {directory}")
    for path in sorted(directory.iterdir()):
        name = path.name.split(".", 1)[0]
        if path.is_file() and len(name) == 64 and path.stat().st_size <= MAX_ASSET_FILE_BYTES:
            files[name] = path.read_bytes()
    return files


def gzip_estimate(built: BuiltPack) -> int:
    """Bytes on the wire if the manifest and lesson objects are gzipped (assets already are)."""
    total = len(gzip.compress(built.manifest_bytes, compresslevel=9, mtime=0))
    for key, data in built.objects.items():
        if key.startswith("lessons/"):
            total += len(gzip.compress(data, compresslevel=9, mtime=0))
        else:
            total += len(data)
    return total


def report(built: BuiltPack) -> None:
    for line in size_report(built):
        print(line)
    print(f"with gzip on manifest and lesson objects (assets as they are): {gzip_estimate(built)}")
    print("to record this manifest (staff action, not done by this script):")
    print(f"  release_id       {built.manifest['pack']['release_id']}")
    print(f"  manifest key     {built.manifest_key}")
    print(f"  manifest sha256  {built.manifest_sha256}")
    print(f"  manifest bytes   {len(built.manifest_bytes)}")


def _store(built: BuiltPack, out: Path) -> None:
    try:
        write_pack(LocalDirectoryStorage(out), built)
    except (StorageError, PackIntegrityError) as error:
        _fail(f"could not store or verify the pack: {error}")
    print(f"written and verified: {out}")
    report(built)


async def _build_from_database(args: argparse.Namespace) -> BuiltPack:
    import asyncpg

    admin_url = read_env_file().get("LOCAL_ADMIN_DATABASE_URL", "")
    if not admin_url:
        _fail(".env has no LOCAL_ADMIN_DATABASE_URL. Run `make start && make db-reset` first.")
    host = urlsplit(admin_url).hostname
    if host not in LOCAL_HOSTS:
        _fail(f"database host '{host}' is not this machine. Refusing to continue.")
    conn = await asyncpg.connect(admin_url, timeout=10)
    try:
        async with conn.transaction(readonly=True):
            pack, attached = await load_pack_input(conn, args.release_id, args.content_format)
    finally:
        await conn.close()
    return build_pack(pack, read_asset_files(args.assets_dir), attached)


def cmd_build(args: argparse.Namespace) -> None:
    try:
        built = asyncio.run(_build_from_database(args))
    except PackBuildError as error:
        _fail(f"pack refused: {error}")
    _store(built, args.out)


def cmd_build_file(args: argparse.Namespace) -> None:
    try:
        document = json.loads(args.input.read_text(encoding="utf-8"))
        assets = {
            name: base64.b64decode(data, validate=True)
            for name, data in document.get("assets_base64", {}).items()
        }
        assets |= read_asset_files(args.assets_dir)
        built = build_pack(pack_input_from_json(document), assets)
    except PackBuildError as error:
        _fail(f"pack refused: {error}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        _fail(f"cannot read the pack description: {type(error).__name__}")
    _store(built, args.out)


def cmd_verify(args: argparse.Namespace) -> None:
    try:
        manifest = verify_pack(
            LocalDirectoryStorage(args.dir),
            args.manifest_key,
            args.sha256,
            require_optional=not args.allow_missing_audio,
        )
    except (PackIntegrityError, StorageError) as error:
        _fail(f"pack is NOT intact: {error}")
    totals = manifest["totals"]
    print(
        f"pack is intact: {totals['lessons']} lessons, {totals['questions']} questions, "
        f"{totals['assets']} assets, content format {manifest['content_format']}"
    )
    if args.sha256 is None:
        print(
            "note: no --sha256 given, so the manifest itself was not checked against a known hash"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build one pack release from the LOCAL database")
    build.add_argument("--release-id", type=uuid.UUID, required=True)
    build.add_argument("--assets-dir", type=Path, default=None)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--content-format", type=int, choices=SUPPORTED_FORMATS, default=None)
    build.set_defaults(run=cmd_build)

    build_file = commands.add_parser("build-file", help="build a pack from a JSON description")
    build_file.add_argument("--input", type=Path, required=True)
    build_file.add_argument("--assets-dir", type=Path, default=None)
    build_file.add_argument("--out", type=Path, required=True)
    build_file.set_defaults(run=cmd_build_file)

    verify = commands.add_parser("verify", help="verify a pack directory against its manifest")
    verify.add_argument("--dir", type=Path, required=True)
    verify.add_argument("--manifest-key", required=True)
    verify.add_argument("--sha256", default=None, help="expected SHA-256 of the manifest")
    verify.add_argument("--allow-missing-audio", action="store_true")
    verify.set_defaults(run=cmd_verify)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
