"""The single rewards step in the push path.

Runs inside the push transaction, right after ``app.sync_apply_operation``
accepted an operation, and inside a SAVEPOINT of its own:

* success  -> the Gold rows commit atomically with the learning operation;
* deferred -> the learner's rewards lock was busy. The SQL function waits at
  most ~200 ms for it and never raises for that reason;
* failure  -> only the savepoint is rolled back.

In the last two cases the learning operation still commits, the push response
is unchanged, one structured log line is written, and reconciliation awards
the operation later. **The rest of the batch then skips the reward step**: the
push transaction is holding the learner's sync lock, so one slow or failing
award must not be repeated for every remaining operation.

Replays of an accepted operation are passed through too: the SQL function is
idempotent (it repeats its recorded decision), and this heals an operation
whose first award attempt failed as soon as the phone retries.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger("edu_api.rewards")

_AWARD = text("SELECT rewards.award_for_operation(:op_id) AS outcome")

AwardHook = Callable[[AsyncConnection, uuid.UUID, uuid.UUID], Awaitable[None]]


def batch_award_hook() -> AwardHook:
    """A fresh hook for ONE push batch (it remembers that the batch gave up)."""
    gave_up = False

    async def award_after_accept(
        conn: AsyncConnection, learner_id: uuid.UUID, op_id: uuid.UUID
    ) -> None:
        nonlocal gave_up
        if gave_up:
            return
        try:
            async with conn.begin_nested():
                outcome = (await conn.execute(_AWARD, {"op_id": op_id})).scalar_one()
        except Exception as exc:
            gave_up = True
            # Never the exception text: driver messages may carry SQL or values.
            logger.error(
                "rewards_award_failed learner=%s op_id=%s error=%s sqlstate=%s "
                "action=skip_rest_of_batch_reconcile_later",
                learner_id,
                op_id,
                type(exc).__name__,
                getattr(getattr(exc, "orig", None), "sqlstate", None),
            )
            return
        if outcome.get("status") == "deferred":
            gave_up = True
            logger.warning(
                "rewards_award_deferred learner=%s op_id=%s reason=learner_lock_busy "
                "action=skip_rest_of_batch_reconcile_later",
                learner_id,
                op_id,
            )

    return award_after_accept
