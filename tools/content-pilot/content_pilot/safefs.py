"""The only way the tool touches the filesystem and parses JSON.

THREAT MODEL (what is and is not claimed)

* The OPERATOR names two kinds of directory: the pilot root (`--root`) and, optionally, an output directory.
  Both are TRUSTED inputs: their own ancestors are resolved once by the operator's choice. Run the tool on a checked-out
  tree you control, writing to a private directory. It is not designed to run on a tree another user can modify
  while it runs, and nothing here defends against a hostile process with write access to those directories.
* Everything BELOW the pilot root (descriptor file names, lesson files, extra files) is UNTRUSTED data. It is read
  by directory handle: each component is opened relative to the previous handle with no-follow, so a symbolic link
  planted at any level below the root is refused and no name is ever re-resolved after it was checked. Directory
  enumeration is streamed and bounded (entries, depth, bytes) and counts directories, links and other entries too.
* Output directories fail CLOSED: if any ancestor of an explicit output directory is a symbolic link (for example
  `/tmp` on macOS), the tool refuses and asks for the real path. Files are written through a temporary file created
  and renamed by directory handle, so an existing link is replaced, never followed.
* Tested: links at the file, directory, descriptor and output levels; linked ancestors of output directories;
  handle-relative opens; bounded enumeration. NOT tested and NOT claimed: behaviour under a concurrent attacker
  racing the tool, hard links, bind mounts, or file systems without `O_NOFOLLOW`/`dir_fd` support.
* Bytes are bounded before parsing and JSON is parsed strictly (UTF-8 only, no duplicate members, no NaN/Infinity).
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import re
import stat
from dataclasses import dataclass
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


_DIR = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_FILE = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
_LINK_ERRORS = (errno.ELOOP, errno.ENOTDIR, errno.EMLINK)


def _open(name: str | Path, flags: int, what: str, dir_fd: int | None = None, mode: int = 0o777) -> int:
    """`os.open` that never follows a link in the last component; a link or a non-directory becomes `file_unsafe`."""
    try:
        return os.open(name, flags, mode, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno in _LINK_ERRORS:
            raise ContentFileError("file_unsafe", f"{what}: a symbolic link or a non-directory where a plain entry is required") from exc
        raise


def open_trusted_root(path: Path | str) -> int:
    """A handle on the directory the OPERATOR named (`--root`, a repository root). Its own ancestors are the operator's
    responsibility and are resolved once, here; everything BELOW it is walked by handle with no link ever followed."""
    return _open(os.path.realpath(path), _DIR, str(path))


def open_dir_strict(path: Path | str) -> int:
    """A handle on `path` obtained one component at a time from `/` with NO link followed anywhere, including ancestors.
    It fails closed on a path that crosses a symbolic link (for example `/tmp` on macOS): give the real path."""
    absolute = os.path.abspath(path)
    fd = _open("/", _DIR, "/")
    try:
        for part in PurePosixPath(absolute).parts[1:]:
            nxt = _open(part, _DIR, absolute, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _walk(root_fd: int, parts: tuple[str, ...], what: str) -> int:
    fd = os.dup(root_fd)
    try:
        for part in parts:
            nxt = _open(part, _DIR, what, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_fd(fd: int, name: str, max_bytes: int) -> bytes:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise ContentFileError("file_unsafe", f"{name}: not a regular file")
    if st.st_size > max_bytes:
        raise ContentFileError("file_too_large", f"{name}: {st.st_size} bytes exceeds the {max_bytes}-byte limit")
    data = os.read(fd, max_bytes + 1)
    while len(data) <= max_bytes:
        more = os.read(fd, max_bytes + 1 - len(data))
        if not more:
            break
        data += more
    if len(data) > max_bytes:
        raise ContentFileError("file_too_large", f"{name}: more than {max_bytes} bytes")
    return data


def read_regular(path: Path, max_bytes: int) -> bytes:
    """Read ONE file of the TOOL itself (its own schemas). Not for untrusted trees: use `read_confined`."""
    fd = _open(path, _FILE, Path(path).name)
    try:
        return _read_fd(fd, Path(path).name, max_bytes)
    finally:
        os.close(fd)


def read_confined(root: Path, rel: object, max_bytes: int) -> bytes:
    """Read `rel` below the trusted `root`: every directory component is opened relative to the previous handle with
    no-follow, so a link planted at ANY level below the root is refused and no path is ever re-resolved by name."""
    parts = check_relative(rel).parts
    root_fd = open_trusted_root(root)
    try:
        dir_fd = _walk(root_fd, parts[:-1], str(rel))
        try:
            fd = _open(parts[-1], _FILE, str(rel), dir_fd=dir_fd)
            try:
                return _read_fd(fd, str(rel), max_bytes)
            finally:
                os.close(fd)
        finally:
            os.close(dir_fd)
    finally:
        os.close(root_fd)


def read_in_dir(directory: Path | str, name: str, max_bytes: int) -> bytes:
    """Read `directory/name` where the directory path is checked strictly (no link in any ancestor)."""
    if not _NAME.match(name):
        raise ContentFileError("file_reference", f"name {name!r:.80} is not a simple file name")
    dir_fd = open_dir_strict(directory)
    try:
        fd = _open(name, _FILE, name, dir_fd=dir_fd)
        try:
            return _read_fd(fd, name, max_bytes)
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)


@dataclass(frozen=True)
class TreeEntry:
    rel: str
    kind: str  # "file" | "dir" | "link" | "other"
    size: int = 0


def scan_tree(root: Path, *, max_entries: int, max_depth: int, max_bytes: int) -> tuple[list[TreeEntry], str | None]:
    """Enumerate `root` by directory handle, never following a link, never holding more than `max_entries` entries in
    memory, stopping as soon as a budget is exceeded. Returns (entries seen so far, reason the scan stopped or None)."""
    seen: list[TreeEntry] = []
    total = 0
    root_fd = open_trusted_root(root)
    stack: list[tuple[int, str, int]] = [(root_fd, "", 0)]
    try:
        while stack:
            fd, prefix, depth = stack.pop()
            try:
                with os.scandir(fd) as it:
                    for entry in it:  # streamed: a huge directory is cut off, not loaded and sorted
                        if len(seen) >= max_entries:
                            return seen, f"more than {max_entries} entries"
                        st = entry.stat(follow_symlinks=False)
                        rel = f"{prefix}{entry.name}"
                        if stat.S_ISLNK(st.st_mode):
                            seen.append(TreeEntry(rel, "link"))
                        elif stat.S_ISDIR(st.st_mode):
                            seen.append(TreeEntry(rel, "dir"))
                            if depth >= max_depth:
                                return seen, f"directories nested deeper than {max_depth} levels"
                            stack.append((_open(entry.name, _DIR, rel, dir_fd=fd), f"{rel}/", depth + 1))
                        elif stat.S_ISREG(st.st_mode):
                            total += st.st_size
                            seen.append(TreeEntry(rel, "file", st.st_size))
                            if total > max_bytes:
                                return seen, f"more than {max_bytes} bytes"
                        else:
                            seen.append(TreeEntry(rel, "other"))
            finally:
                if fd != root_fd:
                    os.close(fd)
        return seen, None
    finally:
        for fd, _, _ in stack:
            if fd != root_fd:
                os.close(fd)
        os.close(root_fd)


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
    """Create `base/rel` one component at a time by handle, refusing links; returns the real path of the directory."""
    parts = check_relative(rel).parts
    cur = open_trusted_root(base)
    try:
        for part in parts:
            with contextlib.suppress(FileExistsError):
                os.mkdir(part, 0o777, dir_fd=cur)
            nxt = _open(part, _DIR, rel, dir_fd=cur)
            os.close(cur)
            cur = nxt
    finally:
        os.close(cur)
    return Path(os.path.realpath(base)).joinpath(*parts)


def _open_output_dir(directory: Path | str) -> int:
    """The output directory: its PARENT is checked strictly (no link in any ancestor); the final directory is created
    when missing and is never a link."""
    directory = Path(os.path.abspath(directory))
    parent_fd = open_dir_strict(directory.parent)
    try:
        with contextlib.suppress(FileExistsError):
            os.mkdir(directory.name, 0o777, dir_fd=parent_fd)
        return _open(directory.name, _DIR, str(directory), dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def write_text_atomic(directory: Path, name: str, text: str) -> Path:
    """Write `directory/name` through a temporary file created and renamed by directory handle, so an existing link is
    replaced, never followed. Fails closed when any ancestor of the directory is a link."""
    if not _NAME.match(name):
        raise ContentFileError("file_reference", f"output name {name!r:.80} is not a simple file name")
    dir_fd = _open_output_dir(directory)
    tmp = f".tmp-{os.getpid()}-{name}.part"
    try:
        try:
            st = os.lstat(name, dir_fd=dir_fd)
            if not stat.S_ISREG(st.st_mode):
                raise ContentFileError("file_unsafe", f"{name}: output target is a link or not a regular file")
        except FileNotFoundError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o644, dir_fd=dir_fd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            os.rename(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp, dir_fd=dir_fd)
            raise
    finally:
        os.close(dir_fd)
    return Path(os.path.abspath(directory)) / name
