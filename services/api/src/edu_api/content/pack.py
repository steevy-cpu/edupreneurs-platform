"""Deterministic pack builder and verifier (manifest ``pack-manifest-1``).

A *pack* is what a phone downloads for one (pack_key, locale): a manifest that
lists lesson objects and assets with their true SHA-256 and sizes. Everything
here is pure - bytes in, bytes out; storage is behind
:class:`~edu_api.content.storage.PackStorage`.

OBJECTS AND KEYS

    packs/<pack_key>/<locale>/<revision>/manifest.json   the manifest
    lessons/sha256/<aa>/<sha256>.json                    one lesson revision
    assets/sha256/<aa>/<sha256>                          one image or audio file

Lesson objects and assets are content-addressed, so unchanged lessons and
pictures are shared between releases and are never downloaded twice.

THE MANIFEST (canonical JSON ``edu-canon-json-1``; arrays in this fixed order)

    manifest_version  "pack-manifest-1"
    content_format    1 or 2; no lesson in the pack needs a higher format
    pack              {release_id, pack_key, locale, revision}
    lessons           ordered by position:
                      {position, lesson_id, revision_id, revision, title,
                       content_format, object_key, sha256, bytes,
                       questions: [{id, question_key, position, kind}] by position,
                       assets: [sha256, ...] sorted}
    assets            sorted by sha256:
                      {sha256, object_key, bytes, mime, kind, required}
                      required is true for images and false for audio
    totals            {lessons, questions, assets, lesson_bytes,
                       required_asset_bytes, optional_asset_bytes}

It contains no timestamp, no host name and nothing random: the same input
always gives the same bytes, hence the same hash (golden test).

A LESSON OBJECT (``pack-lesson-1``, canonical JSON) carries what
``GET /v1/lessons/{id}`` returns today plus its format:

    {blob_version, content_format, lesson_id, revision_id, revision, locale,
     title, blocks, questions: [{id, question_key, position, kind, prompt,
     response_spec, answer_key, explanation}]}

Answer keys are included on purpose (offline practice), exactly as today.
"""

from __future__ import annotations

import json
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from edu_api.content.blocks import asset_references, validate_blocks
from edu_api.content.canonical import canonical_json, is_canonical_json, sha256_hex
from edu_api.content.formats import (
    SUPPORTED_FORMATS,
    V1_QUESTION_KINDS,
    V2_QUESTION_KINDS,
    required_format,
)
from edu_api.content.issues import Collector, Issue, is_plain_text
from edu_api.content.questions import validate_question
from edu_api.content.storage import PackStorage, StorageError

MANIFEST_VERSION = "pack-manifest-1"
LESSON_BLOB_VERSION = "pack-lesson-1"
MAX_PACK_LESSONS = 500
MAX_PACK_ASSETS = 2000
MAX_QUESTIONS_PER_LESSON = 100
MAX_MANIFEST_BYTES = 1_048_576
MAX_LESSON_BYTES = 262_144

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_PACK_KEY = re.compile(r"[a-z0-9_-]{3,100}")
_QUESTION_KEY = re.compile(r"[a-z0-9_-]{1,80}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MIMES = ("image/webp", "image/png", "image/jpeg", "audio/mp4", "audio/mpeg")
_LOCALES = ("fr", "ht")


class PackBuildError(Exception):
    """The input cannot be turned into a pack. ``code`` is stable; ``detail`` is for people."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class PackIntegrityError(Exception):
    """A stored pack does not match its manifest. ``key`` names the offending object."""

    def __init__(self, code: str, key: str) -> None:
        super().__init__(f"{code}: {key}")
        self.code = code
        self.key = key


# --- input ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PackQuestion:
    id: str
    question_key: str
    position: int
    kind: str
    prompt: dict[str, Any]
    response_spec: dict[str, Any]
    answer_key: dict[str, Any]
    explanation: dict[str, Any]


@dataclass(frozen=True)
class PackLesson:
    position: int
    lesson_id: str
    revision_id: str
    revision: int
    title: str
    blocks: list[dict[str, Any]]
    questions: tuple[PackQuestion, ...] = ()


@dataclass(frozen=True)
class PackInput:
    release_id: str
    pack_key: str
    locale: str
    revision: int
    content_format: int
    lessons: tuple[PackLesson, ...]


# --- output --------------------------------------------------------------------------
@dataclass(frozen=True)
class LessonSize:
    """Download cost of one lesson: its own object plus the assets it references."""

    position: int
    revision_id: str
    title: str
    lesson_bytes: int
    required_asset_bytes: int
    optional_asset_bytes: int

    @property
    def required_bytes(self) -> int:
        return self.lesson_bytes + self.required_asset_bytes


@dataclass(frozen=True)
class BuiltPack:
    manifest: dict[str, Any]
    manifest_key: str
    manifest_bytes: bytes
    manifest_sha256: str
    #: every object except the manifest: key -> bytes
    objects: dict[str, bytes]
    sizes: tuple[LessonSize, ...] = field(default=())

    @property
    def total_bytes(self) -> int:
        """Bytes of a full download: manifest + every lesson object + every asset."""
        return len(self.manifest_bytes) + sum(len(data) for data in self.objects.values())


# --- object keys and file signatures ----------------------------------------------------
def manifest_object_key(pack_key: str, locale: str, revision: int) -> str:
    return f"packs/{pack_key}/{locale}/{revision}/manifest.json"


def lesson_object_key(sha256: str) -> str:
    return f"lessons/sha256/{sha256[:2]}/{sha256}.json"


def asset_object_key(sha256: str) -> str:
    """Same rule as the SQL function ``content.asset_object_key``."""
    return f"assets/sha256/{sha256[:2]}/{sha256}"


def sniff_mime(data: bytes) -> str | None:
    """Media type suggested by the file's first bytes, or ``None``.

    This is a signature check, not a decoder: it stops a file from being
    shipped under the wrong type (an HTML page named ``.png``), nothing more.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    return None


def png_size(data: bytes) -> tuple[int, int] | None:
    """Intrinsic (width, height) of a PNG, read from its IHDR chunk."""
    if sniff_mime(data) != "image/png" or len(data) < 24 or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


# --- build ---------------------------------------------------------------------------
def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_types(pack: PackInput) -> None:
    """Wrong Python types in the input are a refusal, never a traceback (review L3)."""
    if not (
        isinstance(pack.release_id, str)
        and isinstance(pack.pack_key, str)
        and isinstance(pack.locale, str)
        and _is_int(pack.revision)
        and _is_int(pack.content_format)
        and isinstance(pack.lessons, tuple | list)
    ):
        raise PackBuildError("pack.identity", "a pack field has the wrong type")
    for lesson in pack.lessons:
        if not (
            isinstance(lesson, PackLesson)
            and _is_int(lesson.position)
            and _is_int(lesson.revision)
            and isinstance(lesson.lesson_id, str)
            and isinstance(lesson.revision_id, str)
            and isinstance(lesson.title, str)
            and isinstance(lesson.questions, tuple | list)
        ):
            raise PackBuildError("lesson.identity", "a lesson field has the wrong type")
        for question in lesson.questions:
            if not (
                isinstance(question, PackQuestion)
                and isinstance(question.id, str)
                and isinstance(question.question_key, str)
                and _is_int(question.position)
                and isinstance(question.kind, str)
            ):
                raise PackBuildError("lesson.questions", "a question field has the wrong type")


def _check_identity(pack: PackInput) -> None:
    _check_types(pack)
    if not _UUID.fullmatch(pack.release_id) or not _PACK_KEY.fullmatch(pack.pack_key):
        raise PackBuildError("pack.identity", "release_id or pack_key is malformed")
    if pack.locale not in _LOCALES or pack.revision < 1:
        raise PackBuildError("pack.identity", "locale or revision is malformed")
    if pack.content_format not in SUPPORTED_FORMATS:
        raise PackBuildError("pack.content_format", "unsupported content format")
    if not 1 <= len(pack.lessons) <= MAX_PACK_LESSONS:
        raise PackBuildError("pack.lessons", "a pack holds between 1 and 500 lessons")
    positions = [lesson.position for lesson in pack.lessons]
    revisions = [lesson.revision_id for lesson in pack.lessons]
    if len(set(positions)) != len(positions) or min(positions) < 1:
        raise PackBuildError("pack.lessons", "lesson positions must be unique and positive")
    if len(set(revisions)) != len(revisions):
        raise PackBuildError("pack.lessons", "a lesson revision appears twice")


def _first(issues: list[Issue]) -> str:
    return f"{issues[0].rule} at '{issues[0].path}' ({issues[0].message})"


def _check_lesson(pack: PackInput, lesson: PackLesson) -> int:
    """Validate one lesson against the pack's format. Returns the lesson's required format."""
    where = f"lesson at position {lesson.position}"
    if not _UUID.fullmatch(lesson.lesson_id) or not _UUID.fullmatch(lesson.revision_id):
        raise PackBuildError("lesson.identity", f"{where}: malformed id")
    if lesson.revision < 1 or not 1 <= len(lesson.title) <= 200:
        raise PackBuildError("lesson.identity", f"{where}: malformed revision or title")
    if not is_plain_text(lesson.title):
        raise PackBuildError(
            "lesson.title", f"{where}: the title must be plain text (no control, no markup)"
        )
    if len(lesson.questions) > MAX_QUESTIONS_PER_LESSON:
        raise PackBuildError("lesson.questions", f"{where}: too many questions")
    kinds = [question.kind for question in lesson.questions]
    if not isinstance(lesson.blocks, list) or not all(isinstance(b, dict) for b in lesson.blocks):
        raise PackBuildError("lesson.blocks", f"{where}: blocks must be a list of objects")
    try:
        needed = required_format(lesson.blocks, kinds)
    except ValueError as error:
        raise PackBuildError("lesson.blocks", f"{where}: {error}") from None
    # The negotiation rule: a pack never contains content above its declared format.
    if needed > pack.content_format:
        raise PackBuildError(
            "pack.content_format",
            f"{where} needs content format {needed}; the pack declares {pack.content_format}",
        )
    issues = validate_blocks(lesson.blocks, needed)
    if issues:
        raise PackBuildError("lesson.blocks", f"{where}: {_first(issues)}")
    seen_positions: set[int] = set()
    seen_ids: set[str] = set()
    for question in lesson.questions:
        if (
            not _UUID.fullmatch(question.id)
            or not _QUESTION_KEY.fullmatch(question.question_key)
            or question.position < 1
            or question.position in seen_positions
            or question.id in seen_ids
        ):
            raise PackBuildError("lesson.questions", f"{where}: malformed question identity")
        seen_positions.add(question.position)
        seen_ids.add(question.id)
        issues = validate_question(
            question.kind,
            {
                "prompt": question.prompt,
                "response_spec": question.response_spec,
                "answer_key": question.answer_key,
                "explanation": question.explanation,
            },
        )
        if issues:
            raise PackBuildError(
                "lesson.questions", f"{where}, question {question.question_key}: {_first(issues)}"
            )
    return needed


def _check_asset_bytes(sha256: str, reference: Mapping[str, Any], data: bytes | None) -> None:
    if data is None:
        raise PackBuildError("asset.missing", f"no file was provided for asset {sha256}")
    if sha256_hex(data) != sha256:
        raise PackBuildError("asset.hash", f"file content does not hash to {sha256}")
    if len(data) != reference["bytes"]:
        raise PackBuildError("asset.bytes", f"asset {sha256}: size differs from its reference")
    if sniff_mime(data) != reference["mime"]:
        raise PackBuildError("asset.mime", f"asset {sha256}: content is not {reference['mime']}")
    size = png_size(data)
    if size is not None and size != (reference["width"], reference["height"]):
        raise PackBuildError("asset.size", f"asset {sha256}: intrinsic size differs")


def lesson_blob(pack: PackInput, lesson: PackLesson, content_format: int) -> bytes:
    """Canonical bytes of one lesson object (``pack-lesson-1``)."""
    return canonical_json(
        {
            "blob_version": LESSON_BLOB_VERSION,
            "content_format": content_format,
            "lesson_id": lesson.lesson_id,
            "revision_id": lesson.revision_id,
            "revision": lesson.revision,
            "locale": pack.locale,
            "title": lesson.title,
            "blocks": lesson.blocks,
            "questions": [
                {
                    "id": q.id,
                    "question_key": q.question_key,
                    "position": q.position,
                    "kind": q.kind,
                    "prompt": q.prompt,
                    "response_spec": q.response_spec,
                    "answer_key": q.answer_key,
                    "explanation": q.explanation,
                }
                for q in sorted(lesson.questions, key=lambda q: q.position)
            ],
        }
    )


def build_pack(
    pack: PackInput,
    asset_files: Mapping[str, bytes],
    attached: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
) -> BuiltPack:
    """Build the manifest and every object of a pack. Pure and deterministic.

    ``asset_files`` maps sha256 (hex) to the file's bytes. ``attached``, when
    given, is what the database recorded: revision_id -> sha256 -> {mime, bytes,
    width, height}. Every asset a lesson references must then be attached to
    that lesson revision with the same metadata (which is what puts it under
    the rights gate). Raises :class:`PackBuildError`; nothing is written.
    """
    _check_identity(pack)
    lessons = sorted(pack.lessons, key=lambda lesson: lesson.position)
    objects: dict[str, bytes] = {}
    manifest_lessons: list[dict[str, Any]] = []
    assets: dict[str, dict[str, Any]] = {}
    sizes: list[LessonSize] = []

    for lesson in lessons:
        needed = _check_lesson(pack, lesson)
        references = asset_references(lesson.blocks)
        for sha256, reference in references.items():
            known = assets.get(sha256)
            if known is not None and known != reference:
                raise PackBuildError(
                    "asset.inconsistent", f"asset {sha256} differs between lessons"
                )
            if attached is not None:
                recorded = attached.get(lesson.revision_id, {}).get(sha256)
                if recorded is None:
                    raise PackBuildError(
                        "asset.not_attached",
                        f"asset {sha256} is not attached to revision {lesson.revision_id}",
                    )
                if any(recorded.get(name) != reference.get(name) for name in recorded):
                    raise PackBuildError(
                        "asset.metadata", f"asset {sha256}: block and database disagree"
                    )
            if known is None:
                _check_asset_bytes(sha256, reference, asset_files.get(sha256))
                assets[sha256] = reference
                objects[asset_object_key(sha256)] = asset_files[sha256]

        try:
            blob = lesson_blob(pack, lesson, needed)
        except TypeError as error:  # a float, a lone surrogate, an odd key in a question
            raise PackBuildError(
                "lesson.canonical", f"lesson at position {lesson.position}: {error}"
            ) from None
        if len(blob) > MAX_LESSON_BYTES:
            raise PackBuildError("lesson.bytes", f"lesson at position {lesson.position} is too big")
        blob_hash = sha256_hex(blob)
        objects[lesson_object_key(blob_hash)] = blob
        manifest_lessons.append(
            {
                "position": lesson.position,
                "lesson_id": lesson.lesson_id,
                "revision_id": lesson.revision_id,
                "revision": lesson.revision,
                "title": lesson.title,
                "content_format": needed,
                "object_key": lesson_object_key(blob_hash),
                "sha256": blob_hash,
                "bytes": len(blob),
                "questions": [
                    {
                        "id": q.id,
                        "question_key": q.question_key,
                        "position": q.position,
                        "kind": q.kind,
                    }
                    for q in sorted(lesson.questions, key=lambda q: q.position)
                ],
                "assets": sorted(references),
            }
        )
        sizes.append(
            LessonSize(
                position=lesson.position,
                revision_id=lesson.revision_id,
                title=lesson.title,
                lesson_bytes=len(blob),
                required_asset_bytes=sum(
                    r["bytes"] for r in references.values() if r["kind"] == "image"
                ),
                optional_asset_bytes=sum(
                    r["bytes"] for r in references.values() if r["kind"] == "audio"
                ),
            )
        )

    if len(assets) > MAX_PACK_ASSETS:
        raise PackBuildError("pack.assets", "too many assets in one pack")
    manifest_assets = [
        {
            "sha256": sha256,
            "object_key": asset_object_key(sha256),
            "bytes": assets[sha256]["bytes"],
            "mime": assets[sha256]["mime"],
            "kind": assets[sha256]["kind"],
            "required": assets[sha256]["kind"] == "image",
        }
        for sha256 in sorted(assets)
    ]
    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "content_format": pack.content_format,
        "pack": {
            "release_id": pack.release_id,
            "pack_key": pack.pack_key,
            "locale": pack.locale,
            "revision": pack.revision,
        },
        "lessons": manifest_lessons,
        "assets": manifest_assets,
        "totals": _totals(manifest_lessons, manifest_assets),
    }
    manifest_bytes = canonical_json(manifest)
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise PackBuildError("pack.manifest_bytes", "manifest is too big")
    return BuiltPack(
        manifest=manifest,
        manifest_key=manifest_object_key(pack.pack_key, pack.locale, pack.revision),
        manifest_bytes=manifest_bytes,
        manifest_sha256=sha256_hex(manifest_bytes),
        objects=objects,
        sizes=tuple(sizes),
    )


def _totals(
    lessons: Sequence[Mapping[str, Any]], assets: Sequence[Mapping[str, Any]]
) -> dict[str, int]:
    """The ``totals`` object of a manifest, computed from its two lists."""
    return {
        "lessons": len(lessons),
        "questions": sum(len(entry["questions"]) for entry in lessons),
        "assets": len(assets),
        "lesson_bytes": sum(entry["bytes"] for entry in lessons),
        "required_asset_bytes": sum(a["bytes"] for a in assets if a["required"]),
        "optional_asset_bytes": sum(a["bytes"] for a in assets if not a["required"]),
    }


# --- manifest structure (mirrors pack-manifest.v1.schema.json) ---------------------------
def validate_manifest(document: Any) -> list[Issue]:
    """Structural check of a parsed manifest. Empty list = well-formed."""
    c = Collector()
    if not c.obj(
        document, "", ("manifest_version", "content_format", "pack", "lessons", "assets", "totals")
    ):
        return c.issues
    c.const(document["manifest_version"], "/manifest_version", MANIFEST_VERSION)
    c.integer(document["content_format"], "/content_format", 1, 2)
    pack = document["pack"]
    if c.obj(pack, "/pack", ("release_id", "pack_key", "locale", "revision")):
        c.string(pack["release_id"], "/pack/release_id", min_len=36, max_len=36, pattern=_UUID)
        c.string(pack["pack_key"], "/pack/pack_key", min_len=3, max_len=100, pattern=_PACK_KEY)
        c.enum(pack["locale"], "/pack/locale", _LOCALES)
        c.integer(pack["revision"], "/pack/revision", 1, 2_147_483_647)
    if c.array(document["lessons"], "/lessons", 1, MAX_PACK_LESSONS):
        for index, lesson in enumerate(document["lessons"]):
            _manifest_lesson(c, lesson, f"/lessons/{index}")
            # The negotiation rule, structurally: a format-1 pack lists only format-1 lessons.
            if (
                _is_one(document["content_format"])
                and isinstance(lesson, dict)
                and "content_format" in lesson
                and not _is_one(lesson["content_format"])
            ):
                c.schema(f"/lessons/{index}/content_format", "is higher than the pack's format")
    if c.array(document["assets"], "/assets", 0, MAX_PACK_ASSETS):
        for index, asset in enumerate(document["assets"]):
            path = f"/assets/{index}"
            if c.obj(asset, path, ("sha256", "object_key", "bytes", "mime", "kind", "required")):
                c.string(asset["sha256"], f"{path}/sha256", min_len=64, max_len=64, pattern=_SHA256)
                c.string(asset["object_key"], f"{path}/object_key", max_len=300, no_control=True)
                c.integer(asset["bytes"], f"{path}/bytes", 1, 2_000_000)
                c.enum(asset["mime"], f"{path}/mime", _MIMES)
                c.enum(asset["kind"], f"{path}/kind", ("image", "audio"))
                c.boolean(asset["required"], f"{path}/required")
    totals = document["totals"]
    names = (
        "lessons",
        "questions",
        "assets",
        "lesson_bytes",
        "required_asset_bytes",
        "optional_asset_bytes",
    )
    if c.obj(totals, "/totals", names):
        for name in names:
            c.integer(totals[name], f"/totals/{name}", 0, 2**53)
    return c.issues


def _is_one(value: Any) -> bool:
    """JSON Schema ``const: 1`` (a boolean is not the number 1)."""
    return not isinstance(value, bool) and isinstance(value, int | float) and value == 1


def _manifest_lesson(c: Collector, lesson: Any, path: str) -> None:
    names = (
        "position",
        "lesson_id",
        "revision_id",
        "revision",
        "title",
        "content_format",
        "object_key",
        "sha256",
        "bytes",
        "questions",
        "assets",
    )
    if not c.obj(lesson, path, names):
        return
    c.integer(lesson["position"], f"{path}/position", 1, 2_147_483_647)
    c.string(lesson["lesson_id"], f"{path}/lesson_id", min_len=36, max_len=36, pattern=_UUID)
    c.string(lesson["revision_id"], f"{path}/revision_id", min_len=36, max_len=36, pattern=_UUID)
    c.integer(lesson["revision"], f"{path}/revision", 1, 2_147_483_647)
    c.string(lesson["title"], f"{path}/title", max_len=200, plain=True)
    c.integer(lesson["content_format"], f"{path}/content_format", 1, 2)
    format_1 = _is_one(lesson["content_format"])
    c.string(lesson["object_key"], f"{path}/object_key", max_len=300, no_control=True)
    c.string(lesson["sha256"], f"{path}/sha256", min_len=64, max_len=64, pattern=_SHA256)
    c.integer(lesson["bytes"], f"{path}/bytes", 1, MAX_LESSON_BYTES)
    if c.array(lesson["questions"], f"{path}/questions", 0, MAX_QUESTIONS_PER_LESSON):
        for index, question in enumerate(lesson["questions"]):
            q = f"{path}/questions/{index}"
            if c.obj(question, q, ("id", "question_key", "position", "kind")):
                c.string(question["id"], f"{q}/id", min_len=36, max_len=36, pattern=_UUID)
                c.string(
                    question["question_key"], f"{q}/question_key", max_len=80, pattern=_QUESTION_KEY
                )
                c.integer(question["position"], f"{q}/position", 1, 2_147_483_647)
                c.enum(question["kind"], f"{q}/kind", V2_QUESTION_KINDS)
                # A format-1 lesson only has format-1 question kinds (mcq).
                kind = question["kind"]
                if format_1 and not (isinstance(kind, str) and kind in V1_QUESTION_KINDS):
                    c.schema(f"{q}/kind", "is not a question kind of content format 1")
    if c.array(lesson["assets"], f"{path}/assets", 0, 200):
        for index, sha256 in enumerate(lesson["assets"]):
            c.string(sha256, f"{path}/assets/{index}", min_len=64, max_len=64, pattern=_SHA256)


# --- write and verify ------------------------------------------------------------------
def write_pack(storage: PackStorage, built: BuiltPack) -> None:
    """Store every object, the manifest LAST, then read everything back and verify it.

    Writing the manifest last means a manifest in storage always has its objects.
    """
    for key in sorted(built.objects):
        storage.put(key, built.objects[key])
    storage.put(built.manifest_key, built.manifest_bytes)
    verify_pack(storage, built.manifest_key, built.manifest_sha256)


def _read(storage: PackStorage, key: str) -> bytes:
    try:
        return storage.get(key)
    except StorageError:
        raise PackIntegrityError("object.missing", key) from None


def _verified(storage: PackStorage, key: str, sha256: str, size: int) -> bytes:
    data = _read(storage, key)
    if len(data) != size:
        raise PackIntegrityError("object.size", key)
    if sha256_hex(data) != sha256:
        raise PackIntegrityError("object.hash", key)
    return data


def verify_pack(
    storage: PackStorage,
    manifest_key: str,
    expected_manifest_sha256: str | None = None,
    *,
    require_optional: bool = True,
) -> dict[str, Any]:
    """Check a stored pack end to end; returns the parsed manifest.

    Raises :class:`PackIntegrityError` on the first problem. Order of checks:
    the manifest's own hash (when the caller knows the expected one - the
    server does, from ``pack_releases.manifest_sha256``), its canonical form and
    structure, then every lesson object and asset: present, right size, right
    hash, right type, and consistent with what the manifest says about it.
    ``require_optional=False`` tolerates ABSENT audio files (a phone may skip
    them); an audio file that is present is always checked.
    """
    raw = _read(storage, manifest_key)
    if expected_manifest_sha256 is not None and sha256_hex(raw) != expected_manifest_sha256:
        raise PackIntegrityError("manifest.hash", manifest_key)
    if len(raw) > MAX_MANIFEST_BYTES or not is_canonical_json(raw):
        raise PackIntegrityError("manifest.not_canonical", manifest_key)
    manifest: dict[str, Any] = json.loads(raw)
    if validate_manifest(manifest):
        raise PackIntegrityError("manifest.structure", manifest_key)
    pack = manifest["pack"]
    if manifest_key != manifest_object_key(pack["pack_key"], pack["locale"], pack["revision"]):
        raise PackIntegrityError("manifest.key", manifest_key)

    assets = {asset["sha256"]: asset for asset in manifest["assets"]}
    if sorted(assets) != [asset["sha256"] for asset in manifest["assets"]]:
        raise PackIntegrityError("manifest.structure", manifest_key)
    for sha256, asset in assets.items():
        key = asset_object_key(sha256)
        if asset["object_key"] != key or asset["required"] != (asset["kind"] == "image"):
            raise PackIntegrityError("manifest.structure", manifest_key)
        if not asset["required"] and not require_optional and not storage.exists(key):
            continue
        data = _verified(storage, key, sha256, asset["bytes"])
        if sniff_mime(data) != asset["mime"]:
            raise PackIntegrityError("object.type", key)

    referenced: set[str] = set()
    positions = [lesson["position"] for lesson in manifest["lessons"]]
    if positions != sorted(set(positions)):
        raise PackIntegrityError("manifest.structure", manifest_key)
    # A lesson, a lesson revision and a question appear once in a pack; inside a
    # lesson the questions are in ascending, distinct positions.
    question_ids: list[str] = []
    for name in ("lesson_id", "revision_id"):
        values = [lesson[name] for lesson in manifest["lessons"]]
        if len(set(values)) != len(values):
            raise PackIntegrityError("manifest.duplicate", manifest_key)
    for entry in manifest["lessons"]:
        question_positions = [question["position"] for question in entry["questions"]]
        if question_positions != sorted(set(question_positions)):
            raise PackIntegrityError("manifest.duplicate", manifest_key)
        question_ids.extend(question["id"] for question in entry["questions"])
    if len(set(question_ids)) != len(question_ids):
        raise PackIntegrityError("manifest.duplicate", manifest_key)
    # The totals are recomputed, never believed: a phone budgets its download from them.
    if manifest["totals"] != _totals(manifest["lessons"], manifest["assets"]):
        raise PackIntegrityError("manifest.totals", manifest_key)
    for entry in manifest["lessons"]:
        key = lesson_object_key(entry["sha256"])
        if entry["object_key"] != key or entry["content_format"] > manifest["content_format"]:
            raise PackIntegrityError("manifest.structure", manifest_key)
        data = _verified(storage, key, entry["sha256"], entry["bytes"])
        _verify_lesson_object(data, key, entry, pack["locale"], assets)
        referenced.update(entry["assets"])
    if referenced != set(assets):
        raise PackIntegrityError("manifest.structure", manifest_key)
    return manifest


def _verify_lesson_object(
    data: bytes,
    key: str,
    entry: Mapping[str, Any],
    locale: str,
    assets: Mapping[str, Mapping[str, Any]],
) -> None:
    if not is_canonical_json(data):
        raise PackIntegrityError("lesson.not_canonical", key)
    lesson = json.loads(data)
    expected_keys = {
        "blob_version",
        "content_format",
        "lesson_id",
        "revision_id",
        "revision",
        "locale",
        "title",
        "blocks",
        "questions",
    }
    if not isinstance(lesson, dict) or set(lesson) != expected_keys:
        raise PackIntegrityError("lesson.structure", key)
    same = ("content_format", "lesson_id", "revision_id", "revision", "title")
    if (
        lesson["blob_version"] != LESSON_BLOB_VERSION
        or lesson["locale"] != locale
        or any(lesson[name] != entry[name] for name in same)
        or not isinstance(lesson["questions"], list)
        or lesson["content_format"] not in SUPPORTED_FORMATS
    ):
        raise PackIntegrityError("lesson.mismatch", key)
    if validate_blocks(lesson["blocks"], lesson["content_format"]):
        raise PackIntegrityError("lesson.blocks", key)
    # The negotiation rule on the object itself: a lesson declares exactly the
    # smallest format that carries its blocks AND its question kinds. A lesson
    # that says "format 1" therefore holds only the four format-1 block types
    # and only 'mcq' questions - whatever the manifest says.
    kinds: list[str] = []
    for question in lesson["questions"]:
        kind = question.get("kind") if isinstance(question, dict) else None
        if not isinstance(kind, str) or kind not in V2_QUESTION_KINDS:
            raise PackIntegrityError("lesson.questions", key)
        kinds.append(kind)
    if required_format(lesson["blocks"], kinds) != lesson["content_format"]:
        raise PackIntegrityError("lesson.content_format", key)
    listed = [
        {name: q.get(name) for name in ("id", "question_key", "position", "kind")}
        if isinstance(q, dict)
        else None
        for q in lesson["questions"]
    ]
    if listed != entry["questions"]:
        raise PackIntegrityError("lesson.mismatch", key)
    for question in lesson["questions"]:
        # (ids and positions were compared with the manifest entry just above,
        # where they are required to be unique)
        columns = {
            name: question.get(name)
            for name in ("prompt", "response_spec", "answer_key", "explanation")
        }
        if len(question) != 8 or validate_question(question["kind"], columns):
            raise PackIntegrityError("lesson.questions", key)
    references = asset_references(lesson["blocks"])
    if sorted(references) != entry["assets"]:
        raise PackIntegrityError("lesson.mismatch", key)
    for sha256, reference in references.items():
        asset = assets.get(sha256)
        if asset is None or any(asset[n] != reference[n] for n in ("bytes", "mime", "kind")):
            raise PackIntegrityError("lesson.mismatch", key)


def pack_input_from_json(document: Mapping[str, Any]) -> PackInput:
    """Build a :class:`PackInput` from the JSON shape used by vectors/pack-manifest.json.

    A description of the wrong shape is a :class:`PackBuildError` (``pack.input``).
    """
    try:
        return _pack_input_from_json(document)
    except (KeyError, TypeError, AttributeError) as error:
        raise PackBuildError(
            "pack.input", f"malformed pack description ({type(error).__name__})"
        ) from None


def _pack_input_from_json(document: Mapping[str, Any]) -> PackInput:
    pack = document["pack"]
    lessons = tuple(
        PackLesson(
            position=lesson["position"],
            lesson_id=lesson["lesson_id"],
            revision_id=lesson["revision_id"],
            revision=lesson["revision"],
            title=lesson["title"],
            blocks=lesson["blocks"],
            questions=tuple(PackQuestion(**question) for question in lesson["questions"]),
        )
        for lesson in document["lessons"]
    )
    return PackInput(
        release_id=pack["release_id"],
        pack_key=pack["pack_key"],
        locale=pack["locale"],
        revision=pack["revision"],
        content_format=document["content_format"],
        lessons=lessons,
    )


def size_report(built: BuiltPack) -> Sequence[str]:
    """Human-readable size lines, one per lesson, then totals."""
    lines = [
        f"{'pos':>3}  {'lesson':>8}  {'images':>8}  {'audio (optional)':>16}  title",
    ]
    for size in built.sizes:
        lines.append(
            f"{size.position:>3}  {size.lesson_bytes:>8}  {size.required_asset_bytes:>8}  "
            f"{size.optional_asset_bytes:>16}  {size.title}"
        )
    totals = built.manifest["totals"]
    required = len(built.manifest_bytes) + totals["lesson_bytes"] + totals["required_asset_bytes"]
    lines.append(f"manifest: {len(built.manifest_bytes)} bytes, sha256 {built.manifest_sha256}")
    lines.append(
        f"required download: {required} bytes; optional audio: {totals['optional_asset_bytes']} "
        f"bytes; everything: {built.total_bytes} bytes (uncompressed, shared assets counted once)"
    )
    return lines
