"""Request and response shapes of the learner-facing notification routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

#: Mirrors the CHECK constraints in supabase/migrations/20261124080100_notify_outbox.sql.
Category = Literal["account", "learning", "reminders"]
CATEGORIES: tuple[Category, ...] = ("account", "learning", "reminders")
PRODUCT_TIME_ZONE = "America/Port-au-Prince"

#: Wall-clock time of day, 24-hour ``HH:MM``, in the product time zone.
TimeOfDay = Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]


class QuietHours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: TimeOfDay
    end: TimeOfDay

    @model_validator(mode="after")
    def _not_empty(self) -> QuietHours:
        if self.start == self.end:
            raise ValueError("start and end must differ")
        return self


class PreferencesUpdate(BaseModel):
    """Full replacement of the caller's preferences. There is no user id field."""

    model_config = ConfigDict(extra="forbid")

    push_enabled: StrictBool = Field(
        description="Opt in to push delivery. Off by default. Nothing is sent by this build."
    )
    muted_categories: list[Category] = Field(
        max_length=len(CATEGORIES),
        description="Categories that must not be pushed. The in-app list is unaffected.",
    )
    quiet_hours: QuietHours | None = Field(
        description="The learner's own quiet window, in addition to the platform's. "
        "`null` for none. May wrap midnight."
    )


class PreferencesResponse(BaseModel):
    push_enabled: bool
    muted_categories: list[Category]
    quiet_hours: QuietHours | None
    platform_quiet_hours: QuietHours = Field(
        description="Always applies, whatever the learner chooses. Synthetic default; "
        "the real policy is an open product decision."
    )
    time_zone: Literal["America/Port-au-Prince"] = Field(
        description="Every time of day above is wall-clock time in this zone, not the device's."
    )
    categories: list[Category] = Field(description="Every category that can be muted.")
    updated_at: datetime | None = Field(description="`null` until preferences are first saved.")


class NotificationItem(BaseModel):
    id: uuid.UUID
    kind: str = Field(description="What happened. The app renders the words in its own language.")
    category: Category
    refs: dict[str, uuid.UUID] = Field(
        description="Opaque reference ids (for example `word_id`). Never text."
    )
    available_at: datetime
    expires_at: datetime | None


class NotificationList(BaseModel):
    items: list[NotificationItem]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get older items. `null` when there are none."
    )
