# ruff: noqa: F811
"""Fixes from the independent review of B2 (LOCAL stack only).

M-B2-1: only the author changes, sources or submits a draft — an admin does not.
L-B2-2: a pack holds one revision per lesson.
L-B2-1: control characters in text are a 422, not a 500.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg
import httpx
import pytest

from tests.helpers import bearer
from tests.integration.test_staff_editorial import (  # noqa: F401
    Desk,
    S,
    assert_error,
    desk,
    learner_lesson,
    slug,
)
from tests.staff_fixtures import (  # noqa: F401
    MakeStaff,
    make_staff,
    reset_denial_windows,
    sample_revision_body,
    staff_app,
    staff_client,
    staff_settings,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def fresh_denial_windows(admin: asyncpg.Pool) -> None:
    await reset_denial_windows(admin)


async def _stored(admin: asyncpg.Pool, revision_id: str) -> tuple[Any, ...]:
    row = await admin.fetchrow(
        "SELECT r.status, r.title, r.blocks::text AS blocks, r.created_by, r.approved_by,"
        " (SELECT count(*) FROM app.lesson_revision_sources s"
        "  WHERE s.lesson_revision_id = r.id) AS sources,"
        " (SELECT count(*) FROM app.editorial_reviews e"
        "  WHERE e.lesson_revision_id = r.id) AS reviews,"
        " (SELECT count(*) FROM app.pack_items i WHERE i.lesson_revision_id = r.id) AS packed"
        " FROM app.lesson_revisions r WHERE r.id = $1",
        uuid.UUID(revision_id),
    )
    assert row is not None
    return tuple(row.values())


# ------------------------------------------------------------------ M-B2-1
@pytest.mark.parametrize(
    "roles",
    [("admin",), ("admin", "editor", "reviewer", "publisher")],
    ids=["admin-only", "every-role"],
)
async def test_an_admin_cannot_put_their_words_under_an_editors_name(
    desk: Desk,
    make_staff: MakeStaff,
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
    roles: tuple[str, ...],
) -> None:
    """The exact sequence of the finding: edit, source, submit, approve, build, release."""
    boss = await make_staff(*roles)
    lesson_id = await desk.lesson()
    draft = await desk.draft(lesson_id)
    rid = draft["id"]
    before = await _stored(admin, rid)
    rewrite = {
        "title": "Texte de l'admin",
        "blocks": [{"key": "a", "type": "paragraph", "text": "Jamais relu par un tiers."}],
        "questions": [],
    }

    assert_error(await desk.put(boss, f"/revisions/{rid}", rewrite), 403, "forbidden")

    # the admin may create a source and clear its rights — but not attach it
    created = await desk.post(boss, "/sources", {"source_title": "Source de l'admin (test)"})
    assert created.status_code == 201, created.text
    source_id = created.json()["source_id"]
    cleared = await desk.put(
        boss, f"/sources/{source_id}/rights", {"rights_status": "cleared", "rights_notes": "x"}
    )
    assert cleared.status_code == 204, cleared.text
    assert_error(
        await desk.post(boss, f"/revisions/{rid}/sources", {"source_id": source_id}),
        403,
        "forbidden",
    )
    assert_error(await desk.post(boss, f"/revisions/{rid}/submit"), 403, "forbidden")
    assert_error(
        await desk.post(boss, f"/revisions/{rid}/reviews", {"verdict": "approved"}),
        409,
        "revision_not_in_review",
    )
    built = await desk.post(
        boss, "/packs", {"pack_key": slug(), "locale": "fr", "revision_ids": [rid]}
    )
    assert_error(built, 409, "pack_item_not_approved")

    assert await _stored(admin, rid) == before, "the draft is exactly as its author left it"
    assert before[0] == "draft"
    assert (await learner_lesson(client, tokens["student_a"], lesson_id)).status_code == 404

    denied = await admin.fetch(
        "SELECT details FROM app.audit_events WHERE actor_id = $1 AND outcome = 'denied'"
        " ORDER BY created_at, id",
        boss.user_id,
    )
    assert [json.loads(row["details"])["route"] for row in denied][:1] == [
        "/v1/staff/revisions/{revision_id}"
    ]
    assert not await admin.fetchval(
        "SELECT count(*) FROM app.audit_events WHERE actor_id = $1 AND target_id = $2"
        " AND outcome = 'allowed'",
        boss.user_id,
        uuid.UUID(rid),
    )


async def test_an_admin_cannot_detach_a_source_from_an_editors_draft(
    desk: Desk, make_staff: MakeStaff, admin: asyncpg.Pool
) -> None:
    boss = await make_staff("admin")
    lesson_id = await desk.lesson()
    rid = (await desk.draft(lesson_id))["id"]
    source_id = await desk.cleared_source()
    attached = await desk.post(desk.author, f"/revisions/{rid}/sources", {"source_id": source_id})
    assert attached.status_code == 200, attached.text

    refused = await desk.http.delete(
        f"{S}/revisions/{rid}/sources/{source_id}", headers=bearer(boss.token)
    )
    assert_error(refused, 403, "forbidden")
    assert (await _stored(admin, rid))[5] == 1

    # the author still can
    done = await desk.http.delete(
        f"{S}/revisions/{rid}/sources/{source_id}", headers=bearer(desk.author.token)
    )
    assert done.status_code == 204, done.text


async def test_an_admin_who_is_the_author_still_cannot_approve_or_release_their_revision(
    staff_client: httpx.AsyncClient,
    make_staff: MakeStaff,
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    """The legitimate way for an admin to change content: write a revision. It
    then needs somebody else's review like anyone's."""
    boss = await make_staff("admin", "editor", "reviewer", "publisher")
    solo = Desk(staff_client, boss, boss)
    lesson_id = await solo.lesson()
    rid = (await solo.draft(lesson_id))["id"]
    source_id = await solo.cleared_source()
    assert (
        await solo.post(boss, f"/revisions/{rid}/sources", {"source_id": source_id})
    ).status_code == 200
    assert (await solo.post(boss, f"/revisions/{rid}/submit")).status_code == 200

    for verdict in ("approved", "rejected", "changes_requested"):
        assert_error(
            await solo.post(boss, f"/revisions/{rid}/reviews", {"verdict": verdict}),
            409,
            "author_cannot_review",
        )
    assert_error(
        await solo.post(
            boss, "/packs", {"pack_key": slug(), "locale": "fr", "revision_ids": [rid]}
        ),
        409,
        "pack_item_not_approved",
    )
    stored = await _stored(admin, rid)
    assert (stored[0], stored[4], stored[6], stored[7]) == ("in_review", None, 0, 0)
    assert (await learner_lesson(client, tokens["student_a"], lesson_id)).status_code == 404


# ------------------------------------------------------------------ L-B2-2
async def test_a_pack_holds_one_revision_per_lesson(desk: Desk, admin: asyncpg.Pool) -> None:
    lesson_id = await desk.lesson()
    older = await desk.approved(lesson_id, title="Version un")
    newer = await desk.approved(lesson_id, title="Version deux")
    other = await desk.approved(await desk.lesson(), title="Autre leçon")
    pack_key = slug()

    for ids in ([older["id"], newer["id"]], [newer["id"], older["id"]]):
        refused = await desk.post(
            desk.author, "/packs", {"pack_key": pack_key, "locale": "fr", "revision_ids": ids}
        )
        assert_error(refused, 422, "pack_lesson_duplicated")
    refused = await desk.post(
        desk.author,
        "/packs",
        {
            "pack_key": pack_key,
            "locale": "fr",
            "revision_ids": [older["id"], other["id"], newer["id"]],
        },
    )
    assert_error(refused, 422, "pack_lesson_duplicated")
    assert (
        await admin.fetchval("SELECT count(*) FROM app.pack_releases WHERE pack_key = $1", pack_key)
        == 0
    )

    # different lessons in one pack are fine
    built = await desk.post(
        desk.author,
        "/packs",
        {"pack_key": pack_key, "locale": "fr", "revision_ids": [newer["id"], other["id"]]},
    )
    assert built.status_code == 201, built.text


# ------------------------------------------------------------------ L-B2-1
def _set_title(body: dict[str, Any], text: str) -> None:
    body["title"] = text


def _set_heading(body: dict[str, Any], text: str) -> None:
    next(b for b in body["blocks"] if b["type"] == "heading")["text"] = text


def _set_paragraph(body: dict[str, Any], text: str) -> None:
    next(b for b in body["blocks"] if b["type"] == "paragraph")["text"] = text


def _set_prompt(body: dict[str, Any], text: str) -> None:
    body["questions"][0]["prompt"]["text"] = text


def _set_choice(body: dict[str, Any], text: str) -> None:
    body["questions"][0]["response_spec"]["choices"][0]["text"] = text


def _set_explanation(body: dict[str, Any], text: str) -> None:
    body["questions"][0]["explanation"]["text"] = text


@pytest.mark.parametrize(
    "put_text",
    [_set_title, _set_heading, _set_paragraph, _set_prompt, _set_choice, _set_explanation],
)
@pytest.mark.parametrize(
    "bad", ["a\u0000b", "a\u0007b", "a\rb", "a\u001bb", "a\u007fb", "a\u0085b"]
)
async def test_a_control_character_in_lesson_or_question_text_is_a_422(
    desk: Desk, admin: asyncpg.Pool, put_text: Any, bad: str
) -> None:
    lesson_id = await desk.lesson()
    body = json.loads(json.dumps(sample_revision_body()))
    put_text(body, bad)
    refused = await desk.post(desk.author, f"/lessons/{lesson_id}/revisions", body)
    assert_error(refused, 422, "validation_error")
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.lesson_revisions WHERE lesson_id = $1", uuid.UUID(lesson_id)
        )
        == 0
    )


async def test_a_control_character_is_also_a_422_when_updating_and_in_notes(desk: Desk) -> None:
    lesson_id = await desk.lesson()
    draft = await desk.draft(lesson_id)
    rid = draft["id"]
    body = json.loads(json.dumps(sample_revision_body()))
    del body["locale"]
    body["title"] = "nul\u0000"
    assert_error(await desk.put(desk.author, f"/revisions/{rid}", body), 422, "validation_error")
    assert (await desk.get(desk.author, f"/revisions/{rid}")).json()["title"] == draft["title"]

    assert_error(
        await desk.post(desk.author, "/sources", {"source_title": "nul\u0000"}),
        422,
        "validation_error",
    )
    source_id = await desk.cleared_source()
    assert_error(
        await desk.put(
            desk.reviewer,
            f"/sources/{source_id}/rights",
            {"rights_status": "blocked", "rights_notes": "nul\u0000"},
        ),
        422,
        "validation_error",
    )
    assert (
        await desk.post(desk.author, f"/revisions/{rid}/sources", {"source_id": source_id})
    ).status_code == 200
    assert (await desk.post(desk.author, f"/revisions/{rid}/submit")).status_code == 200
    assert_error(
        await desk.post(
            desk.reviewer,
            f"/revisions/{rid}/reviews",
            {"verdict": "rejected", "notes": "nul\u0000"},
        ),
        422,
        "validation_error",
    )
    assert (await desk.get(desk.author, f"/revisions/{rid}")).json()["status"] == "in_review"


async def test_tab_and_line_feed_stay_allowed_in_text(desk: Desk) -> None:
    lesson_id = await desk.lesson()
    body = json.loads(json.dumps(sample_revision_body()))
    _set_paragraph(body, "ligne 1\n\tligne 2 — é ô")
    created = await desk.post(desk.author, f"/lessons/{lesson_id}/revisions", body)
    assert created.status_code == 201, created.text
    texts = [b.get("text") for b in created.json()["blocks"]]
    assert "ligne 1\n\tligne 2 — é ô" in texts
