"""No sockets are opened by these isolation and configuration probes."""

import logging

import pytest
from pydantic import SecretStr

from disposable import validate_urls
from edu_api.config import Settings
from edu_api.db.staging import validate_runtime
from staging_service import EventFormatter
from staging_verify import pending_versions, versions

REF = "s" * 20
ISSUER = f"https://{REF}.supabase.co/auth/v1"
DSN = f"postgresql+asyncpg://edu_api_login:fixture@db.{REF}.supabase.co:5432/postgres"


def profile(**changes: object) -> Settings:
    fields = dict(
        environment="staging",
        database_url=SecretStr(DSN),
        auth_issuer=ISSUER,
        auth_jwks_url=ISSUER + "/.well-known/jwks.json",
        staging_project_ref=REF,
    )
    return Settings.model_validate({**fields, **changes})


@pytest.mark.parametrize(
    "change",
    [
        {"environment": "local"},
        {"environment": "production"},
        {"staging_project_ref": "p" * 20},
        {"auth_issuer": "https://production.invalid/auth/v1"},
        {"auth_jwks_url": "https://elsewhere.invalid/keys"},
        {"auth_audience": "other"},
        {"database_url": DSN.replace("edu_api_login", "postgres")},
        {"database_url": DSN + "?sslmode=disable"},
        {"database_url": DSN.replace(":5432", ":6543")},
        {"database_url": DSN.replace("/postgres", "/other")},
    ],
)
def test_stage_rejects_endpoint_or_identity_drift(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        validate_runtime(profile(**change))


def test_pinned_direct_and_session_connections() -> None:
    validate_runtime(profile())
    pooled = DSN.replace("edu_api_login:", f"edu_api_login.{REF}:").replace(
        f"db.{REF}.supabase.co", "aws-0-us-east-1.pooler.supabase.com"
    )
    validate_runtime(profile(database_url=pooled))


def test_local_effective_urls_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "EDU_ENVIRONMENT": "local",
        "EDU_DATABASE_URL": "postgresql+asyncpg://edu_api_login:x@127.0.0.1:30002/postgres",
        "LOCAL_ADMIN_DATABASE_URL": "postgresql://postgres:x@127.0.0.1:30002/postgres",
        "LOCAL_SUPABASE_URL": "http://127.0.0.1:30001",
        "EDU_AUTH_ISSUER": "http://127.0.0.1:30001/auth/v1",
        "EDU_AUTH_JWKS_URL": "http://127.0.0.1:30001/auth/v1/.well-known/jwks.json",
    }
    for key in env:
        monkeypatch.delenv(key, raising=False)
    validate_urls(env, 30001, 30002)
    for key in env:
        with pytest.raises(ValueError):
            validate_urls({**env, key: "https://unexpected.invalid/"}, 30001, 30002)
    monkeypatch.setenv("EDU_DATABASE_URL", env["EDU_DATABASE_URL"].replace("30002", "54322"))
    with pytest.raises(ValueError):
        validate_urls(env, 30001, 30002)


def test_release_history_and_private_log_args() -> None:
    assert versions()[-1] >= "20261125100000"
    record = logging.LogRecord(
        "uvicorn.error", logging.ERROR, "", 1, "untrusted %s", ("private",), None
    )
    assert EventFormatter().format(record) == '{"level": "ERROR", "event": "service_event"}'


def test_disposable_identity_and_bindings_fail_before_db_access(tmp_path, monkeypatch):
    import disposable

    original = disposable.CONFIG.read_text()
    # Use an in-memory copy of the unconfigured layout, independent of the developer's ports.
    config = tmp_path / "config.toml"
    config.write_text(
        'project_id="mon-edupreneur"\n[api]\nport=54321\n[db]\nport=54322\n'
        "shadow_port=54320\n[studio]\nport=54323\n"
    )
    monkeypatch.setattr(disposable, "CONFIG", config)
    with pytest.raises(ValueError, match="disposable project"):
        disposable.layout()
    config.write_text(original.replace('project_id = "', 'project_id = "another-'))
    with pytest.raises(ValueError, match="disposable project"):
        disposable.layout()
    monkeypatch.setattr(disposable, "layout", lambda: ("edu-test-synthetic", 32501, 32502))
    monkeypatch.setattr(disposable, "ROOT", tmp_path)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "tcp://elsewhere.invalid:2376")
    with pytest.raises(ValueError, match="local Docker socket"):
        disposable.verify()
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    monkeypatch.setattr(
        disposable.subprocess,
        "check_output",
        lambda *a, **kw: '{"5432/tcp":[{"HostPort":"54322"}]}',
    )
    with pytest.raises(ValueError, match="binding"):
        disposable.verify()


def test_planner_accepts_only_an_ordered_prefix() -> None:
    ids = versions()
    assert pending_versions(ids, ids[:-1]) == [ids[-1]]
    assert pending_versions(ids, ids) == []
    for incorrect in (ids[1:], [*ids, ids[-1]], [*ids[:-1], "unknown"]):
        with pytest.raises(ValueError, match="prefix"):
            pending_versions(ids, incorrect)
