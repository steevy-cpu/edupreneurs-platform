"""The token bucket, route classes, address handling and bounded memory (no I/O)."""

from __future__ import annotations

import uuid

import pytest

from edu_api.auth.verifier import InvalidToken, Principal
from edu_api.ratelimit import Budget, MemoVerifier, RateLimiter, classify, client_address


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def limiter(clock: FakeClock, *, max_keys: int = 100, **budgets: Budget) -> RateLimiter:
    defaults = {
        "read": Budget(3, 60),
        "write": Budget(2, 60),
        "sync_push": Budget(2, 30),
        "anonymous": Budget(2, 60),
    }
    return RateLimiter({**defaults, **budgets}, max_keys=max_keys, clock=clock)


def test_burst_then_refusal_with_the_time_to_wait() -> None:
    clock = FakeClock()
    buckets = limiter(clock)
    assert [buckets.take("read", "u:a") for _ in range(3)] == [0.0, 0.0, 0.0]
    assert buckets.take("read", "u:a") == pytest.approx(1.0)  # 60/min = one per second
    clock.advance(0.25)
    assert buckets.take("read", "u:a") == pytest.approx(0.75), "a refused request costs nothing"


def test_refill_is_gradual_and_capped_at_the_burst() -> None:
    clock = FakeClock()
    buckets = limiter(clock)
    for _ in range(3):
        buckets.take("read", "u:a")
    clock.advance(1.0)
    assert buckets.take("read", "u:a") == 0.0, "one token back after one second"
    assert buckets.take("read", "u:a") > 0.0
    clock.advance(3600.0)  # a long idle period does not build up more than the burst
    assert [buckets.take("read", "u:a") == 0.0 for _ in range(4)] == [True, True, True, False]


def test_refusal_never_pushes_the_wait_further_away() -> None:
    """Hammering while limited must not extend the penalty (no starvation of a
    client that retries a little early)."""
    clock = FakeClock()
    buckets = limiter(clock)
    for _ in range(3):
        buckets.take("read", "u:a")
    for _ in range(50):
        assert buckets.take("read", "u:a") == pytest.approx(1.0)
    clock.advance(1.0)
    assert buckets.take("read", "u:a") == 0.0


def test_principals_and_route_classes_are_isolated() -> None:
    clock = FakeClock()
    buckets = limiter(clock)
    for _ in range(3):
        assert buckets.take("read", "u:a") == 0.0
    assert buckets.take("read", "u:a") > 0.0
    assert buckets.take("read", "u:b") == 0.0, "another learner is unaffected"
    assert buckets.take("write", "u:a") == 0.0, "another route class of the same learner too"
    assert buckets.take("sync_push", "u:a") == 0.0
    assert buckets.take("anonymous", "a:192.0.2.1") == 0.0


def test_a_flood_of_distinct_keys_never_switches_the_limiter_off() -> None:
    """Bounded memory must not mean "fails open": once the store is full, unknown
    keys share ONE overflow bucket with the anonymous budget."""
    clock = FakeClock()
    buckets = limiter(clock, max_keys=100)  # 50 anonymous + 50 verified
    allowed = 0
    for index in range(10_000):  # every request from a new address / invalid token
        allowed += buckets.take("anonymous", f"a:flood-{index}") == 0.0
        assert len(buckets) <= 100
    # 50 keys got their own bucket (one request each); everyone after that shared
    # the overflow bucket: burst 2, then refused.
    assert allowed == 50 + 2
    assert buckets.overflowed == 10_000 - 50
    assert buckets.take("anonymous", "a:yet-another") == pytest.approx(1.0)
    clock.advance(0.5)  # nothing has refilled completely yet: still the shared bucket
    assert buckets.take("anonymous", "a:and-another") == pytest.approx(0.5)
    # Sustained, a flood gets what its distinct addresses are each entitled to and
    # no more: a bucket is only handed to a new key once an old one has fully refilled.


def test_a_flood_cannot_reset_a_limited_key() -> None:
    clock = FakeClock()
    buckets = limiter(clock, max_keys=100)
    for _ in range(2):
        buckets.take("anonymous", "a:victim-or-attacker")
    assert buckets.take("anonymous", "a:victim-or-attacker") > 0.0
    for index in range(5_000):
        buckets.take("anonymous", f"a:flood-{index}")
    assert buckets.take("anonymous", "a:victim-or-attacker") > 0.0, "still limited"


def test_an_anonymous_flood_cannot_touch_verified_learners() -> None:
    """Only a verified token creates a learner bucket, so invented addresses and
    invalid tokens can neither evict a learner nor push learners into overflow."""
    clock = FakeClock()
    buckets = limiter(clock, max_keys=100)
    for _ in range(3):
        buckets.take("read", "u:limited-learner")
    assert buckets.take("read", "u:limited-learner") > 0.0
    for index in range(5_000):
        buckets.take("anonymous", f"a:flood-{index}")
    assert buckets.take("read", "u:limited-learner") > 0.0, "not reset by the flood"
    assert buckets.take("read", "u:new-learner") == 0.0, "a new learner still gets a full bucket"
    assert [buckets.take("read", "u:new-learner") == 0.0 for _ in range(3)] == [True, True, False]


def test_idle_buckets_are_forgotten_so_memory_is_reused() -> None:
    clock = FakeClock()
    buckets = limiter(clock, max_keys=20)  # 10 per store
    for index in range(10):
        buckets.take("anonymous", f"a:morning-{index}")
    clock.advance(3600.0)  # all of them have refilled: forgetting them loses nothing
    for index in range(10):
        assert buckets.take("anonymous", f"a:evening-{index}") == 0.0
    assert buckets.overflowed == 0 and len(buckets) == 10
    assert not [key for key in buckets.known_keys() if "morning" in key]


def test_verified_store_overflows_to_a_limited_bucket_too() -> None:
    clock = FakeClock()
    buckets = limiter(clock, max_keys=4)  # 2 learner buckets
    buckets.take("read", "u:a")
    buckets.take("read", "u:b")
    results = [buckets.take("read", f"u:extra-{index}") == 0.0 for index in range(4)]
    assert results == [True, True, False, False], "anonymous budget (burst 2), shared"
    assert buckets.take("read", "u:a") == 0.0, "existing learners keep their own bucket"


class CountingVerifier:
    def __init__(self) -> None:
        self.calls = 0
        self._keys = object()

    async def verify(self, token: str) -> Principal:
        self.calls += 1
        if token.startswith("bad"):
            raise InvalidToken("bad_signature")
        return Principal(user_id=uuid.UUID(int=len(token)))


async def test_memo_verifier_checks_a_token_once_and_never_remembers_a_failure() -> None:
    clock = FakeClock()
    inner = CountingVerifier()
    memo = MemoVerifier(inner, ttl_s=2.0, max_entries=3, clock=clock)  # type: ignore[arg-type]
    first = await memo.verify("token-one")
    assert await memo.verify("token-one") == first and inner.calls == 1
    clock.advance(2.5)
    await memo.verify("token-one")
    assert inner.calls == 2, "after the short window the token is verified again"
    for _ in range(3):
        with pytest.raises(InvalidToken):
            await memo.verify("bad-token")
    assert inner.calls == 5, "every use of a bad token is a real verification"
    for index in range(10):
        await memo.verify(f"token-{index:04d}")
    assert len(memo._seen) == 3, "bounded"
    assert all(len(digest) == 32 for digest in memo._seen), "digests, not tokens, are kept"
    assert memo._keys is inner._keys


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/health", None),
        ("GET", "/ready", None),
        ("POST", "/v1/sync/push", "sync_push"),
        ("GET", "/v1/sync/pull", "read"),
        ("GET", "/v1/catalog", "read"),
        ("GET", "/v1/lessons/b0000000-0000-4000-8000-000000000005", "read"),
        ("PUT", "/v1/me/notification-preferences", "write"),
        ("DELETE", "/v1/anything", "write"),
        ("GET", "/docs", "read"),
        ("GET", "/health/", "read"),  # only the exact probe paths are exempt
        ("POST", "/ready/x", "write"),
    ],
)
def test_route_classes(method: str, path: str, expected: str | None) -> None:
    assert classify(method, path) == expected


def scope(peer: str | None, forwarded: str | None = None) -> dict[str, object]:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return {"client": (peer, 5000) if peer else None, "headers": headers}


def test_forwarded_header_is_ignored_unless_proxies_are_declared() -> None:
    spoofed = scope("203.0.113.9", "198.51.100.1, 198.51.100.2")
    assert client_address(spoofed, 0) == "203.0.113.9"
    # One trusted proxy: the LAST entry is the one that proxy wrote.
    assert client_address(spoofed, 1) == "198.51.100.2"
    assert client_address(spoofed, 2) == "198.51.100.1"
    # Fewer entries than trusted hops, or rubbish: fall back to the peer / "unknown".
    assert client_address(scope("203.0.113.9", "198.51.100.1"), 2) == "203.0.113.9"
    assert client_address(scope("203.0.113.9", "<script>, x"), 1) == "unknown"
    assert client_address(scope(None), 0) == "unknown"


def test_ipv6_clients_are_counted_per_64_prefix() -> None:
    first = client_address(scope("2001:db8:1:2:aaaa:bbbb:cccc:dddd"), 0)
    second = client_address(scope("2001:db8:1:2::1"), 0)
    other = client_address(scope("2001:db8:1:3::1"), 0)
    assert first == second == "2001:db8:1:2::/64" and other != first
    assert client_address(scope("::ffff:192.0.2.7"), 0) == "192.0.2.7"
