"""The FastAPI router: correct on a throwaway app, and absent from the real one."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from edu_api.auth.verifier import Principal
from edu_api.config import Settings
from edu_api.deps import get_principal
from edu_api.errors import install_error_handlers
from edu_api.main import create_app
from edu_api.tutor import demo_content
from edu_api.tutor.errors import ALL_ERRORS
from edu_api.tutor.router import build_tutor_router, to_api_error

from .conftest import LEARNER_A, Harness, build_harness

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "packages" / "contracts" / "tutor"


def contract(name: str) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    return schema


def body(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "idempotency_key": str(uuid.uuid4()),
        "lesson_id": str(demo_content.EQUATIONS_LESSON_ID),
        "locale": "fr",
        "intent": "ask_question",
        "message": "Pourquoi on soustrait 5 des deux côtés ?",
    }
    values.update(overrides)
    return values


def app_with(harness: Harness, *, signed_in: bool = True) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(build_tutor_router(lambda: harness.service))
    if signed_in:
        app.dependency_overrides[get_principal] = lambda: Principal(user_id=LEARNER_A)
    return app


@pytest.fixture
async def api() -> AsyncIterator[tuple[httpx.AsyncClient, Harness]]:
    harness = build_harness()
    transport = httpx.ASGITransport(app=app_with(harness))
    async with httpx.AsyncClient(transport=transport, base_url="http://tutor.test") as client:
        yield client, harness


async def test_post_request_returns_a_cited_answer_matching_the_published_contract(
    api: tuple[httpx.AsyncClient, Harness],
) -> None:
    client, _ = api
    request_body = body(response_locale="ht")
    jsonschema.validate(request_body, contract("tutor-request.schema.json"))
    response = await client.post("/v1/jude/requests", json=request_body)
    assert response.status_code == 200
    payload = response.json()
    jsonschema.validate(payload, contract("tutor-response.schema.json"))
    assert payload["status"] == "answered" and payload["language"] == "ht"
    assert payload["request_id"] == request_body["idempotency_key"]
    assert payload["references"][0]["lesson_revision_id"] == str(
        demo_content.EQUATIONS_FR_REVISION_ID
    )


async def test_tutor_errors_use_the_api_error_shape_with_stable_codes(
    api: tuple[httpx.AsyncClient, Harness],
) -> None:
    client, harness = api
    await harness.usage.set_paused(True, actor="test")
    response = await client.post("/v1/jude/requests", json=body())
    assert response.status_code == 503
    assert response.headers["retry-after"] == "300"
    assert response.json() == {
        "error": {
            "code": "tutor_paused",
            "message": "Jude is paused. Lessons and practice still work.",
        }
    }


async def test_unknown_lesson_is_404_and_duplicate_is_409(
    api: tuple[httpx.AsyncClient, Harness],
) -> None:
    client, _ = api
    missing = await client.post("/v1/jude/requests", json=body(lesson_id=str(uuid.uuid4())))
    assert (missing.status_code, missing.json()["error"]["code"]) == (
        404,
        "tutor_lesson_unavailable",
    )
    request_body = body()
    assert (await client.post("/v1/jude/requests", json=request_body)).status_code == 200
    again = await client.post("/v1/jude/requests", json=request_body)
    assert (again.status_code, again.json()["error"]["code"]) == (409, "tutor_duplicate_request")


async def test_validation_errors_do_not_echo_the_students_text(
    api: tuple[httpx.AsyncClient, Harness],
) -> None:
    client, _ = api
    secret = "mon secret " + "x" * 700
    response = await client.post("/v1/jude/requests", json=body(message=secret))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "mon secret" not in response.text


async def test_a_body_naming_another_learner_is_rejected(
    api: tuple[httpx.AsyncClient, Harness],
) -> None:
    client, harness = api
    response = await client.post("/v1/jude/requests", json=body(learner_id=str(uuid.uuid4())))
    assert response.status_code == 422
    assert harness.provider.calls == []


async def test_status_probe_reports_availability_and_own_usage(
    api: tuple[httpx.AsyncClient, Harness],
) -> None:
    client, harness = api
    response = await client.get("/v1/jude/status")
    payload = response.json()
    jsonschema.validate(payload, contract("tutor-availability.schema.json"))
    assert payload == {
        "available": True,
        "reason": None,
        "daily_requests_used": 0,
        "daily_requests_limit": harness.settings.learner_daily_requests,
    }
    await harness.usage.set_paused(True, actor="test")
    paused = (await client.get("/v1/jude/status")).json()
    assert (paused["available"], paused["reason"]) == (False, "tutor_paused")


async def test_every_route_requires_a_signed_in_learner() -> None:
    harness = build_harness()
    transport = httpx.ASGITransport(app=app_with(harness, signed_in=False))
    async with httpx.AsyncClient(transport=transport, base_url="http://tutor.test") as client:
        for response in (
            await client.post("/v1/jude/requests", json=body()),
            await client.get("/v1/jude/status"),
        ):
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "unauthenticated"
    assert harness.provider.calls == []


def test_every_tutor_error_maps_to_a_distinct_code_and_a_sane_status() -> None:
    codes = [error.code for error in ALL_ERRORS]
    assert len(codes) == len(set(codes))
    for error in ALL_ERRORS:
        api_error = to_api_error(error())
        assert api_error.code.startswith("tutor_")
        assert api_error.status_code in {403, 404, 409, 422, 429, 502, 503, 504}
        assert api_error.message == error.message


# --- the tutor is NOT part of the live application ----------------------------------------------
def test_the_production_app_exposes_no_jude_route() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr("postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"),
        auth_issuer="http://127.0.0.1:1/auth/v1",
        auth_jwks_url="http://127.0.0.1:1/auth/v1/.well-known/jwks.json",
    )
    app = create_app(settings, key_provider=object())  # type: ignore[arg-type]
    paths = {getattr(route, "path", "") for route in app.routes}
    assert not any("jude" in path or "tutor" in path for path in paths), paths


def test_shared_application_files_do_not_import_the_tutor() -> None:
    package = ROOT / "services" / "api" / "src" / "edu_api"
    for name in ("main.py", "config.py", "deps.py", "errors.py"):
        assert "tutor" not in (package / name).read_text(encoding="utf-8"), name
    openapi = (ROOT / "packages" / "contracts" / "openapi.json").read_text(encoding="utf-8")
    assert "/v1/jude" not in openapi
