"""Every test in this folder talks to the local stack and starts from clean learner state."""

from __future__ import annotations

import asyncpg
import pytest

from tests.conftest import LEARNING_TABLES


@pytest.fixture(autouse=True)
async def clean_learning_state(admin: asyncpg.Pool) -> None:
    """No attempts / progress / receipts / change feed left over from another test."""
    await admin.execute(f"TRUNCATE {LEARNING_TABLES}")
