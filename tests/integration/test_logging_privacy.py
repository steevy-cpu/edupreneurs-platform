"""Opt-in JSON logs: what a request line contains, and — by planting recognisable
values in tokens, paths, query strings, bodies and exceptions — what never gets in."""

from __future__ import annotations

import io
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from edu_api.logging_config import ACCESS_LOGGER, JsonFormatter, actor_tag, redact
from edu_api.main import create_app
from tests.conftest import build_settings
from tests.helpers import (
    SEED_LESSON,
    SEED_QUESTIONS_FR,
    STUDENT_A,
    STUDENT_B,
    answer_op,
    bearer,
    make_token,
    new_ec_key,
)

PLANTED_EMAIL = "planted.learner@example.test"
PLANTED_ANSWER = "PLANTED-ANSWER-7f3a"
PLANTED_NAME = "Marie-Planted Dupont"
ACTOR_KEY = "k" * 40
REQUEST_KEYS = {"ts", "level", "logger", "event", "request_id", "method", "route", "status"}


class Capture:
    def __init__(self, application: FastAPI, buffer: io.StringIO) -> None:
        self.app = application
        self._buffer = buffer

    @property
    def text(self) -> str:
        return self._buffer.getvalue()

    @property
    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.text.splitlines()]

    @property
    def requests(self) -> list[dict[str, Any]]:
        return [line for line in self.lines if line["logger"] == ACCESS_LOGGER]


async def _json_logging_app(
    local_env: dict[str, str], **overrides: Any
) -> AsyncIterator[tuple[httpx.AsyncClient, Capture]]:
    application = create_app(build_settings(local_env, log_format="json", **overrides))
    buffer = io.StringIO()
    application.state.json_log_handler.setStream(buffer)
    transport = httpx.ASGITransport(app=application, client=("203.0.113.77", 4000))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
            yield http, Capture(application, buffer)
    finally:
        application.state.json_logging_undo()
        await application.state.db.dispose()
        if hasattr(application.state, "notify_db"):
            await application.state.notify_db.dispose()


@pytest.fixture
async def logged(local_env: dict[str, str]) -> AsyncIterator[tuple[httpx.AsyncClient, Capture]]:
    async for pair in _json_logging_app(local_env):
        yield pair


@pytest.fixture
async def logged_with_actor(
    local_env: dict[str, str],
) -> AsyncIterator[tuple[httpx.AsyncClient, Capture]]:
    async for pair in _json_logging_app(local_env, log_actor_hash_key=ACTOR_KEY):
        yield pair


async def test_default_settings_leave_logging_exactly_as_it_was(
    app: FastAPI,
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert app.state.settings.log_format == "text"
    assert not hasattr(app.state, "json_log_handler")
    assert "AccessLogMiddleware" not in [m.cls.__name__ for m in app.user_middleware]
    assert not any(isinstance(h.formatter, JsonFormatter) for h in logging.getLogger().handlers)
    assert logging.getLogger("uvicorn.access").disabled is False
    with caplog.at_level(logging.INFO):
        assert (await client.get("/v1/me", headers=bearer(tokens["student_a"]))).status_code == 200
    assert not [r for r in caplog.records if r.name == ACCESS_LOGGER], "no request line by default"


async def test_request_lines_have_the_documented_fields_and_route_templates(
    logged: tuple[httpx.AsyncClient, Capture], tokens: dict[str, str]
) -> None:
    http, capture = logged
    headers = bearer(tokens["student_a"])
    responses = [
        await http.get("/health"),
        await http.get("/v1/me", headers=headers),
        await http.get(f"/v1/lessons/{SEED_LESSON}", params={"locale": "fr"}, headers=headers),
        await http.get("/v1/me"),
        await http.get("/v1/nothing/here"),
        await http.delete("/v1/me", headers=headers),
    ]
    assert [r.status_code for r in responses] == [200, 200, 200, 401, 404, 405]
    lines = capture.requests
    assert len(lines) == len(responses), "exactly one line per request"
    for line, response in zip(lines, responses, strict=True):
        assert set(line) == REQUEST_KEYS | {"duration_ms"}, line
        assert line["event"] == "http_request" and line["level"] == "INFO"
        assert line["request_id"] == response.headers["x-request-id"]
        assert line["status"] == response.status_code
        assert isinstance(line["duration_ms"], float) and 0 <= line["duration_ms"] < 10_000
        assert line["ts"].endswith("+00:00")
    assert [(line["method"], line["route"]) for line in lines] == [
        ("GET", "/health"),
        ("GET", "/v1/me"),
        ("GET", "/v1/lessons/{lesson_id}"),
        ("GET", "/v1/me"),
        ("GET", "unmatched"),
        ("DELETE", "/v1/me"),
    ]
    assert str(SEED_LESSON) not in capture.text, "the template is logged, not the path"


async def test_planted_token_email_answer_and_name_never_reach_the_logs(
    logged: tuple[httpx.AsyncClient, Capture], tokens: dict[str, str], local_env: dict[str, str]
) -> None:
    http, capture = logged
    real_token = tokens["student_a"]
    forged_token = make_token(new_ec_key(), sub=str(STUDENT_B), email=PLANTED_EMAIL)
    question, _ = SEED_QUESTIONS_FR[0]
    planted_op = answer_op(question, PLANTED_ANSWER)

    me = await http.get("/v1/me", headers=bearer(real_token))
    display_name = me.json()["display_name"]
    assert display_name, "the seed learner has a (synthetic) display name"
    pushed = await http.post(
        "/v1/sync/push", headers=bearer(real_token), json={"ops": [planted_op]}
    )
    assert pushed.status_code == 200, "the answer really was received and processed"
    statuses = [
        # a rejected token (the reason is logged by edu_api.auth)
        (await http.get("/v1/me", headers=bearer(forged_token))).status_code,
        # project keys used as tokens
        (
            await http.get("/v1/me", headers=bearer(local_env["LOCAL_SUPABASE_SECRET_KEY"]))
        ).status_code,
        # personal data in the query string, in the path, and in an unknown path
        (
            await http.get(
                "/v1/sync/pull",
                params={"cursor": PLANTED_EMAIL, "email": PLANTED_EMAIL},
                headers=bearer(real_token),
            )
        ).status_code,
        (
            await http.get(
                f"/v1/lessons/{PLANTED_EMAIL}", params={"locale": "fr"}, headers=bearer(real_token)
            )
        ).status_code,
        (await http.get(f"/v1/users/{PLANTED_EMAIL}/{PLANTED_NAME}")).status_code,
        # personal data in a body that fails validation
        (
            await http.post(
                "/v1/sync/push",
                headers=bearer(real_token),
                json={"ops": [], "email": PLANTED_EMAIL, "name": PLANTED_NAME},
            )
        ).status_code,
        # personal data in arbitrary headers
        (
            await http.get(
                "/health", headers={"X-Learner-Email": PLANTED_EMAIL, "Cookie": PLANTED_NAME}
            )
        ).status_code,
    ]
    assert statuses == [401, 401, 410, 422, 404, 422, 200]

    text = capture.text
    assert len(capture.requests) == 9
    assert "access token rejected" in text, "the non-request records are captured too"
    for forbidden in (
        real_token,
        real_token.split(".")[1],
        real_token.split(".")[2],
        forged_token,
        forged_token.split(".")[2],
        local_env["LOCAL_SUPABASE_SECRET_KEY"],
        "Bearer",
        "eyJ",
        PLANTED_EMAIL,
        "example.test",
        PLANTED_ANSWER,
        PLANTED_NAME,
        "Dupont",
        display_name,
        str(STUDENT_A),
        str(STUDENT_B),
        str(question),
        planted_op["op_id"],
        "203.0.113.77",
        "cursor",
        "locale",
        "choice_id",
    ):
        assert forbidden not in text, f"leaked into the logs: {forbidden[:24]}"
    for line in capture.lines:
        assert "actor" not in line, "no actor field unless a hash key is configured"


async def test_exceptions_are_logged_by_type_and_location_without_their_message(
    logged: tuple[httpx.AsyncClient, Capture],
) -> None:
    _, capture = logged
    try:
        raise ValueError(f"could not parse answer {PLANTED_ANSWER} of {PLANTED_EMAIL}")
    except ValueError:
        logging.getLogger("edu_api.errors").exception("unhandled error")
    (line,) = [entry for entry in capture.lines if entry.get("exc_type")]
    assert line["exc_type"] == "ValueError" and line["message"] == "unhandled error"
    assert line["exc_trace"] and "test_logging_privacy.py" in line["exc_trace"][-1]
    assert PLANTED_ANSWER not in capture.text and PLANTED_EMAIL not in capture.text


async def test_redaction_backstop_and_unknown_extra_fields(
    logged: tuple[httpx.AsyncClient, Capture], tokens: dict[str, str]
) -> None:
    """A careless future log call must still not leak: values are redacted in the
    message, and `extra=` fields that are not on the allow-list are dropped."""
    _, capture = logged
    token = tokens["student_a"]
    careless = logging.getLogger("edu_api.careless")
    careless.warning("auth header was Bearer %s", token)
    careless.warning("token=%s user=%s", token, PLANTED_EMAIL)
    careless.warning("connect failed for postgresql+asyncpg://edu_api_login:hunter2@db:5432/x")
    careless.warning(
        "extra fields", extra={"email": PLANTED_EMAIL, "answer": PLANTED_ANSWER, "status": 418}
    )
    careless.warning("x" * 10_000)
    lines = [line for line in capture.lines if line["logger"] == "edu_api.careless"]
    assert [line["message"] for line in lines[:3]] == [
        "auth header was [redacted-credential]",
        "token=[redacted-token] user=[redacted-email]",
        "connect failed for [redacted-dsn]",
    ]
    assert set(lines[3]) == {"ts", "level", "logger", "message", "status"}
    assert len(lines[4]["message"]) == 2000
    # Third-party libraries (an HTTP client logs whole URLs) are kept from WARNING up only.
    logging.getLogger("httpx").info("HTTP Request: GET http://x/?email=%s", PLANTED_EMAIL)
    logging.getLogger("sqlalchemy.engine").info("SELECT %s", PLANTED_ANSWER)
    logging.getLogger("httpx").warning("pool problem for %s", PLANTED_EMAIL.replace("@", "%40"))
    third_party = [line for line in capture.lines if not line["logger"].startswith("edu_api")]
    assert [(line["logger"], line["message"]) for line in third_party] == [
        ("httpx", "pool problem for [redacted-email]")
    ]
    for forbidden in (token, PLANTED_EMAIL, PLANTED_ANSWER, "hunter2", "example.test"):
        assert forbidden not in capture.text
    assert (
        redact("nothing personal here: sqlstate=57014") == "nothing personal here: sqlstate=57014"
    )


async def test_actor_is_a_keyed_hash_never_the_user_id(
    logged_with_actor: tuple[httpx.AsyncClient, Capture], tokens: dict[str, str]
) -> None:
    http, capture = logged_with_actor
    for account in ("student_a", "student_a", "student_b"):
        assert (await http.get("/v1/me", headers=bearer(tokens[account]))).status_code == 200
    await http.get("/v1/me")  # no token
    await http.get("/v1/me", headers=bearer(make_token(new_ec_key(), sub=str(STUDENT_A))))  # forged
    await http.get("/health")
    first, second, other, anonymous, forged, probe = capture.requests
    assert first["actor"] == second["actor"] != other["actor"], "stable per learner, distinct"
    assert first["actor"] == actor_tag(STUDENT_A, ACTOR_KEY.encode())
    assert len(first["actor"]) == 16 and int(first["actor"], 16) >= 0
    for line in (anonymous, forged, probe):
        assert "actor" not in line, "only a VERIFIED token yields an actor"
    assert actor_tag(STUDENT_A, b"another-key-" * 4) != first["actor"], "depends on the key"
    for forbidden in (str(STUDENT_A), str(STUDENT_B), STUDENT_A.hex, ACTOR_KEY):
        assert forbidden not in capture.text


async def test_logs_stay_clean_with_the_rate_limiter_and_notifications_on(
    local_env: dict[str, str], tokens: dict[str, str]
) -> None:
    async for http, capture in _json_logging_app(
        local_env,
        log_actor_hash_key=ACTOR_KEY,
        rate_limit_enabled=True,
        rate_limit_read_burst=1,
        rate_limit_read_per_minute=1,
        notifications_enabled=True,
    ):
        headers = bearer(tokens["student_a"])
        statuses = [
            (await http.get("/v1/notifications", headers=headers)).status_code,
            (await http.get("/v1/notifications", headers=headers)).status_code,
            (
                await http.put(
                    "/v1/me/notification-preferences",
                    headers=headers,
                    json={
                        "push_enabled": PLANTED_EMAIL,
                        "muted_categories": [],
                        "quiet_hours": None,
                    },
                )
            ).status_code,
        ]
        assert statuses == [200, 429, 422]
        lines = capture.requests
        assert [(line["route"], line["status"]) for line in lines] == [
            ("/v1/notifications", 200),
            ("unmatched", 429),  # refused before routing: no template, and no raw path
            ("/v1/me/notification-preferences", 422),
        ]
        assert len({line["actor"] for line in lines}) == 1, "the limiter's verification is reused"
        for forbidden in (
            tokens["student_a"],
            str(STUDENT_A),
            PLANTED_EMAIL,
            str(uuid.UUID(int=0)),
        ):
            assert forbidden not in capture.text


# ------------------------------------------------------------ real uvicorn (review L-1)
_UVICORN_APPS: list[FastAPI] = []
_UVICORN_SETTINGS: list[Any] = []


def _uvicorn_factory() -> FastAPI:
    application = create_app(_UVICORN_SETTINGS[0])
    _UVICORN_APPS.append(application)
    return application


async def test_uvicorn_records_never_carry_the_request_target_in_json_mode(
    local_env: dict[str, str],
) -> None:
    """Review L-1, driven through a REAL uvicorn server: a refused WebSocket handshake
    makes uvicorn log the peer address and the raw request target (query string
    included). In JSON mode none of that may reach the log; lifecycle lines still do."""
    import asyncio
    import socket

    import uvicorn

    names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    saved = [
        (logging.getLogger(n), logging.getLogger(n).handlers[:], logging.getLogger(n).propagate)
        for n in names
    ]
    _UVICORN_SETTINGS[:] = [
        build_settings(local_env, log_format="json", notifications_enabled=True)
    ]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # Configuring the Config is what installs uvicorn's own log handlers; the app
    # factory then runs (as with `uvicorn --factory`) and switches them to JSON.
    config = uvicorn.Config(
        "tests.integration.test_logging_privacy:_uvicorn_factory",
        factory=True,
        host="127.0.0.1",
        port=port,
    )
    buffer = io.StringIO()
    for handler in logging.getLogger("uvicorn").handlers:
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(buffer)
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        target = "/v1/ws?name=Jean-Baptiste&answer=quarante-deux&phone=50937001234"
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            (
                f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: Upgrade\r\n"
                "Upgrade: websocket\r\nSec-WebSocket-Version: 13\r\n"
                "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n"
            ).encode()
        )
        await writer.drain()
        assert (await reader.read(64)).startswith(b"HTTP/1.1 ")
        writer.close()
        plain = await asyncio.open_connection("127.0.0.1", port)
        plain[1].write(f"GET {target} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n".encode())
        await plain[1].drain()
        await plain[0].read(64)
        plain[1].close()
        await asyncio.sleep(0.2)
    finally:
        server.should_exit = True
        await serving
        for application in _UVICORN_APPS:
            application.state.json_logging_undo()
            await application.state.db.dispose()
            if hasattr(application.state, "notify_db"):
                await application.state.notify_db.dispose()
        _UVICORN_APPS.clear()
        for logger, handlers, propagate in saved:
            logger.handlers[:] = handlers
            logger.propagate = propagate
    output = buffer.getvalue()
    for planted in ("Jean-Baptiste", "quarante-deux", "50937001234", "/v1/ws", ' - "', "WebSocket"):
        assert planted not in output, planted
    lines = [json.loads(line) for line in output.splitlines()]
    assert lines, "lifecycle lines are still logged"
    assert any(line["message"].startswith("Started server process") for line in lines)
