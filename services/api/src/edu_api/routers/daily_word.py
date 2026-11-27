"""Word of the Day for learners.

Always registered (director ruling R-01). While ``EDU_DAILY_WORD_ENABLED`` is
off the route answers the same 404 ``not_found`` as an unknown path, before
authentication, and it stays out of the OpenAPI document until the director
flips ``INCLUDE_IN_SCHEMA`` at integration.

The query runs as the least-privileged ``edu_api`` role, which can execute one
function in schema ``vocab`` and read none of its tables: a draft, a rejected
revision or a future date cannot appear in a response
(tests/integration/test_vocab_daily_word.py).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response

from edu_api.deps import AppSettings, CurrentPrincipal, Db, Locale
from edu_api.errors import ApiError, error_responses
from edu_api.vocab.schemas import DailyWordResponse
from edu_api.vocab.service import (
    build_response,
    compute_etag,
    if_none_match_matches,
    load_daily_word,
)

#: Ruling R-01: new paths stay out of the generated contract on lane branches.
#: The director sets this to True once, at integration.
INCLUDE_IN_SCHEMA = False


async def require_daily_word_enabled(settings: AppSettings) -> None:
    """Feature flag. Runs before authentication: with the flag off the path
    behaves exactly like a path that does not exist."""
    if not settings.daily_word_enabled:
        raise ApiError(404, "not_found", "Not Found")


router = APIRouter(
    prefix="/v1", tags=["daily-word"], dependencies=[Depends(require_daily_word_enabled)]
)

#: ``private``: the response is for one signed-in user's app, never a shared
#: cache. ``no-cache``: a stored copy must be revalidated (a cheap 304) before
#: reuse, because the word can be withdrawn during the day.
CACHE_CONTROL = "private, no-cache"


@router.get(
    "/daily-word",
    response_model=DailyWordResponse,
    responses=error_responses(401, 404, 422, 503),
    summary="Today's word (Haiti date), in French or Haitian Creole",
    include_in_schema=INCLUDE_IN_SCHEMA,
)
async def get_daily_word(
    principal: CurrentPrincipal,
    db: Db,
    locale: Locale,
    response: Response,
    if_none_match: Annotated[
        str | None,
        Header(description="Entity tag(s) of the copy the app already holds."),
    ] = None,
) -> DailyWordResponse | Response:
    """The word assigned to today's date in Haiti (`America/Port-au-Prince`).

    * "Today" is decided by the server clock. No date or time is accepted.
    * If the requested language has no approved translation today, the French
      word is returned with `is_fallback_locale: true`.
    * If no word is assigned today the answer is 404 `daily_word_not_available`
      — a word is never invented and yesterday's word is never repeated.
    * The response carries a strong `ETag`. Send it back in `If-None-Match`:
      an unchanged word answers **304 Not Modified** with no body.
    * `valid_until` is the next Haiti midnight; after it a cached copy is "the
      last downloaded word", not today's.
    * Reading the word records nothing: no progress, no reward, no history.
    """
    async with db.transaction(principal.user_id, read_only=True) as conn:
        row = await load_daily_word(conn, locale)
    if row is None:
        raise ApiError(
            404,
            "daily_word_not_available",
            "No word is available for today.",
            headers={"Cache-Control": "private, no-store"},
        )
    etag = compute_etag(row)
    if if_none_match_matches(if_none_match, etag):
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": CACHE_CONTROL})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = CACHE_CONTROL
    return build_response(row)
