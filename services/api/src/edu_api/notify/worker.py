"""One delivery pass: claim due deliveries, hand them to an adapter, report back.

This is a library function, NOT a running process: nothing in the API imports
or schedules it. A worker process (staff lane, "B2") will call ``deliver_due``
on a timer with the dummy adapter until a real channel is approved.

THE WORKER ROLE
---------------
``notify.claim_due``, ``notify.recheck_lease`` and ``notify.record_attempt`` are
executable by the ``edu_worker`` database role (migrations 20261124080200 and
20261125000100) and by nobody else but the owner. ``SqlOutboxPort`` takes whatever
engine it is given: production code passes the ``edu_worker`` engine, tests do too
(``worker_engine`` in ``tests/notify_fixtures.py``).

LEASES
------
Claimed rows share one lease but are attempted one after another. Before each
attempt the pass (1) skips a row whose remaining lease is shorter than the adapter
timeout, and (2) asks ``recheck_lease`` whether the lease is still held and quiet
hours have not begun in the meantime. A skipped row is simply left to its lease:
the next claim records ``lease_lost`` and retries it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from edu_api.notify.adapter import (
    ClaimedDelivery,
    ContentNotAllowed,
    DeliveryAdapter,
    DeliveryResult,
    ErrorCode,
    Outcome,
    build_push_payload,
)

logger = logging.getLogger("edu_api.notify")

_CLAIM = text(
    "SELECT outbox_id, channel, lease_token, attempt_no, recipient_id, kind, refs "
    "FROM notify.claim_due(:channel, :row_limit, :lease_seconds)"
)
_RECHECK = text("SELECT notify.recheck_lease(:outbox_id, :channel, :lease_token)")
_RECORD = text(
    "SELECT notify.record_attempt(:outbox_id, :channel, :lease_token, :outcome, :error_code)"
)


class OutboxPort(Protocol):
    async def claim_due(
        self, channel: str, *, limit: int, lease_seconds: int
    ) -> list[ClaimedDelivery]: ...

    async def recheck_lease(self, delivery: ClaimedDelivery) -> str:
        """``send``, ``deferred`` (quiet hours began; nothing may be sent) or ``stale``."""
        ...

    async def record_attempt(
        self, delivery: ClaimedDelivery, outcome: Outcome, error_code: ErrorCode | None
    ) -> str: ...


class SqlOutboxPort:
    """Talks to the ``notify`` functions. Each call is its own transaction, so a
    lease is committed before delivery starts and survives a crash of this process."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def claim_due(
        self, channel: str, *, limit: int, lease_seconds: int
    ) -> list[ClaimedDelivery]:
        async with self._engine.begin() as conn:
            rows = (
                await conn.execute(
                    _CLAIM,
                    {"channel": channel, "row_limit": limit, "lease_seconds": lease_seconds},
                )
            ).all()
        return [
            ClaimedDelivery(
                outbox_id=row.outbox_id,
                channel=row.channel,
                lease_token=row.lease_token,
                attempt_no=row.attempt_no,
                recipient_id=row.recipient_id,
                kind=row.kind,
                refs=dict(row.refs),
            )
            for row in rows
        ]

    async def recheck_lease(self, delivery: ClaimedDelivery) -> str:
        async with self._engine.begin() as conn:
            answer = (
                await conn.execute(
                    _RECHECK,
                    {
                        "outbox_id": delivery.outbox_id,
                        "channel": delivery.channel,
                        "lease_token": delivery.lease_token,
                    },
                )
            ).scalar_one()
        return str(answer)

    async def record_attempt(
        self, delivery: ClaimedDelivery, outcome: Outcome, error_code: ErrorCode | None
    ) -> str:
        async with self._engine.begin() as conn:
            state = (
                await conn.execute(
                    _RECORD,
                    {
                        "outbox_id": delivery.outbox_id,
                        "channel": delivery.channel,
                        "lease_token": delivery.lease_token,
                        "outcome": outcome,
                        "error_code": error_code,
                    },
                )
            ).scalar_one()
        return str(state)


@dataclass
class DeliveryRunSummary:
    claimed: int = 0
    delivered: int = 0
    retried: int = 0
    failed: int = 0
    stale: int = 0
    #: Not attempted: too little lease left, or quiet hours began after the claim.
    skipped: int = 0


async def _attempt(
    adapter: DeliveryAdapter, delivery: ClaimedDelivery, timeout_s: float
) -> DeliveryResult:
    try:
        payload = build_push_payload(delivery)
    except ContentNotAllowed:
        # Cannot happen while the table constraint holds; if it ever does, never send.
        return DeliveryResult("failed", "rejected")
    try:
        async with asyncio.timeout(timeout_s):
            return await adapter.deliver(delivery.recipient_id, payload)
    except TimeoutError:
        return DeliveryResult("retry", "timeout")
    except ContentNotAllowed:
        return DeliveryResult("failed", "rejected")
    except Exception as exc:  # an adapter bug must not lose the delivery: retry later
        logger.warning("delivery adapter failed: %s", type(exc).__name__)
        return DeliveryResult("retry", "adapter_error")


async def deliver_due(
    port: OutboxPort,
    adapter: DeliveryAdapter,
    *,
    limit: int = 20,
    lease_seconds: int = 60,
    clock: Callable[[], float] = time.monotonic,
) -> DeliveryRunSummary:
    """Claim up to ``limit`` due deliveries for the adapter's channel and attempt each once.

    Delivery is at-least-once: if this process dies after the adapter succeeded
    but before the report is stored, the lease runs out and another pass tries
    again. The payload carries the notification id so a device can drop a repeat.

    The claimed rows share one lease but are attempted one after another, so
    before each attempt: a row with less lease left than the adapter timeout is
    skipped (its lease runs out and the next claim retries it; attempting it could
    overlap another worker's attempt), and ``recheck_lease`` confirms the lease is
    still held and that quiet hours have not begun since the claim.
    """
    summary = DeliveryRunSummary()
    # Leave time to report before the lease runs out.
    timeout_s = max(1.0, lease_seconds / 2)
    # Measured from BEFORE the claim: the lease starts inside the claim call, so this
    # can only under-estimate the time that is left.
    claimed_at = clock()
    claimed = await port.claim_due(adapter.channel, limit=limit, lease_seconds=lease_seconds)
    summary.claimed = len(claimed)
    for delivery in claimed:
        if lease_seconds - (clock() - claimed_at) < timeout_s:
            summary.skipped += 1
            continue
        verdict = await port.recheck_lease(delivery)
        if verdict != "send":
            if verdict == "deferred":
                summary.skipped += 1
            else:
                summary.stale += 1
            continue
        result = await _attempt(adapter, delivery, timeout_s)
        state = await port.record_attempt(delivery, result.outcome, result.error_code)
        if state == "delivered":
            summary.delivered += 1
        elif state == "pending":
            summary.retried += 1
        elif state == "failed":
            summary.failed += 1
        else:
            summary.stale += 1
        logger.info(
            "notification delivery attempt: kind=%s attempt=%d state=%s",
            delivery.kind,
            delivery.attempt_no,
            state,
        )
    return summary
