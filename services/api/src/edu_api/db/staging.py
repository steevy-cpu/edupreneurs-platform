"""Staging policy is checked by the serving process, independently of deployment tooling."""

import re
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from edu_api.config import Settings

SECURITY_SQL = Path(__file__).with_name("staging_security.sql").read_text().strip()


def validate_hosted_dsn(value: str, project: str, role: str, scheme: str) -> None:
    """Direct Postgres or the pinned Virginia Supavisor session endpoint."""
    u = urlsplit(value)
    direct = u.hostname == f"db.{project}.supabase.co" and u.username == role
    pooled = (
        u.hostname in {"aws-0-us-east-1.pooler.supabase.com", "aws-1-us-east-1.pooler.supabase.com"}
        and u.username == f"{role}.{project}"
    )
    if (
        not (direct or pooled)
        or u.scheme != scheme
        or u.port != 5432
        or not u.password
        or u.path != "/postgres"
        or u.query
        or u.fragment
    ):
        raise ValueError("database target does not match the selected project and login")


def validate_runtime(settings: Settings) -> None:
    if settings.environment == "production":
        raise ValueError("production has no approved deployment profile")
    if settings.environment in {"local", "test"}:
        db = urlsplit(settings.database_url.get_secret_value())
        issuer = urlsplit(settings.auth_issuer)
        if (
            db.hostname not in {"127.0.0.1", "localhost", "::1"}
            or db.username != "edu_api_login"
            or db.query
            or db.fragment
            or db.path != "/postgres"
            or issuer.hostname not in {"127.0.0.1", "localhost", "::1"}
            or issuer.scheme != "http"
            or issuer.username
            or issuer.query
            or issuer.fragment
            or issuer.path != "/auth/v1"
            or settings.auth_jwks_url != settings.auth_issuer + "/.well-known/jwks.json"
        ):
            raise ValueError("local runtime requires local database and Auth endpoints")
        return
    project = settings.staging_project_ref or ""
    if not re.fullmatch(r"[a-z0-9]{20}", project):
        raise ValueError("a separately approved staging project reference is required")
    issuer_url = f"https://{project}.supabase.co/auth/v1"
    if (
        settings.auth_issuer != issuer_url
        or settings.auth_jwks_url != issuer_url + "/.well-known/jwks.json"
        or settings.auth_audience != "authenticated"
    ):
        raise ValueError("staging Auth endpoints or audience mismatch")
    validate_hosted_dsn(
        settings.database_url.get_secret_value(), project, "edu_api_login", "postgresql+asyncpg"
    )


async def assert_database(conn: AsyncConnection) -> None:
    checks = (await conn.execute(text(SECURITY_SQL))).one()
    if not all(checks) or await conn.scalar(text("SELECT current_user")) != "edu_api_login":
        raise ValueError("database staging invariants failed")
