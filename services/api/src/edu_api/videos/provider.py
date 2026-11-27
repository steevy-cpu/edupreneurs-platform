"""YouTube Data API metadata client, used ONLY by the staff refresh, never by a learner request.

Design rules:

* One read method, ``videos.list`` (part=snippet,contentDetails,status): 1 quota unit
  per call of up to 50 ids. Search is not implemented here (its quota cost must be
  re-verified, see docs/youtube-01/08-open-questions.md, OQ-7); :func:`staff_search_terms`
  only prepares the text a future staff tool would send.
* No network call unless BOTH a key is configured and ``youtube_live_calls_authorized``
  is true. Tests inject a transport; they never use a real key or real quota.
* The key travels in the ``X-goog-api-key`` header (not in the URL, so it cannot end
  up in access logs), only to ``https://www.googleapis.com``, with redirects disabled.
  It is never logged, never returned, and redacted from every error.
* Nothing about a learner is ever part of a request: the only inputs are video ids.
* The answer is reduced to a small, bounded record; unknown or oversized values make
  the video non-presentable rather than being stored.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr

from edu_api.videos.ids import CHANNEL_ID, VIDEO_ID, InvalidVideoId, validate_video_id

API_ORIGIN = "https://www.googleapis.com"
VIDEOS_PATH = "/youtube/v3/videos"
MAX_IDS_PER_CALL = 50
#: Stored API data is refreshed or dropped within this window (see the policy report).
METADATA_TTL = dt.timedelta(days=30)
#: Our own, shorter refresh target, so a video does not disappear on the last day.
REFRESH_AFTER = dt.timedelta(days=7)
MAX_TITLE = 200
MAX_CHANNEL_TITLE = 120
MAX_DURATION_S = 4 * 3600
HAITI = "HT"

_DURATION = re.compile(r"P(?:(\d{1,2})D)?(?:T(?:(\d{1,3})H)?(?:(\d{1,4})M)?(?:(\d{1,6})S)?)?")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]")


class ProviderNotAuthorized(RuntimeError):
    """Live calls are switched off, or no key is configured."""


class ProviderError(RuntimeError):
    """The provider answered with an error or an unusable document.

    The message never contains the key."""


@dataclass(frozen=True)
class VideoMetadata:
    provider_video_id: str
    title: str
    channel_id: str
    channel_title: str
    duration_seconds: int
    audio_language: str | None
    made_for_kids: bool
    age_restricted: bool
    embeddable: bool
    privacy_status: str
    upload_status: str
    blocked_in_ht: bool
    fetched_at: dt.datetime
    expires_at: dt.datetime

    @property
    def presentable(self) -> bool:
        """The same rule as the database policy: may a learner be shown this video?"""
        return (
            self.embeddable
            and not self.age_restricted
            and not self.blocked_in_ht
            and self.privacy_status in ("public", "unlisted")
            and self.upload_status == "processed"
            and self.expires_at > self.fetched_at
        )


@dataclass(frozen=True)
class RefreshResult:
    found: dict[str, VideoMetadata]
    #: Requested ids the provider did not return: deleted, private or terminated.
    removed: frozenset[str]
    #: Returned but unusable (malformed or out-of-bounds metadata): treated like removed.
    rejected: dict[str, str]


def parse_duration(value: object) -> int:
    """ISO-8601 duration as returned by the API (``PT4M13S``) to seconds, bounded."""
    if not isinstance(value, str) or not (m := _DURATION.fullmatch(value)) or value in ("P", "PT"):
        raise ValueError("unrecognised duration")
    days, hours, minutes, seconds = (int(g) if g else 0 for g in m.groups())
    total = ((days * 24 + hours) * 60 + minutes) * 60 + seconds
    if not 1 <= total <= MAX_DURATION_S:
        raise ValueError("duration out of range")
    return total


def _clean_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError("missing text")
    text = " ".join(_CONTROL.sub("", unicodedata.normalize("NFC", value)).split())
    if not text:
        raise ValueError("empty text")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _blocked_in_haiti(restriction: object) -> bool:
    if not isinstance(restriction, dict):
        return False
    allowed, blocked = restriction.get("allowed"), restriction.get("blocked")
    if isinstance(allowed, list) and HAITI not in allowed:
        return True
    return isinstance(blocked, list) and HAITI in blocked


def parse_item(item: Any, now: dt.datetime) -> VideoMetadata:
    """One ``videos.list`` item to a bounded record. Raises ValueError when unusable."""
    if not isinstance(item, dict):
        raise ValueError("item is not an object")
    vid = item.get("id")
    if not isinstance(vid, str) or not VIDEO_ID.fullmatch(vid):
        raise ValueError("invalid video id")
    snippet, details, status = (item.get(k) for k in ("snippet", "contentDetails", "status"))
    if not (isinstance(snippet, dict) and isinstance(details, dict) and isinstance(status, dict)):
        raise ValueError("missing snippet, contentDetails or status")
    channel_id = snippet.get("channelId")
    if not isinstance(channel_id, str) or not CHANNEL_ID.fullmatch(channel_id):
        raise ValueError("invalid channel id")
    language = snippet.get("defaultAudioLanguage")
    if not (
        isinstance(language, str) and re.fullmatch(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})?", language)
    ):
        language = None
    rating = details.get("contentRating")
    age_restricted = isinstance(rating, dict) and rating.get("ytRating") == "ytAgeRestricted"
    made_for_kids = status.get("madeForKids")
    embeddable = status.get("embeddable")
    if not isinstance(made_for_kids, bool) or not isinstance(embeddable, bool):
        raise ValueError("madeForKids and embeddable must be present")
    privacy = status.get("privacyStatus")
    upload = status.get("uploadStatus")
    if privacy not in ("public", "unlisted", "private"):
        raise ValueError("unknown privacy status")
    if upload not in ("processed", "uploaded", "failed", "rejected", "deleted"):
        raise ValueError("unknown upload status")
    return VideoMetadata(
        provider_video_id=vid,
        title=_clean_text(snippet.get("title"), MAX_TITLE),
        channel_id=channel_id,
        channel_title=_clean_text(snippet.get("channelTitle"), MAX_CHANNEL_TITLE),
        duration_seconds=parse_duration(details.get("duration")),
        audio_language=language,
        made_for_kids=made_for_kids,
        age_restricted=age_restricted,
        embeddable=embeddable,
        privacy_status=privacy,
        upload_status=upload,
        blocked_in_ht=_blocked_in_haiti(details.get("regionRestriction")),
        fetched_at=now,
        expires_at=now + METADATA_TTL,
    )


def parse_videos_list(document: Any, requested: Sequence[str], now: dt.datetime) -> RefreshResult:
    if not isinstance(document, dict) or not isinstance(document.get("items", []), list):
        raise ProviderError("unusable provider document")
    wanted = set(requested)
    found: dict[str, VideoMetadata] = {}
    rejected: dict[str, str] = {}
    for item in document.get("items", []):
        vid = item.get("id") if isinstance(item, dict) else None
        if vid not in wanted:
            continue  # never accept a video that was not asked for
        try:
            found[vid] = parse_item(item, now)
        except ValueError as exc:
            rejected[vid] = str(exc)
    removed = frozenset(wanted - set(found) - set(rejected))
    return RefreshResult(found=found, removed=removed, rejected=rejected)


def staff_search_terms(text: object, *, limit: int = 100) -> str:
    """Normalise free text a STAFF member typed before a future provider search.

    Only staff text is ever searched: no learner name, profile, grade, history or
    activity is an input of this function or of any request in this module.
    """
    if not isinstance(text, str):
        raise ValueError("search text must be a string")
    cleaned = " ".join(_CONTROL.sub(" ", unicodedata.normalize("NFKC", text)).split())
    if not cleaned:
        raise ValueError("search text is empty")
    if len(cleaned) > limit:
        raise ValueError(f"search text is longer than {limit} characters")
    return cleaned


class YouTubeMetadataClient:
    def __init__(
        self,
        api_key: SecretStr | None,
        *,
        live_calls_authorized: bool,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self._key = api_key
        self._authorized = live_calls_authorized
        self._transport = transport
        self._timeout = timeout_s

    def __repr__(self) -> str:
        key = "set" if self._key else "unset"
        return f"YouTubeMetadataClient(authorized={self._authorized}, key={key})"

    async def fetch(
        self, video_ids: Iterable[str], *, now: dt.datetime | None = None
    ) -> RefreshResult:
        ids = list(dict.fromkeys(validate_video_id(v) for v in video_ids))
        if not ids:
            return RefreshResult(found={}, removed=frozenset(), rejected={})
        if len(ids) > MAX_IDS_PER_CALL:
            raise InvalidVideoId(f"at most {MAX_IDS_PER_CALL} ids per call")
        if not self._authorized or self._key is None or not self._key.get_secret_value():
            raise ProviderNotAuthorized("live YouTube Data API calls are not authorized")
        moment = now or dt.datetime.now(dt.UTC)
        try:
            async with httpx.AsyncClient(
                base_url=API_ORIGIN,
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
            ) as http:
                response = await http.get(
                    VIDEOS_PATH,
                    params={
                        "part": "snippet,contentDetails,status",
                        "id": ",".join(ids),
                        "maxResults": len(ids),
                    },
                    headers={
                        "X-goog-api-key": self._key.get_secret_value(),
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"provider unreachable ({type(exc).__name__})") from None
        if response.status_code != 200:
            raise ProviderError(f"provider answered HTTP {response.status_code}")
        try:
            document = response.json()
        except ValueError:
            raise ProviderError("provider answered with invalid JSON") from None
        return parse_videos_list(document, ids, moment)
