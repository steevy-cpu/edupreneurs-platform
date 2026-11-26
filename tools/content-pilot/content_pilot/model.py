from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .safe_eval import EvalLimits
from .safefs import load_json_file

# Fixed namespace so lesson and unit ids are stable and reproducible (uuid5), never random.
PILOT_NAMESPACE = uuid.UUID("7a0f0c3e-02a0-4c1b-9d3e-7af000000001")
PILOT_ID = "7af-math-pilot"
LOCALES = ("fr", "ht")

MIN_QUESTIONS = 5
SIZE_WARN_BYTES = 8 * 1024  # per lesson and locale (blocks + questions, minified UTF-8)
SIZE_ERROR_BYTES = 16 * 1024

TOOL_DIR = Path(__file__).resolve().parent.parent

REVIEW_STATUSES = ("draft_unreviewed", "in_review", "changes_requested", "approved", "rejected")
REQUIRED_APPROVALS = ("mathematics_teacher", "native_speaker")


def stable_id(kind: str, slug: str) -> str:
    return str(uuid.uuid5(PILOT_NAMESPACE, f"{PILOT_ID}/{kind}/{slug}"))


@dataclass(frozen=True)
class Finding:
    code: str
    where: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        return f"[{self.severity}] {self.code} @ {self.where}: {self.message}"


@dataclass(frozen=True)
class Limits:
    """Resource limits applied before and while reading untrusted pilot content. Tests inject small ones."""

    max_file_bytes: int = 256 * 1024  # blocks, questions, verification
    max_descriptor_bytes: int = 512 * 1024  # pilot.json and the preview manifest
    max_total_bytes: int = 4 * 1024 * 1024
    max_files: int = 80
    max_json_depth: int = 40
    eval: EvalLimits = field(default_factory=EvalLimits)


DEFAULT_LIMITS = Limits()


def read_json(path: Path, max_bytes: int = DEFAULT_LIMITS.max_descriptor_bytes) -> Any:
    """Strict JSON read of one regular file (no symbolic link, bounded size, no duplicate members)."""
    return load_json_file(Path(path), max_bytes)


def lesson_dir(lesson: dict[str, Any]) -> str:
    return f"lessons/{lesson['position']:02d}-{lesson['slug']}"


def expected_files(lesson: dict[str, Any]) -> dict[str, Any]:
    """The ONE set of file names a lesson may use. The descriptor must match it exactly."""
    d = lesson_dir(lesson)
    return {
        "blocks": {loc: f"{d}/blocks.{loc}.json" for loc in LOCALES},
        "questions": {loc: f"{d}/questions.{loc}.json" for loc in LOCALES},
        "verification": f"{d}/verification.json",
    }


def minified(obj: Any) -> bytes:
    """Delivery-shaped bytes: compact JSON, UTF-8, no ASCII escaping."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def find_repo_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "packages" / "contracts" / "content" / "lesson-blocks.schema.json").exists():
            return p
    raise FileNotFoundError("repository root (packages/contracts/content) not found")
