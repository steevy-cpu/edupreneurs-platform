"""Read side of the rewards lane: summary and ledger pages for the caller."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from edu_api.db.session import Database
from edu_api.errors import ApiError
from edu_api.rewards.cursor import (
    InvalidLedgerCursor,
    decode_ledger_cursor,
    encode_ledger_cursor,
)
from edu_api.rewards.schemas import (
    EarnedAchievement,
    LedgerEntry,
    LedgerPage,
    RewardsSummary,
    StreakSummary,
)

logger = logging.getLogger("edu_api.rewards")

_RECONCILE = text("SELECT rewards.reconcile_learner(:limit) AS outcome")

_TODAY = text("SELECT rewards.haiti_day(now()) AS today")

_BALANCE = text(
    "SELECT balance, lifetime_earned FROM rewards.balances WHERE learner_id = :learner_id"
)

_STREAK = text(
    "SELECT latest_run_days, last_active_day, longest_run_days "
    "FROM rewards.streak_state WHERE learner_id = :learner_id"
)

_ACHIEVEMENTS = text(
    "SELECT a.achievement_code, a.awarded_at, d.titles, COALESCE(l.amount, 0) AS gold "
    "FROM rewards.achievement_awards a "
    "LEFT JOIN rewards.achievement_definitions d ON d.code = a.achievement_code "
    "LEFT JOIN rewards.ledger l ON l.id = a.ledger_id "
    "WHERE a.learner_id = :learner_id "
    "ORDER BY a.awarded_at, a.achievement_code"
)

_LEDGER_COLUMNS = (
    "SELECT id, entry_kind, amount, source_kind, lesson_id, question_key, "
    "       achievement_code, source_op_id, accepted_day, created_at "
    "FROM rewards.ledger WHERE learner_id = :learner_id "
)
_LEDGER_ORDER = "ORDER BY created_at DESC, id DESC LIMIT :limit"

_LEDGER_NEWEST = text(_LEDGER_COLUMNS + _LEDGER_ORDER)
#: Keyset paging on the caller's own (created_at, id) — never a global sequence.
_LEDGER_BEFORE = text(
    _LEDGER_COLUMNS + "AND (created_at, id) < (:before_at, :before_id) " + _LEDGER_ORDER
)


def _entry(row: Any) -> LedgerEntry:
    return LedgerEntry(
        id=row.id,
        kind=row.entry_kind,
        amount=row.amount,
        source=row.source_kind,
        lesson_id=row.lesson_id,
        question_key=row.question_key,
        achievement_code=row.achievement_code,
        op_id=row.source_op_id,
        day=row.accepted_day,
        created_at=row.created_at,
    )


async def _balance(conn: AsyncConnection, learner_id: uuid.UUID) -> tuple[int, int]:
    row = (await conn.execute(_BALANCE, {"learner_id": learner_id})).one_or_none()
    return (int(row.balance), int(row.lifetime_earned)) if row is not None else (0, 0)


async def _heal(db: Database, learner_id: uuid.UUID, limit: int) -> bool:
    """Examine accepted operations the push hook missed (flag was off, or the
    award step failed). Returns whether the ledger is now up to date. A failure
    here never fails the read: the caller just sees ``up_to_date: false``."""
    try:
        async with db.transaction(learner_id) as conn:
            outcome = (await conn.execute(_RECONCILE, {"limit": limit})).scalar_one()
    except DBAPIError as exc:
        logger.error(
            "rewards_reconcile_failed learner=%s error=%s sqlstate=%s",
            learner_id,
            type(exc.orig).__name__,
            getattr(exc.orig, "sqlstate", None),
        )
        return False
    return not bool(outcome["more"])


async def summary(
    db: Database, learner_id: uuid.UUID, *, recent_limit: int, reconcile_limit: int
) -> RewardsSummary:
    up_to_date = await _heal(db, learner_id, reconcile_limit)

    async with db.transaction(learner_id, read_only=True) as conn:
        today = (await conn.execute(_TODAY)).scalar_one()
        balance, lifetime = await _balance(conn, learner_id)
        streak_row = (await conn.execute(_STREAK, {"learner_id": learner_id})).one_or_none()
        achievement_rows = (await conn.execute(_ACHIEVEMENTS, {"learner_id": learner_id})).all()
        recent_rows = (
            await conn.execute(_LEDGER_NEWEST, {"learner_id": learner_id, "limit": recent_limit})
        ).all()

    if streak_row is None:
        streak = StreakSummary(
            current_days=0, longest_days=0, last_active_day=None, active_today=False
        )
    else:
        in_progress = streak_row.last_active_day >= today - timedelta(days=1)
        streak = StreakSummary(
            current_days=streak_row.latest_run_days if in_progress else 0,
            longest_days=streak_row.longest_run_days,
            last_active_day=streak_row.last_active_day,
            active_today=streak_row.last_active_day == today,
        )
    return RewardsSummary(
        balance=balance,
        lifetime_earned=lifetime,
        streak=streak,
        achievements=[
            EarnedAchievement(
                code=row.achievement_code,
                titles=row.titles or {},
                earned_at=row.awarded_at,
                gold=row.gold,
            )
            for row in achievement_rows
        ],
        recent=[_entry(row) for row in recent_rows],
        today=today,
        up_to_date=up_to_date,
    )


async def ledger_page(
    db: Database, learner_id: uuid.UUID, cursor: str | None, *, limit: int
) -> LedgerPage:
    statement = _LEDGER_NEWEST
    params: dict[str, Any] = {"learner_id": learner_id, "limit": limit + 1}
    if cursor is not None:
        try:
            before_at, before_id = decode_ledger_cursor(learner_id, cursor)
        except InvalidLedgerCursor:
            raise ApiError(
                422,
                "invalid_cursor",
                "This cursor cannot be used. Request the ledger again without a cursor.",
            ) from None
        statement = _LEDGER_BEFORE
        params.update(before_at=before_at, before_id=before_id)

    async with db.transaction(learner_id, read_only=True) as conn:
        balance, _ = await _balance(conn, learner_id)
        rows = (await conn.execute(statement, params)).all()

    has_more = len(rows) > limit
    page = rows[:limit]
    return LedgerPage(
        entries=[_entry(row) for row in page],
        next_cursor=(
            encode_ledger_cursor(learner_id, page[-1].created_at, page[-1].id) if has_more else None
        ),
        has_more=has_more,
        balance=balance,
    )
