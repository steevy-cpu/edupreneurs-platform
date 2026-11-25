"""Response models for the rewards read API.

There is no request model on purpose: the device never sends an amount, a
balance or a learner id. Gold is only ever read.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class LedgerEntry(BaseModel):
    id: uuid.UUID
    kind: Literal["award", "reversal"]
    amount: int = Field(description="Gold. Positive for an award, negative for a reversal.")
    source: Literal["question_first_correct", "lesson_first_completed", "achievement", "reversal"]
    lesson_id: uuid.UUID | None = None
    question_key: str | None = None
    achievement_code: str | None = None
    op_id: uuid.UUID | None = Field(
        default=None, description="The accepted sync operation that earned this entry."
    )
    day: date = Field(description="Haiti calendar date on which the server accepted it.")
    created_at: datetime


class StreakSummary(BaseModel):
    current_days: int = Field(
        description="Consecutive active days up to today or yesterday; 0 when there is "
        "no run in progress. There is deliberately no 'lost streak' state."
    )
    longest_days: int
    last_active_day: date | None
    active_today: bool


class EarnedAchievement(BaseModel):
    code: str
    titles: dict[str, str] = Field(description="Draft wording by locale (`fr`, `ht`).")
    earned_at: datetime
    gold: int = Field(description="One-off Gold bonus credited with it (0 if none).")


class RewardsSummary(BaseModel):
    balance: int
    lifetime_earned: int
    streak: StreakSummary
    achievements: list[EarnedAchievement]
    recent: list[LedgerEntry]
    today: date = Field(description="The server's current Haiti calendar date.")
    up_to_date: bool = Field(
        description="False while accepted operations are still waiting to be examined."
    )
    rules_status: Literal["provisional"] = Field(
        default="provisional",
        description="Reward amounts are placeholders until the product owner decides them.",
    )


class LedgerPage(BaseModel):
    entries: list[LedgerEntry]
    next_cursor: str | None = Field(
        description="Pass back as `cursor` for older entries; null on the last page."
    )
    has_more: bool
    balance: int
