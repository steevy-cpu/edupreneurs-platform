"""Validation findings and the small structural checks shared by the validators.

Two layers, always in this order:

* ``schema``   - the shape described by the JSON Schema files in
  ``packages/contracts/content``. Re-implemented here in plain Python because
  ``jsonschema`` is a development-only dependency and must not be needed at
  run time; a unit test proves both implementations agree on every vector.
* ``semantic`` - rules JSON Schema cannot express. Only evaluated when the
  structural layer found nothing, so each rule can assume a well-shaped input.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Literal

Layer = Literal["schema", "semantic"]

_CONTROL = re.compile(r"[\u0000-\u001f\u007f]")
_MARKUP = re.compile(r"<[A-Za-z/!?]")


@dataclass(frozen=True)
class Issue:
    """One finding. ``path`` is a JSON Pointer into the validated document."""

    path: str
    layer: Layer
    rule: str
    message: str


class Collector:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def schema(self, path: str, message: str) -> None:
        self.issues.append(Issue(path, "schema", "structure", message))

    def semantic(self, path: str, rule: str, message: str) -> None:
        self.issues.append(Issue(path, "semantic", rule, message))

    # --- structural helpers: each returns True when the value is usable -----------
    def obj(
        self, value: Any, path: str, required: Collection[str], optional: Collection[str] = ()
    ) -> bool:
        if not isinstance(value, dict):
            self.schema(path, "must be an object")
            return False
        ok = True
        for name in value:
            if name not in required and name not in optional:
                self.schema(f"{path}/{name}" if isinstance(name, str) else path, "unknown property")
                ok = False
        for name in required:
            if name not in value:
                self.schema(path, f"missing property '{name}'")
                ok = False
        return ok

    def string(
        self,
        value: Any,
        path: str,
        *,
        min_len: int = 1,
        max_len: int,
        pattern: re.Pattern[str] | None = None,
        plain: bool = False,
        no_control: bool = False,
    ) -> bool:
        """``plain`` = single-line human text: no control characters, no tag opener."""
        if not isinstance(value, str):
            self.schema(path, "must be a string")
            return False
        if not min_len <= len(value) <= max_len:
            self.schema(path, f"length must be between {min_len} and {max_len} code points")
            return False
        if (plain or no_control) and _CONTROL.search(value):
            self.schema(path, "control characters are not allowed")
            return False
        if plain and _MARKUP.search(value):
            self.schema(path, "markup is not allowed")
            return False
        if pattern is not None and not pattern.fullmatch(value):
            self.schema(path, "does not match the required pattern")
            return False
        return True

    def integer(self, value: Any, path: str, minimum: int, maximum: int) -> bool:
        if isinstance(value, bool) or not isinstance(value, int):
            self.schema(path, "must be an integer")
            return False
        if not minimum <= value <= maximum:
            self.schema(path, f"must be between {minimum} and {maximum}")
            return False
        return True

    def boolean(self, value: Any, path: str) -> bool:
        if not isinstance(value, bool):
            self.schema(path, "must be true or false")
            return False
        return True

    def const(self, value: Any, path: str, expected: str) -> bool:
        if not isinstance(value, str) or value != expected:
            self.schema(path, f"must be '{expected}'")
            return False
        return True

    def enum(self, value: Any, path: str, allowed: Collection[str]) -> bool:
        if not isinstance(value, str) or value not in allowed:
            self.schema(path, "is not one of the allowed values")
            return False
        return True

    def array(self, value: Any, path: str, min_items: int, max_items: int) -> bool:
        if not isinstance(value, list):
            self.schema(path, "must be an array")
            return False
        if not min_items <= len(value) <= max_items:
            self.schema(path, f"must have between {min_items} and {max_items} items")
            return False
        return True
