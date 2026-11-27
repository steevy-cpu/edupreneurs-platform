"""Every test in this folder talks to the local stack and starts from clean learner state."""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from edu_api.main import create_app
from tests.conftest import LEARNING_TABLES, build_settings


@pytest.fixture(autouse=True)
async def clean_learning_state(admin: asyncpg.Pool) -> None:
    """No attempts / progress / receipts / change feed left over from another test."""
    await admin.execute(f"TRUNCATE {LEARNING_TABLES}")


# --- ExamHub-01: the feature is off by default, so its tests use an app with the flag on ---
@pytest.fixture(scope="session")
async def exam_app(local_env: dict[str, str]) -> AsyncIterator[FastAPI]:
    application = create_app(build_settings(local_env, exams_enabled=True))
    yield application
    await application.state.db.dispose()


@pytest.fixture
async def exam_client(exam_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=exam_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http
