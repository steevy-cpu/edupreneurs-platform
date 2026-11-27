"""Request and response models of the staff entitlement routes (``/v1/staff/billing``).

Nothing here is free text: reasons are codes. What a staff member types never
reaches the audit log (director ruling R-03).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edu_api.billing.schemas import EntitlementScope, EntitlementSource

#: Mirrors billing.staff_grant_entitlement. 'purchase' is absent on purpose: a
#: purchase grant can only come from a verified provider event.
StaffGrantSource = Literal["gift", "promo", "school_licence", "trial", "staff_grant", "migration"]
GrantReasonCode = Literal[
    "goodwill", "promotion", "school_agreement", "trial", "migration", "correction"
]
RevokeReasonCode = Literal[
    "granted_in_error", "duplicate", "misuse", "learner_request", "correction"
]
GrantState = Literal["active", "scheduled", "expired", "revoked"]


class StaffGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    learner_id: uuid.UUID
    scope: EntitlementScope
    duration_days: int = Field(ge=1, le=366, description="The grant lasts this many 24-hour days.")
    source: StaffGrantSource
    reason_code: GrantReasonCode
    idempotency_key: str = Field(
        min_length=8,
        max_length=200,
        pattern=r"^[A-Za-z0-9_.:-]+$",
        description="Chosen by the client, unique per intended grant. Sending the same "
        "request again with the same key returns the original grant.",
    )

    @model_validator(mode="after")
    def _scope_shape(self) -> StaffGrantRequest:
        if (self.scope.kind == "all") != (self.scope.id is None):
            raise ValueError("scope.id must be null for kind 'all' and set otherwise")
        return self


class StaffGrantResponse(BaseModel):
    entitlement_id: uuid.UUID
    replayed: bool = Field(description="True when this request had already been applied.")
    starts_at: datetime
    ends_at: datetime


class StaffRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: RevokeReasonCode


class StaffRevokeResponse(BaseModel):
    entitlement_id: uuid.UUID
    replayed: bool = Field(description="True when the grant had already been revoked.")
    revoked_at: datetime


class StaffGrantItem(BaseModel):
    id: uuid.UUID
    scope: EntitlementScope
    starts_at: datetime
    ends_at: datetime
    source: EntitlementSource
    state: GrantState
    order_id: uuid.UUID | None
    granted_by: uuid.UUID | None
    created_at: datetime
    revoked_at: datetime | None
    revocation_reason: Literal["staff_revoke", "refund"] | None


class StaffLearnerGrantsResponse(BaseModel):
    learner_id: uuid.UUID
    grants: list[StaffGrantItem] = Field(
        description="Every grant of the learner, oldest first, whatever its state."
    )
