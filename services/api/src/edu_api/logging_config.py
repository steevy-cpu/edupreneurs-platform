"""Privacy-respecting structured logs (opt-in: ``EDU_LOG_FORMAT=json``, default ``text``).

With the default ``text`` nothing in this module is installed and logging is
exactly what it was. With ``json`` every log record becomes one JSON line, and
one ``http_request`` line is written per request.

WHAT A REQUEST LINE CONTAINS
----------------------------
``ts``, ``level``, ``logger``, ``event``, ``request_id``, ``method``, ``route``
(the route TEMPLATE, e.g. ``/v1/lessons/{lesson_id}`` — never the raw path or
the query string), ``status``, ``duration_ms`` and, optionally, ``actor``.

WHAT IS NEVER LOGGED
--------------------
Tokens, the ``Authorization`` header, any other header, request or response
bodies, answers, names, e-mail addresses, raw paths, query strings, client
addresses, and the raw user id.

THE ACTOR: OMITTED BY DEFAULT, KEYED HASH ON REQUEST
----------------------------------------------------
A learner's user id is personal data about a (probably minor) person, and log
stores usually have wider access and longer retention than the database. So:

* by default there is NO actor field at all — the request id is enough to
  follow one request;
* if ``EDU_LOG_ACTOR_HASH_KEY`` is set, ``actor`` is the first 16 hex digits of
  HMAC-SHA-256(key, user id). Operators can then follow one learner's requests
  (abuse, a stuck sync) without the log holding an identifier that can be
  joined to the database. A plain SHA-256 would not do: user ids can be
  enumerated from the database, so an unkeyed hash is reversible by anyone who
  has both. Rotating the key unlinks old logs.

Records from third-party libraries are kept only from WARNING up (they are not
vetted for what they log). Other log records keep their developer-written message, passed through a
redaction filter as a backstop (tokens, bearer headers, e-mail addresses), and
exceptions are reduced to the exception TYPE and code locations: exception
messages can carry submitted values and are dropped.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import sys
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import IO, Any

from edu_api.auth.verifier import TokenVerifier
from edu_api.middleware import ASGIApp, Message, Receive, Scope, Send
from edu_api.ratelimit import (
    VERIFIED_USER_STATE_KEY,
    MemoVerifier,
    resolve_verified_user_id,
)

ACCESS_LOGGER = "edu_api.access"
_MAX_MESSAGE_LENGTH = 2000
_MAX_FRAMES = 12
#: The only ``extra=`` fields a record may add to its line. Anything else is dropped.
_ALLOWED_EXTRA = (
    "event",
    "request_id",
    "method",
    "route",
    "status",
    "duration_ms",
    "actor",
)
_KNOWN_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
#: Paths that are safe to log verbatim although they are not API route templates.
_STATIC_PATHS = frozenset({"/health", "/ready", "/docs", "/redoc", "/openapi.json"})

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), "[redacted-credential]"),
    (
        re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"),
        "[redacted-token]",
    ),
    (re.compile(r"sb_(?:secret|publishable)_[A-Za-z0-9_-]+"), "[redacted-key]"),
    (
        re.compile(r"(?i)[A-Za-z0-9._%+-]+(?:@|%40)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        "[redacted-email]",
    ),
    (re.compile(r"postgres(?:ql)?(?:\+\w+)?://\S+"), "[redacted-dsn]"),
)


def redact(text: str) -> str:
    """Backstop only: the rule is to never pass such values to a logger."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text[:_MAX_MESSAGE_LENGTH]


def actor_tag(user_id: uuid.UUID, key: bytes) -> str:
    """Stable pseudonym of a user id under ``key``. Not reversible without the key."""
    return hmac.new(key, user_id.bytes, hashlib.sha256).hexdigest()[:16]


class OwnCodeOrWarning(logging.Filter):
    """Third-party libraries are not vetted for what they put in a log line (an
    HTTP client logs full URLs, a driver may log statements). In JSON mode their
    records are kept only from WARNING up; this service's own loggers and
    uvicorn's lifecycle messages are kept from INFO."""

    _OWN = ("edu_api", "uvicorn")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return record.name.split(".", 1)[0] in self._OWN


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
        }
        for name in _ALLOWED_EXTRA:
            value = record.__dict__.get(name)
            if value is not None:
                line[name] = value
        if record.name != ACCESS_LOGGER:
            line["message"] = redact(record.getMessage())
        if record.exc_info and record.exc_info[0] is not None:
            # Type and code locations only. The exception MESSAGE may contain
            # submitted values (a validation error, a driver detail) and is dropped.
            line["exc_type"] = record.exc_info[0].__name__
            frames = traceback.extract_tb(record.exc_info[2])[-_MAX_FRAMES:]
            line["exc_trace"] = [
                f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno} in {frame.name}"
                for frame in frames
            ]
        return json.dumps(line, ensure_ascii=True, separators=(",", ":"))


def install_json_logging(
    stream: IO[str] | None = None,
) -> tuple[logging.StreamHandler[IO[str]], Callable[[], None]]:
    """Switch this process to JSON log lines. Returns ``(handler, undo)``.

    * the root logger gets one JSON handler; the plain handler that
      ``logging.basicConfig`` installed is removed;
    * uvicorn's own handlers are given the JSON formatter;
    * uvicorn's access log is switched off: it prints the raw path and query
      string, which this module exists to keep out of the logs.
    """
    formatter = JsonFormatter()
    handler: logging.StreamHandler[IO[str]] = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(formatter)
    handler.addFilter(OwnCodeOrWarning())
    root = logging.getLogger()
    removed = [h for h in root.handlers if type(h) is logging.StreamHandler]
    for old in removed:
        root.removeHandler(old)
    root.addHandler(handler)
    previous_level = root.level
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)

    restyled: list[tuple[logging.Handler, logging.Formatter | None]] = []
    for name in ("uvicorn", "uvicorn.error"):
        for other in logging.getLogger(name).handlers:
            restyled.append((other, other.formatter))
            other.setFormatter(formatter)
    uvicorn_access = logging.getLogger("uvicorn.access")
    access_was_disabled = uvicorn_access.disabled
    uvicorn_access.disabled = True

    def undo() -> None:
        root.removeHandler(handler)
        for old in removed:
            root.addHandler(old)
        root.setLevel(previous_level)
        for other, previous in restyled:
            other.setFormatter(previous)
        uvicorn_access.disabled = access_was_disabled

    return handler, undo


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    path = scope.get("path")
    return path if path in _STATIC_PATHS else "unmatched"


class AccessLogMiddleware:
    """Pure ASGI: one ``http_request`` line per request. Reads no body and no header
    value except, when an actor key is configured, the access token to verify it."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        verifier: TokenVerifier | MemoVerifier,
        actor_key: bytes | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.app = app
        self.verifier = verifier
        self.actor_key = actor_key
        self.clock = clock
        self.logger = logging.getLogger(ACCESS_LOGGER)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = self.clock()
        status = 500  # what the client gets if the application raises before answering

        async def send_and_observe(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_and_observe)
        finally:
            await self._log(scope, status, (self.clock() - started) * 1000.0)

    async def _log(self, scope: Scope, status: int, duration_ms: float) -> None:
        try:
            fields: dict[str, Any] = {
                "event": "http_request",
                "request_id": scope.get("state", {}).get("request_id"),
                "method": scope["method"] if scope["method"] in _KNOWN_METHODS else "OTHER",
                "route": _route_template(scope),
                "status": status,
                "duration_ms": round(duration_ms, 1),
            }
            if self.actor_key is not None:
                state = scope.get("state", {})
                user_id = (
                    state[VERIFIED_USER_STATE_KEY]
                    if VERIFIED_USER_STATE_KEY in state
                    else await resolve_verified_user_id(scope, self.verifier)
                )
                if user_id is not None:
                    fields["actor"] = actor_tag(user_id, self.actor_key)
            self.logger.info("http_request", extra=fields)
        except Exception:  # logging must never break a request
            self.logger.warning("access log line could not be written")
