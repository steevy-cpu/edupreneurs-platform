"""Database access for the learner-facing notification routes.

Runs as the least-privileged ``edu_api`` role. Row-level security returns only
the caller's own rows; the queries filter explicitly as well. The only write is
``notify.set_preferences()``, which takes the actor from the transaction.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from edu_api.notify.cursor import encode_cursor
from edu_api.notify.schemas import (
    CATEGORIES,
    PRODUCT_TIME_ZONE,
    NotificationItem,
    NotificationList,
    PreferencesResponse,
    PreferencesUpdate,
    QuietHours,
)

_SELECT_PREFERENCES = text(
    "SELECT pol.quiet_start AS platform_start, pol.quiet_end AS platform_end, "
    "       p.learner_id, p.push_enabled, p.muted_categories, p.quiet_start, p.quiet_end, "
    "       p.updated_at "
    "FROM notify.policy pol "
    "LEFT JOIN notify.preferences p ON p.learner_id = :user_id"
)

_SET_PREFERENCES = text(
    "SELECT notify.set_preferences(:push_enabled, :muted_categories, :quiet_start, :quiet_end)"
)

_LIST_COLUMNS = (
    "SELECT o.id, o.seq, o.kind, k.category, o.refs, o.deliver_after, o.expires_at "
    "FROM notify.outbox o JOIN notify.kinds k ON k.kind = o.kind "
    "WHERE o.recipient_id = :user_id AND 'in_app' = ANY (o.channels) "
    "  AND o.deliver_after <= now() AND (o.expires_at IS NULL OR o.expires_at > now()) "
)
_LIST_ORDER = "ORDER BY o.deliver_after DESC, o.seq DESC LIMIT :row_limit"
_LIST_FIRST_PAGE = text(_LIST_COLUMNS + _LIST_ORDER)
_LIST_NEXT_PAGE = text(
    _LIST_COLUMNS + "AND (o.deliver_after, o.seq) < (:before_at, :before_seq) " + _LIST_ORDER
)


def _hhmm(value: dt.time) -> str:
    return value.strftime("%H:%M")


def _time(value: str) -> dt.time:
    return dt.time.fromisoformat(value)


async def load_preferences(conn: AsyncConnection, user_id: uuid.UUID) -> PreferencesResponse:
    row = (await conn.execute(_SELECT_PREFERENCES, {"user_id": user_id})).one()
    saved = row.learner_id is not None
    own = (
        QuietHours(start=_hhmm(row.quiet_start), end=_hhmm(row.quiet_end))
        if saved and row.quiet_start is not None and row.quiet_end is not None
        else None
    )
    return PreferencesResponse(
        # No row means "never opted in": push stays off.
        push_enabled=bool(row.push_enabled) if saved else False,
        muted_categories=sorted(row.muted_categories) if saved else [],
        quiet_hours=own,
        platform_quiet_hours=QuietHours(
            start=_hhmm(row.platform_start), end=_hhmm(row.platform_end)
        ),
        time_zone=PRODUCT_TIME_ZONE,
        categories=list(CATEGORIES),
        updated_at=row.updated_at if saved else None,
    )


async def save_preferences(conn: AsyncConnection, update: PreferencesUpdate) -> None:
    quiet = update.quiet_hours
    await conn.execute(
        _SET_PREFERENCES,
        {
            "push_enabled": update.push_enabled,
            "muted_categories": sorted(set(update.muted_categories)),
            "quiet_start": _time(quiet.start) if quiet else None,
            "quiet_end": _time(quiet.end) if quiet else None,
        },
    )


async def list_notifications(
    conn: AsyncConnection,
    user_id: uuid.UUID,
    *,
    limit: int,
    before: tuple[dt.datetime, int] | None,
) -> NotificationList:
    params: dict[str, object] = {"user_id": user_id, "row_limit": limit + 1}
    if before is None:
        rows = (await conn.execute(_LIST_FIRST_PAGE, params)).all()
    else:
        params.update({"before_at": before[0], "before_seq": before[1]})
        rows = (await conn.execute(_LIST_NEXT_PAGE, params)).all()

    page = rows[:limit]
    items = [
        NotificationItem(
            id=row.id,
            kind=row.kind,
            category=row.category,
            refs=row.refs,
            available_at=row.deliver_after,
            expires_at=row.expires_at,
        )
        for row in page
    ]
    next_cursor = (
        encode_cursor(user_id, page[-1].deliver_after, page[-1].seq) if len(rows) > limit else None
    )
    return NotificationList(items=items, next_cursor=next_cursor)
