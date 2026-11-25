"""Runtime configuration, read from environment variables (prefix ``EDU_``).

Nothing here has a secret default. Locally, ``make setup`` writes a git-ignored
``.env`` file; in a hosted environment the platform's secret manager provides
the same variables.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Only asymmetric algorithms are accepted. With ES256/RS256 the API holds a
#: PUBLIC key and can verify tokens but never mint them. Shared-secret HS256 is
#: deliberately unsupported: it would make the API able to forge any identity.
SUPPORTED_JWT_ALGORITHMS = frozenset({"ES256", "RS256"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EDU_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: Literal["local", "test", "staging", "production"] = "local"

    # --- Database -----------------------------------------------------------
    #: Must log in as ``edu_api_login`` (member of ``edu_api``). Never postgres,
    #: service_role, or any role with BYPASSRLS.
    database_url: SecretStr
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_pool_timeout_s: float = Field(default=5.0, gt=0)
    db_connect_timeout_s: float = Field(default=3.0, gt=0)
    db_statement_timeout_ms: int = Field(default=5000, ge=100)
    #: Set true behind a transaction-mode pooler (Supavisor/PgBouncer), which
    #: cannot keep asyncpg's prepared statements between transactions.
    db_disable_statement_cache: bool = False

    # --- Auth (Supabase Auth access tokens) ----------------------------------
    auth_issuer: str
    auth_audience: str = "authenticated"
    auth_jwks_url: str
    auth_algorithms: tuple[str, ...] = ("ES256",)
    auth_leeway_s: int = Field(default=30, ge=0, le=120)
    auth_jwks_cache_ttl_s: int = Field(default=600, ge=1)
    auth_jwks_min_refresh_interval_s: int = Field(default=30, ge=0)

    # --- Offline sync limits --------------------------------------------------
    sync_max_ops: int = Field(default=50, ge=1, le=500)
    #: Largest request body accepted on the wire (compressed size when gzip is used).
    max_wire_body_bytes: int = Field(default=20 * 1024, ge=1024)
    #: Largest request body after gzip decompression (guards against zip bombs).
    max_decoded_body_bytes: int = Field(default=128 * 1024, ge=1024)
    pull_default_limit: int = Field(default=100, ge=1)
    pull_max_limit: int = Field(default=200, ge=1)

    # --- Rewards lane (overnight 2026-11-24): Gold ledger, streaks, achievements ---
    #: OFF by default. Off = the push path and every response are exactly as
    #: before, and /v1/rewards/* answers 404. Reward amounts are synthetic
    #: placeholders until the owner decides PO-09.
    rewards_enabled: bool = False
    rewards_ledger_default_limit: int = Field(default=20, ge=1, le=100)
    rewards_ledger_max_limit: int = Field(default=100, ge=1, le=500)
    rewards_recent_limit: int = Field(default=5, ge=1, le=20)
    #: Most unexamined operations healed by one summary request.
    rewards_reconcile_limit: int = Field(default=200, ge=1, le=500)
    # --- end rewards lane ---

    @field_validator("auth_algorithms")
    @classmethod
    def _only_asymmetric(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unsupported = set(value) - SUPPORTED_JWT_ALGORITHMS
        if not value or unsupported:
            raise ValueError(
                f"auth_algorithms must be a non-empty subset of {sorted(SUPPORTED_JWT_ALGORITHMS)}"
            )
        return value

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must start with postgresql+asyncpg://")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
