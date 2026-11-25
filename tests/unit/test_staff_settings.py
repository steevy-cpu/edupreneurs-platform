"""Staff-side configuration: off unless a staff database URL is given."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from edu_api.config import Settings
from edu_api.main import create_app
from edu_api.staff.db import build_staff_database
from edu_api.staff.deps import STAFF_ROLES, require_staff

STAFF_URL = "postgresql+asyncpg://edu_staff_login:unused@127.0.0.1:1/unused"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": SecretStr("postgresql+asyncpg://unused@127.0.0.1:1/unused"),
        "auth_issuer": "http://127.0.0.1:1/auth/v1",
        "auth_jwks_url": "http://127.0.0.1:1/auth/v1/.well-known/jwks.json",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_the_staff_side_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EDU_STAFF_DATABASE_URL", raising=False)
    settings = make_settings()
    assert settings.staff_database_url is None
    assert build_staff_database(settings) is None
    app = create_app(settings)
    assert app.state.staff_db is None
    assert not [path for path in app.openapi()["paths"] if path.startswith("/v1/staff")]


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_staff_url_means_unset(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    monkeypatch.setenv("EDU_STAFF_DATABASE_URL", blank)
    assert make_settings().staff_database_url is None


def test_the_staff_url_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDU_STAFF_DATABASE_URL", STAFF_URL)
    settings = make_settings()
    assert settings.staff_database_url is not None
    assert settings.staff_database_url.get_secret_value() == STAFF_URL
    assert "unused@" not in repr(settings), "the URL (with its password) is never printed"


def test_the_staff_url_must_use_asyncpg() -> None:
    with pytest.raises(ValidationError, match="staff_database_url"):
        make_settings(staff_database_url=SecretStr("postgresql://edu_staff_login@127.0.0.1/x"))


async def test_a_configured_staff_side_has_its_own_pool_and_an_unchanged_contract() -> None:
    settings = make_settings(staff_database_url=SecretStr(STAFF_URL), staff_db_pool_size=3)
    app = create_app(settings)
    try:
        assert app.state.staff_db is not None
        assert app.state.staff_db.engine is not app.state.db.engine
        assert app.state.staff_db.engine.url.username == "edu_staff_login"
        assert app.state.db.engine.url.username != "edu_staff_login"
        assert app.state.staff_db.engine.pool.size() == 3  # type: ignore[attr-defined]
        # ruling R-01: registered (the integration tests call it), but not in the
        # published contract on lane branches
        assert not [path for path in app.openapi()["paths"] if path.startswith("/v1/staff")]
    finally:
        await app.state.db.dispose()
        await app.state.staff_db.dispose()


def test_require_staff_knows_exactly_the_four_roles() -> None:
    assert frozenset({"editor", "reviewer", "publisher", "admin"}) == STAFF_ROLES
    for role in STAFF_ROLES:
        assert callable(require_staff(role))
    assert callable(require_staff())
    with pytest.raises(ValueError, match="unknown staff role"):
        require_staff("Editor")
