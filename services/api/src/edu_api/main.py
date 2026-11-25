"""Application factory.

uvicorn edu_api.main:create_app --factory   # reads environment / .env
create_app(settings, key_provider=...)      # tests inject settings and signing keys
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from edu_api import __version__
from edu_api.auth.jwks import JWKSCache, KeyProvider
from edu_api.auth.verifier import TokenVerifier
from edu_api.config import Settings, get_settings
from edu_api.db.session import Database, build_engine
from edu_api.errors import install_error_handlers
from edu_api.logging_config import AccessLogMiddleware, install_json_logging
from edu_api.middleware import BodyLimitMiddleware, RequestIdMiddleware
from edu_api.ratelimit import RateLimitMiddleware, build_rate_limiter
from edu_api.routers import catalog, health, me, notifications, staff, sync
from edu_api.staff.db import build_staff_database


def create_app(
    settings: Settings | None = None, *, key_provider: KeyProvider | None = None
) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Lane notify, Part B: opt-in JSON logs. With the default "text" nothing changes.
    json_logging = install_json_logging() if settings.log_format == "json" else None

    jwks_cache: JWKSCache | None = None
    if key_provider is None:
        jwks_cache = JWKSCache(
            settings.auth_jwks_url,
            allowed_algorithms=frozenset(settings.auth_algorithms),
            cache_ttl_s=settings.auth_jwks_cache_ttl_s,
            min_refresh_interval_s=settings.auth_jwks_min_refresh_interval_s,
        )
        key_provider = jwks_cache

    # Creating the engine opens no connection; the first request does.
    database = Database(build_engine(settings))
    # The staff side has its own pool and its own database login (edu_staff_login).
    # None when EDU_STAFF_DATABASE_URL is unset: staff routes then answer 503.
    staff_database = build_staff_database(settings)
    # Lane notify: only when the flag is on; its own small pool (see config.py).
    notify_database = (
        notifications.build_database(settings) if settings.notifications_enabled else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await database.dispose()
        if staff_database is not None:
            await staff_database.dispose()
        if notify_database is not None:
            await notify_database.dispose()
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
    app.state.staff_db = staff_database
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
    # Lane notify, Part B (both opt-in, both absent by default). Added here so that
    # they run AFTER the request id exists and BEFORE a body is read.
    if settings.rate_limit_enabled:
        app.state.rate_limiter = build_rate_limiter(settings)
        app.add_middleware(
            RateLimitMiddleware,
            limiter=app.state.rate_limiter,
            verifier=app.state.token_verifier,
            trusted_proxy_hops=settings.rate_limit_trusted_proxy_hops,
        )
    if json_logging is not None:
        app.state.json_log_handler, app.state.json_logging_undo = json_logging
        actor_key = settings.log_actor_hash_key
        app.add_middleware(
            AccessLogMiddleware,
            verifier=app.state.token_verifier,
            actor_key=actor_key.get_secret_value().encode("utf-8") if actor_key else None,
        )
    app.add_middleware(RequestIdMiddleware)

    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(catalog.router)
    app.include_router(sync.router)
    # Documented only where the staff side is switched on, so the learner
    # contract (packages/contracts/openapi.json) is unchanged by its existence.
    app.include_router(staff.router, include_in_schema=staff_database is not None)
    # Always registered (ruling R-01); every route answers 404 while the flag is off.
    if notify_database is not None:
        app.state.notify_db = notify_database
    app.include_router(notifications.router)
    return app
