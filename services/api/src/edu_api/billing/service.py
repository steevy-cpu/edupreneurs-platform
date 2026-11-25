"""Read the caller's own active entitlement grants.

The query filters by learner explicitly AND row-level security filters again
(policy ``entitlements_select_own``). The student API role can read only the
columns selected here; it has no way to write.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from edu_api.billing.schemas import Entitlement, EntitlementScope, EntitlementsResponse

#: A learner holds a handful of grants; the bound only protects the response size.
MAX_GRANTS = 200

# now() is the transaction's start time: the list and server_time are one instant.
_ACTIVE_GRANTS = text(
    "SELECT e.id, e.scope_kind, e.scope_grade_id, e.scope_course_id, "
    "       e.starts_at, e.ends_at, e.source "
    "FROM billing.entitlements e "
    "WHERE e.learner_id = :learner_id "
    "  AND e.starts_at <= now() AND now() < e.ends_at "
    "  AND NOT EXISTS (SELECT 1 FROM billing.entitlement_revocations r "
    "                  WHERE r.entitlement_id = e.id AND r.revoked_at <= now()) "
    "ORDER BY e.ends_at DESC, e.id "
    "LIMIT :limit"
)
_SERVER_TIME = text("SELECT now() AS server_time")


async def load_active_entitlements(
    conn: AsyncConnection, learner_id: uuid.UUID
) -> EntitlementsResponse:
    server_time = (await conn.execute(_SERVER_TIME)).scalar_one()
    rows = (
        await conn.execute(_ACTIVE_GRANTS, {"learner_id": learner_id, "limit": MAX_GRANTS})
    ).all()
    return EntitlementsResponse(
        server_time=server_time,
        entitlements=[
            Entitlement(
                id=row.id,
                scope=EntitlementScope(
                    kind=row.scope_kind,
                    id=row.scope_grade_id if row.scope_kind == "grade" else row.scope_course_id,
                ),
                starts_at=row.starts_at,
                ends_at=row.ends_at,
                source=row.source,
            )
            for row in rows
        ],
    )
