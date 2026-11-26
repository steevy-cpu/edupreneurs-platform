"""Database access with a transaction-scoped, verified actor.

HOW IDENTITY REACHES THE DATABASE
---------------------------------
Row-level security policies compare rows with ``app.current_actor_id()``, which
reads the PostgreSQL setting ``edu.actor_id``. For every authenticated request
we open ONE transaction and, as its first statement, run::

    SELECT set_config('edu.actor_id', <verified user id>, true)

The final ``true`` means "local to this transaction": PostgreSQL discards the
value at COMMIT or ROLLBACK. Connections are pooled and reused by other
learners, so this is what stops learner A's identity leaking into learner B's
request. The value is passed as a bound parameter, never formatted into SQL.

There is intentionally no way to obtain a connection with an actor set outside
of ``Database.transaction``.
"""

from __future__ import annotations

import ssl
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from edu_api.config import Settings

_SET_ACTOR = text("SELECT set_config('edu.actor_id', :actor_id, true)")
_SET_READ_ONLY = text("SET TRANSACTION READ ONLY")


def build_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, object] = {
        "timeout": settings.db_connect_timeout_s,
        "command_timeout": settings.db_statement_timeout_ms / 1000 + 2,
        "server_settings": {
            "application_name": "edu-api",
            # A runaway query or a stuck transaction must not pin a pooled
            # connection (and the learner's sync lock) forever.
            "statement_timeout": str(settings.db_statement_timeout_ms),
            "idle_in_transaction_session_timeout": str(settings.db_statement_timeout_ms * 2),
            "lock_timeout": str(settings.db_statement_timeout_ms),
        },
    }
    if settings.environment == "staging":
        connect_args["ssl"] = ssl.create_default_context(cafile=settings.db_ca_file)
    if settings.db_disable_statement_cache:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_pre_ping=True,
        # Belt and braces: any connection returned to the pool is rolled back,
        # which also clears transaction-local settings.
        pool_reset_on_return="rollback",
        connect_args=connect_args,
        hide_parameters=True,  # never put bound values (answers, ids) in error text/logs
    )


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    @asynccontextmanager
    async def transaction(
        self, actor_id: uuid.UUID | None, *, read_only: bool = False
    ) -> AsyncIterator[AsyncConnection]:
        """One connection, one transaction, one actor.

        Commits when the block exits normally and rolls back on any exception.
        ``actor_id=None`` is for unauthenticated work (the readiness probe);
        every "own row" policy then matches nothing.
        """
        async with self.engine.connect() as conn, conn.begin():
            if read_only:
                await conn.execute(_SET_READ_ONLY)
            if actor_id is not None:
                await conn.execute(_SET_ACTOR, {"actor_id": str(actor_id)})
            yield conn

    async def dispose(self) -> None:
        await self.engine.dispose()
