"""Accounting invariants over the suite's freshly-created UUID-named database."""

import asyncio
import contextlib
import uuid
from dataclasses import replace

import pytest

from edu_api.tutor.factory import build_tutor_service
from edu_api.tutor.providers.base import TokenUsage
from edu_api.tutor.providers.mock import DeterministicMockProvider
from tests.tutor_pg.test_budget_postgres import A, global_totals, spent
from tests.unit.tutor.conftest import ask, build_harness


async def test_each_admitted_attempt_has_a_fresh_lease(store) -> None:
    key = uuid.uuid4()
    first = await store.reserve(learner_id=A, request_key=key, estimate_micro=8)
    await store.release(first, outcome="unsent")
    second = await store.reserve(learner_id=A, request_key=key, estimate_micro=8)
    assert first.id != second.id, "a completed lease must not identify later work"


async def test_sweep_and_settlement_reconcile_once(store, owner) -> None:
    hold = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=8)
    await owner.execute("UPDATE tutor.usage_requests SET expires_at = now() - interval '1 second'")
    await asyncio.gather(
        store.settle(hold, spent(5)), owner.fetchval("SELECT tutor.expire_stale()")
    )
    status, charge = await owner.fetchrow("SELECT status, spent_micro FROM tutor.usage_requests")
    assert (status, charge) in (("settled", 5), ("expired", 8))
    assert await global_totals(owner) == (charge, 0)


async def test_normal_provider_framing_fits_the_admitted_ceiling(store, owner) -> None:
    # A synthetic tariff charges one micro per input token. The fake reports
    # ordinary message usage plus one framing token; there is no live tokenizer.
    from edu_api.tutor.config import PriceEntry
    from edu_api.tutor.providers.mock import MOCK_MODEL

    settings = dict(
        max_attempts=1,
        prices=(
            PriceEntry(
                price_version="fixture",
                model=MOCK_MODEL,
                input_micro_per_mtok=1_000_000,
                output_micro_per_mtok=0,
            ),
        ),
    )
    control = build_harness(**settings)
    await control.service.answer(A, ask())
    admitted = control.usage.records()[0].reserved_micro
    await owner.execute(
        "UPDATE tutor.policy SET global_monthly_micro=$1, learner_monthly_micro=$1, learner_daily_micro=$1",
        admitted,
    )

    class FramedMock(DeterministicMockProvider):
        async def complete(self, request):
            result = await super().complete(request)
            usage = TokenUsage(result.usage.input_tokens + 1, result.usage.output_tokens)
            return replace(result, usage=usage)

    service = build_tutor_service(
        control.settings,
        lessons=control.lessons,
        usage=store,
        consent=control.consent,
        entitlements=control.entitlements,
        provider=FramedMock(),
    )
    await service.answer(A, ask())
    paid, held = await global_totals(owner)
    assert paid + held <= admitted


async def test_pause_stops_new_provider_attempts_during_backoff(store, owner) -> None:
    from edu_api.tutor.errors import TutorError
    from tests.unit.tutor.conftest import LEARNER_A

    harness = build_harness()
    provider = DeterministicMockProvider(script=("unavailable", "ok"))

    async def pause_during_wait(_seconds):
        await owner.fetchval("SELECT tutor.set_paused(true, NULL)")

    await owner.execute(
        "UPDATE tutor.policy SET learner_daily_micro=20000, learner_monthly_micro=20000"
    )
    service = build_tutor_service(
        harness.settings,
        lessons=harness.lessons,
        usage=store,
        consent=harness.consent,
        entitlements=harness.entitlements,
        provider=provider,
        retry_sleep=pause_during_wait,
    )
    with contextlib.suppress(TutorError):
        await service.answer(LEARNER_A, ask())
    assert await store.is_paused()
    assert len(provider.calls) == 1, "no new dispatch should begin after an emergency pause"


async def test_integer_boundary_fails_closed_without_losing_the_existing_hold(store, owner):
    from sqlalchemy.exc import DBAPIError

    from edu_api.tutor.errors import TutorError

    await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=7)
    before = await global_totals(owner)
    with pytest.raises((TutorError, DBAPIError)):
        await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=2**63 - 1)
    assert await global_totals(owner) == before
    assert (await store.learner_usage(A)).day_requests == 1


async def test_erasure_and_late_settlement_do_not_recreate_an_erased_account(store, owner):
    hold = await store.reserve(learner_id=A, request_key=uuid.uuid4(), estimate_micro=8)
    await owner.fetchval("SELECT tutor.erase_learner($1, NULL)", A)
    await store.settle(hold, spent(5))
    assert (
        await owner.fetchval("SELECT count(*) FROM tutor.usage_requests WHERE learner_id=$1", A)
        == 0
    )
    assert (
        await owner.fetchval("SELECT count(*) FROM tutor.budget_counters WHERE learner_id=$1", A)
        == 0
    )
    assert await global_totals(owner) == (8, 0)
