"""Tutor configuration (environment prefix ``EDU_TUTOR_``).

Kept apart from ``edu_api.config`` on purpose: the tutor is not wired into the
application yet, and reading these settings must never be able to stop the
API from starting.

Every default is the SAFE one: disabled, mock provider, live calls not
authorised. Limits and prices below are placeholders so the code can run in
tests — the real numbers are owner decisions (docs/jude-01/10-open-decisions.md).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from edu_api.tutor.budget import BudgetPolicy, ModelPrice
from edu_api.tutor.prompts import DEFAULT_PROMPT_VERSION
from edu_api.tutor.providers.mock import MOCK_MODEL


class PriceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_version: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    input_micro_per_mtok: int = Field(ge=0)
    output_micro_per_mtok: int = Field(ge=0)

    def to_price(self) -> ModelPrice:
        return ModelPrice(
            self.price_version, self.model, self.input_micro_per_mtok, self.output_micro_per_mtok
        )


#: Synthetic price for the mock model so cost accounting is exercised. Not a real price.
SYNTHETIC_MOCK_PRICE = PriceEntry(
    price_version="synthetic-2026-11",
    model=MOCK_MODEL,
    input_micro_per_mtok=500_000,
    output_micro_per_mtok=1_500_000,
)


class TutorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EDU_TUTOR_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- switches -------------------------------------------------------------------
    #: Master switch. Off: every request is refused before anything else happens.
    enabled: bool = False
    #: Static kill switch, in addition to the one in the usage store.
    paused: bool = False

    # --- provider -------------------------------------------------------------------
    provider: Literal["mock", "openai_compatible"] = "mock"
    #: Must be set true by the owner before any adapter that leaves the machine is built.
    live_provider_calls_authorized: bool = False
    model: str = MOCK_MODEL
    fallback_model: str | None = None
    allow_costlier_fallback: bool = False
    provider_base_url: str | None = None
    provider_api_key: SecretStr | None = None
    request_timeout_s: float = Field(default=20.0, gt=0, le=120)
    max_attempts: int = Field(default=2, ge=1, le=4)
    max_output_tokens: int = Field(default=500, ge=50, le=2000)
    temperature: float = Field(default=0.2, ge=0, le=1)

    # --- prompt and retrieval ---------------------------------------------------------
    prompt_version: str = DEFAULT_PROMPT_VERSION
    retrieval_top_k: int = Field(default=4, ge=1, le=10)
    max_context_chars: int = Field(default=6000, ge=200, le=20000)
    #: Let the model add labelled general school knowledge beyond the lesson.
    allow_general_answers: bool = True

    # --- budget (PLACEHOLDERS; owner decisions) ------------------------------------------
    learner_daily_requests: int = Field(default=20, ge=0)
    learner_daily_micro: int = Field(default=50_000, ge=0)
    learner_monthly_micro: int = Field(default=500_000, ge=0)
    global_monthly_micro: int = Field(default=50_000_000, ge=0)
    max_concurrent_per_learner: int = Field(default=1, ge=1)
    max_concurrent_global: int = Field(default=20, ge=1)
    reservation_ttl_s: int = Field(default=120, ge=1)
    budget_timezone: str = "America/Port-au-Prince"
    prices: tuple[PriceEntry, ...] = (SYNTHETIC_MOCK_PRICE,)

    @model_validator(mode="after")
    def _consistent(self) -> TutorSettings:
        models = [p.model for p in self.prices]
        if len(models) != len(set(models)):
            raise ValueError("prices must list each model once (one active price per model)")
        needed = [self.model] + ([self.fallback_model] if self.fallback_model else [])
        missing = [m for m in needed if m not in models]
        if missing:
            raise ValueError(f"no price configured for model(s): {missing}")
        # +1 call for a possible fallback, +10 s for retry pauses and bookkeeping.
        if self.reservation_ttl_s <= self.request_timeout_s * (self.max_attempts + 1) + 10:
            raise ValueError(
                "reservation_ttl_s must exceed the longest a request can run "
                "(request_timeout_s * (max_attempts + 1) + 10), or a reservation could "
                "expire while its request is still in flight"
            )
        return self

    def price_for(self, model: str) -> ModelPrice:
        return next(p for p in self.prices if p.model == model).to_price()

    def budget_policy(self) -> BudgetPolicy:
        return BudgetPolicy(
            learner_daily_requests=self.learner_daily_requests,
            learner_daily_micro=self.learner_daily_micro,
            learner_monthly_micro=self.learner_monthly_micro,
            global_monthly_micro=self.global_monthly_micro,
            max_concurrent_per_learner=self.max_concurrent_per_learner,
            max_concurrent_global=self.max_concurrent_global,
            reservation_ttl_s=self.reservation_ttl_s,
            timezone=self.budget_timezone,
        )
