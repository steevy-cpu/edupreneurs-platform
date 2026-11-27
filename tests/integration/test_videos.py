"""YouTube-01 over HTTP: only approved, presentable, freshly checked videos reach a learner.

Synthetic videos and ids only. The API is configured with a FAKE provider key to prove it
never appears anywhere a client can read it; no request in this file reaches YouTube.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from edu_api.main import create_app
from tests.conftest import build_settings, create_lesson
from tests.helpers import EDITOR, REVIEWER, SEED_LESSON, bearer

pytestmark = pytest.mark.integration

FAKE_KEY = "FAKE-TEST-KEY-not-a-real-credential-0123456789"
CHANNEL = "UC" + "A" * 22


@pytest.fixture(scope="session")
async def video_app(local_env: dict[str, str]) -> AsyncIterator[FastAPI]:
    application = create_app(
        build_settings(local_env, videos_enabled=True, youtube_api_key=SecretStr(FAKE_KEY))
    )
    yield application
    await application.state.db.dispose()


@pytest.fixture
async def vclient(video_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=video_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http


@pytest.fixture(autouse=True)
async def clean_videos(admin: asyncpg.Pool) -> None:
    await admin.execute("TRUNCATE app.lesson_video_links, app.videos CASCADE")


async def add_video(admin: asyncpg.Pool, vid: str, **over: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "provider_video_id": vid,
        "title": f"Vidéo synthétique {vid}",
        "channel_id": CHANNEL,
        "channel_title": "Chaîne synthétique",
        "duration_seconds": 300,
        "made_for_kids": False,
        "age_restricted": False,
        "embeddable": True,
        "privacy_status": "public",
        "upload_status": "processed",
        "blocked_in_ht": False,
        "availability": "available",
        "created_by": EDITOR,
    }
    values.update(over)
    cols = ", ".join(values)
    marks = ", ".join(f"${i}" for i in range(1, len(values) + 1))
    return await admin.fetchval(
        f"INSERT INTO app.videos ({cols}, metadata_fetched_at, metadata_expires_at) "
        f"VALUES ({marks}, now() - interval '1 day', now() + interval '6 days') RETURNING id",
        *values.values(),
    )


async def attach(
    admin: asyncpg.Pool,
    video: uuid.UUID,
    position: int,
    *,
    lesson: uuid.UUID = SEED_LESSON,
    locales: tuple[str, ...] = ("fr", "ht"),
    approve: bool = True,
    start: int = 0,
) -> uuid.UUID:
    link = await admin.fetchval(
        "INSERT INTO app.lesson_video_links (lesson_id, video_id, locales, position, source, proposed_by, start_seconds) "
        "VALUES ($1, $2, $3, $4, 'teacher', $5, $6) RETURNING id",
        lesson, video, list(locales), position, EDITOR, start,
    )  # fmt: skip
    if approve:
        await admin.execute(
            "UPDATE app.lesson_video_links SET review_status = 'approved', reviewed_by = $2, "
            "reviewed_at = now() WHERE id = $1",
            link, REVIEWER,
        )  # fmt: skip
    return link


async def get_videos(
    client: httpx.AsyncClient, token: str, lesson: uuid.UUID = SEED_LESSON, locale: str = "fr"
) -> httpx.Response:
    return await client.get(
        f"/v1/lessons/{lesson}/videos", params={"locale": locale}, headers=bearer(token)
    )


def ids_of(response: httpx.Response) -> list[str]:
    assert response.status_code == 200, response.text
    return [v["video_id"] for v in response.json()["videos"]]


# ------------------------------------------------------------------ flag and auth
async def test_feature_is_off_by_default(
    client: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    await attach(admin, await add_video(admin, "okVideo0001"), 1)
    assert (await get_videos(client, tokens["student_a"])).status_code == 404


async def test_a_token_is_required(vclient: httpx.AsyncClient) -> None:
    assert (
        await vclient.get(f"/v1/lessons/{SEED_LESSON}/videos", params={"locale": "fr"})
    ).status_code == 401


# ------------------------------------------------------------------ the card
async def test_approved_video_card_is_complete_and_safe(
    vclient: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    await attach(admin, await add_video(admin, "okVideo0001"), 1, start=42)
    response = await get_videos(vclient, tokens["student_a"])
    body = response.json()
    assert body["requires_network"] is True and body["locale"] == "fr"
    (card,) = body["videos"]
    assert card["video_id"] == "okVideo0001"
    assert (card["title"], card["channel_title"]) == (
        "Vidéo synthétique okVideo0001",
        "Chaîne synthétique",
    )
    assert card["channel_url"] == f"https://www.youtube.com/channel/{CHANNEL}"
    assert card["thumbnail_url"] == "https://i.ytimg.com/vi/okVideo0001/hqdefault.jpg"
    assert card["embed_url"] == "https://www.youtube.com/embed/okVideo0001"
    assert card["watch_url"] == "https://www.youtube.com/watch?v=okVideo0001&t=42s"
    assert (card["start_seconds"], card["made_for_kids"], card["provider"]) == (
        42,
        False,
        "youtube",
    )
    # Nothing about the review, the staff, the provider key or the learner.
    text = response.text
    for forbidden in (
        FAKE_KEY,
        "reviewed_by",
        "review_note",
        "proposed_by",
        str(REVIEWER),
        str(EDITOR),
        "status_reason",
    ):
        assert forbidden not in text, forbidden


async def test_ordering_and_locale(
    vclient: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    await attach(admin, await add_video(admin, "second00002"), 2)
    await attach(admin, await add_video(admin, "first000001"), 1)
    await attach(admin, await add_video(admin, "creoleOnly1"), 3, locales=("ht",))
    token = tokens["student_a"]
    assert ids_of(await get_videos(vclient, token, locale="fr")) == ["first000001", "second00002"]
    assert ids_of(await get_videos(vclient, token, locale="ht")) == [
        "first000001",
        "second00002",
        "creoleOnly1",
    ]


async def test_lesson_without_videos_is_an_empty_list(
    vclient: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    assert ids_of(await get_videos(vclient, tokens["student_a"])) == []


async def test_unknown_or_unpublished_lesson_is_404(
    vclient: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    draft_lesson = await create_lesson(admin)  # exists, but has no published revision
    await attach(admin, await add_video(admin, "okVideo0001"), 1, lesson=draft_lesson)
    assert (await get_videos(vclient, tokens["student_a"], lesson=draft_lesson)).status_code == 404
    assert (await get_videos(vclient, tokens["student_a"], lesson=uuid.uuid4())).status_code == 404
    bad = await vclient.get(
        "/v1/lessons/not-a-uuid/videos",
        params={"locale": "fr"},
        headers=bearer(tokens["student_a"]),
    )
    assert bad.status_code == 422
    assert (await get_videos(vclient, tokens["student_a"], locale="en")).status_code == 422


# ------------------------------------------------------------------ what must stay hidden
async def test_unreviewed_video_is_hidden(
    vclient: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    await attach(admin, await add_video(admin, "proposed001"), 1, approve=False)
    assert ids_of(await get_videos(vclient, tokens["student_a"])) == []


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("embeddable", False),
        ("age_restricted", True),
        ("blocked_in_ht", True),
        ("privacy_status", "private"),
        ("upload_status", "deleted"),
        ("availability", "removed"),
    ],
)
async def test_non_presentable_videos_are_hidden(
    vclient: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str], column: str, value: Any
) -> None:
    video = await add_video(admin, "okVideo0001")
    await attach(admin, video, 1)
    assert ids_of(await get_videos(vclient, tokens["student_a"])) == ["okVideo0001"]
    await admin.execute(f"UPDATE app.videos SET {column} = $2 WHERE id = $1", video, value)
    assert ids_of(await get_videos(vclient, tokens["student_a"])) == []


async def test_staff_can_disable_and_withdraw(
    vclient: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    video = await add_video(admin, "okVideo0001")
    link = await attach(admin, video, 1)
    await admin.execute(
        "UPDATE app.videos SET status = 'disabled', status_reason = 'synthetic test' WHERE id = $1",
        video,
    )
    assert ids_of(await get_videos(vclient, tokens["student_a"])) == []
    await admin.execute(
        "UPDATE app.videos SET status = 'active', status_reason = NULL WHERE id = $1", video
    )
    assert ids_of(await get_videos(vclient, tokens["student_a"])) == ["okVideo0001"]
    await admin.execute(
        "UPDATE app.lesson_video_links SET review_status = 'withdrawn' WHERE id = $1", link
    )
    assert ids_of(await get_videos(vclient, tokens["student_a"])) == []


async def test_expired_metadata_hides_until_refreshed(
    vclient: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    video = await add_video(admin, "okVideo0001")
    await attach(admin, video, 1)
    await admin.execute(
        "UPDATE app.videos SET metadata_fetched_at = now() - interval '31 days', "
        "metadata_expires_at = now() - interval '1 day' WHERE id = $1",
        video,
    )
    assert ids_of(await get_videos(vclient, tokens["student_a"])) == []
    await admin.execute(
        "UPDATE app.videos SET metadata_fetched_at = now(), metadata_expires_at = now() + interval '30 days' WHERE id = $1",
        video,
    )
    assert ids_of(await get_videos(vclient, tokens["student_a"])) == ["okVideo0001"]


async def test_material_metadata_change_requires_a_new_review(
    vclient: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    video = await add_video(admin, "okVideo0001")
    await attach(admin, video, 1)
    await admin.execute("UPDATE app.videos SET title = 'Titre corrigé' WHERE id = $1", video)
    response = await get_videos(vclient, tokens["student_a"])
    assert (
        response.json()["videos"][0]["title"] == "Titre corrigé"
    )  # the latest API data is displayed
    await admin.execute(
        "UPDATE app.videos SET channel_id = $2 WHERE id = $1", video, "UC" + "B" * 22
    )
    assert ids_of(await get_videos(vclient, tokens["student_a"])) == []
    assert (
        await admin.fetchval("SELECT review_status FROM app.lesson_video_links") == "needs_review"
    )


async def test_made_for_kids_video_is_flagged_for_the_client(
    vclient: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    await attach(admin, await add_video(admin, "kidsVideo01", made_for_kids=True), 1)
    (card,) = (await get_videos(vclient, tokens["student_a"])).json()["videos"]
    assert card["made_for_kids"] is True


# ------------------------------------------------------------------ accounts, secrets and surface
async def test_every_account_sees_the_same_lesson_content(
    vclient: httpx.AsyncClient, admin: asyncpg.Pool, tokens: dict[str, str]
) -> None:
    await attach(admin, await add_video(admin, "okVideo0001"), 1)
    a = (await get_videos(vclient, tokens["student_a"])).json()
    b = (await get_videos(vclient, tokens["student_b"])).json()
    assert a == b  # lesson content; nothing in the response is personal


async def test_no_learner_facing_search_and_no_key_in_the_contract(video_app: FastAPI) -> None:
    spec = video_app.openapi()
    video_paths = [p for p in spec["paths"] if "video" in p or "youtube" in p or "search" in p]
    assert video_paths == ["/v1/lessons/{lesson_id}/videos"]
    assert list(spec["paths"]["/v1/lessons/{lesson_id}/videos"]) == ["get"]
    rendered = str(spec)
    assert FAKE_KEY not in rendered and "youtube_api_key" not in rendered


async def test_error_responses_do_not_leak_the_key(
    vclient: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    for response in (
        await vclient.get(f"/v1/lessons/{SEED_LESSON}/videos", params={"locale": "fr"}),
        await get_videos(vclient, tokens["student_a"], lesson=uuid.uuid4()),
        await get_videos(vclient, tokens["student_a"], locale="xx"),
    ):
        assert FAKE_KEY not in response.text and FAKE_KEY not in str(response.headers)
