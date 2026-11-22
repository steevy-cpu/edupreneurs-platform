"""Pure-ASGI middleware: request ids and request-body limits.

Written as plain ASGI (not ``BaseHTTPMiddleware``) so that they add no
buffering to responses and behave predictably with exceptions.
"""

from __future__ import annotations

import json
import uuid
import zlib
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from edu_api.errors import error_payload

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class RequestIdMiddleware:
    """Give every request a server-generated id and echo it in ``X-Request-ID``.

    The id is generated here rather than accepted from the client so a caller
    cannot inject arbitrary text into our logs.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_id)


class _BodyRejected(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


class BodyLimitMiddleware:
    """Bound every request body BEFORE the application parses it.

    * ``max_wire_bytes`` — bytes actually received (the compressed size when the
      client sends ``Content-Encoding: gzip``). Older phones on metered networks
      are the reason batches are kept this small.
    * ``max_decoded_bytes`` — size after decompression. Decompression stops as
      soon as this is exceeded, so a "zip bomb" cannot exhaust memory.

    The body is read fully (it is at most ``max_wire_bytes``), optionally
    un-gzipped, and replayed to the application as a single chunk.
    """

    def __init__(self, app: ASGIApp, *, max_wire_bytes: int, max_decoded_bytes: int) -> None:
        self.app = app
        self.max_wire_bytes = max_wire_bytes
        self.max_decoded_bytes = max_decoded_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        try:
            body = await self._read_body(headers, receive)
        except _BodyRejected as rejected:
            await self._reject(scope, send, rejected)
            return

        new_headers = [
            (k, v)
            for k, v in scope.get("headers", [])
            if k.lower() not in {b"content-encoding", b"content-length"}
        ]
        new_headers.append((b"content-length", str(len(body)).encode("ascii")))
        scope["headers"] = new_headers

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()  # lets the app observe a later client disconnect

        await self.app(scope, replay, send)

    async def _read_body(self, headers: dict[bytes, bytes], receive: Receive) -> bytes:
        too_large = _BodyRejected(
            413,
            "payload_too_large",
            f"Request body exceeds {self.max_wire_bytes} bytes on the wire.",
        )
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_wire_bytes:
                    raise too_large
            except ValueError:
                raise _BodyRejected(400, "bad_request", "Invalid Content-Length header.") from None

        chunks: list[bytes] = []
        received = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                raise _BodyRejected(400, "bad_request", "Client disconnected.")
            chunk = message.get("body", b"")
            received += len(chunk)
            if received > self.max_wire_bytes:
                raise too_large
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        raw = b"".join(chunks)

        encoding = headers.get(b"content-encoding", b"identity").decode("latin-1").strip().lower()
        if encoding in {"", "identity"}:
            return raw
        if encoding != "gzip":
            raise _BodyRejected(
                415, "unsupported_media_type", "Only gzip Content-Encoding is supported."
            )
        try:
            decompressor = zlib.decompressobj(wbits=zlib.MAX_WBITS | 16)
            decoded = decompressor.decompress(raw, self.max_decoded_bytes + 1)
        except zlib.error:
            raise _BodyRejected(400, "bad_request", "Request body is not valid gzip.") from None
        if len(decoded) > self.max_decoded_bytes or decompressor.unconsumed_tail:
            raise _BodyRejected(
                413,
                "payload_too_large",
                f"Decompressed request body exceeds {self.max_decoded_bytes} bytes.",
            )
        if not decompressor.eof:
            raise _BodyRejected(400, "bad_request", "Request body is truncated gzip.")
        return decoded

    @staticmethod
    async def _reject(scope: Scope, send: Send, rejected: _BodyRejected) -> None:
        request_id = scope.get("state", {}).get("request_id")
        payload = json.dumps(error_payload(rejected.code, rejected.message, request_id)).encode(
            "utf-8"
        )
        await send(
            {
                "type": "http.response.start",
                "status": rejected.status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})
