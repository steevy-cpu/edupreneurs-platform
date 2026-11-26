"""Bind local Supabase mutations and integration fixtures to this checkout's containers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import getproxies_environment

from local_stack import ROOT, read_env_file

CONFIG = ROOT / "supabase/config.toml"
TAG = hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:12]
PROJECT = "edu-test-" + TAG
BASE = 30000 + 4 * (int(TAG[:8], 16) % 4500)


def configure() -> None:
    original = CONFIG.read_text()
    if tomllib.loads(original)["project_id"] == PROJECT:
        layout()
        return
    if (ROOT / ".env").exists() or (ROOT / "supabase/signing_keys.json").exists():
        raise ValueError("configure in a fresh, dedicated worktree")
    updated = original
    for old, new in (
        ('project_id = "mon-edupreneur"', f'project_id = "{PROJECT}"'),
        ("shadow_port = 54320", f"shadow_port = {BASE}"),
        ("port = 54321", f"port = {BASE + 1}"),
        ("port = 54322", f"port = {BASE + 2}"),
        ("port = 54323", f"port = {BASE + 3}"),
    ):
        if updated.count(old) != 1:
            raise ValueError("expected the repository default config")
        updated = updated.replace(old, new)
    CONFIG.write_text(updated)


def layout() -> tuple[str, int, int]:
    if any(
        os.getenv(k)
        for k in (
            "SUPABASE_WORKDIR",
            "SUPABASE_DB_URL",
            "DATABASE_URL",
            "PGHOST",
            "PGHOSTADDR",
            "PGPORT",
            "PGDATABASE",
            "PGUSER",
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGOPTIONS",
        )
    ):
        raise ValueError("remove external database and workdir overrides")
    if os.environ.get("EDU_ENVIRONMENT", "local") not in {"local", "test"}:
        raise ValueError("local or test environment required")
    cfg = tomllib.loads(CONFIG.read_text())
    project = cfg["project_id"]
    ports = (cfg["db"]["shadow_port"], cfg["api"]["port"], cfg["db"]["port"], cfg["studio"]["port"])
    # Compatibility with the existing hosted CI job in its own runner VM.
    ci = (
        os.getenv("GITHUB_ACTIONS") == "true"
        and os.getenv("RUNNER_ENVIRONMENT") == "github-hosted"
        and Path(os.getenv("GITHUB_WORKSPACE", "/")).resolve() == ROOT.resolve()
        and re.fullmatch(r"edu-ci-\d+-\d+", project)
        and project == f"edu-ci-{os.getenv('GITHUB_RUN_ID')}-{os.getenv('GITHUB_RUN_ATTEMPT')}"
    )
    expected = 54320 if ci else BASE
    if (not ci and project != PROJECT) or ports != tuple(range(expected, expected + 4)):
        raise ValueError(
            "expected disposable project; run disposable.py configure in a fresh worktree"
        )
    return project, ports[1], ports[2]


def validate_urls(env: dict[str, str], api: int, db: int) -> None:
    proxies = getproxies_environment()
    excluded = {part.strip() for part in proxies.get("no", "").split(",")}
    if any(proxies.get(k) for k in ("http", "all")) and not excluded.intersection(
        {"*", "127.0.0.1"}
    ):
        raise ValueError("loopback must bypass HTTP proxies for synthetic Auth tests")
    if env.get("EDU_ENVIRONMENT") not in {"local", "test"}:
        raise ValueError("unexpected .env environment")
    expected = {
        "LOCAL_ADMIN_DATABASE_URL": ("postgresql", db, "/postgres", "postgres"),
        "EDU_DATABASE_URL": ("postgresql+asyncpg", db, "/postgres", "edu_api_login"),
        "LOCAL_SUPABASE_URL": ("http", api, "", None),
        "EDU_AUTH_ISSUER": ("http", api, "/auth/v1", None),
        "EDU_AUTH_JWKS_URL": ("http", api, "/auth/v1/.well-known/jwks.json", None),
    }
    for key, (scheme, port, path, user) in expected.items():
        value = env.get(key, "")
        u = urlsplit(value)
        if (
            u.hostname != "127.0.0.1"
            or u.port != port
            or u.scheme != scheme
            or u.path != path
            or u.username != user
            or u.query
            or u.fragment
            or os.environ.get(key, value) != value
        ):
            raise ValueError(f"{key} does not match the disposable stack")


def require_local_docker() -> None:
    socket = os.environ.get("DOCKER_HOST")
    if socket and os.getenv("DOCKER_CONTEXT"):
        raise ValueError("conflicting Docker host and context overrides")
    if not socket:
        socket = subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True
        ).strip()
    if not socket.startswith("unix:///"):
        raise ValueError("expected a local Docker socket")


def verify(*, check_env: bool = False, env: dict[str, str] | None = None) -> str:
    project, api, db = layout()
    if check_env or env is not None or (ROOT / ".env").exists():
        validate_urls(read_env_file() if env is None else env, api, db)
    elif any(
        os.getenv(k)
        for k in (
            "EDU_DATABASE_URL",
            "EDU_AUTH_ISSUER",
            "EDU_AUTH_JWKS_URL",
            "LOCAL_ADMIN_DATABASE_URL",
            "LOCAL_SUPABASE_URL",
        )
    ):
        raise ValueError("unexpected endpoint overrides in an unconfigured worktree")
    require_local_docker()
    for component, internal, port in (("db", "5432/tcp", db), ("kong", "8000/tcp", api)):
        bindings = json.loads(
            subprocess.check_output(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{json .NetworkSettings.Ports}}",
                    f"supabase_{component}_{project}",
                ],
                text=True,
            )
        )
        if {int(b["HostPort"]) for b in bindings.get(internal) or []} != {port}:
            raise ValueError(f"unexpected {component} binding")
    return project


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("configure", "config", "running", "env"))
    action = parser.parse_args().action
    if action == "configure":
        configure()
    elif action == "config":
        layout()
        require_local_docker()
    else:
        verify(check_env=action == "env")
