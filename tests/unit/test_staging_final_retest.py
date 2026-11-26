"""Check both maintenance entry points against inert config, Docker, socket and HTTP adapters."""

import json
import os
from contextlib import nullcontext
from unittest.mock import Mock

import httpx
import pytest

import dev_login
import dev_token
import disposable


@pytest.mark.parametrize("helper", [dev_login, dev_token], ids=["dev-login", "token"])
@pytest.mark.parametrize(
    "case",
    [
        "other_project",
        "shared_project",
        "auth_port",
        "inherited",
        "case",
        "db_binding",
        "gateway_binding",
        "absent_listener",
    ],
)
def test_maintenance_rejects_before_http(case, helper, monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.upper().startswith(("LOCAL_", "EDU_", "PG", "DOCKER_", "SUPABASE_")):
            monkeypatch.delenv(key)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    base = disposable.BASE
    project = {"shared_project": "mon-edupreneur", "other_project": "edu-test-other"}.get(
        case, disposable.PROJECT
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'project_id="{project}"\n[api]\nport={base + 1}\n[db]\nport={base + 2}\n'
        f"shadow_port={base}\n[studio]\nport={base + 3}\n"
    )
    monkeypatch.setattr(disposable, "CONFIG", cfg)
    gateway = f"http://127.0.0.1:{base + 1}"
    env = {
        "EDU_ENVIRONMENT": "local",
        "LOCAL_SUPABASE_URL": gateway if case != "auth_port" else "http://127.0.0.1:1",
        "EDU_AUTH_ISSUER": gateway + "/auth/v1",
        "EDU_AUTH_JWKS_URL": gateway + "/auth/v1/.well-known/jwks.json",
        "LOCAL_ADMIN_DATABASE_URL": f"postgresql://postgres:inert@127.0.0.1:{base + 2}/postgres",
        "EDU_DATABASE_URL": f"postgresql+asyncpg://edu_api_login:inert@127.0.0.1:{base + 2}/postgres",
        "LOCAL_SUPABASE_SECRET_KEY": "inert",
        "LOCAL_SUPABASE_PUBLISHABLE_KEY": "inert",
    }
    if case == "inherited":
        monkeypatch.setenv("LOCAL_SUPABASE_URL", "http://127.0.0.1:1")
    if case == "case":
        monkeypatch.setenv("Edu_Auth_Issuer", "http://127.0.0.1:1/auth/v1")

    def inspect(args, *, text):
        if args[1] == "context":
            return "unix:///synthetic/docker.sock"
        assert args[1] == "inspect"
        db = args[-1] == f"supabase_db_{disposable.PROJECT}"
        assert db or args[-1] == f"supabase_kong_{disposable.PROJECT}"
        wrong_interface = (db and case == "db_binding") or (not db and case == "gateway_binding")
        return json.dumps(
            {
                ("5432/tcp" if db else "8000/tcp"): [
                    {
                        "HostIp": "::1" if wrong_interface else "127.0.0.1",
                        "HostPort": str(base + (2 if db else 1)),
                    }
                ]
            }
        )

    monkeypatch.setattr(helper, "read_env_file", lambda: env)
    monkeypatch.setattr(disposable.subprocess, "check_output", inspect)
    tcp = Mock(return_value=nullcontext())
    if case == "absent_listener":
        tcp.side_effect = [nullcontext(), ConnectionRefusedError()]
    monkeypatch.setattr(disposable.socket, "create_connection", tcp)
    http = Mock(side_effect=AssertionError("unexpected HTTP call"))
    monkeypatch.setattr(httpx.Client, "send", http)
    with pytest.raises(ValueError):
        if helper is dev_login:
            helper.main("student_a")
        else:
            helper.issue_token("student_a")
    http.assert_not_called()
    assert tcp.call_count == (2 if case == "absent_listener" else 0)
