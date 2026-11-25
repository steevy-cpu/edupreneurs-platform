"""Running one ``staff.*`` database function for a verified staff member."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.sql.elements import TextClause

from edu_api.db.session import Database
from edu_api.staff.deps import StaffPrincipal, record_denial
from edu_api.staff.errors import translate_db_error


def as_jsonb(value: Any) -> str:
    """JSON text for a ``CAST(:param AS jsonb)`` bound parameter."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def staff_sql(call: str) -> TextClause:
    """``SELECT staff.<call>`` with bound parameters only."""
    return text(f"SELECT {call}")


async def call_staff(
    request: Request,
    db: Database,
    staff: StaffPrincipal,
    statement: TextClause,
    params: dict[str, Any] | None = None,
    *,
    read_only: bool = False,
) -> Any:
    """One transaction, the staff member as actor, one function call, its result.

    A refusal by the function or by an integrity trigger becomes a 4xx in the
    standard error shape; the transaction (including its audit event) is rolled
    back by PostgreSQL. A refusal for lack of rights (403) is then recorded in
    the audit log in a transaction of its own.
    """
    try:
        async with db.transaction(staff.user_id, read_only=read_only) as conn:
            return (await conn.execute(statement, params or {})).scalar_one()
    except DBAPIError as exc:
        error = translate_db_error(exc)
        if error is None:
            raise
        if error.status_code == 403:
            await record_denial(
                request, db, staff.user_id, required=frozenset(), held=staff.roles, check="function"
            )
        raise error from None
