"""Synthetic Docker metadata, TCP connections and Auth transport; no network traffic."""

import json
import os
from contextlib import nullcontext
from unittest.mock import patch

import httpx
import pytest

import dev_login
import dev_token
import disposable
import local_stack
from edu_api.config import Settings


@pytest.fixture
def owned(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.upper().startswith(("EDU_", "LOCAL_")):
            monkeypatch.delenv(key)
    env = {
        "EDU_ENVIRONMENT": "local",
        "EDU_DATABASE_URL": "postgresql+asyncpg://edu_api_login:x@127.0.0.1:30102/postgres",
        "LOCAL_ADMIN_DATABASE_URL": "postgresql://postgres:x@127.0.0.1:30102/postgres",
        "LOCAL_SUPABASE_URL": "http://127.0.0.1:30101",
        "EDU_AUTH_ISSUER": "http://127.0.0.1:30101/auth/v1",
        "EDU_AUTH_JWKS_URL": "http://127.0.0.1:30101/auth/v1/.well-known/jwks.json",
        "LOCAL_SUPABASE_SECRET_KEY": "fixture",
        "LOCAL_SUPABASE_PUBLISHABLE_KEY": "public-fixture",
    }
    monkeypatch.setattr(disposable, "layout", lambda: ("edu-test-fixture", 30101, 30102))
    monkeypatch.setattr(disposable, "ROOT", tmp_path)
    monkeypatch.setattr(disposable, "require_local_docker", lambda: None)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    return env


@pytest.mark.parametrize("address", ["127.0.0.1", "0.0.0.0", "::1", "192.0.2.1"])  # noqa: S104
def test_gateway_binding_before_tcp(owned, monkeypatch, address):
    def inspect(args, *, text):
        if args[-1] == "supabase_db_edu-test-fixture":
            return '{"5432/tcp":[{"HostIp":"127.0.0.1","HostPort":"30102"}]}'
        assert args[-1] == "supabase_kong_edu-test-fixture"
        return json.dumps({"8000/tcp": [{"HostIp": address, "HostPort": "30101"}]})

    monkeypatch.setattr(disposable.subprocess, "check_output", inspect)
    with patch.object(
        disposable.socket, "create_connection", return_value=nullcontext()
    ) as connect:
        if address in {"::1", "192.0.2.1"}:
            with pytest.raises(ValueError, match="kong binding"):
                disposable.verify(env=owned)
            connect.assert_not_called()
        else:
            assert disposable.verify(env=owned) == "edu-test-fixture"
            assert [c.args[0] for c in connect.call_args_list] == [
                ("127.0.0.1", 30102),
                ("127.0.0.1", 30101),
            ]
            connect.side_effect = ConnectionRefusedError()
            with pytest.raises(ValueError, match="unreachable"):
                disposable.verify(env=owned)


@pytest.mark.parametrize("helper", [dev_login, dev_token])
@pytest.mark.parametrize("conflict", ["gateway", "key", "mixed_case", "shared_database"])
def test_helper_rejects_conflicts_before_transport(owned, helper, conflict, monkeypatch):
    match conflict:
        case "gateway":
            owned["LOCAL_SUPABASE_URL"] = "http://127.0.0.1:54321"
        case "key":
            monkeypatch.setenv("LOCAL_SUPABASE_SECRET_KEY", "different-fixture")
        case "mixed_case":
            monkeypatch.setenv("Edu_Auth_Jwks_Url", "http://127.0.0.1:54321")
        case "shared_database":
            owned["EDU_DATABASE_URL"] = owned["EDU_DATABASE_URL"].replace("30102", "54322")
    monkeypatch.setattr(helper, "read_env_file", lambda: owned)
    with patch.object(httpx.Client, "send") as http, pytest.raises(ValueError):
        if helper is dev_login:
            dev_login.main("student_a")
        else:
            dev_token.issue_token("student_a")
    http.assert_not_called()


def test_generated_file_and_effective_settings_agree(owned, tmp_path, monkeypatch):
    file = tmp_path / ".env"
    monkeypatch.setattr(local_stack, "ENV_FILE", file)
    file.write_text("".join(f'export {key}="{value}"\n' for key, value in owned.items()))
    env = local_stack.read_env_file()
    disposable.validate_urls(env, 30101, 30102)
    effective = Settings(_env_file=file)
    assert (
        effective.database_url.get_secret_value(),
        effective.auth_issuer,
        effective.auth_jwks_url,
    ) == (env["EDU_DATABASE_URL"], env["EDU_AUTH_ISSUER"], env["EDU_AUTH_JWKS_URL"])
    with file.open("a") as out:
        out.write("export edu_auth_issuer=http://127.0.0.1:54321/auth/v1\n")
    with pytest.raises(ValueError, match="uppercase"):
        disposable.validate_urls(local_stack.read_env_file(), 30101, 30102)
