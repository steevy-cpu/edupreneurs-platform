"""The only way the tool touches the filesystem and parses JSON.

Everything the pilot descriptor names is untrusted: it may be an absolute path, contain `..`, or point at a symbolic
link. These helpers confine every read and write to a root directory, refuse symbolic links and non-regular files,
bound the bytes read BEFORE parsing, and parse JSON strictly (UTF-8 only, no duplicate members, no NaN/Infinity).
"""

from __future__ import annotations

import errno
import json
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


class ContentFileError(Exception):
    """A file problem with a stable code, convertible into a `Finding` by callers."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def check_relative(rel: object) -> PurePosixPath:
    """A plain, relative, POSIX path made of simple segments. No absolute paths, no `..`, no backslashes."""
    if not isinstance(rel, str) or not rel or len(rel) > 240:
        raise ContentFileError("file_reference", f"file reference must be a non-empty string of at most 240 characters, got {rel!r:.80}")
    if "\x00" in rel or "\\" in rel or rel.startswith("/") or "//" in rel or rel.endswith("/"):
        raise ContentFileError("file_reference", f"file reference {rel!r:.80} must be a relative POSIX path")
    path = PurePosixPath(rel)
    if str(path) != rel:  # "./a", "a/./b": the name must already be in its canonical form
        raise ContentFileError("file_reference", f"file reference {rel!r:.80} must be in canonical form")
    for part in path.parts:
        if part in (".", "..") or not _SEGMENT.match(part):
            raise ContentFileError("file_reference", f"file reference {rel!r:.80} has a forbidden segment {part!r:.40}")
    return path


def resolve_inside(root: Path, rel: object) -> Path:
    """`root/rel`, after checking that no component below `root` is a symbolic link. Missing -> FileNotFoundError."""
    parts = check_relative(rel).parts
    cur = Path(os.path.realpath(root))
    for part in parts:
        cur = cur / part
        if stat.S_ISLNK(os.lstat(cur).st_mode):
            raise ContentFileError("file_unsafe", f"{rel}: symbolic links are not followed")
    return cur


def read_regular(path: Path, max_bytes: int) -> bytes:
    """Read a regular file without following a final symbolic link, never more than `max_bytes`."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ContentFileError("file_unsafe", f"{path.name}: symbolic links are not followed") from exc
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ContentFileError("file_unsafe", f"{path.name}: not a regular file")
        if st.st_size > max_bytes:
            raise ContentFileError("file_too_large", f"{path.name}: {st.st_size} bytes exceeds the {max_bytes}-byte limit")
        data = os.read(fd, max_bytes + 1)
        while len(data) <= max_bytes:
            more = os.read(fd, max_bytes + 1 - len(data))
            if not more:
                break
            data += more
        if len(data) > max_bytes:
            raise ContentFileError("file_too_large", f"{path.name}: more than {max_bytes} bytes")
        return data
    finally:
        os.close(fd)


def read_confined(root: Path, rel: object, max_bytes: int) -> bytes:
    return read_regular(resolve_inside(root, rel), max_bytes)


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ContentFileError("json_duplicate_member", f"object member {key!r} appears more than once")
        out[key] = value
    return out


def _bad_constant(name: str) -> Any:
    raise ContentFileError("json_invalid", f"{name} is not valid JSON")


def _depth(doc: Any) -> int:
    deepest, stack = 0, [(doc, 1)]
    while stack:
        node, d = stack.pop()
        if isinstance(node, (dict, list)):
            deepest = max(deepest, d)
            stack.extend((c, d + 1) for c in (node.values() if isinstance(node, dict) else node))
    return deepest


def loads_strict(data: bytes, *, max_depth: int = 40) -> Any:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContentFileError("json_invalid", f"not valid UTF-8 ({exc.reason} at byte {exc.start})") from exc
    if text.startswith("﻿"):
        raise ContentFileError("json_invalid", "a byte order mark is not allowed")
    try:
        doc = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_bad_constant)
    except json.JSONDecodeError as exc:
        raise ContentFileError("json_invalid", str(exc)) from exc
    except RecursionError as exc:
        raise ContentFileError("json_invalid", "JSON is nested too deeply") from exc
    except ValueError as exc:
        raise ContentFileError("json_invalid", str(exc)) from exc
    if _depth(doc) > max_depth:
        raise ContentFileError("json_invalid", f"JSON is nested deeper than {max_depth} levels")
    return doc


def load_json_confined(root: Path, rel: object, max_bytes: int, *, max_depth: int = 40) -> Any:
    return loads_strict(read_confined(root, rel, max_bytes), max_depth=max_depth)


def load_json_file(path: Path, max_bytes: int, *, max_depth: int = 40) -> Any:
    return loads_strict(read_regular(Path(path), max_bytes), max_depth=max_depth)


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def ensure_dir_inside(base: Path, rel: str) -> Path:
    """Create `base/rel` one component at a time, refusing symbolic links on the way."""
    cur = Path(os.path.realpath(base))
    for part in check_relative(rel).parts:
        cur = cur / part
        if cur.is_symlink():
            raise ContentFileError("file_unsafe", f"{rel}: symbolic link in the output path")
        if cur.exists() and not cur.is_dir():
            raise ContentFileError("file_unsafe", f"{rel}: not a directory")
        cur.mkdir(exist_ok=True)
    return cur


def write_text_atomic(directory: Path, name: str, text: str) -> Path:
    """Write `directory/name` through a temporary file and `os.replace`, so an existing link is replaced, never followed."""
    if not _NAME.match(name):
        raise ContentFileError("file_reference", f"output name {name!r:.80} is not a simple file name")
    directory = Path(directory)
    if directory.is_symlink():
        raise ContentFileError("file_unsafe", "the output directory is a symbolic link")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ContentFileError("file_unsafe", f"{name}: output target is a link or not a regular file")
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target
