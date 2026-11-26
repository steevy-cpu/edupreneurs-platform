"""Tests of the Jude-02A evaluation harness. Offline: any network connection fails the test."""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Any

import pytest

BENCH = Path(__file__).resolve().parents[3] / "benchmarks" / "jude-02a"
sys.path.insert(0, str(BENCH))


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(self: socket.socket, address: Any, *args: Any, **kwargs: Any) -> None:
        raise AssertionError(f"an evaluation test tried to open a connection to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
