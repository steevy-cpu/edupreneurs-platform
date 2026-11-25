"""Response models of the leaderboard lane. Pseudonyms only: no names, no e-mail."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field


class CohortStanding(BaseModel):
    """The caller's own place inside the one cohort it opted in to."""

    cohort_id: uuid.UUID
    pseudonym: str = Field(description="Assigned by the server from an allow-list.")
    rank: int | None = Field(
        description="Competition rank (1, 1, 3) in the latest snapshot; null until one exists "
        "and for a cohort below the minimum size."
    )
    size: int | None = Field(
        description="Members ranked in that snapshot; null until one exists and for a cohort "
        "below the minimum size."
    )
    snapshot_gold: int | None = Field(description="The caller's Gold as counted by that snapshot.")
    computed_at: dt.datetime | None = Field(description="When the snapshot was computed.")
    frozen: bool = Field(description="True for the closing snapshot of a period that has ended.")


class MyStanding(BaseModel):
    period: str = Field(description="`all`, or the Monday (YYYY-MM-DD) that starts the week.")
    kind: Literal["all_time", "week"]
    starts_on: dt.date | None
    ends_on: dt.date | None
    closed: bool
    gold: int = Field(ge=0, description="The caller's own Gold earned by learning in the period.")
    cohort: CohortStanding | None = Field(
        description="Null unless the caller explicitly opted in to a cohort."
    )
