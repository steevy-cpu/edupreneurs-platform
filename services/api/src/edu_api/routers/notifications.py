"""Learner-facing notification routes (flag ``EDU_NOTIFICATIONS_ENABLED``, default off).

The routes are always registered. With the flag off every one of them answers
the same 404 as an unknown path — before authentication and before the body is
looked at — and no notification database pool exists.

Read my in-app list, read and replace my preferences. There is deliberately no
route that creates a notification: only server code can (``notify.enqueue`` is
not executable by the API's database role).

ISOLATION FROM LEARNING
-----------------------
These routes use their own database pool (``app.state.notify_db``) with a short
timeout, and every database failure here is answered with the same 503. Lessons,
catalog and sync never touch the ``notify`` schema or this pool, so they keep
working when notifications are slow, locked or missing
(``tests/integration/test_notify_isolation.py``).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncConnection

from edu_api.config import Settings
from edu_api.db.session import Database, build_engine
from edu_api.deps import AppSettings, CurrentPrincipal
from edu_api.errors import ApiError, error_responses
from edu_api.identity import ensure_learner_profile
from edu_api.notify import service
from edu_api.notify.cursor import MAX_CURSOR_LENGTH, InvalidCursor, decode_cursor
from edu_api.notify.schemas import NotificationList, PreferencesResponse, PreferencesUpdate

logger = logging.getLogger("edu_api.notify")

#: Director ruling R-01: these are NEW paths, and the baseline contract test pins
#: the exact set of documented paths. Until the director flips this ONE constant at
#: integration, the routes are registered but left out of the OpenAPI document, so
#: packages/contracts/openapi.json and the mobile schema.d.ts stay as on `main`.
#: The contract is written out in docs/overnight-2026-11-24/lanes/notify.md.
INCLUDE_IN_SCHEMA = False


def build_database(settings: Settings) -> Database:
    """A separate, deliberately small pool for the notification routes.

    Same least-privileged login as the rest of the API; only the pool differs.
    Creating it opens no connection.
    """
    return Database(
        build_engine(
            settings.model_copy(
                update={
                    "db_pool_size": settings.notify_db_pool_size,
                    "db_max_overflow": 0,
                    "db_pool_timeout_s": settings.notify_db_pool_timeout_s,
                    "db_statement_timeout_ms": settings.notify_db_statement_timeout_ms,
                }
            )
        )
    )


def _require_enabled(request: Request) -> None:
    """Flag off: indistinguishable from a path that does not exist."""
    settings: Settings = request.app.state.settings
    if not settings.notifications_enabled:
        raise ApiError(404, "not_found", "Not Found")


def _notify_db(request: Request) -> Database:
    database: Database = request.app.state.notify_db
    return database


NotifyDb = Annotated[Database, Depends(_notify_db)]


@asynccontextmanager
async def _transaction(
    db: Database, principal: CurrentPrincipal, *, read_only: bool = False
) -> AsyncIterator[AsyncConnection]:
    """Like ``Database.transaction`` but any database trouble becomes one clean 503."""
    try:
        async with db.transaction(principal.user_id, read_only=read_only) as conn:
            yield conn
    except (DBAPIError, PoolTimeoutError, TimeoutError, OSError) as exc:
        logger.warning(
            "notifications unavailable: %s sqlstate=%s",
            type(exc).__name__,
            getattr(getattr(exc, "orig", None), "sqlstate", None),
        )
        raise ApiError(
            503,
            "notifications_unavailable",
            "Notifications are temporarily unavailable. Lessons and sync are not affected.",
            headers={"Retry-After": "30"},
        ) from None


def build_router(include_in_schema: bool) -> APIRouter:
    """The three learner routes. ``include_in_schema`` only decides whether they
    appear in the OpenAPI document; behaviour is identical either way."""
    router = APIRouter(
        prefix="/v1",
        tags=["notifications"],
        dependencies=[Depends(_require_enabled)],
        include_in_schema=include_in_schema,
    )

    @router.get(
        "/me/notification-preferences",
        response_model=PreferencesResponse,
        responses=error_responses(401, 503),
        summary="The signed-in learner's own notification preferences",
    )
    async def get_preferences(principal: CurrentPrincipal, db: NotifyDb) -> PreferencesResponse:
        """Push is off until the learner turns it on. Quiet hours are wall-clock times
        in `time_zone`; the platform's window always applies in addition to the learner's."""
        async with _transaction(db, principal, read_only=True) as conn:
            return await service.load_preferences(conn, principal.user_id)

    @router.put(
        "/me/notification-preferences",
        response_model=PreferencesResponse,
        responses=error_responses(401, 413, 422, 503),
        summary="Replace the signed-in learner's own notification preferences",
    )
    async def put_preferences(
        body: PreferencesUpdate, principal: CurrentPrincipal, db: NotifyDb
    ) -> PreferencesResponse:
        """Full replacement; safe to repeat. The learner is taken from the access token:
        there is no way to change someone else's preferences."""
        async with _transaction(db, principal) as conn:
            await ensure_learner_profile(conn, principal.user_id)
            await service.save_preferences(conn, body)
            return await service.load_preferences(conn, principal.user_id)

    @router.get(
        "/notifications",
        response_model=NotificationList,
        responses=error_responses(401, 422, 503),
        summary="The signed-in learner's own in-app notifications, newest first",
    )
    async def list_notifications(
        principal: CurrentPrincipal,
        db: NotifyDb,
        settings: AppSettings,
        cursor: Annotated[
            str | None,
            Query(
                max_length=MAX_CURSOR_LENGTH,
                description="`next_cursor` of the previous page, to get older items. "
                "Omit to start from the newest.",
            ),
        ] = None,
        limit: Annotated[int | None, Query(ge=1, description="Page size.")] = None,
    ) -> NotificationList:
        """Each item is a `kind` plus opaque reference ids. There is no title or body:
        the app renders the words in the learner's language. Pull only: nothing is pushed."""
        if limit is not None and limit > settings.notifications_max_limit:
            raise ApiError(
                422,
                "validation_error",
                f"limit must be at most {settings.notifications_max_limit}.",
            )
        before = None
        if cursor is not None:
            try:
                before = decode_cursor(principal.user_id, cursor)
            except InvalidCursor:
                raise ApiError(
                    422,
                    "notification_cursor_invalid",
                    "This cursor cannot be used. Start again without a cursor.",
                ) from None
        async with _transaction(db, principal, read_only=True) as conn:
            return await service.list_notifications(
                conn,
                principal.user_id,
                limit=limit or settings.notifications_default_limit,
                before=before,
            )

    return router


router = build_router(INCLUDE_IN_SCHEMA)
