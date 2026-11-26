"""Security corrections J-02 … J-05 on a real PostgreSQL, with real concurrent transactions.

Runs against the suite's own throwaway database (see ``conftest.py``): the
proposed ``tutor`` schema, synthetic learners, a mock provider. The store is
used as the API role; ``owner`` only arranges policy and inspects tables.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import replace
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text

from edu_api.db.session import Database
from edu_api.tutor import demo_content
from edu_api.tutor.budget import AttemptCharge, UsageOutcome
from edu_api.tutor.content import InMemoryLessonSource
from edu_api.tutor.errors import (
    DuplicateRequest,
    GlobalBudgetExhausted,
    RequestInProgress,
    ReservationLost,
    TutorError,
    TutorPaused,
)
from edu_api.tutor.factory import build_tutor_service
from edu_api.tutor.governance import ConsentState, StaticConsent, StaticEntitlements
from edu_api.tutor.pg_store import PostgresUsageStore
from edu_api.tutor.providers.base import ModelRequest, ModelResult, TokenUsage
from edu_api.tutor.providers.mock import DeterministicMockProvider
from edu_api.tutor.service import TutorService
from tests.tutor_pg.test_budget_postgres import STAFF, A, B, global_totals, spent
from tests.unit.tutor.conftest import ask, make_settings, no_sleep

MARKER = "ZANMI-SEKRE-48151623"
ROOMY = (
    "UPDATE tutor.policy SET learner_daily_requests = 1000, learner_daily_micro = 10000000, "
    "learner_monthly_micro = 10000000, global_monthly_micro = 100000000, "
    "max_concurrent_per_learner = 1"
)


def service_for(
    store: PostgresUsageStore,
    learners: list[uuid.UUID],
    provider: Any,
    *,
    retry_sleep: Any = no_sleep,
    **settings: Any,
) -> TutorService:
    lessons = InMemoryLessonSource()
    lessons.add(demo_content.equations_fr())
    return build_tutor_service(
        make_settings(**settings),
        lessons=lessons,
        usage=store,
        consent=StaticConsent({learner: ConsentState.GRANTED for learner in learners}),
        entitlements=StaticEntitlements(set(learners)),
        provider=provider,
        retry_sleep=retry_sleep,
    )


async def request_rows(owner: asyncpg.Pool) -> list[asyncpg.Record]:
    return list(await owner.fetch("SELECT * FROM tutor.usage_requests ORDER BY created_at, id"))


async def audit(owner: asyncpg.Pool) -> list[tuple[str, dict[str, Any]]]:
    rows = await owner.fetch("SELECT action, details FROM tutor.admin_audit ORDER BY created_at")
    return [(r["action"], json.loads(r["details"])) for r in rows]


async def hold_of_one_request(
    store: PostgresUsageStore, owner: asyncpg.Pool, **settings: Any
) -> int:
    """What the service reserves for the standard question, measured, then cleaned up."""
    await owner.execute(ROOMY)
    learner = uuid.uuid4()
    service = service_for(store, [learner], DeterministicMockProvider(), **settings)
    await service.answer(learner, ask())
    held = await owner.fetchval("SELECT reserved_micro FROM tutor.usage_requests")
    await owner.execute(
        "TRUNCATE tutor.usage_attempts, tutor.usage_requests, tutor.budget_counters, "
        "tutor.admin_audit"
    )
    return int(held)


# =================================================================================================
# J-02  the hold, the ceilings, and a provider that bills above the bound
# =================================================================================================
class Meter(DeterministicMockProvider):
    """The mock, reporting ``delta`` more (or fewer) input tokens than its own count."""

    def __init__(self, delta: int = 0, **options: Any) -> None:
        super().__init__(**options)
        self.delta = delta

    async def complete(self, request: ModelRequest) -> ModelResult:
        result = await super().complete(request)
        return replace(
            result,
            usage=TokenUsage(result.usage.input_tokens + self.delta, result.usage.output_tokens),
        )


@pytest.mark.parametrize("framing_tokens", [0, 1, 7, 40, 90])
async def test_the_ceiling_holds_for_a_range_of_provider_framing(
    store: PostgresUsageStore, owner: asyncpg.Pool, framing_tokens: int
) -> None:
    """The reviewer's overrun (1,736 against 1,735) with the framing varied.

    The ceiling is set to exactly one hold. The provider bills its message count
    plus ``framing_tokens``; all of these are inside the declared allowance, so
    what is paid never passes the ceiling and nothing is flagged.
    """
    hold = await hold_of_one_request(store, owner, max_attempts=1)
    await owner.execute(
        "UPDATE tutor.policy SET global_monthly_micro = $1, learner_monthly_micro = $1, "
        "learner_daily_micro = $1",
        hold,
    )
    learner = uuid.uuid4()
    service = service_for(store, [learner], Meter(framing_tokens), max_attempts=1)
    await service.answer(learner, ask())
    paid, held = await global_totals(owner)
    row = (await request_rows(owner))[0]
    assert held == 0 and 0 < paid <= hold == row["reserved_micro"]
    assert (row["overage_micro"], row["bound_violations"]) == (0, 0)
    assert await store.is_paused() is False


@pytest.mark.parametrize("message_chars", [1, 40, 250, 559])
async def test_the_hold_grows_with_the_prompt_and_always_covers_the_invoice(
    store: PostgresUsageStore, owner: asyncpg.Pool, message_chars: int
) -> None:
    await owner.execute(ROOMY)
    learner = uuid.uuid4()
    # Accented text: several bytes per character, the costly case for a byte bound.
    message = ("Pourquoi on soustrait 5 des deux côtés ? " + "é" * message_chars)[:600]
    await service_for(store, [learner], Meter(64)).answer(learner, ask(message=message))
    row = (await request_rows(owner))[0]
    assert row["status"] == "settled" and row["spent_micro"] * 2 <= row["reserved_micro"]
    assert row["overage_micro"] == 0


async def test_a_provider_that_bills_above_the_bound_is_recorded_in_full_and_pauses_everything(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    await owner.execute(ROOMY)
    learner, other = uuid.uuid4(), uuid.uuid4()
    provider = Meter(60_000)  # far above the bound
    service = service_for(store, [learner, other], provider)
    await service.answer(learner, ask(message=f"Pourquoi on soustrait 5 des deux côtés ? {MARKER}"))

    row = (await request_rows(owner))[0]
    attempt = await owner.fetchrow("SELECT * FROM tutor.usage_attempts")
    # The ledger says what the provider said. Nothing was trimmed to make it fit.
    assert row["spent_micro"] == attempt["cost_micro"] > row["reserved_micro"] > 0
    assert row["overage_micro"] == row["spent_micro"] - row["reserved_micro"]
    assert (row["bound_violations"], attempt["over_bound"], attempt["metered"]) == (1, True, True)
    paid, held = await global_totals(owner)
    assert (paid, held) == (row["spent_micro"], 0)

    # Dispatch is stopped for everyone, by the database, with a reason.
    policy = await owner.fetchrow("SELECT paused, pause_reason FROM tutor.policy")
    assert (policy["paused"], policy["pause_reason"]) == (True, "cost_bound_exceeded")
    with pytest.raises(TutorPaused):
        await service.answer(other, ask())
    assert provider.call_count == 1

    # An auditable discrepancy: amounts and versions, no learner and no text.
    action, details = (await audit(owner))[-1]
    assert action == "tutor.cost_bound.exceeded"
    assert details["overage_micro"] == row["overage_micro"]
    assert details["spent_micro"] == row["spent_micro"]
    assert details["model"] == "mock/jude-deterministic-v1"
    everything = json.dumps(await audit(owner)) + json.dumps(
        [dict(r) for r in await request_rows(owner)], default=str
    )
    assert MARKER not in everything
    assert str(learner) not in json.dumps(await audit(owner))

    # Staff resume deliberately; the reason is cleared and audited.
    await owner.fetchval("SELECT tutor.set_paused(false, $1)", STAFF)
    policy = await owner.fetchrow("SELECT paused, pause_reason FROM tutor.policy")
    assert (policy["paused"], policy["pause_reason"]) == (False, None)


async def test_unknown_usage_is_charged_at_the_bound_and_marked_unmetered(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    await owner.execute(ROOMY)
    learner = uuid.uuid4()
    provider = DeterministicMockProvider(script=("unavailable", "timeout"))
    service = service_for(store, [learner], provider, request_timeout_s=0.05)
    with pytest.raises(TutorError):
        await service.answer(learner, ask())
    row = (await request_rows(owner))[0]
    assert (row["status"], row["spent_micro"]) == ("settled", row["reserved_micro"])
    assert (row["attempts"], row["dispatches"], row["unmetered_attempts"]) == (2, 2, 2)
    attempts = await owner.fetch("SELECT * FROM tutor.usage_attempts ORDER BY attempt_no")
    assert [(a["outcome"], a["metered"]) for a in attempts] == [
        ("unavailable", False),
        ("timeout", False),
    ]
    assert sum(a["cost_micro"] for a in attempts) == row["spent_micro"]
    assert await store.is_paused() is False  # charging the bound is not an overage


async def test_differently_priced_calls_can_be_recosted_from_the_ledger(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    from edu_api.tutor.config import PriceEntry

    await owner.execute(ROOMY)
    learner = uuid.uuid4()
    backup = PriceEntry(
        price_version="backup-v2",
        model="mock/backup",
        input_micro_per_mtok=7,
        output_micro_per_mtok=9,
    )
    settings = make_settings()
    lessons = InMemoryLessonSource()
    lessons.add(demo_content.equations_fr())
    service = build_tutor_service(
        make_settings(
            max_attempts=1, fallback_model="mock/backup", prices=(*settings.prices, backup)
        ),
        lessons=lessons,
        usage=store,
        consent=StaticConsent({learner: ConsentState.GRANTED}),
        entitlements=StaticEntitlements({learner}),
        provider=DeterministicMockProvider(script=("invalid_json",)),
        fallback_provider=DeterministicMockProvider(name="backup"),
        retry_sleep=no_sleep,
    )
    await service.answer(learner, ask())
    row = (await request_rows(owner))[0]
    attempts = await owner.fetch("SELECT * FROM tutor.usage_attempts ORDER BY attempt_no")
    assert [(a["provider"], a["model"], a["price_version"], a["outcome"]) for a in attempts] == [
        ("mock", "mock/jude-deterministic-v1", "synthetic-2026-11", "output_rejected"),
        ("backup", "mock/backup", "backup-v2", "ok"),
    ]
    # Each call re-costs from its own tokens and its own price version.
    prices = {"synthetic-2026-11": settings.prices[0].to_price(), "backup-v2": backup.to_price()}
    for attempt in attempts:
        usage = TokenUsage(attempt["input_tokens"], attempt["output_tokens"])
        assert prices[attempt["price_version"]].cost_micro(usage) == attempt["cost_micro"]
    assert sum(a["cost_micro"] for a in attempts) == row["spent_micro"]


async def test_simultaneous_requests_exhaust_the_ceiling_exactly_and_never_pass_it(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    hold = await hold_of_one_request(store, owner)
    fits = 4
    await owner.execute(
        "UPDATE tutor.policy SET global_monthly_micro = $1, max_concurrent_global = 500",
        hold * fits + hold - 1,
    )
    learners = [uuid.uuid4() for _ in range(24)]
    provider = DeterministicMockProvider()
    provider.gate = asyncio.Event()  # every admitted request stays in flight together
    service = service_for(store, learners, provider)

    async def one(learner: uuid.UUID) -> str:
        try:
            await service.answer(learner, ask())
        except GlobalBudgetExhausted:
            return "refused"
        return "answered"

    tasks = [asyncio.create_task(one(learner)) for learner in learners]
    for _ in range(200):
        refused = sum(task.done() for task in tasks)
        if refused == len(learners) - fits:
            break
        await asyncio.sleep(0.02)
    # With every request in flight: exactly what fits is held, and not a micro more.
    paid, held = await global_totals(owner)
    assert (paid, held) == (0, hold * fits)
    provider.gate.set()
    results = await asyncio.gather(*tasks)
    assert (results.count("answered"), results.count("refused")) == (fits, len(learners) - fits)
    assert provider.call_count == fits
    paid, held = await global_totals(owner)
    assert held == 0 and 0 < paid <= hold * fits
    assert paid == await owner.fetchval("SELECT sum(spent_micro) FROM tutor.usage_requests")


async def test_per_learner_ceiling_holds_when_one_learner_sends_many_requests_at_once(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    hold = await hold_of_one_request(store, owner)
    await owner.execute(
        "UPDATE tutor.policy SET learner_daily_micro = $1, max_concurrent_per_learner = 50",
        hold * 2,
    )
    learner = uuid.uuid4()
    provider = DeterministicMockProvider()
    provider.gate = asyncio.Event()
    service = service_for(store, [learner], provider)

    async def one() -> str:
        try:
            await service.answer(learner, ask())
        except TutorError as exc:
            return exc.code
        return "answered"

    tasks = [asyncio.create_task(one()) for _ in range(12)]
    for _ in range(200):
        if sum(task.done() for task in tasks) == 10:
            break
        await asyncio.sleep(0.02)
    usage = await store.learner_usage(learner)
    assert usage.day_micro == hold * 2  # two holds, never three
    provider.gate.set()
    results = await asyncio.gather(*tasks)
    assert results.count("answered") == 2
    assert results.count("tutor_daily_limit_reached") == 10
    assert (await store.learner_usage(learner)).day_micro <= hold * 2


# =================================================================================================
# J-03  a provider call that happened stays in the books
# =================================================================================================
async def test_a_validator_fault_after_a_metered_call_is_settled_in_postgres(
    store: PostgresUsageStore, owner: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    await owner.execute(ROOMY)
    learner = uuid.uuid4()
    provider = DeterministicMockProvider()
    service = service_for(store, [learner], provider, max_attempts=3, reservation_ttl_s=200)

    def crash(*_: Any, **__: Any) -> None:
        raise RuntimeError("synthetic validator outage")

    monkeypatch.setattr("edu_api.tutor.service.validate_model_output", crash)
    request = ask()
    with pytest.raises(TutorError):
        await service.answer(learner, request)
    assert provider.call_count == 1
    row = (await request_rows(owner))[0]
    attempt = await owner.fetchrow("SELECT * FROM tutor.usage_attempts")
    assert (row["status"], row["attempts"], row["dispatches"]) == ("settled", 1, 1)
    assert row["spent_micro"] == attempt["cost_micro"] > 0
    assert (attempt["outcome"], attempt["metered"]) == ("validation_failed", True)
    assert (row["input_tokens"], row["output_tokens"]) == (
        attempt["input_tokens"],
        attempt["output_tokens"],
    )
    assert await global_totals(owner) == (row["spent_micro"], 0)

    # The key has been charged: it cannot be used for a second billable call.
    monkeypatch.undo()
    with pytest.raises(DuplicateRequest):
        await service.answer(learner, request)
    assert provider.call_count == 1 and len(await request_rows(owner)) == 1


async def test_the_database_refuses_a_release_that_hides_an_authorised_dispatch(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    hold = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=400)
    await store.authorize_dispatch(hold)
    assert await store.release(hold, outcome="tutor_unavailable") == "dispatch_mismatch"
    row = (await request_rows(owner))[0]
    assert (row["status"], row["dispatches"]) == ("reserved", 1)
    assert await global_totals(owner) == (0, 400)  # the money is still held
    assert (await audit(owner))[-1] == (
        "tutor.release.dispatch_mismatch",
        {"authorized": 1, "refused": 0},
    )
    # Accounted for as a refusal by the provider, it may be given back.
    assert await store.release(hold, outcome="tutor_unavailable", refused_attempts=1) == "released"
    assert await global_totals(owner) == (0, 0)


async def test_a_request_cancelled_mid_call_is_settled_once_at_the_bound(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    await owner.execute(ROOMY)
    learner = uuid.uuid4()
    provider = DeterministicMockProvider()
    provider.gate = asyncio.Event()
    service = service_for(store, [learner], provider, max_attempts=1)
    task = asyncio.create_task(service.answer(learner, ask()))
    await provider.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    row = (await request_rows(owner))[0]
    assert (row["status"], row["outcome"]) == ("settled", "cancelled")
    assert row["spent_micro"] == row["reserved_micro"] and row["unmetered_attempts"] == 1
    assert await global_totals(owner) == (row["spent_micro"], 0)


# =================================================================================================
# J-04  each admission has its own identity; stale finalizers are no-ops
# =================================================================================================
async def test_stale_settlement_and_release_cannot_reach_a_newer_admission(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    key = uuid.uuid4()
    old = await store.reserve(learner_id=A, request_key=key, estimate_micro=400)
    assert await store.release(old, outcome="tutor_provider_unavailable") == "released"
    new = await store.reserve(learner_id=A, request_key=key, estimate_micro=300)
    assert new.id != old.id

    # Delayed finalizers for the OLD admission arrive while the new one is in flight.
    assert await store.settle(old, spent(999)) == "already_finished"
    assert await store.release(old, outcome="late") == "already_finished"
    with pytest.raises(ReservationLost):
        await store.authorize_dispatch(old)
    rows = {r["id"]: r for r in await request_rows(owner)}
    assert (rows[old.id]["status"], rows[old.id]["spent_micro"]) == ("released", 0)
    assert (rows[new.id]["status"], rows[new.id]["reserved_micro"], rows[new.id]["dispatches"]) == (
        "reserved",
        300,
        0,
    )
    assert await global_totals(owner) == (0, 300)
    # The stale claim of a charge is kept for audit, and changes nothing.
    assert (await audit(owner))[-1] == ("tutor.settlement.stale", {"reported_micro": 999})

    assert await store.settle(new, spent(120)) == "settled"
    assert await global_totals(owner) == (120, 0)
    with pytest.raises(DuplicateRequest):
        await store.reserve(learner_id=A, request_key=key, estimate_micro=10)


async def test_stale_finalizers_racing_a_new_admission_never_corrupt_it(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    await owner.execute(
        "UPDATE tutor.policy SET learner_daily_requests = 1000, learner_daily_micro = 1000000, "
        "learner_monthly_micro = 1000000, global_monthly_micro = 10000000, "
        "max_concurrent_per_learner = 100"
    )
    rounds = 15

    async def one_round() -> tuple[Any, Any]:
        key = uuid.uuid4()
        old = await store.reserve(learner_id=A, request_key=key, estimate_micro=50)
        await store.release(old, outcome="tutor_provider_unavailable")
        new, *_ = await asyncio.gather(
            store.reserve(learner_id=A, request_key=key, estimate_micro=30),
            store.settle(old, spent(40)),
            store.release(old, outcome="late"),
            store.settle(old, spent(41)),
        )
        return old, new

    pairs = await asyncio.gather(*(one_round() for _ in range(rounds)))
    assert len({new.id for _, new in pairs} | {old.id for old, _ in pairs}) == 2 * rounds
    assert await global_totals(owner) == (0, 30 * rounds)
    statuses = await owner.fetch(
        "SELECT status, count(*) AS n, sum(spent_micro) AS spent FROM tutor.usage_requests "
        "GROUP BY status ORDER BY status"
    )
    assert [(r["status"], r["n"], r["spent"]) for r in statuses] == [
        ("released", rounds, 0),
        ("reserved", rounds, 0),
    ]
    await asyncio.gather(*(store.settle(new, spent(20)) for _, new in pairs))
    assert await global_totals(owner) == (20 * rounds, 0)


async def test_the_same_key_sent_many_times_at_once_gets_one_live_admission(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    await owner.execute("UPDATE tutor.policy SET max_concurrent_per_learner = 100")
    key = uuid.uuid4()

    async def attempt() -> Any:
        try:
            return await store.reserve(learner_id=A, request_key=key, estimate_micro=10)
        except (RequestInProgress, DuplicateRequest) as exc:
            return exc

    results = await asyncio.gather(*(attempt() for _ in range(30)))
    admitted = [r for r in results if not isinstance(r, Exception)]
    assert len(admitted) == 1
    assert all(isinstance(r, RequestInProgress) for r in results if isinstance(r, Exception))
    assert await global_totals(owner) == (0, 10)
    # The database itself forbids a second live row for the key.
    with pytest.raises(asyncpg.UniqueViolationError):
        await owner.execute(
            "INSERT INTO tutor.usage_requests (learner_id, request_key, status, usage_day, "
            "usage_month, reserved_micro, expires_at) VALUES ($1, $2, 'settled', current_date, "
            "current_date, 0, now())",
            A,
            key,
        )


async def test_late_settlement_after_expiry_is_never_lower_and_never_hidden(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    low = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=400)
    high = await store.reserve(learner_id=B, request_key=uuid.uuid4(), estimate_micro=400)
    await owner.execute("UPDATE tutor.usage_requests SET expires_at = now() - interval '1 second'")
    # An expired hold authorises nothing more, even before the sweeper has run.
    with pytest.raises(ReservationLost):
        await store.authorize_dispatch(low)
    assert await owner.fetchval("SELECT tutor.expire_stale()") == 2
    assert await global_totals(owner) == (800, 0)

    assert await store.settle(low, spent(150)) == "already_finished"
    assert await global_totals(owner) == (800, 0)  # the full hold stays charged

    assert await store.settle(high, spent(460)) == "late_overage"
    assert await global_totals(owner) == (860, 0)
    row = await owner.fetchrow("SELECT * FROM tutor.usage_requests WHERE id = $1", high.id)
    assert (row["status"], row["spent_micro"], row["overage_micro"], row["outcome"]) == (
        "expired",
        460,
        60,
        "expired_late_overage",
    )
    assert (await store.learner_usage(B)).day_micro == 460
    assert await store.is_paused() is True
    assert await store.settle(high, spent(460)) == "already_finished"  # once
    assert await global_totals(owner) == (860, 0)


async def test_expiry_and_a_new_admission_of_the_same_key_do_not_share_an_identity(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    key = uuid.uuid4()
    first = await store.reserve(learner_id=A, request_key=key, estimate_micro=100)
    await owner.execute("UPDATE tutor.usage_requests SET expires_at = now() - interval '1 second'")
    # The learner's next request charges the stale hold. The key was charged, so it is used up.
    with pytest.raises(DuplicateRequest):
        await store.reserve(learner_id=A, request_key=key, estimate_micro=100)
    other = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=50)
    assert other.id != first.id
    assert await store.settle(first, spent(60)) == "already_finished"
    assert await global_totals(owner) == (100, 50)


async def test_erasing_a_learner_fences_outstanding_work(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    """Account deletion while a request is in flight."""
    await owner.execute(ROOMY)
    learner, bystander = uuid.uuid4(), uuid.uuid4()
    provider = DeterministicMockProvider(script=("unavailable", "ok"))

    async def erase_during_backoff(_: float) -> None:
        await owner.fetchval("SELECT tutor.erase_learner($1, $2)", learner, STAFF)

    service = service_for(store, [learner, bystander], provider, retry_sleep=erase_during_backoff)
    with pytest.raises(TutorError):
        await service.answer(learner, ask())
    # The retry was never dispatched: an erased hold authorises nothing.
    assert provider.call_count == 1
    for table in ("usage_requests", "budget_counters"):
        assert (
            await owner.fetchval(
                f"SELECT count(*) FROM tutor.{table} WHERE learner_id = $1", learner
            )
            == 0
        )
    assert await owner.fetchval("SELECT count(*) FROM tutor.usage_attempts") == 0
    # The money is not forgotten: the hold became anonymous spend, and the late
    # settlement (which found no row) left its figure in the audit trail, unattributed.
    paid, held = await global_totals(owner)
    assert held == 0 and paid > 0
    trail = await audit(owner)
    assert [action for action, _ in trail] == ["tutor.learner.erase", "tutor.settlement.orphan"]
    assert str(learner) not in json.dumps(trail)
    # Other learners are untouched.
    assert (await service.answer(bystander, ask())).references


async def test_one_learner_cannot_authorise_settle_or_release_anothers_admission(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    hold = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=400)
    forged = replace(hold, learner_id=B)
    with pytest.raises(ReservationLost):
        await store.authorize_dispatch(forged)
    assert await store.settle(forged, spent(1)) == "not_found"
    assert await store.release(forged, outcome="x") == "not_found"
    row = (await request_rows(owner))[0]
    assert (row["status"], row["dispatches"], row["learner_id"]) == ("reserved", 0, A)
    assert (await store.learner_usage(B)).day_micro == 0


async def test_the_api_role_can_call_the_new_function_and_still_touches_no_table(
    database: Database,
) -> None:
    for statement in (
        "SELECT * FROM tutor.usage_attempts",
        "DELETE FROM tutor.usage_attempts",
        "UPDATE tutor.usage_requests SET dispatches = 0",
        "UPDATE tutor.policy SET pause_reason = NULL",
        "SELECT tutor._trip_cost_bound(gen_random_uuid())",
        "SELECT tutor._describe(gen_random_uuid(), 0, 0, 0, 'x', 'p', 'm', 'v', 'v', NULL, 0, 0, '[]')",
    ):
        with pytest.raises(Exception, match="permission denied"):
            async with database.transaction(A) as conn:
                await conn.execute(text(statement))
    async with database.transaction(A) as conn:
        verdict = (
            await conn.execute(text("SELECT tutor.authorize_dispatch(gen_random_uuid())"))
        ).scalar_one()
    assert verdict == "not_active"
    with pytest.raises(Exception, match="no authenticated learner"):
        async with database.transaction(None) as conn:
            await conn.execute(text("SELECT tutor.authorize_dispatch(gen_random_uuid())"))


async def test_per_call_rows_are_constrained_to_codes_and_numbers(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    hold = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=400)
    charge = AttemptCharge(
        provider="mock",
        model="mock/jude-deterministic-v1",
        price_version="synthetic-2026-11",
        outcome="Pourquoi on soustrait 5 des deux côtés ?",  # text where a code belongs
        metered=True,
        input_tokens=1,
        output_tokens=1,
        cost_micro=5,
    )
    with pytest.raises(Exception, match="usage_attempts_outcome_check"):
        await store.settle(
            hold,
            UsageOutcome(5, 1, 1, 1, "answered", True, charges=(charge,)),
        )
    # The refused settlement changed nothing; the hold is intact and can be settled properly.
    assert await global_totals(owner) == (0, 400)
    assert await store.settle(hold, spent(5)) == "settled"


# =================================================================================================
# J-05  where exactly a pause takes effect
# =================================================================================================
async def test_a_pause_commits_strictly_before_or_after_each_dispatch_authorisation(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    """The linearisation boundary, shown with a pause held open in a transaction.

    While a pause has been written but not committed, an authorisation cannot
    slip past it on the old value: it waits. Once the pause commits, it is refused.
    """
    hold = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=400)
    async with owner.acquire() as staff:
        transaction = staff.transaction()
        await transaction.start()
        await staff.fetchval("SELECT tutor.set_paused(true, $1)", STAFF)  # not committed yet
        authorisation = asyncio.create_task(store.authorize_dispatch(hold))
        admission = asyncio.create_task(
            store.reserve(learner_id=B, request_key=uuid.uuid4(), estimate_micro=10)
        )
        done, _ = await asyncio.wait({authorisation, admission}, timeout=0.5)
        assert not done, "a dispatch or an admission was decided while a pause was pending"
        await transaction.commit()
    with pytest.raises(TutorPaused):
        await authorisation
    with pytest.raises(TutorPaused):
        await admission
    row = await owner.fetchrow("SELECT * FROM tutor.usage_requests WHERE id = $1", hold.id)
    assert (row["status"], row["dispatches"]) == ("reserved", 0)  # nothing was authorised


async def test_a_pause_that_is_rolled_back_stops_nothing(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    hold = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=400)
    async with owner.acquire() as staff:
        transaction = staff.transaction()
        await transaction.start()
        await staff.fetchval("SELECT tutor.set_paused(true, $1)", STAFF)
        authorisation = asyncio.create_task(store.authorize_dispatch(hold))
        await asyncio.sleep(0.2)
        assert not authorisation.done()
        await transaction.rollback()
    await authorisation  # authorised: the pause never took effect
    assert await owner.fetchval("SELECT dispatches FROM tutor.usage_requests") == 1


async def test_a_pause_waits_for_authorisations_in_progress_and_stops_every_later_one(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    await owner.execute(
        "UPDATE tutor.policy SET max_concurrent_per_learner = 500, learner_daily_requests = 500"
    )
    holds = [
        await store.reserve(learner_id=uuid.uuid4(), request_key=uuid.uuid4(), estimate_micro=1)
        for _ in range(40)
    ]

    async def authorise(hold: Any) -> bool:
        try:
            await store.authorize_dispatch(hold)
        except TutorPaused:
            return False
        return True

    first = [asyncio.create_task(authorise(hold)) for hold in holds[:20]]
    pause = asyncio.create_task(owner.fetchval("SELECT tutor.set_paused(true, $1)", STAFF))
    early = await asyncio.gather(*first)
    await pause
    late = await asyncio.gather(*(authorise(hold) for hold in holds[20:]))
    assert late == [False] * 20  # nothing after the pause committed
    # Every authorisation that was granted is counted on its hold; none was half-done.
    counted = await owner.fetchval("SELECT sum(dispatches) FROM tutor.usage_requests")
    assert counted == sum(early)


async def test_an_admission_cannot_use_limits_older_than_a_committed_change(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    """The review's source observation: reserve read the policy before taking its locks."""
    async with owner.acquire() as staff:
        transaction = staff.transaction()
        await transaction.start()
        await staff.execute("UPDATE tutor.policy SET global_monthly_micro = 5")
        admission = asyncio.create_task(
            store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=10)
        )
        done, _ = await asyncio.wait({admission}, timeout=0.5)
        assert not done
        await transaction.commit()
    with pytest.raises(GlobalBudgetExhausted):
        await admission
    assert await global_totals(owner) == (0, 0)


async def test_work_dispatched_before_a_pause_still_settles_its_cost(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    await owner.execute(ROOMY)
    learner = uuid.uuid4()
    provider = DeterministicMockProvider()
    provider.gate = asyncio.Event()
    service = service_for(store, [learner], provider)
    task = asyncio.create_task(service.answer(learner, ask()))
    await provider.started.wait()
    await owner.fetchval("SELECT tutor.set_paused(true, $1)", STAFF)
    provider.gate.set()
    assert (await task).references
    row = (await request_rows(owner))[0]
    assert row["status"] == "settled" and 0 < row["spent_micro"] < row["reserved_micro"]
    with pytest.raises(TutorPaused):
        await service.answer(learner, ask())
    assert provider.call_count == 1


async def test_a_pause_during_backoff_settles_the_first_call_and_starts_no_fallback(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    from edu_api.tutor.config import PriceEntry

    await owner.execute(ROOMY)
    learner = uuid.uuid4()
    primary = DeterministicMockProvider(script=("unavailable", "unavailable"))
    backup = DeterministicMockProvider(name="backup")

    async def pause_during_wait(_: float) -> None:
        await owner.fetchval("SELECT tutor.set_paused(true, $1)", STAFF)

    lessons = InMemoryLessonSource()
    lessons.add(demo_content.equations_fr())
    settings = make_settings()
    service = build_tutor_service(
        make_settings(
            fallback_model="mock/backup",
            prices=(
                *settings.prices,
                PriceEntry(
                    price_version="t1",
                    model="mock/backup",
                    input_micro_per_mtok=1,
                    output_micro_per_mtok=1,
                ),
            ),
        ),
        lessons=lessons,
        usage=store,
        consent=StaticConsent({learner: ConsentState.GRANTED}),
        entitlements=StaticEntitlements({learner}),
        provider=primary,
        fallback_provider=backup,
        retry_sleep=pause_during_wait,
    )
    with pytest.raises(TutorPaused):
        await service.answer(learner, ask())
    assert (primary.call_count, backup.call_count) == (1, 0)
    row = (await request_rows(owner))[0]
    assert (row["status"], row["outcome"], row["dispatches"]) == ("settled", "tutor_paused", 1)
    assert row["spent_micro"] > 0 and row["unmetered_attempts"] == 1
    assert await global_totals(owner) == (row["spent_micro"], 0)


async def test_charging_a_stale_hold_from_an_earlier_day_does_not_deadlock_a_late_settlement(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    """``reserve`` used to lock a stale row before its counters; ``settle`` does the reverse."""
    await owner.execute(
        "UPDATE tutor.policy SET learner_daily_requests = 1000, learner_daily_micro = 1000000, "
        "learner_monthly_micro = 1000000, global_monthly_micro = 10000000, "
        "max_concurrent_per_learner = 100"
    )
    for _ in range(12):
        learner = uuid.uuid4()
        stale = await store.reserve(learner_id=learner, request_key=uuid.uuid4(), estimate_micro=40)
        # The hold belongs to yesterday (other counters) and has run out of time.
        await owner.execute(
            "INSERT INTO tutor.budget_counters (scope, learner_id, period_kind, period_start, "
            "reserved_micro, request_count) VALUES ('learner', $1, 'day', current_date - 1, 40, 1)",
            learner,
        )
        await owner.execute(
            "UPDATE tutor.budget_counters SET reserved_micro = 0, request_count = 0 "
            "WHERE learner_id = $1 AND period_kind = 'day' AND period_start <> current_date - 1",
            learner,
        )
        await owner.execute(
            "UPDATE tutor.usage_requests SET usage_day = current_date - 1, "
            "expires_at = now() - interval '1 second' WHERE id = $1",
            stale.id,
        )
        result, fresh = await asyncio.gather(
            store.settle(stale, spent(25)),
            store.reserve(learner_id=learner, request_key=uuid.uuid4(), estimate_micro=10),
        )
        row = await owner.fetchrow("SELECT * FROM tutor.usage_requests WHERE id = $1", stale.id)
        # Whichever won, the stale hold was finished exactly once.
        assert (result, row["status"], row["spent_micro"]) in (
            ("settled", "settled", 25),
            ("already_finished", "expired", 40),
        )
        assert fresh.reserved_micro == 10
    paid, held = await global_totals(owner)
    assert held == 10 * 12
    assert paid == await owner.fetchval(
        "SELECT sum(spent_micro) FROM tutor.usage_requests WHERE status <> 'reserved'"
    )
