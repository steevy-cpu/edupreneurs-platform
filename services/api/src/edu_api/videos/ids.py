"""Strict YouTube identifiers and the only URLs the API ever builds from them.

Every URL that reaches the app is built here from a validated id, never copied from
stored text, so a malicious or malformed value can never become a link, a script or
a different host.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")

# Hosts a staff member may paste a link from. Anything else is refused.
_WATCH_HOSTS = frozenset({"www.youtube.com", "youtube.com", "m.youtube.com"})
_SHORT_HOSTS = frozenset({"youtu.be"})
_EMBED_HOSTS = frozenset({"www.youtube.com", "youtube.com", "www.youtube-nocookie.com"})


class InvalidVideoId(ValueError):
    """Not an 11-character YouTube video id (or a link that does not carry exactly one)."""


def validate_video_id(value: object) -> str:
    if not isinstance(value, str) or not VIDEO_ID.fullmatch(value):
        raise InvalidVideoId("a YouTube video id is exactly 11 characters from A-Z a-z 0-9 _ -")
    return value


def validate_channel_id(value: object) -> str:
    if not isinstance(value, str) or not CHANNEL_ID.fullmatch(value):
        raise InvalidVideoId("a YouTube channel id is 'UC' followed by 22 characters")
    return value


def video_id_from_url(url: object) -> str:
    """Extract the id from a pasted link (watch, youtu.be, embed, shorts), refusing anything else.

    Used when importing the prototype's `lessons.youtube_url` values. Only https on the
    known hosts is accepted; credentials, ports and other hosts are refused.
    """
    if not isinstance(url, str) or len(url) > 300 or any(c.isspace() for c in url):
        raise InvalidVideoId("not a YouTube link")
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        raise InvalidVideoId("only https YouTube links are accepted")
    path = parts.path
    if host in _SHORT_HOSTS:
        candidate = path.removeprefix("/")
    elif host in _WATCH_HOSTS and path == "/watch":
        values = parse_qs(parts.query, strict_parsing=False).get("v", [])
        if len(values) != 1:
            raise InvalidVideoId("a watch link must carry exactly one v= parameter")
        candidate = values[0]
    elif host in _EMBED_HOSTS and path.startswith("/embed/"):
        candidate = path.removeprefix("/embed/")
    elif host in _WATCH_HOSTS and path.startswith("/shorts/"):
        candidate = path.removeprefix("/shorts/")
    else:
        raise InvalidVideoId("not a recognised YouTube video link")
    return validate_video_id(candidate)


def watch_url(video_id: str, start_seconds: int = 0) -> str:
    """Link that opens the video on YouTube (app or website): the external fallback."""
    vid = validate_video_id(video_id)
    return f"https://www.youtube.com/watch?v={vid}" + (
        f"&t={start_seconds}s" if start_seconds > 0 else ""
    )


def embed_url(video_id: str) -> str:
    """Base URL of the official embedded player. Player parameters are added by the app
    (see docs/youtube-01/05-mobile-handoff.md); none of them alters controls or ads."""
    return f"https://www.youtube.com/embed/{validate_video_id(video_id)}"


def thumbnail_url(video_id: str) -> str:
    """The thumbnail served by YouTube itself. It is displayed as-is, never stored or altered."""
    return f"https://i.ytimg.com/vi/{validate_video_id(video_id)}/hqdefault.jpg"


def channel_url(channel_id: str) -> str:
    return f"https://www.youtube.com/channel/{validate_channel_id(channel_id)}"
