"""Test spies. Nothing here is importable from the application package.

``RecordingMockProvider`` keeps every request it is given so a test can look at
exactly what would have been sent to a model. The provider the factory builds
by default (``DeterministicMockProvider``) keeps nothing; a test that needs
inspection has to inject this spy explicitly.
"""

from __future__ import annotations

from typing import Any

from edu_api.tutor.providers.base import ModelRequest, ModelResult
from edu_api.tutor.providers.mock import DeterministicMockProvider


class RecordingMockProvider(DeterministicMockProvider):
    """The deterministic mock, plus a list of every request. TESTS ONLY."""

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.recorded: list[ModelRequest] = []

    @property
    def calls(self) -> list[ModelRequest]:  # type: ignore[override]
        return self.recorded

    async def complete(self, request: ModelRequest) -> ModelResult:
        self.recorded.append(request)
        return await super().complete(request)
