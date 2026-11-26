"""PostgreSQL ``UsageStore`` over the ``tutor`` schema.

The schema is a PROPOSAL (``docs/jude-01/sql/tutor_schema.sql``): it is not in
``supabase/migrations`` and is not applied anywhere. This class is exercised
only by ``tests/tutor_pg`` against a throwaway database.

All decisions are made inside the database functions, in one transaction each,
under row locks — that is where the atomicity of the budget comes from. This
class only calls them, translates outcome codes into typed errors, and hands
the result of every settlement and release back to the caller. Every
call runs in ``Database.transaction(learner_id)``, so the functions see the
learner through ``app.current_actor_id()`` and cannot be pointed at another
learner's rows by a parameter.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from typing import cast

from sqlalchemy import text

from edu_api.db.session import Database
from edu_api.tutor.budget import (
    LearnerUsage,
    ReleaseResult,
    Reservation,
    SettleResult,
    UsageOutcome,
)
from edu_api.tutor.errors import (
    DuplicateRequest,
    GlobalBudgetExhausted,
    LearnerDailyLimitReached,
    LearnerMonthlyLimitReached,
    RequestInProgress,
    ReservationLost,
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
_AUTHORIZE = text("SELECT tutor.authorize_dispatch(:reservation_id)")
_SETTLE = text(
    "SELECT tutor.settle(:reservation_id, :spent_micro, :input_tokens, :output_tokens, "
    ":attempts, :outcome, :counts_as_request, :provider, :model, :price_version, "
    ":prompt_version, :lesson_revision_id, :unmetered_attempts, :bound_violations, "
    "CAST(:charges AS jsonb))"
)
_RELEASE = text("SELECT tutor.release(:reservation_id, :outcome, :refused_attempts)")
_SETTLE_RESULTS = frozenset({"settled", "late_overage", "already_finished", "not_found"})
_RELEASE_RESULTS = frozenset({"released", "already_finished", "not_found", "dispatch_mismatch"})
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

    async def authorize_dispatch(self, reservation: Reservation) -> None:
        async with self._database.transaction(reservation.learner_id) as conn:
            verdict = (
                await conn.execute(_AUTHORIZE, {"reservation_id": reservation.id})
            ).scalar_one()
        if verdict == "authorized":
            return
        if verdict == "paused":
            raise TutorPaused()
        # "not_active", or anything this code does not know: no call may start.
        raise ReservationLost(str(verdict))

    async def settle(self, reservation: Reservation, outcome: UsageOutcome) -> SettleResult:
        async with self._database.transaction(reservation.learner_id) as conn:
            result = (
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
                        "unmetered_attempts": outcome.unmetered_attempts,
                        "bound_violations": outcome.bound_violations,
                        "charges": json.dumps([asdict(charge) for charge in outcome.charges]),
                    },
                )
            ).scalar_one()
        if result not in _SETTLE_RESULTS:
            raise TutorError(f"unexpected settlement result: {result}")
        return cast(SettleResult, result)

    async def release(
        self, reservation: Reservation, *, outcome: str, refused_attempts: int = 0
    ) -> ReleaseResult:
        async with self._database.transaction(reservation.learner_id) as conn:
            result = (
                await conn.execute(
                    _RELEASE,
                    {
                        "reservation_id": reservation.id,
                        "outcome": outcome,
                        "refused_attempts": refused_attempts,
                    },
                )
            ).scalar_one()
        if result not in _RELEASE_RESULTS:
            raise TutorError(f"unexpected release result: {result}")
        return cast(ReleaseResult, result)

    async def learner_usage(self, learner_id: uuid.UUID) -> LearnerUsage:
        async with self._database.transaction(learner_id, read_only=True) as conn:
            row = (await conn.execute(_USAGE)).one()
        return LearnerUsage(
            day_requests=row.day_requests,
            day_micro=row.day_micro,
            month_micro=row.month_micro,
            daily_requests_limit=row.daily_requests_limit,
        )
