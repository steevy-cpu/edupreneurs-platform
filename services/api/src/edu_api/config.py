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

    # --- Staff boundary (overnight 2026-11-24, staff lane) -------------------
    #: Optional. Must log in as ``edu_staff_login`` (member of ``edu_staff`` only).
    #: When unset the staff side is off: every ``/v1/staff`` route answers 503
    #: and none of them appears in the OpenAPI document.
    staff_database_url: SecretStr | None = None
    staff_db_pool_size: int = Field(default=2, ge=1, le=20)
    staff_db_max_overflow: int = Field(default=3, ge=0, le=20)

    # --- Notifications (lane notify; policy is product decision PO-10) ---------
    #: Off by default: the routes answer 404 and no extra database pool is
    #: created. Turning it on sends NOTHING; it only lets a learner read
    #: their own in-app list and edit their own preferences.
    notifications_enabled: bool = False
    #: Notification routes use their OWN small pool so that a slow or broken
    #: `notify` schema can never use up the connections lessons and sync need.
    notify_db_pool_size: int = Field(default=2, ge=1, le=10)
    notify_db_pool_timeout_s: float = Field(default=1.0, gt=0)
    notify_db_statement_timeout_ms: int = Field(default=2000, ge=100)
    notifications_default_limit: int = Field(default=20, ge=1)
    notifications_max_limit: int = Field(default=50, ge=1)

    # --- Rate limiting and structured logs (lane notify, Part B) ----------------
    #: Off by default: no middleware is added. PER PROCESS, in memory — a hosted
    #: multi-instance deployment still needs a gateway/shared-store limiter.
    rate_limit_enabled: bool = False
    #: Each budget: `burst` requests at once, refilled at `per_minute`.
    #: Verified learners, per learner and route class:
    rate_limit_read_burst: int = Field(default=60, ge=1, le=10_000)
    rate_limit_read_per_minute: int = Field(default=240, ge=1, le=100_000)
    rate_limit_write_burst: int = Field(default=20, ge=1, le=10_000)
    rate_limit_write_per_minute: int = Field(default=60, ge=1, le=100_000)
    #: POST /v1/sync/push. 40 batches of 50 = a 2000-operation offline backlog at once.
    rate_limit_sync_push_burst: int = Field(default=40, ge=1, le=10_000)
    rate_limit_sync_push_per_minute: int = Field(default=120, ge=1, le=100_000)
    #: Requests without a VERIFIED token, per client address, all routes together.
    rate_limit_anonymous_burst: int = Field(default=30, ge=1, le=10_000)
    rate_limit_anonymous_per_minute: int = Field(default=60, ge=1, le=100_000)
    #: Upper bound on buckets kept in memory (least recently used are dropped).
    rate_limit_max_keys: int = Field(default=20_000, ge=10, le=1_000_000)
    #: How many reverse proxies in front of the API are trusted to append to
    #: X-Forwarded-For. 0 = ignore the header and use the socket peer.
    rate_limit_trusted_proxy_hops: int = Field(default=0, ge=0, le=5)

    #: "text" = unchanged default formatting. "json" = one JSON line per record
    #: plus one line per request, without personal data (see logging_config.py).
    log_format: Literal["text", "json"] = "text"
    #: Optional key for a pseudonymous `actor` field in request lines. Unset = no
    #: actor field at all. Never the raw user id.
    log_actor_hash_key: SecretStr | None = None

    @field_validator("log_actor_hash_key")
    @classmethod
    def _long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("log_actor_hash_key must be at least 32 bytes")
        return value

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

    # --- Staff boundary (overnight 2026-11-24, staff lane) -------------------
    @field_validator("staff_database_url", mode="before")
    @classmethod
    def _blank_staff_url_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("staff_database_url")
    @classmethod
    def _staff_asyncpg_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("staff_database_url must start with postgresql+asyncpg://")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
