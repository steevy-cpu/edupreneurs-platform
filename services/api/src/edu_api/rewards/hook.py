"""The single rewards step in the push path.

Runs inside the push transaction, right after ``app.sync_apply_operation``
accepted an operation, and inside a SAVEPOINT of its own:

* success  -> the Gold rows commit atomically with the learning operation;
* deferred -> the learner's rewards lock was busy. The SQL function waits at
  most ~200 ms for it and never raises for that reason;
* any other blocking (a DDL lock on a rewards table, a row lock on the
  balance, a slow query) is cut short by a SHORT ``lock_timeout`` and
  ``statement_timeout`` that apply only inside the savepoint; the caller's own
  values are restored afterwards on every path, so the rest of the push keeps
  its normal limits;
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
_READ_TIMEOUTS = text(
    "SELECT current_setting('lock_timeout') AS lock_timeout, "
    "current_setting('statement_timeout') AS statement_timeout"
)
# set_config(..., true) = SET LOCAL: transaction scoped, parameters bound.
_SET_TIMEOUTS = text(
    "SELECT set_config('lock_timeout', :lock_timeout, true), "
    "set_config('statement_timeout', :statement_timeout, true)"
)

#: Defaults mirror Settings.rewards_hook_*_timeout_ms.
DEFAULT_LOCK_TIMEOUT_MS = 250
DEFAULT_STATEMENT_TIMEOUT_MS = 500

AwardHook = Callable[[AsyncConnection, uuid.UUID, uuid.UUID], Awaitable[None]]


def batch_award_hook(
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> AwardHook:
    """A fresh hook for ONE push batch (it remembers that the batch gave up)."""
    gave_up = False
    short = {
        "lock_timeout": f"{int(lock_timeout_ms)}ms",
        "statement_timeout": f"{int(statement_timeout_ms)}ms",
    }

    async def award_after_accept(
        conn: AsyncConnection, learner_id: uuid.UUID, op_id: uuid.UUID
    ) -> None:
        nonlocal gave_up
        if gave_up:
            return
        # The caller's limits, read before anything is changed. SET LOCAL inside a
        # savepoint survives RELEASE, so they are put back explicitly below.
        previous = (await conn.execute(_READ_TIMEOUTS)).mappings().one()
        restore = {k: str(previous[k]) for k in short}
        try:
            try:
                async with conn.begin_nested():
                    await conn.execute(_SET_TIMEOUTS, short)
                    outcome = (await conn.execute(_AWARD, {"op_id": op_id})).scalar_one()
            finally:
                # Success, failure or cancellation: the rest of the push keeps
                # its normal timeouts. (If the connection itself is gone this
                # raises and the whole push fails, which is safe: nothing commits.)
                await conn.execute(_SET_TIMEOUTS, restore)
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
