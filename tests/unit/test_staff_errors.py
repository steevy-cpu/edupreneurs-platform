"""Database refusals on the staff side become clean, non-leaking API errors."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy.exc import DBAPIError

from edu_api.staff.errors import TRIGGER_ERRORS, translate_db_error

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


class FakePgError(Exception):
    def __init__(self, sqlstate: str | None, message: str) -> None:
        super().__init__(f"<class 'asyncpg.exceptions.X'>: {message}")
        self.sqlstate = sqlstate
        self.message = message


def db_error(sqlstate: str | None, message: str = "") -> DBAPIError:
    return DBAPIError("SELECT 1", {}, FakePgError(sqlstate, message))


def test_every_trigger_message_of_the_app_schema_has_a_translation() -> None:
    guards = (MIGRATIONS / "20261121000200_integrity_guards.sql").read_text(encoding="utf-8")
    raised = set(re.findall(r"RAISE EXCEPTION '([^']+)'", guards))
    assert len(raised) >= 25
    assert raised - set(TRIGGER_ERRORS) == set(), "a trigger message has no API translation"
    assert set(TRIGGER_ERRORS) - raised == set(), "a translation matches no trigger any more"
    for status, code, message in TRIGGER_ERRORS.values():
        assert status in (403, 404, 409)
        assert re.fullmatch(r"[a-z][a-z0-9_]+", code)
        assert message.endswith(".")


@pytest.mark.parametrize(
    ("sqlstate", "message", "status", "code"),
    [
        ("ED404", "revision_not_found", 404, "revision_not_found"),
        ("ED409", "revision_in_review", 409, "revision_in_review"),
        ("ED422", "slug_invalid", 422, "slug_invalid"),
        ("42501", "not_the_author", 403, "forbidden"),
        ("42501", "permission denied for table staff_roles", 403, "forbidden"),
        ("P0001", "Author cannot review own lesson", 409, "author_cannot_review"),
        ("P0001", "Reviewer role required", 403, "forbidden"),
        ("P0001", "Lesson revision does not exist", 404, "revision_not_found"),
        ("P0001", "some future rule nobody translated yet", 409, "editorial_rule_violation"),
        ("23505", 'duplicate key value violates unique constraint "x"', 409, "conflict"),
        ("23503", "violates foreign key constraint", 409, "reference_conflict"),
        ("23514", "violates check constraint", 422, "invalid_content"),
        ("22P02", "invalid input syntax for type uuid", 422, "invalid_content"),
    ],
)
def test_translation(sqlstate: str, message: str, status: int, code: str) -> None:
    error = translate_db_error(db_error(sqlstate, message))
    assert error is not None
    assert (error.status_code, error.code) == (status, code)


@pytest.mark.parametrize("sqlstate", ["08006", "57014", "53300", "XX000", "40001", None])
def test_outages_and_unknown_errors_are_left_to_the_global_handler(sqlstate: str | None) -> None:
    assert translate_db_error(db_error(sqlstate, "anything")) is None


@pytest.mark.parametrize(
    "message",
    [
        "DROP TABLE x; --",
        "Élève A (synthétique) a écrit ceci",
        'relation "app.staff_roles" does not exist',
        "x" * 500,
        "",
    ],
)
def test_database_text_never_reaches_the_client(message: str) -> None:
    for sqlstate in ("ED404", "ED409", "ED422", "P0001", "42501", "23505", "23514"):
        error = translate_db_error(db_error(sqlstate, message))
        assert error is not None
        assert re.fullmatch(r"[a-z][a-z0-9_]+", error.code)
        if message:
            assert message not in error.message and message not in error.code
