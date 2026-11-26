"""In-process token-bucket rate limiting (opt-in: ``EDU_RATE_LIMIT_ENABLED``, default off).

WHAT THIS IS — AND IS NOT
-------------------------
A small safety net inside ONE API process. Buckets live in this process's
memory: with N worker processes or N instances a caller gets up to N times the
budget, a restart forgets every bucket, and nothing here stops traffic before it
reaches the process. A hosted, multi-instance deployment still needs a limiter
at the gateway or in a shared store (Platform-02). This module is not that.

Memory is bounded, and running out of room never switches the limiter off:
see ``RateLimiter``.

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

import hashlib
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
    Principal,
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
    """Token buckets with bounded memory that never fails open.

    ``take`` is synchronous and never awaits, so on one event loop it is atomic.

    Buckets are kept in two separate stores — verified learners (``u:…``) and
    everything else — each holding at most half of ``max_keys``. Only a verified
    token creates a learner bucket, so a flood of invented addresses or invalid
    tokens can fill the anonymous store but can never push a learner's bucket out.

    When a store is full and a NEW key arrives:

    * the least recently used bucket is dropped only if it has refilled
      completely — forgetting it changes nothing, its owner would start with a
      full bucket anyway;
    * otherwise the new key gets NO bucket of its own and is charged to one
      shared ``overflow`` bucket with the anonymous budget. Under a flood of
      distinct keys the limiter therefore becomes STRICTER for unknown keys, not
      absent, and existing (possibly limited) buckets are never reset.
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
        self._capacity = max(1, max_keys // 2)
        self._stores: dict[bool, OrderedDict[tuple[str, str], tuple[float, float]]] = {
            True: OrderedDict(),
            False: OrderedDict(),
        }
        self._overflow: dict[bool, tuple[float, float]] = {}
        #: How many requests were charged to a shared overflow bucket (for operators).
        self.overflowed = 0

    def __len__(self) -> int:
        return len(self._stores[True]) + len(self._stores[False])

    def known_keys(self) -> list[str]:
        return [key for store in self._stores.values() for _, key in store]

    @staticmethod
    def _spend(budget: Budget, state: tuple[float, float], now: float) -> tuple[float, float]:
        tokens, updated = state
        tokens = min(float(budget.burst), tokens + max(0.0, now - updated) * budget.per_second)
        if tokens >= 1.0:
            return tokens - 1.0, 0.0
        return tokens, (1.0 - tokens) / budget.per_second

    def _make_room(
        self, store: OrderedDict[tuple[str, str], tuple[float, float]], now: float
    ) -> bool:
        """Drop the least recently used bucket if that loses no information."""
        (oldest_class, _), (tokens, updated) = next(iter(store.items()))
        budget = self.budgets[oldest_class]
        if tokens + max(0.0, now - updated) * budget.per_second >= budget.burst:
            store.popitem(last=False)
            return True
        return False

    def take(self, route_class: str, key: str) -> float:
        """Spend one token. Returns 0.0 when allowed, else the seconds to wait."""
        now = self.clock()
        verified = key.startswith("u:")
        store = self._stores[verified]
        bucket_key = (route_class, key)
        state = store.get(bucket_key)
        if state is None and len(store) >= self._capacity and not self._make_room(store, now):
            # No room and nothing safe to forget: charge the shared overflow bucket.
            budget = self.budgets["anonymous"]
            tokens, wait = self._spend(
                budget, self._overflow.get(verified, (float(budget.burst), now)), now
            )
            self._overflow[verified] = (tokens, now)
            self.overflowed += 1
            return wait
        budget = self.budgets[route_class]
        tokens, wait = self._spend(budget, state or (float(budget.burst), now), now)
        store[bucket_key] = (tokens, now)
        store.move_to_end(bucket_key)
        return wait


class MemoVerifier:
    """Wraps the token verifier so that one request verifies its token ONCE.

    The limiter (and the access log) must know the VERIFIED principal before the
    route runs; the route's own dependency then verifies the same token again.
    This wrapper is installed as ``app.state.token_verifier`` only when one of
    those features is on. It remembers successful verifications for a couple of
    seconds, keyed by the SHA-256 of the token (the token itself is not kept),
    in a small bounded table. Failures are never remembered. The window is far
    inside the verifier's own 30-second clock leeway, so a token is not accepted
    meaningfully longer than without the wrapper.
    """

    def __init__(
        self,
        inner: TokenVerifier,
        *,
        ttl_s: float = 2.0,
        max_entries: int = 2048,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._ttl = ttl_s
        self._max = max_entries
        self._clock = clock
        self._seen: OrderedDict[bytes, tuple[float, Principal]] = OrderedDict()

    @property
    def _keys(self) -> object:  # tests and shutdown reach the key provider through here
        return self._inner._keys

    async def verify(self, token: str) -> Principal:
        digest = hashlib.sha256(token.encode("utf-8", "surrogatepass")).digest()
        now = self._clock()
        hit = self._seen.get(digest)
        if hit is not None and now - hit[0] <= self._ttl:
            return hit[1]
        principal = await self._inner.verify(token)
        self._seen[digest] = (now, principal)
        self._seen.move_to_end(digest)
        while len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return principal


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


def _header_joined(scope: Scope, name: bytes) -> str | None:
    """Every line of a repeatable header, in order, joined with ``,``.

    HTTP lets a sender (or a proxy) put one header on several lines; the values
    are equivalent to one comma-joined line. Reading only the first line would let
    a client choose the entry a proxy appended on a later line.
    """
    values = [
        bytes(value).decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.lower() == name
    ]
    return ",".join(values) if values else None


async def resolve_verified_user_id(
    scope: Scope, verifier: TokenVerifier | MemoVerifier
) -> uuid.UUID | None:
    """The caller's user id if — and only if — the access token verifies.

    Cached in ``scope["state"]`` for the rest of the request. The route dependency
    verifies the same token again; ``MemoVerifier`` makes that second check a
    table lookup.
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
        forwarded = _header_joined(scope, b"x-forwarded-for")
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
        verifier: TokenVerifier | MemoVerifier,
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
