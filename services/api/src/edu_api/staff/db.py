"""The staff connection pool.

Staff routes never use the student pool. They log in as ``edu_staff_login``
(member of ``edu_staff`` only), a role that holds no table privilege at all:
everything it can do is a ``SECURITY DEFINER`` function in the private schemas
``staff`` and ``ops``. The verified actor reaches the database exactly as on the
student side (``Database.transaction`` sets the transaction-local
``edu.actor_id``), so the same pooled-connection isolation guarantees apply.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine

from edu_api.config import Settings
from edu_api.db.session import Database


def build_staff_database(settings: Settings) -> Database | None:
    """``None`` when the staff side is not configured. Opens no connection."""
    if settings.staff_database_url is None:
        return None
    connect_args: dict[str, object] = {
        "timeout": settings.db_connect_timeout_s,
        "command_timeout": settings.db_statement_timeout_ms / 1000 + 2,
        "server_settings": {
            "application_name": "edu-api-staff",
            "statement_timeout": str(settings.db_statement_timeout_ms),
            "idle_in_transaction_session_timeout": str(settings.db_statement_timeout_ms * 2),
            "lock_timeout": str(settings.db_statement_timeout_ms),
        },
    }
    if settings.db_disable_statement_cache:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
    engine = create_async_engine(
        settings.staff_database_url.get_secret_value(),
        pool_size=settings.staff_db_pool_size,
        max_overflow=settings.staff_db_max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_pre_ping=True,
        pool_reset_on_return="rollback",
        connect_args=connect_args,
        hide_parameters=True,  # never put bound values in error text/logs
    )
    return Database(engine)
