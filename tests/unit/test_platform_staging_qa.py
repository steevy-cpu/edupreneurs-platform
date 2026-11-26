"""Independent, network-free checks of the #33 release entry points."""

import json
import os
import runpy
import ssl
import sys
from unittest.mock import patch

import pytest

import disposable
import staging_verify
from edu_api.config import Settings
from edu_api.db.session import build_engine
from edu_api.db.staging import validate_runtime
from local_stack import ROOT


class ControlMiss(AssertionError):
    """Only this exact missed-control observation counts as a known finding."""


@pytest.fixture
def stage_env(monkeypatch):
    # Synthetic project coordinates. Never open a connection to these names.
    for key in list(os.environ):
        if key.upper().startswith("EDU_") or key in {"WEB_CONCURRENCY", "UVICORN_RELOAD"}:
            monkeypatch.delenv(key)
    ref = "q" * 20
    issuer = f"https://{ref}.supabase.co/auth/v1"
    env = {
        "EDU_ENVIRONMENT": "staging",
        "EDU_STAGING_PROJECT_REF": ref,
        "EDU_DATABASE_URL": f"postgresql+asyncpg://edu_api_login:qa-fixture@db.{ref}.supabase.co:5432/postgres",
        "EDU_AUTH_ISSUER": issuer,
        "EDU_AUTH_JWKS_URL": issuer + "/.well-known/jwks.json",
        "PORT": "8123",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("EDU_ENVIRONMENT", "production"),
        ("EDU_AUTH_ISSUER", "https://other.invalid/auth/v1"),
        ("EDU_AUTH_JWKS_URL", "https://other.invalid/jwks"),
        ("PORT", "65536"),
    ],
)
def test_launcher_rejects_bad_profile_without_echo(stage_env, key, value, monkeypatch, capsys):
    monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["staging_service.py", "--environment", "staging"])
    with patch("uvicorn.run") as serve, pytest.raises(SystemExit) as error:
        runpy.run_path(str(ROOT / "scripts/staging_service.py"), run_name="__main__")
    assert error.value.code == 2
    serve.assert_not_called()
    err = capsys.readouterr().err
    assert err and "qa-fixture" not in err and stage_env["EDU_DATABASE_URL"] not in err


@pytest.mark.parametrize(
    "workers",
    [
        "1",
        pytest.param(
            "2",
            marks=pytest.mark.xfail(
                strict=True,
                raises=ControlMiss,
                reason="QA-4: inherited WEB_CONCURRENCY overrides single-worker design",
            ),
        ),
    ],
)
def test_real_launcher_reaches_single_server(stage_env, workers, monkeypatch):
    import uvicorn

    captured = []
    monkeypatch.setenv("WEB_CONCURRENCY", workers)
    monkeypatch.setattr(sys, "argv", ["staging_service.py", "--environment", "staging"])
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, **kw: captured.append(self.config))
    # Preserve pytest's log handlers. Uvicorn builds its real configuration and selects its run mode.
    with patch("logging.basicConfig"):
        try:
            runpy.run_path(str(ROOT / "scripts/staging_service.py"), run_name="__main__")
        except SystemExit as exc:
            if workers == "2" and exc.code == 3 and not captured:
                raise ControlMiss("launcher exited before running a server") from exc
            raise
    assert len(captured) == 1
    assert captured[0].workers == 1 and not captured[0].access_log


def test_tls_and_pool_parameters_used_by_driver(stage_env):
    cfg = Settings(_env_file=None)
    validate_runtime(cfg)
    with patch("edu_api.db.session.create_async_engine") as factory:
        build_engine(cfg)
    kw = factory.call_args.kwargs
    ctx = kw["connect_args"]["ssl"]
    assert isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname and kw["pool_pre_ping"] and kw["pool_reset_on_return"] == "rollback"


@pytest.mark.xfail(
    strict=True, raises=ControlMiss, reason="QA-1: port number checked without host interface"
)
def test_binding_must_serve_validated_loopback(monkeypatch, tmp_path):
    monkeypatch.setattr(disposable, "layout", lambda: ("qa-synthetic", 30001, 30002))
    monkeypatch.setattr(disposable, "ROOT", tmp_path)
    monkeypatch.setattr(disposable, "require_local_docker", lambda: None)
    for key in (
        "EDU_DATABASE_URL",
        "EDU_AUTH_ISSUER",
        "EDU_AUTH_JWKS_URL",
        "LOCAL_ADMIN_DATABASE_URL",
        "LOCAL_SUPABASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    def fixture_inspect(cmd, *, text):
        db = cmd[-1].startswith("supabase_db_")
        return json.dumps(
            {
                ("5432/tcp" if db else "8000/tcp"): [
                    {"HostIp": "192.0.2.4", "HostPort": str(30002 if db else 30001)}
                ]
            }
        )

    monkeypatch.setattr(disposable.subprocess, "check_output", fixture_inspect)
    try:
        disposable.verify()
    except ValueError:
        return
    raise ControlMiss("accepted a binding that does not serve 127.0.0.1")


def test_manifest_rejects_byte_drift_with_same_version(monkeypatch, tmp_path):
    from shutil import copytree

    src = tmp_path / "supabase/migrations"
    copytree(ROOT / "supabase/migrations", src)
    target = sorted(src.glob("*.sql"))[-1]
    with target.open("a") as out:
        out.write("\n-- synthetic checksum perturbation\n")
    monkeypatch.setattr(staging_verify, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="manifest"):
        staging_verify.versions()
