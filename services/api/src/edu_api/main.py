"""Application factory.

uvicorn edu_api.main:create_app --factory   # reads environment / .env
create_app(settings, key_provider=...)      # tests inject settings and signing keys
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from edu_api import __version__
from edu_api.auth.jwks import JWKSCache, KeyProvider
from edu_api.auth.verifier import TokenVerifier
from edu_api.config import Settings, get_settings
from edu_api.db.session import Database, build_engine
from edu_api.db.staging import assert_database, validate_runtime
from edu_api.errors import install_error_handlers
from edu_api.middleware import BodyLimitMiddleware, RequestIdMiddleware
from edu_api.routers import catalog, health, me, sync


def create_app(
    settings: Settings | None = None, *, key_provider: KeyProvider | None = None
) -> FastAPI:
    if settings is None:
        settings = get_settings()
        validate_runtime(settings)
    elif settings.environment in {"staging", "production"}:
        validate_runtime(settings)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    jwks_cache: JWKSCache | None = None
    if key_provider is None:
        jwks_cache = JWKSCache(
            settings.auth_jwks_url,
            allowed_algorithms=frozenset(settings.auth_algorithms),
            cache_ttl_s=settings.auth_jwks_cache_ttl_s,
            min_refresh_interval_s=settings.auth_jwks_min_refresh_interval_s,
        )
        key_provider = jwks_cache

    # The staging lifespan checks its connection before accepting traffic.
    database = Database(build_engine(settings))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            if settings.environment == "staging":
                async with asyncio.timeout(5), database.transaction(None, read_only=True) as conn:
                    await assert_database(conn)
            yield
        finally:
            await database.dispose()
            if jwks_cache is not None:
                await jwks_cache.aclose()

    app = FastAPI(
        title="Mon Edupreneur API",
        version=__version__,
        description=(
            "Student API for Mon Edupreneur 2.0: identity, published catalog and lessons, "
            "and exactly-once offline sync. All `/v1` routes need a Supabase Auth access "
            "token (`Authorization: Bearer ...`). Errors always have the shape "
            '`{"error": {"code", "message", "request_id", "details"}}`.'
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = database
    app.state.token_verifier = TokenVerifier(
        key_provider,
        issuer=settings.auth_issuer,
        audience=settings.auth_audience,
        algorithms=settings.auth_algorithms,
        leeway_s=settings.auth_leeway_s,
    )

    install_error_handlers(app)
    # Order matters: the LAST middleware added runs FIRST, so request ids exist
    # before a body can be rejected.
    app.add_middleware(
        BodyLimitMiddleware,
        max_wire_bytes=settings.max_wire_body_bytes,
        max_decoded_bytes=settings.max_decoded_body_bytes,
    )
    app.add_middleware(RequestIdMiddleware)

    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(catalog.router)
    app.include_router(sync.router)
    return app
