"""One delivery pass: claim due deliveries, hand them to an adapter, report back.

This is a library function, NOT a running process: nothing in the API imports
or schedules it. A worker process (staff lane, "B2") will call ``deliver_due``
on a timer with the dummy adapter until a real channel is approved.

SEAM(notify-worker-role)
------------------------
``notify.claim_due`` and ``notify.record_attempt`` are executable by nobody but
the database owner until the worker role exists. ``SqlOutboxPort`` therefore
takes whatever engine it is given: tests pass an owner engine (see
``tests/notify_fixtures.py``); the worker will pass its own ``edu_worker``
engine once the grant in the migration's SEAM comment is applied. No code here
changes when that happens.
"""

from __future__ import annotations

import asyncio
import logging
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
_RECORD = text(
    "SELECT notify.record_attempt(:outbox_id, :channel, :lease_token, :outcome, :error_code)"
)


class OutboxPort(Protocol):
    async def claim_due(
        self, channel: str, *, limit: int, lease_seconds: int
    ) -> list[ClaimedDelivery]: ...

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
) -> DeliveryRunSummary:
    """Claim up to ``limit`` due deliveries for the adapter's channel and attempt each once.

    Delivery is at-least-once: if this process dies after the adapter succeeded
    but before the report is stored, the lease runs out and another pass tries
    again. The payload carries the notification id so a device can drop a repeat.
    """
    summary = DeliveryRunSummary()
    # Leave time to report before the lease runs out.
    timeout_s = max(1.0, lease_seconds / 2)
    claimed = await port.claim_due(adapter.channel, limit=limit, lease_seconds=lease_seconds)
    summary.claimed = len(claimed)
    for delivery in claimed:
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
