"""Fetch and cache the Auth server's PUBLIC signing keys (JWKS).

Supabase Auth signs access tokens with a private key and publishes the matching
public keys at ``/auth/v1/.well-known/jwks.json``. We verify with those public
keys, so this service never holds anything that could mint a token.

Caching and rotation:
* keys are cached for ``cache_ttl_s``;
* a token whose ``kid`` (key id) is unknown triggers ONE refresh, because the
  Auth server may have rotated keys — but refreshes are rate-limited by
  ``min_refresh_interval_s`` so random ``kid`` values cannot be used to make us
  hammer the Auth server;
* if a refresh fails but we still hold the key, we keep using it (availability);
  if we do not hold it, the request fails closed with 503.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx
import jwt

logger = logging.getLogger("edu_api.auth.jwks")


class KeySourceUnavailable(Exception):
    """The JWKS endpoint could not be reached and no cached key can be used."""


class KeyNotFound(Exception):
    """No published key has this key id."""


class KeyProvider(Protocol):
    async def get_key(self, kid: str) -> jwt.PyJWK: ...


def parse_jwks(document: Any, allowed_algorithms: frozenset[str]) -> dict[str, jwt.PyJWK]:
    """Turn a JWKS document into ``{kid: key}``, keeping only usable signing keys."""
    keys: dict[str, jwt.PyJWK] = {}
    raw_keys = document.get("keys") if isinstance(document, dict) else None
    if not isinstance(raw_keys, list):
        raise ValueError("JWKS document has no 'keys' list")
    for raw in raw_keys:
        if not isinstance(raw, dict):
            continue
        kid = raw.get("kid")
        if not isinstance(kid, str) or not kid:
            continue
        if raw.get("use") not in (None, "sig"):
            continue
        if raw.get("kty") not in ("EC", "RSA"):
            continue  # never accept symmetric ("oct") keys from a JWKS
        try:
            key = jwt.PyJWK(raw)
        except jwt.PyJWTError:
            continue
        if key.algorithm_name not in allowed_algorithms:
            continue
        keys[kid] = key
    return keys


class JWKSCache:
    def __init__(
        self,
        jwks_url: str,
        *,
        allowed_algorithms: frozenset[str],
        cache_ttl_s: float,
        min_refresh_interval_s: float,
        http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = jwks_url
        self._allowed = allowed_algorithms
        self._ttl = cache_ttl_s
        self._min_interval = min_refresh_interval_s
        self._client = http_client
        self._owns_client = http_client is None
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._last_attempt_at: float | None = None
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()

    async def get_key(self, kid: str) -> jwt.PyJWK:
        now = self._clock()
        fresh = self._fetched_at is not None and (now - self._fetched_at) < self._ttl
        if fresh and kid in self._keys:
            return self._keys[kid]

        async with self._lock:
            # Another request may have refreshed while we waited for the lock.
            now = self._clock()
            fresh = self._fetched_at is not None and (now - self._fetched_at) < self._ttl
            if fresh and kid in self._keys:
                return self._keys[kid]

            recently_tried = (
                self._last_attempt_at is not None
                and (now - self._last_attempt_at) < self._min_interval
            )
            if not recently_tried:
                self._last_attempt_at = now
                try:
                    self._keys = await self._fetch()
                    self._fetched_at = self._clock()
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("JWKS refresh failed: %s", type(exc).__name__)
                    if kid in self._keys:
                        return self._keys[kid]  # stale but previously trusted
                    raise KeySourceUnavailable from exc

            if kid in self._keys:
                return self._keys[kid]
            if self._fetched_at is None:
                raise KeySourceUnavailable
            raise KeyNotFound(kid)

    async def _fetch(self) -> dict[str, jwt.PyJWK]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(3.0), follow_redirects=False)
        response = await self._client.get(self._url, headers={"Accept": "application/json"})
        response.raise_for_status()
        if len(response.content) > 64 * 1024:
            raise ValueError("JWKS document too large")
        return parse_jwks(response.json(), self._allowed)


class StaticKeyProvider:
    """Fixed key set, for tests and offline tooling."""

    def __init__(self, keys: dict[str, jwt.PyJWK]) -> None:
        self._keys = keys

    async def get_key(self, kid: str) -> jwt.PyJWK:
        try:
            return self._keys[kid]
        except KeyError:
            raise KeyNotFound(kid) from None
