"""Read side of the leaderboard lane: the caller's own standing, nobody else's."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from edu_api.db.session import Database
from edu_api.errors import ApiError
from edu_api.leaderboard.schemas import MyStanding

#: The only leaderboard function the API role may execute. It takes no learner
#: id: the actor is the verified, transaction-scoped one.
_MY_STANDING = text("SELECT leaderboard.my_standing(:period) AS standing")


async def my_standing(
    db: Database, learner_id: uuid.UUID, period: str, *, include_cohort: bool
) -> MyStanding:
    """``include_cohort`` is ``EDU_LEADERBOARD_COHORTS_ENABLED``: with it off the answer is the
    caller's own Gold and ``cohort: null``, whatever the database knows about their cohort."""
    try:
        async with db.transaction(learner_id, read_only=True) as conn:
            standing = (await conn.execute(_MY_STANDING, {"period": period})).scalar_one()
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "22023":
            raise ApiError(
                422, "validation_error", "Unknown period. Use all, week or a past Monday."
            ) from None
        raise
    if not include_cohort:
        standing["cohort"] = None
    return MyStanding.model_validate(standing)
