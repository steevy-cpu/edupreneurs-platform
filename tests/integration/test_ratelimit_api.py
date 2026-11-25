"""The opt-in rate limiter in front of the real API: default off, keys, 429 shape,
and the sync retry contract (a limited batch is never lost and never applied twice)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from edu_api.main import create_app
from tests.conftest import build_settings
from tests.helpers import SEED_QUESTIONS_FR, STUDENT_A, answer_op, bearer


class FakeClock:
    def __init__(self) -> None:
        self.now = 50_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def limited(
    local_env: dict[str, str],
) -> AsyncIterator[tuple[httpx.AsyncClient, FakeClock, FastAPI]]:
    """The API with the limiter ON, tiny budgets and a clock the test controls."""
    settings = build_settings(
        local_env,
        rate_limit_enabled=True,
        rate_limit_read_burst=3,
        rate_limit_read_per_minute=60,
        rate_limit_write_burst=2,
        rate_limit_write_per_minute=60,
        rate_limit_sync_push_burst=2,
        rate_limit_sync_push_per_minute=6,  # one batch per 10 s
        rate_limit_anonymous_burst=2,
        rate_limit_anonymous_per_minute=60,
    )
    application = create_app(settings)
    clock = FakeClock()
    application.state.rate_limiter.clock = clock
    transport = httpx.ASGITransport(app=application, client=("203.0.113.5", 4000))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
            yield http, clock, application
    finally:
        await application.state.db.dispose()


def assert_limited(response: httpx.Response, *, retry_after: int | None = None) -> None:
    assert response.status_code == 429, response.text
    error = response.json()["error"]
    assert set(error) == {"code", "message", "request_id"}
    assert error["code"] == "rate_limited"
    assert error["request_id"] == response.headers["x-request-id"]
    assert int(response.headers["retry-after"]) >= 1
    if retry_after is not None:
        assert int(response.headers["retry-after"]) == retry_after


async def test_default_settings_have_no_limiter_at_all(
    app: FastAPI, client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """Behaviour with default settings is exactly today's: nothing is installed."""
    assert app.state.settings.rate_limit_enabled is False
    assert not hasattr(app.state, "rate_limiter")
    assert "RateLimitMiddleware" not in [m.cls.__name__ for m in app.user_middleware]
    assert [m.cls.__name__ for m in app.user_middleware] == [
        "RequestIdMiddleware",
        "BodyLimitMiddleware",
    ]
    for _ in range(80):
        assert (await client.get("/v1/me", headers=bearer(tokens["student_a"]))).status_code == 200


async def test_burst_refill_and_error_shape(
    limited: tuple[httpx.AsyncClient, FakeClock, FastAPI], tokens: dict[str, str]
) -> None:
    http, clock, _ = limited
    headers = bearer(tokens["student_a"])
    for _ in range(3):
        assert (await http.get("/v1/me", headers=headers)).status_code == 200
    assert_limited(await http.get("/v1/me", headers=headers), retry_after=1)
    # The whole read class shares the learner's bucket, whatever the route.
    assert_limited(await http.get("/v1/catalog", params={"locale": "fr"}, headers=headers))
    clock.now += 1.0
    assert (await http.get("/v1/me", headers=headers)).status_code == 200
    assert_limited(await http.get("/v1/me", headers=headers))
    clock.now += 600.0  # idle: back to a full burst, not more
    statuses = [(await http.get("/v1/me", headers=headers)).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]


async def test_learners_do_not_share_a_bucket_even_behind_one_address(
    limited: tuple[httpx.AsyncClient, FakeClock, FastAPI], tokens: dict[str, str]
) -> None:
    """A school or a mobile carrier puts many learners behind one address."""
    http, _, _ = limited
    for _ in range(3):
        assert (await http.get("/v1/me", headers=bearer(tokens["student_a"]))).status_code == 200
    assert_limited(await http.get("/v1/me", headers=bearer(tokens["student_a"])))
    for _ in range(3):
        assert (await http.get("/v1/me", headers=bearer(tokens["student_b"]))).status_code == 200
    # ... and the read budget being spent does not block A's sync upload.
    question, correct = SEED_QUESTIONS_FR[0]
    pushed = await http.post(
        "/v1/sync/push",
        headers=bearer(tokens["student_a"]),
        json={"ops": [answer_op(question, correct)]},
    )
    assert pushed.status_code == 200


async def test_unverified_tokens_are_counted_by_address_never_by_their_claims(
    limited: tuple[httpx.AsyncClient, FakeClock, FastAPI], tokens: dict[str, str]
) -> None:
    """A forged token naming Student A must not spend A's budget, and inventing
    subjects must not give an attacker fresh buckets."""
    import jwt

    from tests.helpers import make_token, new_ec_key

    http, _, application = limited
    forged = [make_token(new_ec_key(), sub=str(STUDENT_A)) for _ in range(2)]
    forged += [make_token(new_ec_key(), sub=str(uuid.uuid4())) for _ in range(3)]
    assert jwt.decode(forged[0], options={"verify_signature": False})["sub"] == str(STUDENT_A)
    statuses = [(await http.get("/v1/me", headers=bearer(token))).status_code for token in forged]
    assert statuses == [401, 401, 429, 429, 429], "one anonymous bucket for the address"
    assert_limited(await http.get("/v1/me"))  # no token at all: same bucket
    assert_limited(await http.get("/openapi.json"))
    # The real Student A, from the same address, is untouched.
    for _ in range(3):
        assert (await http.get("/v1/me", headers=bearer(tokens["student_a"]))).status_code == 200
    keys = [key for _, key in application.state.rate_limiter._buckets]
    assert sorted(set(keys)) == sorted({"a:203.0.113.5", f"u:{STUDENT_A}"})
    assert not any(token in key for token in forged for key in keys), "tokens are never keys"


async def test_probes_are_never_limited(
    limited: tuple[httpx.AsyncClient, FakeClock, FastAPI],
) -> None:
    http, _, _ = limited
    for _ in range(3):
        await http.get("/v1/me")  # exhaust the anonymous bucket of this address
    assert_limited(await http.get("/v1/me"))
    for _ in range(50):
        assert (await http.get("/health")).status_code == 200
        assert (await http.get("/ready")).status_code == 200


async def test_a_limited_sync_batch_is_neither_lost_nor_applied_twice(
    limited: tuple[httpx.AsyncClient, FakeClock, FastAPI],
    tokens: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    """The client retry contract: on 429 wait `Retry-After` seconds and resend the
    SAME batch (same op_ids). A refused batch was not read, so nothing was applied;
    a batch that was applied but whose answer was lost is answered `replayed`."""
    http, clock, _ = limited
    headers = bearer(tokens["student_a"])
    batches: list[dict[str, Any]] = [
        {"ops": [answer_op(question, correct)]} for question, correct in SEED_QUESTIONS_FR[:3]
    ]

    async def attempts() -> int:
        return int(
            await admin.fetchval(
                "SELECT count(*) FROM app.practice_attempts WHERE learner_id = $1", STUDENT_A
            )
        )

    assert (await http.post("/v1/sync/push", headers=headers, json=batches[0])).status_code == 200
    assert (await http.post("/v1/sync/push", headers=headers, json=batches[1])).status_code == 200
    refused = await http.post("/v1/sync/push", headers=headers, json=batches[2])
    assert_limited(refused, retry_after=10)
    assert await attempts() == 2, "the refused batch wrote nothing"

    # An impatient client that retries early is refused again and still loses nothing.
    clock.now += 3.0
    assert_limited(
        await http.post("/v1/sync/push", headers=headers, json=batches[2]), retry_after=7
    )
    assert await attempts() == 2

    clock.now += float(refused.headers["retry-after"])
    accepted = await http.post("/v1/sync/push", headers=headers, json=batches[2])
    assert accepted.status_code == 200
    (result,) = accepted.json()["results"]
    assert (result["status"], result["replayed"]) == ("accepted", False)
    assert await attempts() == 3

    # "Answer lost on the way back": the client resends a batch that WAS applied.
    clock.now += 60.0
    replay = await http.post("/v1/sync/push", headers=headers, json=batches[0])
    assert replay.status_code == 200 and replay.json()["results"][0]["replayed"] is True
    assert await attempts() == 3, "exactly once"
    receipts = await admin.fetchval(
        "SELECT count(*) FROM app.sync_receipts WHERE learner_id = $1", STUDENT_A
    )
    assert receipts == 3
    # Pulling is a different route class: a limited upload never blocks the download.
    assert (await http.get("/v1/sync/pull", headers=headers)).status_code == 200


async def test_a_limited_request_is_rejected_before_its_body_is_read(
    limited: tuple[httpx.AsyncClient, FakeClock, FastAPI], tokens: dict[str, str]
) -> None:
    http, _, _ = limited
    headers = bearer(tokens["student_a"])
    question, correct = SEED_QUESTIONS_FR[0]
    for _ in range(2):
        await http.post(
            "/v1/sync/push", headers=headers, json={"ops": [answer_op(question, correct)]}
        )
    # Oversized and malformed bodies would be 413 / 400 if they were looked at.
    assert_limited(await http.post("/v1/sync/push", headers=headers, content=b"x" * 100_000))
    assert_limited(
        await http.post(
            "/v1/sync/push",
            headers={**headers, "Content-Encoding": "gzip"},
            content=b"not gzip",
        )
    )


async def test_trusted_proxy_setting_decides_which_address_is_counted(
    local_env: dict[str, str],
) -> None:
    for hops, expected_statuses in ((0, [401, 401, 429]), (1, [401, 401, 401])):
        application = create_app(
            build_settings(
                local_env,
                rate_limit_enabled=True,
                rate_limit_anonymous_burst=2,
                rate_limit_anonymous_per_minute=1,
                rate_limit_trusted_proxy_hops=hops,
            )
        )
        transport = httpx.ASGITransport(app=application, client=("10.0.0.1", 4000))
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
                statuses = [
                    (
                        await http.get("/v1/me", headers={"X-Forwarded-For": f"198.51.100.{index}"})
                    ).status_code
                    for index in range(3)
                ]
        finally:
            await application.state.db.dispose()
        # hops=0: the header is client-controlled text and is ignored (one bucket).
        # hops=1: the proxy's entry is the client (three clients, three buckets).
        assert statuses == expected_statuses, hops
