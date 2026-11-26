"""Usage accounting and spending limits.

MONEY IS INTEGERS
-----------------
All amounts are micro-USD (millionths of a US dollar) in ``int``. No floats.

RESERVE, THEN CALL, THEN SETTLE
-------------------------------
Before a provider is called the service *reserves* the worst case the request
could cost (every allowed attempt, at full input and full output). The
reservation succeeds only if, counting what is already spent AND what is
currently reserved by other in-flight requests, no limit would be exceeded.
After the call the reservation is *settled* at the real cost or *released*.
A reservation nobody settles (crashed worker) *expires* and is charged at its
full reserved amount, because the provider may have billed for it.

Invariant every ``UsageStore`` must keep, at all times and under concurrency:

    spent + reserved <= limit        for the global ceiling and each learner

WHAT IS STORED
--------------
Identifiers, counters, token counts, amounts, model and prompt version, an
outcome code. No student text, no model text, no hash of either.

``InMemoryUsageStore`` is a single-process test double. It serialises with an
``asyncio.Lock`` and proves the accounting rules, NOT database atomicity.
The PostgreSQL implementation is ``edu_api.tutor.pg_store`` over
``docs/jude-01/sql/tutor_schema.sql``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from edu_api.tutor.errors import (
    DuplicateRequest,
    GlobalBudgetExhausted,
    LearnerDailyLimitReached,
    LearnerMonthlyLimitReached,
    RequestInProgress,
    TooManyConcurrentRequests,
    TutorBusy,
    TutorPaused,
)
from edu_api.tutor.providers.base import TokenUsage

MICROS_PER_USD = 1_000_000
_TOKENS_PER_PRICE_UNIT = 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    """One immutable price for one model. A price change is a NEW ``price_version``."""

    price_version: str
    model: str
    input_micro_per_mtok: int
    output_micro_per_mtok: int

    def __post_init__(self) -> None:
        if self.input_micro_per_mtok < 0 or self.output_micro_per_mtok < 0:
            raise ValueError("prices cannot be negative")

    def cost_micro(self, usage: TokenUsage) -> int:
        """Cost of ``usage``, rounded UP to a whole micro-USD per direction."""
        return _ceil_div(
            usage.input_tokens * self.input_micro_per_mtok, _TOKENS_PER_PRICE_UNIT
        ) + _ceil_div(usage.output_tokens * self.output_micro_per_mtok, _TOKENS_PER_PRICE_UNIT)


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


@dataclass(frozen=True)
class BudgetPolicy:
    """Limits. Every number is an owner decision; the defaults are placeholders for tests."""

    learner_daily_requests: int
    learner_daily_micro: int
    learner_monthly_micro: int
    global_monthly_micro: int
    max_concurrent_per_learner: int = 1
    max_concurrent_global: int = 20
    reservation_ttl_s: int = 120
    #: Days and months roll over on the learner's wall clock, not UTC.
    timezone: str = "America/Port-au-Prince"

    def __post_init__(self) -> None:
        for name in (
            "learner_daily_requests",
            "learner_daily_micro",
            "learner_monthly_micro",
            "global_monthly_micro",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.max_concurrent_per_learner < 1 or self.max_concurrent_global < 1:
            raise ValueError("concurrency limits must be at least 1")
        if self.reservation_ttl_s < 1:
            raise ValueError("reservation_ttl_s must be at least 1")
        ZoneInfo(self.timezone)  # fail at wiring time, not on the first request

    def periods(self, now: datetime) -> tuple[date, date]:
        """(day, first day of month) of ``now`` in the budget time zone."""
        local = now.astimezone(ZoneInfo(self.timezone)).date()
        return local, local.replace(day=1)


ReservationStatus = Literal["reserved", "settled", "released", "expired"]


@dataclass(frozen=True)
class Reservation:
    id: uuid.UUID
    learner_id: uuid.UUID
    request_key: uuid.UUID
    reserved_micro: int
    expires_at: datetime


@dataclass(frozen=True)
class UsageOutcome:
    """What a request finally cost. Operational metadata only."""

    spent_micro: int
    input_tokens: int
    output_tokens: int
    attempts: int
    #: A stable code: ``answered`` or a tutor error code.
    outcome: str
    #: Whether this counts against the learner's daily number of requests.
    counts_as_request: bool
    provider: str | None = None
    model: str | None = None
    price_version: str | None = None
    prompt_version: str | None = None
    lesson_revision_id: uuid.UUID | None = None


@dataclass(frozen=True)
class LearnerUsage:
    day_requests: int
    day_micro: int
    month_micro: int
    daily_requests_limit: int


class UsageStore(Protocol):
    async def is_paused(self) -> bool:
        """True when the kill switch is on."""
        ...

    async def reserve(
        self, *, learner_id: uuid.UUID, request_key: uuid.UUID, estimate_micro: int
    ) -> Reservation:
        """Atomically hold ``estimate_micro`` or raise the limit that refused it.

        Raises ``TutorPaused``, ``DuplicateRequest``, ``RequestInProgress``,
        ``TooManyConcurrentRequests``, ``TutorBusy``, ``LearnerDailyLimitReached``,
        ``LearnerMonthlyLimitReached`` or ``GlobalBudgetExhausted``.
        """
        ...

    async def settle(self, reservation: Reservation, outcome: UsageOutcome) -> None:
        """Record the real cost exactly once. Settling twice changes nothing."""
        ...

    async def release(self, reservation: Reservation, *, outcome: str) -> None:
        """Give the hold back: no provider call happened and nothing was spent."""
        ...

    async def learner_usage(self, learner_id: uuid.UUID) -> LearnerUsage:
        """The caller's own counters. There is no way to ask for someone else's."""
        ...


# ----------------------------------------------------------------------------------------
@dataclass
class _Counter:
    reserved: int = 0
    spent: int = 0
    requests: int = 0


@dataclass
class UsageRecord:
    """One row of the usage ledger. Note what is NOT here: any text."""

    id: uuid.UUID
    learner_id: uuid.UUID
    request_key: uuid.UUID
    status: ReservationStatus
    day: date
    month: date
    reserved_micro: int
    expires_at: datetime
    created_at: datetime
    spent_micro: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0
    outcome: str | None = None
    provider: str | None = None
    model: str | None = None
    price_version: str | None = None
    prompt_version: str | None = None
    lesson_revision_id: uuid.UUID | None = None


@dataclass
class AuditEntry:
    actor: str
    action: str
    at: datetime
    details: dict[str, str] = field(default_factory=dict)


class InMemoryUsageStore:
    """Deterministic single-process ``UsageStore`` for tests and the demo."""

    def __init__(
        self,
        policy: BudgetPolicy,
        *,
        clock: Callable[[], datetime],
        paused: bool = False,
    ) -> None:
        self.policy = policy
        self._clock = clock
        self._paused = paused
        self._lock = asyncio.Lock()
        self._records: dict[tuple[uuid.UUID, uuid.UUID], UsageRecord] = {}
        self._global: dict[date, _Counter] = {}
        self._learner_day: dict[tuple[uuid.UUID, date], _Counter] = {}
        self._learner_month: dict[tuple[uuid.UUID, date], _Counter] = {}
        self.audit_log: list[AuditEntry] = []

    # -- privileged operations (audited) -------------------------------------------------
    async def set_paused(self, paused: bool, *, actor: str) -> None:
        async with self._lock:
            self._paused = paused
            self.audit_log.append(
                AuditEntry(actor, "tutor.kill_switch.set", self._clock(), {"paused": str(paused)})
            )

    async def set_policy(self, policy: BudgetPolicy, *, actor: str) -> None:
        async with self._lock:
            self.policy = policy
            self.audit_log.append(AuditEntry(actor, "tutor.policy.set", self._clock()))

    async def erase_learner(self, learner_id: uuid.UUID, *, actor: str) -> int:
        """Delete everything that names this learner. Aggregate totals stay."""
        async with self._lock:
            keys = [k for k in self._records if k[0] == learner_id]
            for key in keys:
                record = self._records.pop(key)
                if record.status == "reserved":
                    # The hold becomes anonymous spend so the ceiling stays safe.
                    counter = self._global.setdefault(record.month, _Counter())
                    counter.reserved -= record.reserved_micro
                    counter.spent += record.reserved_micro
            for store in (self._learner_day, self._learner_month):
                for counter_key in [k for k in store if k[0] == learner_id]:
                    del store[counter_key]
            self.audit_log.append(AuditEntry(actor, "tutor.learner.erase", self._clock()))
            return len(keys)

    async def purge_older_than(self, cutoff: datetime, *, actor: str) -> int:
        """Retention: drop finished ledger rows created before ``cutoff``."""
        async with self._lock:
            keys = [
                k
                for k, r in self._records.items()
                if r.status != "reserved" and r.created_at < cutoff
            ]
            for key in keys:
                del self._records[key]
            self.audit_log.append(AuditEntry(actor, "tutor.usage.purge", self._clock()))
            return len(keys)

    # -- UsageStore --------------------------------------------------------------------
    async def is_paused(self) -> bool:
        return self._paused

    async def reserve(
        self, *, learner_id: uuid.UUID, request_key: uuid.UUID, estimate_micro: int
    ) -> Reservation:
        if estimate_micro < 0:
            raise ValueError("estimate_micro cannot be negative")
        async with self._lock:
            now = self._clock()
            self._expire_locked(now)
            if self._paused:
                raise TutorPaused()
            existing = self._records.get((learner_id, request_key))
            if existing is not None:
                if existing.status == "reserved":
                    raise RequestInProgress()
                if existing.status in ("settled", "expired"):
                    raise DuplicateRequest()
                # "released": nothing was spent, so the same request may try again.
            active = [r for r in self._records.values() if r.status == "reserved"]
            if sum(1 for r in active if r.learner_id == learner_id) >= (
                self.policy.max_concurrent_per_learner
            ):
                raise TooManyConcurrentRequests()
            if len(active) >= self.policy.max_concurrent_global:
                raise TutorBusy()

            day, month = self.policy.periods(now)
            learner_day = self._learner_day.setdefault((learner_id, day), _Counter())
            learner_month = self._learner_month.setdefault((learner_id, month), _Counter())
            world = self._global.setdefault(month, _Counter())
            policy = self.policy
            if learner_day.requests >= policy.learner_daily_requests:
                raise LearnerDailyLimitReached()
            if learner_day.reserved + learner_day.spent + estimate_micro > (
                policy.learner_daily_micro
            ):
                raise LearnerDailyLimitReached()
            if learner_month.reserved + learner_month.spent + estimate_micro > (
                policy.learner_monthly_micro
            ):
                raise LearnerMonthlyLimitReached()
            if world.reserved + world.spent + estimate_micro > policy.global_monthly_micro:
                raise GlobalBudgetExhausted()

            record = UsageRecord(
                id=uuid.uuid4(),
                learner_id=learner_id,
                request_key=request_key,
                status="reserved",
                day=day,
                month=month,
                reserved_micro=estimate_micro,
                expires_at=now + timedelta(seconds=policy.reservation_ttl_s),
                created_at=now,
            )
            self._records[(learner_id, request_key)] = record
            for counter in (learner_day, learner_month, world):
                counter.reserved += estimate_micro
            # The request is counted while it is in flight, so parallel requests
            # cannot all slip under the daily number.
            learner_day.requests += 1
            return Reservation(
                record.id, learner_id, request_key, estimate_micro, record.expires_at
            )

    async def settle(self, reservation: Reservation, outcome: UsageOutcome) -> None:
        if outcome.spent_micro < 0:
            raise ValueError("spent_micro cannot be negative")
        async with self._lock:
            record = self._owned(reservation)
            if record is None or record.status != "reserved":
                return  # already settled, released or expired: accounted exactly once
            self._finish_locked(
                record, "settled", outcome.spent_micro, counts=outcome.counts_as_request
            )
            self._records[(record.learner_id, record.request_key)] = replace(
                record,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                attempts=outcome.attempts,
                outcome=outcome.outcome,
                provider=outcome.provider,
                model=outcome.model,
                price_version=outcome.price_version,
                prompt_version=outcome.prompt_version,
                lesson_revision_id=outcome.lesson_revision_id,
            )

    async def release(self, reservation: Reservation, *, outcome: str) -> None:
        async with self._lock:
            record = self._owned(reservation)
            if record is None or record.status != "reserved":
                return
            self._finish_locked(record, "released", 0, counts=False)
            record.outcome = outcome

    async def learner_usage(self, learner_id: uuid.UUID) -> LearnerUsage:
        async with self._lock:
            day, month = self.policy.periods(self._clock())
            learner_day = self._learner_day.get((learner_id, day), _Counter())
            learner_month = self._learner_month.get((learner_id, month), _Counter())
            return LearnerUsage(
                day_requests=learner_day.requests,
                day_micro=learner_day.spent + learner_day.reserved,
                month_micro=learner_month.spent + learner_month.reserved,
                daily_requests_limit=self.policy.learner_daily_requests,
            )

    async def expire_stale(self) -> int:
        """Charge reservations whose time ran out. A scheduled job calls this."""
        async with self._lock:
            return self._expire_locked(self._clock())

    # -- inspection helpers for tests ------------------------------------------------------
    def records(self) -> list[UsageRecord]:
        return list(self._records.values())

    def global_totals(self, month: date) -> tuple[int, int]:
        counter = self._global.get(month, _Counter())
        return counter.spent, counter.reserved

    # -- internals -------------------------------------------------------------------------
    def _owned(self, reservation: Reservation) -> UsageRecord | None:
        record = self._records.get((reservation.learner_id, reservation.request_key))
        return record if record is not None and record.id == reservation.id else None

    def _finish_locked(
        self, record: UsageRecord, status: ReservationStatus, spent: int, *, counts: bool
    ) -> None:
        learner_day = self._learner_day.setdefault((record.learner_id, record.day), _Counter())
        learner_month = self._learner_month.setdefault(
            (record.learner_id, record.month), _Counter()
        )
        world = self._global.setdefault(record.month, _Counter())
        for counter in (learner_day, learner_month, world):
            counter.reserved -= record.reserved_micro
            counter.spent += spent
        if not counts:
            learner_day.requests -= 1
        record.status = status
        record.spent_micro = spent

    def _expire_locked(self, now: datetime) -> int:
        expired = 0
        for record in self._records.values():
            if record.status == "reserved" and record.expires_at <= now:
                # Unknown outcome: assume the provider billed the whole hold.
                self._finish_locked(record, "expired", record.reserved_micro, counts=True)
                record.outcome = "expired_unsettled"
                expired += 1
        return expired
