"""Usage accounting and spending limits.

MONEY IS INTEGERS
-----------------
All amounts are micro-USD (millionths of a US dollar) in ``int``. No floats.

RESERVE, AUTHORISE, CALL, SETTLE
--------------------------------
1. ``reserve``: before anything is sent, hold the most the request is ASSUMED
   to be able to cost (every allowed call, at the token bound of
   ``edu_api.tutor.metering``). The hold is refused unless, counting what is
   already spent and what other in-flight requests hold, every limit still fits.
   Each admission gets a NEW reservation id; a retry of the same idempotency key
   after a release is a different reservation.
2. ``authorize_dispatch``: immediately before EVERY provider call. It refuses
   when the kill switch is on or the hold is no longer active, and counts the
   dispatch on the hold. This is where a pause takes effect for work in flight.
3. the provider call.
4. ``settle`` at the real cost, exactly once — or ``release`` when no billable
   provider operation happened. A hold nobody finishes *expires* and is charged
   in full, because the provider may have billed for it.

Invariant every ``UsageStore`` keeps under concurrency, AS LONG AS no provider
bills more than the hold assumed:

    spent + reserved <= limit        for the global ceiling and each learner

A provider that reports more than the bound is not capped to keep that true.
The real figure is recorded, the difference is kept as ``overage_micro``, an
audit entry is written and the kill switch is turned on (reason
``cost_bound_exceeded``) so nothing else is dispatched until staff look.
This ledger is an admission control. It is not a guarantee about a third
party's invoice; for a live provider the hard ceiling is a limit enforced on
the provider's side.

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
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from edu_api.tutor.errors import (
    DuplicateRequest,
    GlobalBudgetExhausted,
    LearnerDailyLimitReached,
    LearnerMonthlyLimitReached,
    RequestInProgress,
    ReservationLost,
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

#: What a finalizer did. Anything but the first value of each line means the
#: reservation was NOT changed by this call (it was finished already, belongs to
#: nobody, or the call contradicted the recorded dispatches).
SettleResult = Literal["settled", "late_overage", "already_finished", "not_found"]
ReleaseResult = Literal["released", "already_finished", "not_found", "dispatch_mismatch"]

#: Why the store paused itself.
PAUSE_COST_BOUND_EXCEEDED = "cost_bound_exceeded"


@dataclass(frozen=True)
class Reservation:
    """One ADMITTED attempt at a request.

    ``request_key`` is the client's logical idempotency key and may be admitted
    again after a release. ``id`` identifies this admission only and is never
    reused: settling or releasing an old ``id`` cannot touch a newer admission.
    """

    id: uuid.UUID
    learner_id: uuid.UUID
    request_key: uuid.UUID
    reserved_micro: int
    expires_at: datetime


@dataclass(frozen=True)
class AttemptCharge:
    """What ONE provider call cost, with the price it was charged at."""

    provider: str
    model: str
    price_version: str
    #: A stable code (``ok``, ``output_rejected``, ``timeout`` ...).
    outcome: str
    #: False when the provider gave no usable figures and the bound was charged.
    metered: bool
    input_tokens: int
    output_tokens: int
    cost_micro: int
    #: The provider reported more tokens than the server assumed possible.
    over_bound: bool = False


@dataclass(frozen=True)
class UsageOutcome:
    """What a request finally cost. Operational metadata only."""

    spent_micro: int
    input_tokens: int
    output_tokens: int
    #: Provider calls that were dispatched (billable or refused by the provider).
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
    #: Calls charged at the bound because the provider reported no usable usage.
    unmetered_attempts: int = 0
    #: Calls whose reported usage was above the bound the hold was sized with.
    bound_violations: int = 0
    #: One entry per billable call, so differently priced calls can be re-costed.
    charges: tuple[AttemptCharge, ...] = ()

    def __post_init__(self) -> None:
        if self.spent_micro < 0:
            raise ValueError("spent_micro cannot be negative")
        if self.charges and sum(c.cost_micro for c in self.charges) != self.spent_micro:
            raise ValueError("spent_micro must equal the sum of the attempt charges")


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

    async def authorize_dispatch(self, reservation: Reservation) -> None:
        """Permit ONE provider call for this hold and count it, or refuse.

        Raises ``TutorPaused`` when the kill switch is on and ``ReservationLost``
        when the hold is no longer active. Called before every call, the first
        included. A pause is effective for every authorisation decided after it.
        """
        ...

    async def settle(self, reservation: Reservation, outcome: UsageOutcome) -> SettleResult:
        """Record the real cost exactly once. Settling twice changes nothing.

        The amount is never reduced to fit the hold. An amount above the hold,
        or any ``bound_violations``, is recorded as it is and pauses the tutor.
        """
        ...

    async def release(
        self, reservation: Reservation, *, outcome: str, refused_attempts: int = 0
    ) -> ReleaseResult:
        """Give the hold back: NO billable provider operation happened.

        ``refused_attempts`` is how many dispatches the provider refused before
        doing any work. It must equal the dispatches authorised for this hold;
        otherwise a call is unaccounted for, nothing is released
        (``dispatch_mismatch``) and the hold is left to expire at its full amount.
        """
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
    #: Provider calls authorised for this hold.
    dispatches: int = 0
    unmetered_attempts: int = 0
    bound_violations: int = 0
    #: ``spent_micro - reserved_micro`` when the provider billed above the hold.
    overage_micro: int = 0
    charges: tuple[AttemptCharge, ...] = ()


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
        self.pause_reason: str | None = None
        self._lock = asyncio.Lock()
        #: Every admission ever made, by reservation id (released ones included).
        self._records: dict[uuid.UUID, UsageRecord] = {}
        #: The one admission of a key that is not released, if there is one.
        self._current: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID] = {}
        self._global: dict[date, _Counter] = {}
        self._learner_day: dict[tuple[uuid.UUID, date], _Counter] = {}
        self._learner_month: dict[tuple[uuid.UUID, date], _Counter] = {}
        self.audit_log: list[AuditEntry] = []

    # -- privileged operations (audited) -------------------------------------------------
    async def set_paused(self, paused: bool, *, actor: str) -> None:
        async with self._lock:
            self._paused = paused
            self.pause_reason = None
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
            ids = [i for i, r in self._records.items() if r.learner_id == learner_id]
            for record_id in ids:
                record = self._records.pop(record_id)
                if record.status == "reserved":
                    # The hold becomes anonymous spend so the ceiling stays safe.
                    counter = self._global.setdefault(record.month, _Counter())
                    counter.reserved -= record.reserved_micro
                    counter.spent += record.reserved_micro
            for key in [k for k in self._current if k[0] == learner_id]:
                del self._current[key]
            for store in (self._learner_day, self._learner_month):
                for counter_key in [k for k in store if k[0] == learner_id]:
                    del store[counter_key]
            self.audit_log.append(AuditEntry(actor, "tutor.learner.erase", self._clock()))
            return len(ids)

    async def purge_older_than(self, cutoff: datetime, *, actor: str) -> int:
        """Retention: drop finished ledger rows created before ``cutoff``."""
        async with self._lock:
            ids = [
                i
                for i, r in self._records.items()
                if r.status != "reserved" and r.created_at < cutoff
            ]
            for record_id in ids:
                record = self._records.pop(record_id)
                key = (record.learner_id, record.request_key)
                if self._current.get(key) == record_id:
                    del self._current[key]
            self.audit_log.append(AuditEntry(actor, "tutor.usage.purge", self._clock()))
            return len(ids)

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
            current = self._records.get(
                self._current.get((learner_id, request_key), uuid.UUID(int=0))
            )
            if current is not None:
                if current.status == "reserved":
                    raise RequestInProgress()
                # settled or expired: this key was answered or charged once already.
                raise DuplicateRequest()
            # No current admission (never asked, or released with nothing spent):
            # the key may be admitted, as a NEW reservation.
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
            self._records[record.id] = record
            self._current[(learner_id, request_key)] = record.id
            for counter in (learner_day, learner_month, world):
                counter.reserved += estimate_micro
            # The request is counted while it is in flight, so parallel requests
            # cannot all slip under the daily number.
            learner_day.requests += 1
            return Reservation(
                record.id, learner_id, request_key, estimate_micro, record.expires_at
            )

    async def authorize_dispatch(self, reservation: Reservation) -> None:
        async with self._lock:
            self._expire_locked(self._clock())
            record = self._owned(reservation)
            if record is None or record.status != "reserved":
                raise ReservationLost()
            if self._paused:
                raise TutorPaused()
            record.dispatches += 1

    async def settle(self, reservation: Reservation, outcome: UsageOutcome) -> SettleResult:
        async with self._lock:
            record = self._owned(reservation)
            if record is None:
                return "not_found"
            if record.status == "expired" and outcome.spent_micro > record.spent_micro:
                # The hold ran out and was charged in full; the real figure, known
                # only now, is higher. Charge the difference: never the smaller number.
                self._add_spend_locked(record, outcome.spent_micro - record.spent_micro)
                self._describe(record, outcome)
                self._trip_locked(record)
                return "late_overage"
            if record.status != "reserved":
                return "already_finished"  # accounted exactly once
            self._finish_locked(
                record, "settled", outcome.spent_micro, counts=outcome.counts_as_request
            )
            self._describe(record, outcome)
            if record.overage_micro > 0 or outcome.bound_violations > 0:
                self._trip_locked(record)
            return "settled"

    async def release(
        self, reservation: Reservation, *, outcome: str, refused_attempts: int = 0
    ) -> ReleaseResult:
        async with self._lock:
            record = self._owned(reservation)
            if record is None:
                return "not_found"
            if record.status != "reserved":
                return "already_finished"
            if record.dispatches != refused_attempts:
                # A dispatch nobody accounted for may have been billed: keep the hold.
                return "dispatch_mismatch"
            self._finish_locked(record, "released", 0, counts=False)
            record.outcome = outcome
            record.attempts = refused_attempts
            del self._current[(record.learner_id, record.request_key)]
            return "released"

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
        record = self._records.get(reservation.id)
        if record is None or record.learner_id != reservation.learner_id:
            return None
        return record

    def _counters(self, record: UsageRecord) -> tuple[_Counter, _Counter, _Counter]:
        return (
            self._learner_day.setdefault((record.learner_id, record.day), _Counter()),
            self._learner_month.setdefault((record.learner_id, record.month), _Counter()),
            self._global.setdefault(record.month, _Counter()),
        )

    def _finish_locked(
        self, record: UsageRecord, status: ReservationStatus, spent: int, *, counts: bool
    ) -> None:
        learner_day, learner_month, world = self._counters(record)
        for counter in (learner_day, learner_month, world):
            counter.reserved -= record.reserved_micro
            counter.spent += spent
        if not counts:
            learner_day.requests -= 1
        record.status = status
        record.spent_micro = spent
        record.overage_micro = max(spent - record.reserved_micro, 0)

    def _add_spend_locked(self, record: UsageRecord, extra: int) -> None:
        for counter in self._counters(record):
            counter.spent += extra
        record.spent_micro += extra
        record.overage_micro = max(record.spent_micro - record.reserved_micro, 0)

    @staticmethod
    def _describe(record: UsageRecord, outcome: UsageOutcome) -> None:
        record.input_tokens = outcome.input_tokens
        record.output_tokens = outcome.output_tokens
        record.attempts = outcome.attempts
        record.outcome = outcome.outcome
        record.provider = outcome.provider
        record.model = outcome.model
        record.price_version = outcome.price_version
        record.prompt_version = outcome.prompt_version
        record.lesson_revision_id = outcome.lesson_revision_id
        record.unmetered_attempts = outcome.unmetered_attempts
        record.bound_violations = outcome.bound_violations
        record.charges = outcome.charges

    def _trip_locked(self, record: UsageRecord) -> None:
        """A provider billed beyond the assumed bound: stop all further dispatch."""
        self._paused = True
        self.pause_reason = PAUSE_COST_BOUND_EXCEEDED
        # Amounts and versions only: the entry names no learner and holds no text.
        self.audit_log.append(
            AuditEntry(
                "system",
                "tutor.cost_bound.exceeded",
                self._clock(),
                {
                    "reserved_micro": str(record.reserved_micro),
                    "spent_micro": str(record.spent_micro),
                    "overage_micro": str(record.overage_micro),
                    "bound_violations": str(record.bound_violations),
                    "model": record.model or "",
                    "price_version": record.price_version or "",
                },
            )
        )

    def _expire_locked(self, now: datetime) -> int:
        expired = 0
        for record in self._records.values():
            if record.status == "reserved" and record.expires_at <= now:
                # Unknown outcome: assume the provider billed the whole hold.
                self._finish_locked(record, "expired", record.reserved_micro, counts=True)
                record.outcome = "expired_unsettled"
                expired += 1
        return expired
