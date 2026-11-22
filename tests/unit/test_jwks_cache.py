"""JWKS caching, rotation and failure behaviour (HTTP mocked, no network)."""

from __future__ import annotations

import json

import httpx
import jwt
import pytest

from edu_api.auth.jwks import JWKSCache, KeyNotFound, KeySourceUnavailable, parse_jwks
from tests.helpers import new_ec_key, public_jwk

ALLOWED = frozenset({"ES256"})


def jwk_dict(kid: str) -> dict[str, object]:
    raw = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(new_ec_key().public_key()))
    raw.update({"kid": kid, "alg": "ES256", "use": "sig"})
    return raw


class FakeAuthServer:
    def __init__(self) -> None:
        self.keys: list[dict[str, object]] = [jwk_dict("k1")]
        self.calls = 0
        self.fail = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail:
            return httpx.Response(503)
        return httpx.Response(200, json={"keys": self.keys})


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def cache_for(server: FakeAuthServer, clock: Clock) -> JWKSCache:
    client = httpx.AsyncClient(transport=httpx.MockTransport(server.handler))
    return JWKSCache(
        "https://auth.test.invalid/jwks.json",
        allowed_algorithms=ALLOWED,
        cache_ttl_s=600,
        min_refresh_interval_s=30,
        http_client=client,
        clock=clock,
    )


async def test_keys_are_cached() -> None:
    server, clock = FakeAuthServer(), Clock()
    cache = cache_for(server, clock)
    await cache.get_key("k1")
    await cache.get_key("k1")
    assert server.calls == 1


async def test_cache_expires_after_ttl() -> None:
    server, clock = FakeAuthServer(), Clock()
    cache = cache_for(server, clock)
    await cache.get_key("k1")
    clock.now += 601
    await cache.get_key("k1")
    assert server.calls == 2


async def test_rotation_new_kid_triggers_one_refresh() -> None:
    server, clock = FakeAuthServer(), Clock()
    cache = cache_for(server, clock)
    await cache.get_key("k1")
    server.keys.append(jwk_dict("k2"))
    clock.now += 31
    assert (await cache.get_key("k2")).key_id == "k2"
    assert server.calls == 2


async def test_unknown_kids_cannot_force_repeated_refreshes() -> None:
    server, clock = FakeAuthServer(), Clock()
    cache = cache_for(server, clock)
    await cache.get_key("k1")
    for attempt in range(20):
        with pytest.raises(KeyNotFound):
            await cache.get_key(f"bogus-{attempt}")
    assert server.calls <= 2  # initial fetch + at most one refresh inside the interval


async def test_unreachable_with_no_cache_fails_closed() -> None:
    server, clock = FakeAuthServer(), Clock()
    server.fail = True
    with pytest.raises(KeySourceUnavailable):
        await cache_for(server, clock).get_key("k1")


async def test_unreachable_keeps_serving_a_previously_trusted_key() -> None:
    server, clock = FakeAuthServer(), Clock()
    cache = cache_for(server, clock)
    await cache.get_key("k1")
    server.fail = True
    clock.now += 601
    assert (await cache.get_key("k1")).key_id == "k1"


def test_symmetric_and_non_signing_keys_are_ignored() -> None:
    good = jwk_dict("good")
    document = {
        "keys": [
            good,
            {"kty": "oct", "kid": "shared-secret", "k": "c2VjcmV0", "alg": "HS256"},
            {**jwk_dict("enc"), "use": "enc"},
            {**jwk_dict("nokid"), "kid": ""},
            "garbage",
        ]
    }
    assert set(parse_jwks(document, ALLOWED)) == {"good"}


def test_malformed_document_is_rejected() -> None:
    with pytest.raises(ValueError, match="keys"):
        parse_jwks({"not": "jwks"}, ALLOWED)


def test_helper_key_round_trip() -> None:
    assert public_jwk(new_ec_key()).algorithm_name == "ES256"
