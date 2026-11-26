"""Real single-process launcher and HTTP; substitute only a checkout-bound local app for hosted I/O."""

import multiprocessing
import os
import runpy
import socket
import sys
import time
from unittest.mock import patch

import httpx
import pytest

import disposable
from edu_api.main import create_app
from local_stack import ROOT, read_env_file
from tests.conftest import build_settings


def serve(port, concurrency):
    env = read_env_file()
    disposable.verify(env=env)
    cfg = build_settings(env, db_pool_size=3, db_max_overflow=1)
    app = create_app(cfg)
    cfg.environment = "staging"  # exercise the staging lifespan and SQL through the local engine

    @app.get("/__qa_process")
    def identity():
        return os.getpid()

    ref = "q" * 20
    issuer = f"https://{ref}.supabase.co/auth/v1"
    synthetic = {
        "PORT": str(port),
        "WEB_CONCURRENCY": str(concurrency),
        "EDU_ENVIRONMENT": "staging",
        "EDU_STAGING_PROJECT_REF": ref,
        "EDU_AUTH_ISSUER": issuer,
        "EDU_AUTH_JWKS_URL": issuer + "/.well-known/jwks.json",
        "EDU_DATABASE_URL": f"postgresql+asyncpg://edu_api_login:inert@db.{ref}.supabase.co:5432/postgres",
    }
    with (
        patch.dict(os.environ, synthetic),
        patch("edu_api.main.create_app", return_value=app),
        patch.object(sys, "argv", ["staging_service.py", "--environment", "staging"]),
    ):
        runpy.run_path(str(ROOT / "scripts/staging_service.py"), run_name="__main__")


@pytest.mark.parametrize("concurrency", [1, 2])
def test_launcher_serves_from_original_process(local_env, concurrency):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    proc = multiprocessing.get_context("spawn").Process(target=serve, args=(port, concurrency))
    proc.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=3) as http:
            deadline = time.monotonic() + 20
            while proc.is_alive() and time.monotonic() < deadline:
                try:
                    response = http.get("/__qa_process")
                except httpx.ConnectError:
                    time.sleep(0.1)
                    continue
                assert response.json() == proc.pid
                break
            else:
                pytest.fail("launcher did not serve from its original process")
            assert http.get("/health").json()["status"] == "ok"
            ready = http.get("/ready")
            assert ready.status_code == 200 and ready.json()["checks"] == {"database": "ok"}
    finally:
        if proc.is_alive():
            proc.terminate()
        proc.join(10)
        if proc.is_alive():
            proc.kill()
            proc.join()
