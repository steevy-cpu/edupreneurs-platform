"""YouTube-01 identifiers and the mocked metadata provider. No network, no real key, no quota."""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from edu_api.config import Settings
from edu_api.videos import ids
from edu_api.videos.provider import (
    METADATA_TTL,
    ProviderError,
    ProviderNotAuthorized,
    YouTubeMetadataClient,
    parse_duration,
    parse_item,
    parse_videos_list,
    staff_search_terms,
)

FAKE_KEY = "FAKE-TEST-KEY-not-a-real-credential-0123456789"
NOW = dt.datetime(2026, 11, 27, 12, 0, tzinfo=dt.UTC)
CHANNEL = "UC" + "A" * 22


def item(vid: str = "dQw4w9WgXcQ", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": vid,
        "snippet": {"title": "Les fractions", "channelId": CHANNEL, "channelTitle": "Chaîne synthétique",
                    "defaultAudioLanguage": "fr"},
        "contentDetails": {"duration": "PT4M13S"},
        "status": {"privacyStatus": "public", "uploadStatus": "processed", "embeddable": True, "madeForKids": False},
    }  # fmt: skip
    for path, value in over.items():
        section, _, key = path.partition("__")
        if key:
            if value is None:
                base[section].pop(key, None)
            else:
                base[section][key] = value
        else:
            base[section] = value
    return base


# ------------------------------------------------------------------ identifiers
@pytest.mark.parametrize("good", ["dQw4w9WgXcQ", "aaaaaaaaaaa", "A_b-C_d-E_f", "01234567890"])
def test_valid_video_ids(good: str) -> None:
    assert ids.validate_video_id(good) == good


@pytest.mark.parametrize(
    "bad",
    [
        "", "short", "dQw4w9WgXcQx", "dQw4w9WgXc", "dQw4w9WgXc ", " dQw4w9WgXc", "dQw4w9W\ngXc",
        "<script>a1b", "../../etc/p", "dQw4w9WgXc\x00", "dQw4w9WgXc%", "dQw4w9WgXc/", "dQw4w9WgXc?",
        "dQw4w9WgXc\uff31", "dQw4w9WgXcé", "javascript:", None, 12345678901, ["dQw4w9WgXcQ"],
    ],
)  # fmt: skip
def test_malicious_or_malformed_video_ids(bad: object) -> None:
    with pytest.raises(ids.InvalidVideoId):
        ids.validate_video_id(bad)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.com/watch?v=dQw4w9WgXcQ&t=30s", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ],
)
def test_legacy_links_are_parsed(url: str, expected: str) -> None:
    assert ids.video_id_from_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/watch?v=dQw4w9WgXcQ",  # not https
        "https://evil.example/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
        "https://user:pw@www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com:8443/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&v=aaaaaaaaaaa",  # ambiguous
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ%3Cscript",
        "https://youtu.be/dQw4w9WgXcQ/extra",
        "https://www.youtube.com/watch?v= dQw4w9WgXcQ",
        "javascript:alert(1)//youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/" + "a" * 400,
    ],
)
def test_untrusted_links_are_refused(url: str) -> None:
    with pytest.raises(ids.InvalidVideoId):
        ids.video_id_from_url(url)


def test_urls_are_built_only_from_validated_ids() -> None:
    assert ids.watch_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert ids.watch_url("dQw4w9WgXcQ", 75) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=75s"
    assert ids.embed_url("dQw4w9WgXcQ") == "https://www.youtube.com/embed/dQw4w9WgXcQ"
    assert ids.thumbnail_url("dQw4w9WgXcQ") == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert ids.channel_url(CHANNEL) == f"https://www.youtube.com/channel/{CHANNEL}"
    for builder in (ids.watch_url, ids.embed_url, ids.thumbnail_url):
        with pytest.raises(ids.InvalidVideoId):
            builder('x"><img src=x onerror=alert(1)>')
    with pytest.raises(ids.InvalidVideoId):
        ids.channel_url("UCshort")


# ------------------------------------------------------------------ provider documents (mocked)
@pytest.mark.parametrize(
    ("value", "seconds"), [("PT4M13S", 253), ("PT1H", 3600), ("PT45S", 45), ("P0DT2M", 120)]
)
def test_durations(value: str, seconds: int) -> None:
    assert parse_duration(value) == seconds


@pytest.mark.parametrize(
    "value", ["", "P", "PT", "PT0S", "PT5H", "P1D", "4:13", "PT-1S", None, 253]
)
def test_unusable_durations(value: object) -> None:
    with pytest.raises(ValueError):
        parse_duration(value)


def test_ordinary_video_is_presentable() -> None:
    meta = parse_item(item(), NOW)
    assert meta.presentable
    assert (meta.title, meta.channel_title, meta.duration_seconds, meta.audio_language) == (
        "Les fractions", "Chaîne synthétique", 253, "fr",
    )  # fmt: skip
    assert meta.expires_at - meta.fetched_at == METADATA_TTL == dt.timedelta(days=30)


@pytest.mark.parametrize(
    ("override", "why"),
    [
        ({"status__embeddable": False}, "embedding disabled by the owner"),
        ({"status__privacyStatus": "private"}, "private"),
        ({"status__uploadStatus": "rejected"}, "rejected upload"),
        (
            {
                "contentDetails": {
                    "duration": "PT3M",
                    "contentRating": {"ytRating": "ytAgeRestricted"},
                }
            },
            "age-restricted",
        ),
        (
            {
                "contentDetails": {
                    "duration": "PT3M",
                    "regionRestriction": {"blocked": ["HT", "US"]},
                }
            },
            "blocked in Haiti",
        ),
        (
            {
                "contentDetails": {
                    "duration": "PT3M",
                    "regionRestriction": {"allowed": ["FR", "CA"]},
                }
            },
            "not allowed in Haiti",
        ),
    ],
)
def test_restricted_videos_are_not_presentable(override: dict[str, Any], why: str) -> None:
    assert not parse_item(item(**override), NOW).presentable, why


def test_made_for_kids_is_recorded_not_hidden() -> None:
    meta = parse_item(item(status__madeForKids=True), NOW)
    assert meta.made_for_kids and meta.presentable


@pytest.mark.parametrize(
    "override",
    [
        {"status__madeForKids": None},  # the per-video check is mandatory: never assume
        {"status__embeddable": None},
        {"status__madeForKids": "false"},
        {"status__privacyStatus": "secret"},
        {"snippet__channelId": "not-a-channel"},
        {"snippet__title": ""},
        {"snippet__title": "​​"},
        {"contentDetails__duration": "PT9H"},
        {"snippet": "oops"},
        {"status": None},
    ],
)
def test_incomplete_or_strange_metadata_is_rejected(override: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        parse_item(item(**override), NOW)


def test_text_is_cleaned_and_bounded() -> None:
    meta = parse_item(
        item(snippet__title="  Les‮fractions \x00 " + "x" * 400, snippet__channelTitle="C​h"), NOW
    )
    assert "‮" not in meta.title and "\x00" not in meta.title
    assert len(meta.title) <= 200 and meta.title.endswith("…")
    assert meta.channel_title == "Ch"


def test_missing_and_unrequested_items() -> None:
    doc = {
        "items": [
            item("aaaaaaaaaaa"),
            item("bbbbbbbbbbb"),
            item("zzzzzzzzzzz"),
            item("ccccccccccc", status__embeddable=None),
        ]
    }
    result = parse_videos_list(doc, ["aaaaaaaaaaa", "ccccccccccc", "ddddddddddd"], NOW)
    assert set(result.found) == {"aaaaaaaaaaa"}  # bbb and zzz were never asked for
    assert result.removed == frozenset({"ddddddddddd"})  # deleted / private / terminated
    assert set(result.rejected) == {"ccccccccccc"}
    with pytest.raises(ProviderError):
        parse_videos_list(["not", "a", "document"], ["aaaaaaaaaaa"], NOW)


# ------------------------------------------------------------------ client: authorization and secrets
class Recorder(httpx.AsyncBaseTransport):
    def __init__(
        self, response: httpx.Response | None = None, error: Exception | None = None
    ) -> None:
        self.requests: list[httpx.Request] = []
        self.response = response or httpx.Response(200, json={"items": [item()]})
        self.error = error

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response


@pytest.mark.parametrize(
    ("key", "authorized"), [(None, True), (SecretStr(""), True), (SecretStr(FAKE_KEY), False)]
)
async def test_no_network_call_unless_key_and_authorization(
    key: SecretStr | None, authorized: bool
) -> None:
    transport = Recorder()
    client = YouTubeMetadataClient(key, live_calls_authorized=authorized, transport=transport)
    with pytest.raises(ProviderNotAuthorized):
        await client.fetch(["dQw4w9WgXcQ"])
    assert transport.requests == []


async def test_request_shape_key_only_in_header_and_only_to_google(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    transport = Recorder()
    client = YouTubeMetadataClient(
        SecretStr(FAKE_KEY), live_calls_authorized=True, transport=transport
    )
    result = await client.fetch(["dQw4w9WgXcQ", "dQw4w9WgXcQ"], now=NOW)
    assert set(result.found) == {"dQw4w9WgXcQ"}
    (request,) = transport.requests
    assert (request.url.scheme, request.url.host, request.url.path) == (
        "https",
        "www.googleapis.com",
        "/youtube/v3/videos",
    )
    assert request.headers["x-goog-api-key"] == FAKE_KEY
    assert FAKE_KEY not in str(request.url)
    assert dict(request.url.params) == {
        "part": "snippet,contentDetails,status",
        "id": "dQw4w9WgXcQ",
        "maxResults": "1",
    }
    assert FAKE_KEY not in caplog.text and FAKE_KEY not in repr(client)


@pytest.mark.parametrize(
    "transport",
    [
        Recorder(httpx.Response(302, headers={"location": "https://evil.example/collect"})),
        Recorder(httpx.Response(403, json={"error": {"message": f"key {FAKE_KEY} invalid"}})),
        Recorder(httpx.Response(200, content=b"<html>not json</html>")),
        Recorder(error=httpx.ConnectTimeout(f"timeout talking with key={FAKE_KEY}")),
    ],
    ids=["redirect-not-followed", "error-status", "not-json", "network-error"],
)
async def test_provider_failures_never_carry_the_key(transport: Recorder) -> None:
    client = YouTubeMetadataClient(
        SecretStr(FAKE_KEY), live_calls_authorized=True, transport=transport
    )
    with pytest.raises(ProviderError) as info:
        await client.fetch(["dQw4w9WgXcQ"])
    assert FAKE_KEY not in str(info.value) and FAKE_KEY not in repr(info.value)
    # No chained exception that could carry the key (for example the httpx error text).
    assert info.value.__cause__ is None
    assert info.value.__context__ is None or info.value.__suppress_context__
    assert len(transport.requests) == 1  # a redirect was not followed


async def test_input_ids_are_validated_and_bounded_before_any_call() -> None:
    transport = Recorder()
    client = YouTubeMetadataClient(
        SecretStr(FAKE_KEY), live_calls_authorized=True, transport=transport
    )
    with pytest.raises(ids.InvalidVideoId):
        await client.fetch(["dQw4w9WgXcQ", "bad,id&key=x"])
    with pytest.raises(ids.InvalidVideoId):
        await client.fetch([f"{n:011d}" for n in range(51)])
    assert transport.requests == []
    assert (await client.fetch([])).found == {}


def test_settings_never_print_the_key() -> None:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr("postgresql+asyncpg://u:p@127.0.0.1:5432/db"),
        auth_issuer="https://auth.test.invalid/auth/v1",
        auth_jwks_url="https://auth.test.invalid/jwks",
        youtube_api_key=SecretStr(FAKE_KEY),
    )
    assert FAKE_KEY not in repr(settings) and FAKE_KEY not in str(settings)
    assert FAKE_KEY not in json.dumps(settings.model_dump(mode="json"))
    assert settings.videos_enabled is False and settings.youtube_live_calls_authorized is False


# ------------------------------------------------------------------ staff search text
@pytest.mark.parametrize(
    ("text", "expected"),
    [("  les   fractions\n7e ", "les fractions 7e"), ("ﬁgures", "figures"), ("a‮b", "a b")],
)
def test_staff_search_terms_are_normalised(text: str, expected: str) -> None:
    assert staff_search_terms(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "\x00\x01", "x" * 101, None, ["fractions"]])
def test_staff_search_terms_are_bounded(text: object) -> None:
    with pytest.raises(ValueError):
        staff_search_terms(text)


def test_search_text_is_sent_as_data_not_syntax() -> None:
    # Operators and URL syntax are just characters: httpx encodes them as one query value.
    injected = staff_search_terms('fractions" OR 1=1 &key=steal&part=id')
    request = httpx.Request(
        "GET", "https://www.googleapis.com/youtube/v3/search", params={"q": injected}
    )
    assert dict(request.url.params) == {"q": 'fractions" OR 1=1 &key=steal&part=id'}
