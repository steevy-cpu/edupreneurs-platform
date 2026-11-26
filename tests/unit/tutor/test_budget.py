"""Budget rules on the in-memory ledger (single process — NOT a proof of database atomicity;
the PostgreSQL functions are tested in tests/tutor_pg)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest

from edu_api.tutor.budget import BudgetPolicy, InMemoryUsageStore, ModelPrice, UsageOutcome
from edu_api.tutor.errors import (
    DuplicateRequest,
    GlobalBudgetExhausted,
    LearnerDailyLimitReached,
    LearnerMonthlyLimitReached,
    RequestInProgress,
    TooManyConcurrentRequests,
    TutorBusy,
    TutorError,
    TutorPaused,
)
from edu_api.tutor.providers.base import TokenUsage

from .conftest import LEARNER_A, LEARNER_B, FakeClock


def policy(**overrides: int) -> BudgetPolicy:
    values: dict[str, int] = {
        "learner_daily_requests": 5,
        "learner_daily_micro": 1_000,
        "learner_monthly_micro": 3_000,
        "global_monthly_micro": 10_000,
        "max_concurrent_per_learner": 2,
        "max_concurrent_global": 50,
        "reservation_ttl_s": 60,
    }
    values.update(overrides)
    return BudgetPolicy(**values)


def store(clock: FakeClock | None = None, **overrides: int) -> InMemoryUsageStore:
    return InMemoryUsageStore(policy(**overrides), clock=clock or FakeClock())


def spent(amount: int, *, counts: bool = True, outcome: str = "answered") -> UsageOutcome:
    return UsageOutcome(
        spent_micro=amount,
        input_tokens=100,
        output_tokens=50,
        attempts=1,
        outcome=outcome,
        counts_as_request=counts,
    )


def test_price_is_integer_micro_usd_rounded_up() -> None:
    price = ModelPrice("v1", "m", input_micro_per_mtok=500_000, output_micro_per_mtok=1_500_000)
    assert price.cost_micro(TokenUsage(1_000, 500)) == 500 + 750
    assert price.cost_micro(TokenUsage(1, 1)) == 1 + 2  # never rounds a real cost down to zero
    assert price.cost_micro(TokenUsage(0, 0)) == 0
    assert isinstance(price.cost_micro(TokenUsage(3, 7)), int)
    with pytest.raises(ValueError):
        ModelPrice("v1", "m", -1, 0)


def test_days_and_months_roll_over_in_haiti_time_not_utc() -> None:
    clock = FakeClock()
    clock.now = clock.now.replace(
        day=1, hour=2
    )  # 02:00 UTC on the 1st = still the 30th/31st in Haiti
    day, month = policy().periods(clock.now)
    assert day.month == 10 and month.month == 10


async def test_reserve_then_settle_moves_the_hold_into_spend() -> None:
    ledger = store()
    reservation = await ledger.reserve(
        learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=400
    )
    usage = await ledger.learner_usage(LEARNER_A)
    assert (usage.day_requests, usage.day_micro) == (1, 400)  # held while in flight
    await ledger.settle(reservation, spent(120))
    usage = await ledger.learner_usage(LEARNER_A)
    assert (usage.day_requests, usage.day_micro, usage.month_micro) == (1, 120, 120)
    record = ledger.records()[0]
    assert (record.status, record.spent_micro, record.outcome) == ("settled", 120, "answered")


async def test_settlement_is_idempotent() -> None:
    ledger = store()
    reservation = await ledger.reserve(
        learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=400
    )
    await ledger.settle(reservation, spent(120))
    await ledger.settle(reservation, spent(999))
    await ledger.release(reservation, outcome="late")
    assert (await ledger.learner_usage(LEARNER_A)).day_micro == 120
    assert ledger.records()[0].spent_micro == 120


async def test_a_duplicate_key_is_never_charged_twice() -> None:
    ledger = store()
    key = uuid.uuid4()
    reservation = await ledger.reserve(learner_id=LEARNER_A, request_key=key, estimate_micro=400)
    with pytest.raises(RequestInProgress):
        await ledger.reserve(learner_id=LEARNER_A, request_key=key, estimate_micro=400)
    await ledger.settle(reservation, spent(120))
    with pytest.raises(DuplicateRequest):
        await ledger.reserve(learner_id=LEARNER_A, request_key=key, estimate_micro=400)
    assert (await ledger.learner_usage(LEARNER_A)).day_micro == 120
    assert len(ledger.records()) == 1


async def test_the_same_key_from_another_learner_is_a_different_request() -> None:
    ledger = store()
    key = uuid.uuid4()
    await ledger.reserve(learner_id=LEARNER_A, request_key=key, estimate_micro=100)
    await ledger.reserve(learner_id=LEARNER_B, request_key=key, estimate_micro=100)
    assert len(ledger.records()) == 2


async def test_a_released_request_costs_nothing_and_may_be_retried() -> None:
    ledger = store()
    key = uuid.uuid4()
    reservation = await ledger.reserve(learner_id=LEARNER_A, request_key=key, estimate_micro=400)
    await ledger.release(reservation, outcome="tutor_provider_unavailable")
    usage = await ledger.learner_usage(LEARNER_A)
    assert (usage.day_requests, usage.day_micro) == (0, 0)
    again = await ledger.reserve(learner_id=LEARNER_A, request_key=key, estimate_micro=400)
    assert again.id != reservation.id


async def test_a_failed_request_costs_money_but_not_one_of_the_daily_questions() -> None:
    ledger = store()
    reservation = await ledger.reserve(
        learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=400
    )
    await ledger.settle(reservation, spent(300, counts=False, outcome="tutor_provider_timeout"))
    usage = await ledger.learner_usage(LEARNER_A)
    assert (usage.day_requests, usage.day_micro) == (0, 300)


async def test_each_limit_refuses_with_its_own_stable_error() -> None:
    ledger = store(learner_daily_requests=2, max_concurrent_per_learner=5)
    for _ in range(2):
        r = await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=10)
        await ledger.settle(r, spent(10))
    with pytest.raises(LearnerDailyLimitReached):
        await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=10)

    ledger = store(learner_daily_micro=500)
    with pytest.raises(LearnerDailyLimitReached):
        await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=501)

    ledger = store(learner_daily_micro=5_000, learner_monthly_micro=500)
    with pytest.raises(LearnerMonthlyLimitReached):
        await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=501)

    ledger = store(
        learner_daily_micro=50_000, learner_monthly_micro=50_000, global_monthly_micro=500
    )
    with pytest.raises(GlobalBudgetExhausted):
        await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=501)

    ledger = store(max_concurrent_per_learner=1)
    await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=10)
    with pytest.raises(TooManyConcurrentRequests):
        await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=10)

    ledger = store(max_concurrent_global=1)
    await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=10)
    with pytest.raises(TutorBusy):
        await ledger.reserve(learner_id=LEARNER_B, request_key=uuid.uuid4(), estimate_micro=10)


async def test_the_exact_limit_is_allowed_and_one_more_is_not() -> None:
    ledger = store(learner_daily_micro=1_000, max_concurrent_per_learner=5)
    await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=1_000)
    with pytest.raises(LearnerDailyLimitReached):
        await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=1)


async def test_held_money_counts_against_the_global_ceiling_before_it_is_spent() -> None:
    ledger = store(
        global_monthly_micro=1_000, learner_daily_micro=10_000, learner_monthly_micro=10_000
    )
    await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=600)
    with pytest.raises(GlobalBudgetExhausted):
        await ledger.reserve(learner_id=LEARNER_B, request_key=uuid.uuid4(), estimate_micro=600)


async def test_concurrent_reservations_never_exceed_the_global_ceiling() -> None:
    limit, each, learners = 10_000, 900, 40
    ledger = store(
        global_monthly_micro=limit,
        learner_daily_micro=each,
        learner_monthly_micro=each,
        max_concurrent_global=1_000,
    )

    async def one(index: int) -> bool:
        try:
            await ledger.reserve(
                learner_id=uuid.UUID(int=index + 1), request_key=uuid.uuid4(), estimate_micro=each
            )
        except GlobalBudgetExhausted:
            return False
        return True

    results = await asyncio.gather(*(one(i) for i in range(learners)))
    assert sum(results) == limit // each == 11
    month = ledger.policy.periods(FakeClock().now)[1]
    spent_total, reserved_total = ledger.global_totals(month)
    assert spent_total + reserved_total == 11 * each <= limit


async def test_kill_switch_refuses_and_is_audited() -> None:
    ledger = store()
    await ledger.set_paused(True, actor="staff:test")
    assert await ledger.is_paused()
    with pytest.raises(TutorPaused):
        await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=1)
    await ledger.set_paused(False, actor="staff:test")
    await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=1)
    assert [(e.actor, e.action, e.details) for e in ledger.audit_log] == [
        ("staff:test", "tutor.kill_switch.set", {"paused": "True"}),
        ("staff:test", "tutor.kill_switch.set", {"paused": "False"}),
    ]


async def test_an_unsettled_reservation_expires_and_is_charged_in_full() -> None:
    clock = FakeClock()
    ledger = store(clock, reservation_ttl_s=60)
    reservation = await ledger.reserve(
        learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=400
    )
    clock.advance(seconds=59)
    assert await ledger.expire_stale() == 0
    clock.advance(seconds=2)
    assert await ledger.expire_stale() == 1
    record = ledger.records()[0]
    assert (record.status, record.spent_micro, record.outcome) == (
        "expired",
        400,
        "expired_unsettled",
    )
    # A late settlement cannot rewrite history, and the concurrency slot is free again.
    await ledger.settle(reservation, spent(1))
    assert ledger.records()[0].spent_micro == 400
    await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=10)


async def test_daily_allowance_resets_the_next_day_but_the_month_keeps_counting() -> None:
    clock = FakeClock()
    ledger = store(clock, learner_daily_micro=500, learner_monthly_micro=800)
    r = await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=500)
    await ledger.settle(r, spent(500))
    with pytest.raises(LearnerDailyLimitReached):
        await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=100)
    clock.advance(days=1)
    r = await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=300)
    await ledger.settle(r, spent(300))
    with pytest.raises(LearnerMonthlyLimitReached):
        await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=100)


async def test_a_learner_sees_only_their_own_usage() -> None:
    ledger = store()
    r = await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=400)
    await ledger.settle(r, spent(400))
    assert (await ledger.learner_usage(LEARNER_B)).day_micro == 0
    assert (await ledger.learner_usage(LEARNER_B)).day_requests == 0


async def test_one_learner_cannot_settle_anothers_reservation() -> None:
    from dataclasses import replace

    ledger = store()
    reservation = await ledger.reserve(
        learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=400
    )
    await ledger.settle(replace(reservation, learner_id=LEARNER_B), spent(0))
    assert ledger.records()[0].status == "reserved"


async def test_erasing_a_learner_removes_their_rows_but_not_the_money_spent() -> None:
    ledger = store()
    r = await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=400)
    await ledger.settle(r, spent(250))
    await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=100)
    other = await ledger.reserve(learner_id=LEARNER_B, request_key=uuid.uuid4(), estimate_micro=50)
    await ledger.settle(other, spent(50))

    assert await ledger.erase_learner(LEARNER_A, actor="erasure-job") == 2
    assert {r.learner_id for r in ledger.records()} == {LEARNER_B}
    assert (await ledger.learner_usage(LEARNER_A)).month_micro == 0
    month = ledger.policy.periods(FakeClock().now)[1]
    assert ledger.global_totals(month) == (250 + 100 + 50, 0)  # in-flight hold became spend
    assert ledger.audit_log[-1].action == "tutor.learner.erase"
    assert str(LEARNER_A) not in repr(ledger.audit_log)


async def test_retention_purges_only_finished_rows_older_than_the_cutoff() -> None:
    clock = FakeClock()
    ledger = store(clock, max_concurrent_per_learner=5, reservation_ttl_s=10**7)
    old = await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=10)
    await ledger.settle(old, spent(10))
    await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=10)
    clock.advance(days=40)
    recent = await ledger.reserve(learner_id=LEARNER_A, request_key=uuid.uuid4(), estimate_micro=10)
    await ledger.settle(recent, spent(10))
    assert await ledger.purge_older_than(clock.now - timedelta(days=30), actor="retention-job") == 1
    assert sorted(r.status for r in ledger.records()) == ["reserved", "settled"]


def test_every_refusal_is_a_typed_tutor_error_with_a_stable_code() -> None:
    codes = {
        TutorPaused: "tutor_paused",
        LearnerDailyLimitReached: "tutor_daily_limit_reached",
        LearnerMonthlyLimitReached: "tutor_monthly_limit_reached",
        GlobalBudgetExhausted: "tutor_budget_exhausted",
        TooManyConcurrentRequests: "tutor_too_many_requests",
        TutorBusy: "tutor_busy",
        DuplicateRequest: "tutor_duplicate_request",
        RequestInProgress: "tutor_request_in_progress",
    }
    for error, code in codes.items():
        assert issubclass(error, TutorError) and error.code == code


def test_nonsense_policies_are_refused_at_wiring_time() -> None:
    with pytest.raises(ValueError):
        policy(max_concurrent_per_learner=0)
    with pytest.raises(ValueError):
        policy(global_monthly_micro=-1)
    with pytest.raises(Exception):  # noqa: B017 - zoneinfo raises its own error type
        BudgetPolicy(1, 1, 1, 1, timezone="Mars/Olympus")
