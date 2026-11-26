from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Fixed namespace so lesson and unit ids are stable and reproducible (uuid5), never random.
PILOT_NAMESPACE = uuid.UUID("7a0f0c3e-02a0-4c1b-9d3e-7af000000001")
PILOT_ID = "7af-math-pilot"
LOCALES = ("fr", "ht")

MIN_QUESTIONS = 5
SIZE_WARN_BYTES = 8 * 1024  # per lesson and locale (blocks + questions, minified UTF-8)
SIZE_ERROR_BYTES = 16 * 1024

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


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def minified(obj: Any) -> bytes:
    """Delivery-shaped bytes: compact JSON, UTF-8, no ASCII escaping."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def find_repo_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "packages" / "contracts" / "content" / "lesson-blocks.schema.json").exists():
            return p
    raise FileNotFoundError("repository root (packages/contracts/content) not found")
