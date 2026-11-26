"""PostgreSQL ``UsageStore`` over the ``tutor`` schema.

The schema is a PROPOSAL (``docs/jude-01/sql/tutor_schema.sql``): it is not in
``supabase/migrations`` and is not applied anywhere. This class is exercised
only by ``tests/tutor_pg`` against a throwaway database.

All decisions are made inside the database functions, in one transaction each,
under row locks — that is where the atomicity of the budget comes from. This
class only calls them and translates outcome codes into typed errors. Every
call runs in ``Database.transaction(learner_id)``, so the functions see the
learner through ``app.current_actor_id()`` and cannot be pointed at another
learner's rows by a parameter.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from edu_api.db.session import Database
from edu_api.tutor.budget import LearnerUsage, Reservation, UsageOutcome
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

_REFUSALS: dict[str, type[TutorError]] = {
    "paused": TutorPaused,
    "duplicate": DuplicateRequest,
    "in_progress": RequestInProgress,
    "learner_concurrency": TooManyConcurrentRequests,
    "global_concurrency": TutorBusy,
    "learner_daily_requests": LearnerDailyLimitReached,
    "learner_daily_budget": LearnerDailyLimitReached,
    "learner_monthly_budget": LearnerMonthlyLimitReached,
    "global_budget": GlobalBudgetExhausted,
}

_IS_PAUSED = text("SELECT tutor.is_paused()")
_RESERVE = text(
    "SELECT outcome, reservation_id, reserved_micro, expires_at "
    "FROM tutor.reserve(:request_key, :estimate_micro)"
)
_SETTLE = text(
    "SELECT tutor.settle(:reservation_id, :spent_micro, :input_tokens, :output_tokens, "
    ":attempts, :outcome, :counts_as_request, :provider, :model, :price_version, "
    ":prompt_version, :lesson_revision_id)"
)
_RELEASE = text("SELECT tutor.release(:reservation_id, :outcome)")
_USAGE = text(
    "SELECT day_requests, day_micro, month_micro, daily_requests_limit FROM tutor.my_usage()"
)


class PostgresUsageStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def is_paused(self) -> bool:
        async with self._database.transaction(None, read_only=True) as conn:
            return bool((await conn.execute(_IS_PAUSED)).scalar_one())

    async def reserve(
        self, *, learner_id: uuid.UUID, request_key: uuid.UUID, estimate_micro: int
    ) -> Reservation:
        async with self._database.transaction(learner_id) as conn:
            row = (
                await conn.execute(
                    _RESERVE, {"request_key": request_key, "estimate_micro": estimate_micro}
                )
            ).one()
        if row.outcome != "reserved":
            raise _REFUSALS.get(row.outcome, TutorError)(row.outcome)
        return Reservation(
            id=row.reservation_id,
            learner_id=learner_id,
            request_key=request_key,
            reserved_micro=row.reserved_micro,
            expires_at=row.expires_at,
        )

    async def settle(self, reservation: Reservation, outcome: UsageOutcome) -> None:
        async with self._database.transaction(reservation.learner_id) as conn:
            await conn.execute(
                _SETTLE,
                {
                    "reservation_id": reservation.id,
                    "spent_micro": outcome.spent_micro,
                    "input_tokens": outcome.input_tokens,
                    "output_tokens": outcome.output_tokens,
                    "attempts": outcome.attempts,
                    "outcome": outcome.outcome,
                    "counts_as_request": outcome.counts_as_request,
                    "provider": outcome.provider,
                    "model": outcome.model,
                    "price_version": outcome.price_version,
                    "prompt_version": outcome.prompt_version,
                    "lesson_revision_id": outcome.lesson_revision_id,
                },
            )

    async def release(self, reservation: Reservation, *, outcome: str) -> None:
        async with self._database.transaction(reservation.learner_id) as conn:
            await conn.execute(_RELEASE, {"reservation_id": reservation.id, "outcome": outcome})

    async def learner_usage(self, learner_id: uuid.UUID) -> LearnerUsage:
        async with self._database.transaction(learner_id, read_only=True) as conn:
            row = (await conn.execute(_USAGE)).one()
        return LearnerUsage(
            day_requests=row.day_requests,
            day_micro=row.day_micro,
            month_micro=row.month_micro,
            daily_requests_limit=row.daily_requests_limit,
        )
