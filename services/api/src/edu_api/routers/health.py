"""Liveness and readiness probes. Unauthenticated; they reveal nothing sensitive."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from edu_api.db.staging import SECURITY_SQL
from edu_api.deps import Db

logger = logging.getLogger("edu_api.health")
router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "unavailable"]]


@router.get("/health", response_model=HealthResponse, summary="Is the process alive?")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse, "description": "A dependency is unavailable."}},
    summary="Can the service reach its database?",
)
async def ready(db: Db, request: Request) -> JSONResponse:
    try:
        async with asyncio.timeout(3), db.transaction(None, read_only=True) as conn:
            if request.app.state.settings.environment == "staging":
                checks = (await conn.execute(text(SECURITY_SQL))).one()
                if (
                    not all(checks)
                    or await conn.scalar(text("SELECT current_user")) != "edu_api_login"
                ):
                    raise ValueError("database staging invariants failed")
            else:
                await conn.execute(text("SELECT 1"))
    except Exception as exc:  # readiness must never raise: report "not ready" instead
        logger.warning("readiness check failed: %s", type(exc).__name__)
        body = ReadyResponse(status="not_ready", checks={"database": "unavailable"})
        return JSONResponse(status_code=503, content=body.model_dump())
    body = ReadyResponse(status="ready", checks={"database": "ok"})
    return JSONResponse(status_code=200, content=body.model_dump())
