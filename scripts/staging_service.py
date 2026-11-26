"""Explicit entry point for the example Render web service."""

from __future__ import annotations

import argparse
import json
import logging
import os

import uvicorn

from edu_api.config import Settings, require_canonical_settings
from edu_api.db.staging import validate_runtime
from edu_api.main import create_app


class EventFormatter(logging.Formatter):
    """Emit only reviewed event names; never interpolate an exception, URL or log argument."""

    def format(self, record: logging.LogRecord) -> str:
        events = {
            "Application startup complete.": "startup_complete",
            "Application shutdown complete.": "shutdown_complete",
            "sync operation conflict": "sync_conflict",
            "readiness check failed: %s": "readiness_failed",
            "JWKS refresh failed: %s": "jwks_refresh_failed",
            "access token rejected: %s": "token_rejected",
            "dependency unavailable: %s": "dependency_unavailable",
        }
        return json.dumps(
            {"level": record.levelname, "event": events.get(str(record.msg), "service_event")}
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=["staging"])
    args = parser.parse_args()
    if os.environ.get("EDU_ENVIRONMENT") != args.environment:
        parser.error("explicit environment must match EDU_ENVIRONMENT")
    try:
        require_canonical_settings(os.environ)
        settings = Settings(_env_file=None)
        validate_runtime(settings)
        port = int(os.environ["PORT"])
        if not 1 <= port <= 65535:
            raise ValueError
    except (KeyError, ValueError):
        parser.error("invalid staging settings; verify the approved project and secrets")
    handler = logging.StreamHandler()
    handler.setFormatter(EventFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",  # noqa: S104
        port=port,
        workers=1,
        log_config=None,
        access_log=False,
        proxy_headers=False,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=20,
        limit_concurrency=32,
    )
