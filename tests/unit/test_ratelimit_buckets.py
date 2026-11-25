"""The token bucket, route classes, address handling and bounded memory (no I/O)."""

from __future__ import annotations

import pytest

from edu_api.ratelimit import Budget, RateLimiter, classify, client_address


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


def test_memory_is_bounded_by_evicting_the_least_recently_used() -> None:
    clock = FakeClock()
    buckets = limiter(clock, max_keys=50)
    buckets.take("anonymous", "a:victim")
    buckets.take("anonymous", "a:victim")
    assert buckets.take("anonymous", "a:victim") > 0.0, "victim is limited"
    for index in range(10_000):  # a flood of distinct keys
        buckets.take("anonymous", f"a:flood-{index}")
        assert len(buckets) <= 50
    assert len(buckets) == 50
    # Stated limit: an evicted key starts again with a full bucket (fails open).
    assert buckets.take("anonymous", "a:victim") == 0.0


def test_a_recently_used_key_survives_eviction() -> None:
    clock = FakeClock()
    buckets = limiter(clock, max_keys=10)
    for _ in range(3):
        buckets.take("read", "u:busy")
    for index in range(9):
        buckets.take("read", f"u:other-{index}")
        buckets.take("read", "u:busy")  # keeps being used while others arrive
    assert buckets.take("read", "u:busy") > 0.0, "still limited: it was never evicted"


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
