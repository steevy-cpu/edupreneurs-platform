"""FastAPI dependencies shared by the routers."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from edu_api.auth.verifier import AuthUnavailable, InvalidToken, Principal, TokenVerifier
from edu_api.config import Settings
from edu_api.db.session import Database
from edu_api.errors import ApiError

logger = logging.getLogger("edu_api.auth")

# auto_error=False so that WE produce the 401 (in the standard error shape).
_bearer = HTTPBearer(
    auto_error=False,
    bearerFormat="JWT",
    description="Supabase Auth access token of the signed-in learner.",
)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Database:
    database: Database = request.app.state.db
    return database


async def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """Resolve the caller from a cryptographically verified access token.

    The client always gets the same generic 401; the precise reason is logged
    server-side only (and never includes the token).
    """
    challenge = {"WWW-Authenticate": "Bearer"}
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(
            401, "unauthenticated", "A valid access token is required.", headers=challenge
        )
    verifier: TokenVerifier = request.app.state.token_verifier
    try:
        return await verifier.verify(credentials.credentials)
    except InvalidToken as exc:
        logger.info("access token rejected: %s", exc.reason)
        raise ApiError(
            401, "unauthenticated", "A valid access token is required.", headers=challenge
        ) from None
    except AuthUnavailable:
        raise ApiError(
            503,
            "dependency_unavailable",
            "A required service is temporarily unavailable. Retry later.",
            headers={"Retry-After": "5"},
        ) from None


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
Db = Annotated[Database, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Locale = Annotated[
    Literal["fr", "ht"],
    Query(description="Content language: `fr` (French) or `ht` (Haitian Creole)."),
]
