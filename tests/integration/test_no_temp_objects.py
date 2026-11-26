"""The API login cannot create temporary objects (migration 20261125100000).

Temporary objects let a session shadow type names used inside SECURITY DEFINER
functions, so the database refuses them for the API roles altogether.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

STATEMENTS = [
    "CREATE TEMP TABLE t_probe (x int)",
    "CREATE TEMPORARY TABLE t_probe2 AS SELECT 1 AS x",
    "CREATE DOMAIN pg_temp.probe_domain AS text",
    "CREATE FUNCTION pg_temp.probe_fn() RETURNS int LANGUAGE sql AS 'SELECT 1'",
]


@pytest.mark.parametrize("statement", STATEMENTS)
async def test_api_login_cannot_create_temporary_objects(app, statement: str) -> None:  # type: ignore[no-untyped-def]
    async with app.state.db.transaction(None) as conn:
        who = (await conn.execute(text("SELECT session_user AS s"))).one()
        assert who.s == "edu_api_login"
        with pytest.raises(DBAPIError) as raised:
            await conn.execute(text(statement))
    assert "permission denied" in str(raised.value).lower()
