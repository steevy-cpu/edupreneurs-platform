from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from content_pilot.model import find_repo_root

REPO = find_repo_root(Path(__file__).resolve())
PILOT = REPO / "content" / "pilots" / "7af-math"
L1 = "lessons/01-lire-ecrire-comparer-entiers"
L2 = "lessons/02-additionner-soustraire"
L5 = "lessons/05-multiples-diviseurs"


@pytest.fixture()
def pilot_copy(tmp_path: Path) -> Path:
    """A private, writable copy of the real pilot, to be damaged on purpose."""
    dst = tmp_path / "7af-math"
    shutil.copytree(PILOT, dst)
    return dst


def edit_json(root: Path, rel: str, fn: Callable[[Any], Any]) -> None:
    """Mutate the parsed JSON IN PLACE (the return value of `fn` is ignored)."""
    p = root / rel
    data = json.loads(p.read_text(encoding="utf-8"))
    fn(data)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def replace_json(root: Path, rel: str, fn: Callable[[Any], Any]) -> None:
    """Replace the whole parsed JSON by the value `fn` returns."""
    p = root / rel
    p.write_text(json.dumps(fn(json.loads(p.read_text(encoding="utf-8"))), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
