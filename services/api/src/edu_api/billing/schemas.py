"""Response models for ``GET /v1/entitlements``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ScopeKind = Literal["all", "grade", "course"]
EntitlementSource = Literal[
    "purchase", "gift", "promo", "school_licence", "trial", "staff_grant", "migration"
]


class EntitlementScope(BaseModel):
    kind: ScopeKind = Field(description="`all`, one `grade`, or one `course`.")
    id: uuid.UUID | None = Field(
        description="The grade id or course id; `null` when `kind` is `all`."
    )


class Entitlement(BaseModel):
    id: uuid.UUID
    scope: EntitlementScope
    starts_at: datetime
    ends_at: datetime = Field(
        description="Exclusive end: the grant is active while `starts_at <= server_time < ends_at`."
    )
    source: EntitlementSource


class EntitlementsResponse(BaseModel):
    server_time: datetime = Field(
        description="The server's clock when the grants were read. Compare `ends_at` with "
        "this value, never with the device clock."
    )
    free_content_always_available: Literal[True] = Field(
        default=True,
        description="Always `true`: free lessons never depend on an entitlement, on this "
        "endpoint answering, or on the device being online.",
    )
    entitlements: list[Entitlement] = Field(
        description="The caller's own grants that are active now (not expired, not revoked, "
        "already started). Overlapping grants are all listed; access is any one of them."
    )
