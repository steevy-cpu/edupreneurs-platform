"""Content lane against the real local database: exposure, seed compatibility,
and the pack builder reading a release and having its manifest recorded."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import uuid
import zlib
from pathlib import Path

import asyncpg
import httpx
import pytest

from edu_api.content.blocks import validate_blocks
from edu_api.content.formats import required_format
from edu_api.content.pack import (
    PackBuildError,
    PackIntegrityError,
    build_pack,
    verify_pack,
    write_pack,
)
from edu_api.content.questions import validate_question
from edu_api.content.storage import LocalDirectoryStorage
from tests.conftest import approve_revision, create_lesson
from tests.content_fixtures import BLOCK_SCHEMAS, schema_accepts
from tests.helpers import EDITOR, SEED_REV_FR, SEED_SOURCE, bearer

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from build_pack import gzip_estimate, load_pack_input

pytestmark = pytest.mark.integration
SEED_RELEASE_FR = uuid.UUID("f0000000-0000-4000-8000-000000000001")


def synthetic_png(width: int, height: int, seed: bytes) -> bytes:
    """A real, tiny grayscale PNG (stored deflate), different for every seed."""
    row = (seed * (width // len(seed) + 1))[:width]
    raw = b"".join(b"\x00" + row for _ in range(height))
    stored = b"\x78\x01\x01" + struct.pack("<HH", len(raw), len(raw) ^ 0xFFFF) + raw
    stored += struct.pack(">I", zlib.adler32(raw))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", stored) + chunk(b"IEND", b"")
    )


async def test_content_schema_is_not_reachable_through_the_supabase_data_api(
    local_env: dict[str, str], tokens: dict[str, str]
) -> None:
    rest = local_env["LOCAL_SUPABASE_URL"] + "/rest/v1"
    credentials = {
        "publishable key only": {"apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"]},
        "signed-in student": {
            "apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"],
            **bearer(tokens["student_a"]),
        },
        "signed-in editor": {
            "apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"],
            **bearer(tokens["editor"]),
        },
        "SECRET service key": {"apikey": local_env["LOCAL_SUPABASE_SECRET_KEY"]},
    }
    async with httpx.AsyncClient(timeout=10) as http:
        for label, headers in credentials.items():
            for table in ("assets", "revision_assets", "pack_manifests"):
                for profile in ({"Accept-Profile": "content"}, {}):
                    response = await http.get(
                        f"{rest}/{table}", params={"select": "*"}, headers={**headers, **profile}
                    )
                    assert response.status_code >= 400, (label, table, profile, response.text[:200])
            for function in ("register_asset", "attach_asset", "record_release_manifest"):
                rpc = await http.post(
                    f"{rest}/rpc/{function}",
                    headers={**headers, "Content-Profile": "content"},
                    json={},
                )
                assert rpc.status_code >= 400, (label, function, rpc.text[:200])
        exposed = (await http.get(f"{rest}/", headers=credentials["SECRET service key"])).text
    assert "revision_assets" not in exposed and "pack_manifests" not in exposed


async def test_student_api_login_cannot_reach_the_content_schema(
    app: object, admin: asyncpg.Pool
) -> None:
    database = app.state.db  # type: ignore[attr-defined]
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    for statement in (
        "SELECT count(*) FROM content.assets",
        "SELECT content.blocks_required_format('[]'::jsonb)",
        "SELECT content.register_asset(sha256('x'), 1, 'image/png', 1, 1, NULL, '{}'::jsonb, gen_random_uuid())",
    ):
        with pytest.raises(DBAPIError) as refused:
            async with database.transaction(EDITOR) as conn:
                await conn.execute(text(statement))
        assert getattr(refused.value.orig, "sqlstate", None) == "42501", statement


async def test_seed_content_is_valid_format_2_and_requires_only_format_1(
    admin: asyncpg.Pool,
) -> None:
    """'Keep v1 content readable': everything published today passes the v2 contracts unchanged."""
    revisions = await admin.fetch(
        "SELECT id, blocks FROM app.lesson_revisions WHERE id::text LIKE 'c0000000-0000-4000-8000-00000000000_'"
    )
    assert len(revisions) == 2
    for revision in revisions:
        blocks = json.loads(revision["blocks"])
        for content_format in (1, 2):
            assert validate_blocks(blocks, content_format) == []
            assert schema_accepts(BLOCK_SCHEMAS[content_format], blocks)
        questions = await admin.fetch(
            "SELECT kind, prompt, response_spec, answer_key, explanation FROM app.question_revisions "
            "WHERE lesson_revision_id = $1",
            revision["id"],
        )
        assert len(questions) == 5
        for q in questions:
            columns = {
                k: json.loads(q[k])
                for k in ("prompt", "response_spec", "answer_key", "explanation")
            }
            assert validate_question(q["kind"], columns) == []
        assert required_format(blocks, [q["kind"] for q in questions]) == 1
        assert (
            await admin.fetchval("SELECT content.revision_required_format($1)", revision["id"]) == 1
        )


async def test_build_the_seed_release_from_the_database(
    admin: asyncpg.Pool, tmp_path: Path
) -> None:
    async with admin.acquire() as conn:
        pack, attached = await load_pack_input(conn, SEED_RELEASE_FR)
    assert (pack.pack_key, pack.locale, pack.revision, pack.content_format) == (
        "math-9af",
        "fr",
        1,
        1,
    )
    assert attached == {} and [lesson.revision_id for lesson in pack.lessons] == [str(SEED_REV_FR)]
    built = build_pack(pack, {}, attached)
    again = build_pack(pack, {}, attached)
    assert built.manifest_bytes == again.manifest_bytes and built.objects == again.objects
    storage = LocalDirectoryStorage(tmp_path / "seed")
    write_pack(storage, built)
    manifest = verify_pack(storage, built.manifest_key, built.manifest_sha256)
    assert manifest["totals"]["questions"] == 5 and manifest["totals"]["assets"] == 0
    # The lesson object carries exactly what /v1/lessons serves for this revision.
    lesson = json.loads(built.objects[manifest["lessons"][0]["object_key"]])
    stored_blocks = await admin.fetchval(
        "SELECT blocks FROM app.lesson_revisions WHERE id = $1", SEED_REV_FR
    )
    assert lesson["blocks"] == json.loads(stored_blocks) and lesson["content_format"] == 1
    # Corrupt the stored lesson: rejected, and the object is named.
    path = storage.root / manifest["lessons"][0]["object_key"]
    path.write_bytes(path.read_bytes().replace(b"x = 7", b"x = 8"))
    with pytest.raises(PackIntegrityError) as rejected:
        verify_pack(storage, built.manifest_key, built.manifest_sha256)
    assert rejected.value.code == "object.hash"
    print(
        f"\nMEASURED seed pack math-9af/fr: manifest {len(built.manifest_bytes)} B, "
        f"lesson {built.sizes[0].lesson_bytes} B, total {built.total_bytes} B, gzip {gzip_estimate(built)} B"
    )
    # The seed release's stored digest is a labelled placeholder, not this real hash.
    stored = await admin.fetchval(
        "SELECT encode(manifest_sha256, 'hex') FROM app.pack_releases WHERE id = $1",
        SEED_RELEASE_FR,
    )
    assert stored != built.manifest_sha256


async def test_format_2_lesson_from_draft_to_recorded_manifest(
    admin: asyncpg.Pool, tmp_path: Path
) -> None:
    """Asset registered and attached through the staff functions, lesson approved through the
    real editorial workflow, pack built from the database, manifest recorded by a publisher.
    The release, the staff role and the manifest live in a transaction that is rolled back."""
    png = synthetic_png(32, 18, uuid.uuid4().bytes)
    digest = hashlib.sha256(png).digest()
    asset = {
        "sha256": digest.hex(),
        "mime": "image/png",
        "bytes": len(png),
        "width": 32,
        "height": 18,
    }
    blocks = [
        {"key": "intro", "type": "paragraph", "text": "Contenu synthétique de test."},
        {
            "key": "f",
            "type": "math",
            "notation": "edu-math-1",
            "source": "\\frac{1}{2} = 0,5",
            "alt": "un demi égale zéro virgule cinq",
        },
        {"key": "img", "type": "image", "asset": asset, "alt": "Un rectangle gris."},
        {
            "key": "t",
            "type": "table",
            "caption": "Table",
            "columns": ["A", "B"],
            "rows": [["1", "2"]],
        },
    ]
    lesson_id = await create_lesson(admin)
    async with admin.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('edu.actor_id', $1, true)", str(EDITOR))
        revision_id = await conn.fetchval(
            "INSERT INTO app.lesson_revisions (lesson_id, revision, locale, title, blocks, created_by) "
            "VALUES ($1, 1, 'fr', 'Leçon synthétique format 2', $2::jsonb, $3) RETURNING id",
            lesson_id, json.dumps(blocks), EDITOR,
        )  # fmt: skip
        await conn.execute(
            "INSERT INTO app.lesson_revision_sources (lesson_revision_id, source_id) VALUES ($1, $2)",
            revision_id, SEED_SOURCE,
        )  # fmt: skip
        created = await conn.fetchval(
            "SELECT content.register_asset($1, $2, 'image/png', 32, 18, NULL, $3::jsonb, $4) ->> 'created'",
            digest, len(png), '{"fr": "Un rectangle gris."}', SEED_SOURCE,
        )  # fmt: skip
        attached_now = await conn.fetchval(
            "SELECT content.attach_asset($1, $2) ->> 'attached'", revision_id, digest
        )
        assert (created, attached_now) == ("true", "true")
    await approve_revision(admin, revision_id)

    conn = await admin.acquire()
    transaction = conn.transaction()
    await transaction.start()
    try:
        release_id = await conn.fetchval(
            "INSERT INTO app.pack_releases (pack_key, revision, locale, created_by) "
            "VALUES ($1, 1, 'fr', $2) RETURNING id",
            f"it-{uuid.uuid4().hex[:12]}", EDITOR,
        )  # fmt: skip
        await conn.execute(
            "INSERT INTO app.pack_items (pack_release_id, lesson_revision_id, position) VALUES ($1, $2, 1)",
            release_id, revision_id,
        )  # fmt: skip
        with pytest.raises(PackBuildError) as refused:  # the negotiation rule, in the builder
            build_pack((await load_pack_input(conn, release_id, 1))[0], {digest.hex(): png})
        assert refused.value.code == "pack.content_format"
        pack, attached = await load_pack_input(conn, release_id)
        assert pack.content_format == 2 and attached == {
            str(revision_id): {digest.hex(): {k: v for k, v in asset.items() if k != "sha256"}}
        }
        with pytest.raises(PackBuildError) as refused:
            build_pack(pack, {}, attached)
        assert refused.value.code == "asset.missing"
        built = build_pack(pack, {digest.hex(): png}, attached)
        storage = LocalDirectoryStorage(tmp_path / "v2")
        write_pack(storage, built)

        await conn.execute(
            "INSERT INTO app.staff_roles (user_id, role) VALUES ($1, 'publisher')", EDITOR
        )
        await conn.execute("SELECT set_config('edu.actor_id', $1, true)", str(EDITOR))
        recorded = json.loads(
            await conn.fetchval(
                # The manifest's BYTES: the database computes the hash and the size itself.
                "SELECT content.record_release_manifest($1, $2::bytea)",
                release_id,
                built.manifest_bytes,
            )
        )
        assert recorded["status"] == "ready" and recorded["total_bytes"] == built.total_bytes
        assert recorded["manifest_object_key"] == built.manifest_key
        assert recorded["manifest_sha256"] == built.manifest_sha256
        row = await conn.fetchrow(
            "SELECT r.status, encode(r.manifest_sha256, 'hex') AS sha, r.compressed_bytes, m.content_format "
            "FROM app.pack_releases r JOIN content.pack_manifests m ON m.pack_release_id = r.id WHERE r.id = $1",
            release_id,
        )
        assert tuple(row) == ("ready", built.manifest_sha256, built.total_bytes, 2)
        # What the database recorded is what verifies the stored pack.
        verify_pack(storage, built.manifest_key, row["sha"])
        print(
            f"\nMEASURED synthetic format-2 pack (1 lesson: math, 32x18 PNG, table): manifest "
            f"{len(built.manifest_bytes)} B, lesson {built.sizes[0].lesson_bytes} B, image "
            f"{built.sizes[0].required_asset_bytes} B, total {built.total_bytes} B, gzip {gzip_estimate(built)} B"
        )
    finally:
        await transaction.rollback()
        await admin.release(conn)
    assert await admin.fetchval("SELECT count(*) FROM content.pack_manifests") == 0
