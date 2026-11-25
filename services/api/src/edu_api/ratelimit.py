"""In-process token-bucket rate limiting (opt-in: ``EDU_RATE_LIMIT_ENABLED``, default off).

WHAT THIS IS — AND IS NOT
-------------------------
A small safety net inside ONE API process. Buckets live in this process's
memory: with N worker processes or N instances a caller gets up to N times the
budget, a restart forgets every bucket, and nothing here stops traffic before it
reaches the process. A hosted, multi-instance deployment still needs a limiter
at the gateway or in a shared store (Platform-02). This module is not that.

KEYS
----
* A request whose access token VERIFIES is counted per learner (``u:<user id>``),
  per route class (``read`` / ``write`` / ``sync_push``).
* Every other request — no token, bad token, key service down — is counted per
  client address in one shared ``anonymous`` bucket. An unverified token is never
  used as a key: otherwise anyone could spend another learner's budget, or mint
  unlimited keys.
* ``/health`` and ``/ready`` are never limited.

A rejected request gets ``429`` in the standard error shape with ``Retry-After``.
It is rejected BEFORE its body is read, so nothing was applied: for sync the
client waits and resends the same batch with the same ``op_id``s (see
``docs/overnight-2026-11-24/lanes/notify.md``).
"""

from __future__ import annotations

import ipaddress
import json
import math
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from edu_api.auth.verifier import (
    MAX_TOKEN_LENGTH,
    AuthUnavailable,
    InvalidToken,
    TokenVerifier,
)
from edu_api.config import Settings
from edu_api.errors import error_payload
from edu_api.middleware import ASGIApp, Message, Receive, Scope, Send

#: Where the verified user id of this request is kept in ``scope["state"]`` so
#: that it is worked out at most once per request (shared with the access log).
VERIFIED_USER_STATE_KEY = "verified_user_id"
_UNSET = object()

EXEMPT_PATHS = frozenset({"/health", "/ready"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Budget:
    """``burst`` requests at once, refilled at ``per_minute`` requests per minute."""

    burst: int
    per_minute: int

    @property
    def per_second(self) -> float:
        return self.per_minute / 60.0


def classify(method: str, path: str) -> str | None:
    """Route class of a request, or ``None`` when it is never limited."""
    if path in EXEMPT_PATHS:
        return None
    if method == "POST" and path == "/v1/sync/push":
        return "sync_push"
    if method not in _SAFE_METHODS:
        return "write"
    return "read"


class RateLimiter:
    """Token buckets with least-recently-used eviction (bounded memory).

    ``take`` is synchronous and never awaits, so on one event loop it is atomic.
    When more than ``max_keys`` buckets exist the least recently used one is
    dropped; its owner simply starts again with a full bucket. Under a flood of
    distinct keys the limiter therefore degrades towards "no limit" rather than
    towards "no memory" — one more reason a gateway limiter is still required.
    """

    def __init__(
        self,
        budgets: dict[str, Budget],
        *,
        max_keys: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.budgets = budgets
        self.max_keys = max_keys
        self.clock = clock
        self._buckets: OrderedDict[tuple[str, str], tuple[float, float]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._buckets)

    def take(self, route_class: str, key: str) -> float:
        """Spend one token. Returns 0.0 when allowed, else the seconds to wait."""
        budget = self.budgets[route_class]
        now = self.clock()
        bucket_key = (route_class, key)
        tokens, updated = self._buckets.get(bucket_key, (float(budget.burst), now))
        tokens = min(float(budget.burst), tokens + max(0.0, now - updated) * budget.per_second)
        if tokens >= 1.0:
            tokens -= 1.0
            wait = 0.0
        else:
            wait = (1.0 - tokens) / budget.per_second
        self._buckets[bucket_key] = (tokens, now)
        self._buckets.move_to_end(bucket_key)
        while len(self._buckets) > self.max_keys:
            self._buckets.popitem(last=False)
        return wait


def build_rate_limiter(settings: Settings) -> RateLimiter:
    return RateLimiter(
        {
            "read": Budget(settings.rate_limit_read_burst, settings.rate_limit_read_per_minute),
            "write": Budget(settings.rate_limit_write_burst, settings.rate_limit_write_per_minute),
            "sync_push": Budget(
                settings.rate_limit_sync_push_burst, settings.rate_limit_sync_push_per_minute
            ),
            "anonymous": Budget(
                settings.rate_limit_anonymous_burst, settings.rate_limit_anonymous_per_minute
            ),
        },
        max_keys=settings.rate_limit_max_keys,
    )


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return bytes(value).decode("latin-1")
    return None


async def resolve_verified_user_id(scope: Scope, verifier: TokenVerifier) -> uuid.UUID | None:
    """The caller's user id if — and only if — the access token verifies.

    Cached in ``scope["state"]`` for the rest of the request. Verification here
    repeats the signature check the route dependency does later (roughly a
    tenth of a millisecond with a cached key); that is the price of keying by a
    VERIFIED principal without touching the shared dependency module.
    """
    state = scope.setdefault("state", {})
    cached = state.get(VERIFIED_USER_STATE_KEY, _UNSET)
    if cached is not _UNSET:
        return cached  # type: ignore[no-any-return]
    user_id: uuid.UUID | None = None
    authorization = _header(scope, b"authorization")
    if authorization is not None and len(authorization) <= MAX_TOKEN_LENGTH + 16:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            try:
                user_id = (await verifier.verify(token.strip())).user_id
            except (InvalidToken, AuthUnavailable):
                user_id = None
    state[VERIFIED_USER_STATE_KEY] = user_id
    return user_id


def _normalise_address(raw: str | None) -> str:
    if not raw:
        return "unknown"
    try:
        address = ipaddress.ip_address(raw.strip())
    except ValueError:
        return "unknown"
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        # One household or attacker usually controls a whole /64.
        return str(ipaddress.ip_network(f"{address}/64", strict=False).network_address) + "/64"
    return str(address)


def client_address(scope: Scope, trusted_proxy_hops: int) -> str:
    """The address to count an unauthenticated request against.

    By default the socket peer. ``X-Forwarded-For`` is client-controlled text, so
    it is only read when the deployment declares how many proxies it trusts; then
    the entry added by the outermost trusted proxy is used.
    """
    client = scope.get("client")
    peer = client[0] if client else None
    if trusted_proxy_hops > 0:
        forwarded = _header(scope, b"x-forwarded-for")
        if forwarded:
            entries = [part.strip() for part in forwarded.split(",") if part.strip()]
            if len(entries) >= trusted_proxy_hops:
                return _normalise_address(entries[-trusted_proxy_hops])
    return _normalise_address(peer)


class RateLimitMiddleware:
    """Pure ASGI. Sits inside the request-id middleware and outside the body limit."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RateLimiter,
        verifier: TokenVerifier,
        trusted_proxy_hops: int = 0,
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.verifier = verifier
        self.trusted_proxy_hops = trusted_proxy_hops

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        route_class = classify(scope["method"], scope["path"])
        if route_class is None:
            await self.app(scope, receive, send)
            return

        user_id = await resolve_verified_user_id(scope, self.verifier)
        if user_id is not None:
            wait = self.limiter.take(route_class, f"u:{user_id}")
        else:
            address = client_address(scope, self.trusted_proxy_hops)
            wait = self.limiter.take("anonymous", f"a:{address}")
        if wait <= 0.0:
            await self.app(scope, receive, send)
            return
        await self._reject(scope, send, wait)

    @staticmethod
    async def _reject(scope: Scope, send: Send, wait: float) -> None:
        retry_after = max(1, math.ceil(wait))
        request_id = scope.get("state", {}).get("request_id")
        payload = json.dumps(
            error_payload(
                "rate_limited",
                "Too many requests. Wait, then send the same request again.",
                request_id,
            )
        ).encode("utf-8")
        start: Message = {
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
                (b"retry-after", str(retry_after).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
        await send(start)
        await send({"type": "http.response.body", "body": payload})
