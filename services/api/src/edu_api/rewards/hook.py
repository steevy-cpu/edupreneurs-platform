"""The single rewards step in the push path.

Runs inside the push transaction, right after ``app.sync_apply_operation``
accepted an operation, and inside a SAVEPOINT of its own:

* success  -> the Gold rows commit atomically with the learning operation;
* failure  -> only the savepoint is rolled back. The learning operation still
  commits, the push response is unchanged, one structured log line is written,
  and ``rewards.reconcile_learner`` awards the operation later.

Replays of an accepted operation are passed through too: the SQL function is
idempotent (it repeats its recorded decision), and this heals an operation
whose first award attempt failed as soon as the phone retries.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger("edu_api.rewards")

_AWARD = text("SELECT rewards.award_for_operation(:op_id) AS outcome")


async def award_after_accept(
    conn: AsyncConnection, learner_id: uuid.UUID, op_id: uuid.UUID
) -> None:
    try:
        async with conn.begin_nested():
            await conn.execute(_AWARD, {"op_id": op_id})
    except Exception as exc:
        # Never the exception text: driver messages may carry SQL or values.
        logger.error(
            "rewards_award_failed learner=%s op_id=%s error=%s sqlstate=%s action=reconcile_later",
            learner_id,
            op_id,
            type(exc).__name__,
            getattr(getattr(exc, "orig", None), "sqlstate", None),
        )
