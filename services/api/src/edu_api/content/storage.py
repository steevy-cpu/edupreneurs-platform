"""Where pack objects are written. One adapter exists: a LOCAL DIRECTORY.

There is deliberately no cloud adapter here (no R2, no S3, no network). The
:class:`PackStorage` protocol is the seam a real object store will implement
later; the pack builder and the verifier only ever talk to the protocol.

Objects are immutable. A key is either content-addressed (``assets/sha256/..``,
``lessons/sha256/..``) or names the manifest of one immutable release, so
writing different bytes to an existing key is always a bug or tampering and is
refused. Writing the same bytes again is a harmless no-op, which makes a build
safe to re-run after an interruption.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

MAX_KEY_LENGTH = 300
_KEY = re.compile(r"[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*")


class StorageError(Exception):
    """An object could not be stored or read. The message never contains object bytes."""


def check_key(key: str) -> str:
    """Reject anything that is not a plain relative object key (no '..', no absolute path)."""
    if len(key) > MAX_KEY_LENGTH or not _KEY.fullmatch(key):
        raise StorageError("invalid object key")
    return key


class PackStorage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


class LocalDirectoryStorage:
    """Objects as files under one directory on this machine."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / check_key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError("invalid object key")
        return path

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise StorageError(f"object not found: {key}")
        return path.read_bytes()

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        if path.exists():
            if path.is_file() and path.read_bytes() == data:
                return
            raise StorageError(f"object already exists with different content: {key}")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary file in the same directory, then rename: a reader
        # never sees a half-written object, even if the build is interrupted.
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".partial-")
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
