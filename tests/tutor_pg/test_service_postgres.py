"""The whole tutor pipeline with the PostgreSQL ledger instead of the in-memory one."""

from __future__ import annotations

import asyncio
import uuid

import asyncpg

from edu_api.tutor import demo_content
from edu_api.tutor.content import InMemoryLessonSource
from edu_api.tutor.errors import DuplicateRequest, TutorError
from edu_api.tutor.factory import build_tutor_service
from edu_api.tutor.governance import ConsentState, StaticConsent, StaticEntitlements
from edu_api.tutor.pg_store import PostgresUsageStore
from edu_api.tutor.providers.mock import DeterministicMockProvider
from edu_api.tutor.service import TutorService
from tests.unit.tutor.conftest import ask, make_settings, no_sleep

SECRET = "ZANMI-SEKRE-48151623"


def service_for(
    store: PostgresUsageStore, learners: list[uuid.UUID], provider: DeterministicMockProvider
) -> TutorService:
    lessons = InMemoryLessonSource()
    lessons.add(demo_content.equations_fr())
    return build_tutor_service(
        make_settings(),
        lessons=lessons,
        usage=store,
        consent=StaticConsent({learner: ConsentState.GRANTED for learner in learners}),
        entitlements=StaticEntitlements(set(learners)),
        provider=provider,
        retry_sleep=no_sleep,
    )


async def test_answer_is_accounted_once_and_no_text_reaches_the_database(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    await owner.execute(
        "UPDATE tutor.policy SET learner_daily_micro = 100000, learner_monthly_micro = 100000, "
        "global_monthly_micro = 1000000"
    )
    learner = uuid.uuid4()
    provider = DeterministicMockProvider()
    service = service_for(store, [learner], provider)
    request = ask(message=f"Pourquoi on soustrait 5 des deux côtés ? {SECRET}")
    response = await service.answer(learner, request)
    assert response.references

    try:
        await service.answer(learner, request)
    except DuplicateRequest:
        pass
    else:  # pragma: no cover
        raise AssertionError("a repeated idempotency key must be refused")
    assert len(provider.calls) == 1

    row = await owner.fetchrow("SELECT * FROM tutor.usage_requests")
    assert (row["status"], row["outcome"], row["attempts"]) == ("settled", "answered", 1)
    assert 0 < row["spent_micro"] < row["reserved_micro"]
    assert row["lesson_revision_id"] == demo_content.EQUATIONS_FR_REVISION_ID
    dump = await owner.fetchval(
        "SELECT string_agg(t::text, ' ') FROM ("
        "  SELECT to_jsonb(u) AS t FROM tutor.usage_requests u"
        "  UNION ALL SELECT to_jsonb(c) FROM tutor.budget_counters c"
        "  UNION ALL SELECT to_jsonb(a) FROM tutor.admin_audit a) all_rows"
    )
    assert SECRET not in dump and "soustrait" not in dump and "balance" not in dump


async def test_concurrent_learners_cannot_overshoot_the_ceiling_through_the_service(
    store: PostgresUsageStore, owner: asyncpg.Pool
) -> None:
    ceiling = 10_000
    await owner.execute(
        "UPDATE tutor.policy SET learner_daily_micro = 100000, learner_monthly_micro = 100000, "
        "global_monthly_micro = $1",
        ceiling,
    )
    learners = [uuid.uuid4() for _ in range(30)]
    provider = DeterministicMockProvider(gate=asyncio.Event())
    service = service_for(store, learners, provider)

    async def one(learner: uuid.UUID) -> str:
        try:
            return (await service.answer(learner, ask())).status.value
        except TutorError as exc:
            return exc.code

    tasks = [asyncio.create_task(one(learner)) for learner in learners]
    await provider.started.wait()
    await asyncio.sleep(1.0)  # let every request reach the database and reserve or be refused
    held = await owner.fetchval(
        "SELECT reserved_micro FROM tutor.budget_counters WHERE scope = 'global'"
    )
    assert 0 < held <= ceiling
    provider.gate.set()  # type: ignore[union-attr]
    results = await asyncio.gather(*tasks)

    admitted = results.count("answered")
    assert 0 < admitted < len(learners)
    assert results.count("tutor_budget_exhausted") == len(learners) - admitted
    assert len(provider.calls) == admitted  # refused requests never reached the provider
    row = await owner.fetchrow(
        "SELECT spent_micro, reserved_micro FROM tutor.budget_counters WHERE scope = 'global'"
    )
    assert row["reserved_micro"] == 0 and 0 < row["spent_micro"] <= ceiling
