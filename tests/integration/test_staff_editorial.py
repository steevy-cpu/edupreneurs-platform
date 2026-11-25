"""The editorial workflow through the staff API (B2): from a blank lesson to a
lesson a learner can open and answer — and every way it must refuse."""

# ruff: noqa: F811  (fixtures imported from tests.staff_fixtures are requested by name)
from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg
import httpx
import pytest

from edu_api.routers import staff_editorial
from tests.helpers import SEED_UNIT, answer_op, bearer
from tests.staff_fixtures import (  # noqa: F401
    MakeStaff,
    StaffAccount,
    create_account,
    make_staff,
    remove_account,
    reset_denial_windows,
    sample_question,
    sample_revision_body,
    set_role_active,
    staff_app,
    staff_client,
    staff_settings,
)

pytestmark = pytest.mark.integration
S = "/v1/staff"


@pytest.fixture(autouse=True)
async def fresh_denial_windows(admin: asyncpg.Pool) -> None:
    await reset_denial_windows(admin)


def slug() -> str:
    return f"it-{uuid.uuid4().hex[:12]}"


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code, error
    assert set(error) <= {"code", "message", "request_id", "details"}


async def audit_actions(admin: asyncpg.Pool, *actors: uuid.UUID) -> list[tuple[str, str, str]]:
    rows = await admin.fetch(
        "SELECT actor_kind, action, outcome FROM app.audit_events "
        "WHERE actor_id = ANY($1::uuid[]) ORDER BY created_at, id",
        list(actors),
    )
    return [(row["actor_kind"], row["action"], row["outcome"]) for row in rows]


class Desk:
    """Two synthetic staff members and a client: just enough to drive the API."""

    def __init__(self, http: httpx.AsyncClient, author: StaffAccount, reviewer: StaffAccount):
        self.http = http
        self.author = author
        self.reviewer = reviewer

    async def post(self, who: StaffAccount, path: str, body: Any = None) -> httpx.Response:
        return await self.http.post(S + path, headers=bearer(who.token), json=body)

    async def put(self, who: StaffAccount, path: str, body: Any) -> httpx.Response:
        return await self.http.put(S + path, headers=bearer(who.token), json=body)

    async def get(self, who: StaffAccount, path: str, **params: Any) -> httpx.Response:
        return await self.http.get(S + path, headers=bearer(who.token), params=params)

    async def lesson(self) -> str:
        created = await self.post(
            self.author, "/lessons", {"unit_id": str(SEED_UNIT), "slug": slug()}
        )
        assert created.status_code == 201, created.text
        return str(created.json()["lesson_id"])

    async def draft(self, lesson_id: str, **overrides: Any) -> dict[str, Any]:
        body = {**sample_revision_body(), **overrides}
        created = await self.post(self.author, f"/lessons/{lesson_id}/revisions", body)
        assert created.status_code == 201, created.text
        return dict(created.json())

    async def cleared_source(self) -> str:
        created = await self.post(
            self.author, "/sources", {"source_title": "Contenu original synthétique (test)"}
        )
        assert created.status_code == 201, created.text
        source_id = str(created.json()["source_id"])
        cleared = await self.put(
            self.reviewer,
            f"/sources/{source_id}/rights",
            {"rights_status": "cleared", "rights_notes": "Synthetic test content."},
        )
        assert cleared.status_code == 204, cleared.text
        return source_id

    async def approved(self, lesson_id: str, **overrides: Any) -> dict[str, Any]:
        """A revision taken through attach source → submit → independent approval."""
        revision = await self.draft(lesson_id, **overrides)
        rid = revision["id"]
        source_id = await self.cleared_source()
        assert (
            await self.post(self.author, f"/revisions/{rid}/sources", {"source_id": source_id})
        ).status_code == 200
        assert (await self.post(self.author, f"/revisions/{rid}/submit")).status_code == 200
        review = await self.post(
            self.reviewer, f"/revisions/{rid}/reviews", {"verdict": "approved"}
        )
        assert review.status_code == 201, review.text
        return dict(review.json()["revision"])

    async def released(self, revision_id: str, pack_key: str) -> dict[str, Any]:
        built = await self.post(
            self.author,
            "/packs",
            {"pack_key": pack_key, "locale": "fr", "revision_ids": [revision_id]},
        )
        assert built.status_code == 201, built.text
        released = await self.post(self.author, f"/packs/{built.json()['id']}/release")
        assert released.status_code == 200, released.text
        return dict(released.json())


@pytest.fixture
async def desk(staff_client: httpx.AsyncClient, make_staff: MakeStaff) -> Desk:
    author = await make_staff("editor", "publisher")
    reviewer = await make_staff("reviewer", "admin")
    return Desk(staff_client, author, reviewer)


async def learner_lesson(client: httpx.AsyncClient, token: str, lesson_id: str) -> httpx.Response:
    return await client.get(
        f"/v1/lessons/{lesson_id}", params={"locale": "fr"}, headers=bearer(token)
    )


async def catalog_lessons(client: httpx.AsyncClient, token: str) -> dict[str, dict[str, Any]]:
    catalog = (
        await client.get("/v1/catalog", params={"locale": "fr"}, headers=bearer(token))
    ).json()
    return {
        lesson["id"]: lesson
        for course in catalog["courses"]
        for unit in course["units"]
        for lesson in unit["lessons"]
    }


# ------------------------------------------------------------------ end to end
async def test_two_staff_take_a_blank_lesson_to_a_learner_without_any_direct_sql(
    desk: Desk,
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    learner = tokens["student_a"]
    author, reviewer = desk.author, desk.reviewer

    # 1. a blank lesson: nothing a learner can see
    lesson_id = await desk.lesson()
    assert (await learner_lesson(client, learner, lesson_id)).status_code == 404
    assert lesson_id not in await catalog_lessons(client, learner)

    # 2. a draft with blocks and two questions, then an edit
    draft = await desk.draft(lesson_id)
    rid = draft["id"]
    assert (draft["status"], draft["revision"], draft["locale"]) == ("draft", 1, "fr")
    assert draft["created_by"] == str(author.user_id)
    assert [q["question_key"] for q in draft["questions"]] == ["q1", "q2"]
    assert draft["blocks"] == sample_revision_body()["blocks"]

    edited_body = {
        "title": "Additionner de petits nombres",
        "blocks": [
            *sample_revision_body()["blocks"],
            {"key": "fin", "type": "paragraph", "text": "Fin."},
        ],  # type: ignore[misc]
        "questions": [sample_question("q1", "b")],
    }
    edited = await desk.put(author, f"/revisions/{rid}", edited_body)
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "Additionner de petits nombres"
    assert len(edited.json()["blocks"]) == 5 and len(edited.json()["questions"]) == 1
    question_id = edited.json()["questions"][0]["id"]

    # 3. the draft is in "my drafts", not in the review queue; still invisible
    mine = await desk.get(author, "/revisions", status="draft", mine=True)
    assert rid in [r["id"] for r in mine.json()["revisions"]]
    queue = await desk.get(reviewer, "/revisions", status="in_review")
    assert rid not in [r["id"] for r in queue.json()["revisions"]]
    assert (await learner_lesson(client, learner, lesson_id)).status_code == 404

    # 4. a source is registered (unverified), attached, and the draft submitted
    assert_error(await desk.post(author, f"/revisions/{rid}/submit"), 409, "revision_has_no_source")
    source = await desk.post(
        author,
        "/sources",
        {
            "source_title": "Contenu original synthétique",
            "source_uri": "https://example.test/source",
        },
    )
    assert source.status_code == 201
    source_id = source.json()["source_id"]
    attached = await desk.post(author, f"/revisions/{rid}/sources", {"source_id": source_id})
    assert [s["rights_status"] for s in attached.json()["sources"]] == ["unverified"]
    submitted = await desk.post(author, f"/revisions/{rid}/submit")
    assert submitted.json()["status"] == "in_review"
    queue = await desk.get(reviewer, "/revisions", status="in_review")
    assert rid in [r["id"] for r in queue.json()["revisions"]]

    # 5. approval is refused while the source's rights are not cleared (trigger),
    #    and that refusal leaves no review behind
    refused = await desk.post(reviewer, f"/revisions/{rid}/reviews", {"verdict": "approved"})
    assert_error(refused, 409, "sources_not_cleared")
    still = (await desk.get(reviewer, f"/revisions/{rid}")).json()
    assert (still["status"], still["reviews"]) == ("in_review", [])

    # 6. the admin clears the rights; a different person than the author approves
    rights = await desk.put(
        reviewer,
        f"/sources/{source_id}/rights",
        {"rights_status": "cleared", "rights_notes": "Synthetic."},
    )
    assert rights.status_code == 204
    review = await desk.post(
        reviewer, f"/revisions/{rid}/reviews", {"verdict": "approved", "notes": "Relu et vérifié."}
    )
    assert review.status_code == 201, review.text
    approved = review.json()["revision"]
    assert (approved["status"], approved["approved_by"]) == ("approved", str(reviewer.user_id))
    assert approved["approved_at"] is not None
    assert [(r["reviewer_id"], r["verdict"], r["notes"]) for r in approved["reviews"]] == [
        (str(reviewer.user_id), "approved", "Relu et vérifié.")
    ]
    # approved is not yet published
    assert (await learner_lesson(client, learner, lesson_id)).status_code == 404

    # 7. a pack release is built (ready) — still not published
    pack_key = slug()
    built = await desk.post(
        author, "/packs", {"pack_key": pack_key, "locale": "fr", "revision_ids": [rid]}
    )
    assert built.status_code == 201, built.text
    release = built.json()
    assert (release["status"], release["revision"], release["is_current"]) == ("ready", 1, False)
    assert [i["lesson_revision_id"] for i in release["items"]] == [rid]
    assert len(release["manifest_sha256"]) == 64
    assert (await learner_lesson(client, learner, lesson_id)).status_code == 404

    # 8. the publisher releases it: one action, and the lesson is live
    released = await desk.post(author, f"/packs/{release['id']}/release")
    assert released.status_code == 200, released.text
    assert released.json()["previous_release_id"] is None
    assert (released.json()["release"]["status"], released.json()["release"]["is_current"]) == (
        "active",
        True,
    )
    assert released.json()["release"]["released_at"] is not None

    listed = (await catalog_lessons(client, learner))[lesson_id]
    assert (listed["title"], listed["revision_id"], listed["revision"]) == (
        "Additionner de petits nombres",
        rid,
        1,
    )
    lesson = await learner_lesson(client, learner, lesson_id)
    assert lesson.status_code == 200
    assert lesson.json()["blocks"] == edited_body["blocks"]
    assert [q["id"] for q in lesson.json()["questions"]] == [question_id]

    # 9. the learner answers the question and the server scores it
    pushed = await client.post(
        "/v1/sync/push",
        headers=bearer(learner),
        json={"ops": [answer_op(uuid.UUID(question_id), "b")]},
    )
    assert pushed.status_code == 200, pushed.text
    result = pushed.json()["results"][0]
    assert result["status"] == "accepted", result

    # 10. every step left an audit event, attributed to the person who did it
    assert await audit_actions(admin, author.user_id, reviewer.user_id) == [
        ("staff", "lesson.create", "allowed"),
        ("staff", "lesson_revision.create", "allowed"),
        ("staff", "lesson_revision.update", "allowed"),
        ("staff", "content_source.create", "allowed"),
        ("staff", "lesson_revision.attach_source", "allowed"),
        ("staff", "lesson_revision.submit", "allowed"),
        ("staff", "content_source.set_rights", "allowed"),
        ("staff", "lesson_revision.review", "allowed"),
        ("staff", "pack_release.build", "allowed"),
        ("staff", "pack_release.release", "allowed"),
    ]
    by_actor = await admin.fetch(
        "SELECT action, actor_id FROM app.audit_events WHERE actor_id = ANY($1::uuid[])",
        [author.user_id, reviewer.user_id],
    )
    assert {row["action"] for row in by_actor if row["actor_id"] == reviewer.user_id} == {
        "content_source.set_rights",
        "lesson_revision.review",
    }
    # audit details never carry the lesson's text or the reviewer's notes
    details = " ".join(
        row["details"]
        for row in await admin.fetch(
            "SELECT details::text AS details FROM app.audit_events WHERE actor_id = ANY($1::uuid[])",
            [author.user_id, reviewer.user_id],
        )
    )
    assert "Additionner" not in details and "Relu" not in details and "example.test" not in details


async def test_a_new_release_replaces_the_old_one_and_rollback_is_one_audited_action(
    desk: Desk, client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    learner = tokens["student_a"]
    lesson_id = await desk.lesson()
    pack_key = slug()
    first = await desk.approved(lesson_id, title="Version un")
    release_1 = (await desk.released(first["id"], pack_key))["release"]

    second = await desk.approved(lesson_id, title="Version deux")
    assert second["revision"] == 2
    switched = await desk.released(second["id"], pack_key)
    release_2 = switched["release"]
    assert switched["previous_release_id"] == release_1["id"]
    assert release_2["revision"] == 2
    assert (await learner_lesson(client, learner, lesson_id)).json()["title"] == "Version deux"

    releases = (await desk.get(desk.author, "/packs", pack_key=pack_key)).json()["releases"]
    assert [(r["revision"], r["status"], r["is_current"]) for r in releases] == [
        (2, "active", True),
        (1, "retired", False),
    ]

    # rollback: needs a retired release; the active one is refused
    assert_error(
        await desk.post(desk.author, f"/packs/{release_2['id']}/rollback"),
        409,
        "pack_release_not_retired",
    )
    before = len(await audit_actions(admin, desk.author.user_id))
    rolled = await desk.post(desk.author, f"/packs/{release_1['id']}/rollback")
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["previous_release_id"] == release_2["id"]
    assert (rolled.json()["release"]["status"], rolled.json()["release"]["is_current"]) == (
        "active",
        True,
    )
    assert (await learner_lesson(client, learner, lesson_id)).json()["title"] == "Version un"
    assert (await catalog_lessons(client, learner))[lesson_id]["revision"] == 1
    after = await audit_actions(admin, desk.author.user_id)
    assert after[before:] == [("staff", "pack_release.rollback", "allowed")], "one audited action"

    releases = (await desk.get(desk.author, "/packs", pack_key=pack_key)).json()["releases"]
    assert [(r["revision"], r["status"], r["is_current"]) for r in releases] == [
        (2, "retired", False),
        (1, "active", True),
    ]
    # releasing an already used release again is refused; rolling forward is a rollback to 2
    assert_error(
        await desk.post(desk.author, f"/packs/{release_2['id']}/release"),
        409,
        "pack_release_not_ready",
    )
    assert (await desk.post(desk.author, f"/packs/{release_2['id']}/rollback")).status_code == 200
    assert (await learner_lesson(client, learner, lesson_id)).json()["title"] == "Version deux"
    exactly_one_current = await admin.fetchval(
        "SELECT count(*) FROM app.pack_current WHERE pack_key = $1", pack_key
    )
    assert exactly_one_current == 1


# ------------------------------------------------------------- negative cases
async def test_an_author_cannot_approve_their_own_work(
    staff_client: httpx.AsyncClient, make_staff: MakeStaff, desk: Desk, admin: asyncpg.Pool
) -> None:
    """Even an author who also holds the reviewer role (trigger: reviewer ≠ author)."""
    both = await make_staff("editor", "reviewer")
    own = Desk(staff_client, both, desk.reviewer)
    lesson_id = await own.lesson()
    rid = (await own.draft(lesson_id))["id"]
    source_id = await own.cleared_source()
    await own.post(both, f"/revisions/{rid}/sources", {"source_id": source_id})
    assert (await own.post(both, f"/revisions/{rid}/submit")).status_code == 200

    for verdict in ("approved", "rejected", "changes_requested"):
        refused = await own.post(both, f"/revisions/{rid}/reviews", {"verdict": verdict})
        assert_error(refused, 409, "author_cannot_review")
    state = (await own.get(both, f"/revisions/{rid}")).json()
    assert (state["status"], state["reviews"], state["approved_by"]) == ("in_review", [], None)
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.editorial_reviews WHERE lesson_revision_id = $1",
            uuid.UUID(rid),
        )
        == 0
    )
    # the independent reviewer can
    assert (
        await own.post(desk.reviewer, f"/revisions/{rid}/reviews", {"verdict": "approved"})
    ).status_code == 201


async def test_an_editor_cannot_release_or_roll_back(
    staff_client: httpx.AsyncClient, make_staff: MakeStaff, desk: Desk, admin: asyncpg.Pool
) -> None:
    editor = await make_staff("editor")
    lesson_id = await desk.lesson()
    revision = await desk.approved(lesson_id)
    built = await desk.post(
        editor, "/packs", {"pack_key": slug(), "locale": "fr", "revision_ids": [revision["id"]]}
    )
    assert built.status_code == 201, "an editor may build a release"
    release_id = built.json()["id"]

    assert_error(await desk.post(editor, f"/packs/{release_id}/release"), 403, "forbidden")
    assert_error(await desk.post(editor, f"/packs/{release_id}/rollback"), 403, "forbidden")
    state = (await desk.get(editor, "/packs", pack_key=built.json()["pack_key"])).json()["releases"]
    assert [(r["status"], r["is_current"]) for r in state] == [("ready", False)]
    denied = await admin.fetch(
        "SELECT details FROM app.audit_events WHERE actor_id = $1 AND outcome = 'denied'",
        editor.user_id,
    )
    assert len(denied) == 1, "the refusals were audited (one event per minute per account)"
    assert json.loads(denied[0]["details"]) == {
        "method": "POST",
        "route": "/v1/staff/packs/{release_id}/release",
        "check": "route",
        "required_roles": ["admin", "publisher"],
    }
    assert release_id not in denied[0]["details"]
    # a reviewer cannot either; a publisher can
    assert (await desk.post(desk.author, f"/packs/{release_id}/release")).status_code == 200


def _every_staff_route() -> list[tuple[str, str]]:
    routes = [("GET", "/me")]
    for route in staff_editorial.router.routes:
        path = route.path  # type: ignore[attr-defined]
        for name in ("lesson_id", "revision_id", "source_id", "release_id"):
            path = path.replace("{" + name + "}", str(uuid.uuid4()))
        routes.extend((method, path) for method in sorted(route.methods))  # type: ignore[attr-defined]
    return routes


async def test_a_learner_is_refused_on_every_staff_route(
    staff_client: httpx.AsyncClient,
    tokens: dict[str, str],
    local_env: dict[str, str],
    admin: asyncpg.Pool,
) -> None:
    routes = _every_staff_route()
    assert len(routes) >= 17
    fresh_id, _, fresh_token = await create_account(local_env)
    try:
        before = await admin.fetchval(
            "SELECT count(*) FROM app.audit_events WHERE outcome = 'allowed'"
        )
        for method, path in routes:
            for token in (tokens["student_a"], fresh_token):
                # with no body, a valid body or rubbish: the refusal comes first
                for body in (None, sample_revision_body(), {"rubbish": True}):
                    response = await staff_client.request(
                        method, S + path, headers=bearer(token), json=body
                    )
                    assert_error(response, 403, "forbidden")
            assert_error(await staff_client.request(method, S + path), 401, "unauthenticated")
        assert before == await admin.fetchval(
            "SELECT count(*) FROM app.audit_events WHERE outcome = 'allowed'"
        ), "no staff action happened"
        assert (
            await admin.fetchval(
                "SELECT count(*) FROM app.audit_events WHERE actor_id = $1 AND outcome = 'denied'",
                fresh_id,
            )
            == 1
        )
    finally:
        await remove_account(admin, local_env, fresh_id)


async def test_each_role_reaches_only_its_own_actions(
    staff_client: httpx.AsyncClient, make_staff: MakeStaff, desk: Desk
) -> None:
    reviewer_only = await make_staff("reviewer")
    publisher_only = await make_staff("publisher")
    editor_only = await make_staff("editor")
    lesson_id = await desk.lesson()
    revision = await desk.approved(lesson_id)
    rid = revision["id"]

    for who in (reviewer_only, publisher_only):
        assert_error(
            await desk.post(who, "/lessons", {"unit_id": str(SEED_UNIT), "slug": slug()}),
            403,
            "forbidden",
        )
        assert_error(
            await desk.post(who, f"/lessons/{lesson_id}/revisions", sample_revision_body()),
            403,
            "forbidden",
        )
        assert_error(await desk.post(who, "/sources", {"source_title": "x"}), 403, "forbidden")
    for who in (editor_only, publisher_only):
        assert_error(
            await desk.post(who, f"/revisions/{rid}/reviews", {"verdict": "approved"}),
            403,
            "forbidden",
        )
    for who in (editor_only, reviewer_only, publisher_only):
        assert_error(
            await desk.put(who, f"/sources/{uuid.uuid4()}/rights", {"rights_status": "cleared"}),
            403,
            "forbidden",
        )
        # every staff role may read
        assert (await desk.get(who, f"/revisions/{rid}")).status_code == 200
        assert (await desk.get(who, "/revisions")).status_code == 200
        assert (await desk.get(who, "/sources")).status_code == 200
        assert (await desk.get(who, "/packs")).status_code == 200
    assert_error(
        await desk.post(
            reviewer_only, "/packs", {"pack_key": slug(), "locale": "fr", "revision_ids": [rid]}
        ),
        403,
        "forbidden",
    )


async def test_only_the_author_changes_a_draft(
    staff_client: httpx.AsyncClient, make_staff: MakeStaff, desk: Desk, admin: asyncpg.Pool
) -> None:
    other_editor = await make_staff("editor")
    lesson_id = await desk.lesson()
    draft = await desk.draft(lesson_id)
    rid = draft["id"]
    source_id = await desk.cleared_source()
    body = {"title": "Pris par un autre", "blocks": draft["blocks"], "questions": []}

    assert_error(await desk.put(other_editor, f"/revisions/{rid}", body), 403, "forbidden")
    assert_error(
        await desk.post(other_editor, f"/revisions/{rid}/sources", {"source_id": source_id}),
        403,
        "forbidden",
    )
    assert_error(await desk.post(other_editor, f"/revisions/{rid}/submit"), 403, "forbidden")
    unchanged = (await desk.get(other_editor, f"/revisions/{rid}")).json()
    assert (unchanged["title"], unchanged["status"], unchanged["sources"]) == (
        draft["title"],
        "draft",
        [],
    )
    denied = await admin.fetch(
        "SELECT details FROM app.audit_events WHERE actor_id = $1 AND outcome = 'denied'",
        other_editor.user_id,
    )
    assert [json.loads(row["details"]) for row in denied] == [
        {"method": "PUT", "route": "/v1/staff/revisions/{revision_id}", "check": "function"}
    ]
    # an admin may step in
    assert (await desk.put(desk.reviewer, f"/revisions/{rid}", body)).status_code == 200
    assert (await desk.get(desk.author, f"/revisions/{rid}")).json()["created_by"] == str(
        desk.author.user_id
    ), "authorship does not move"


async def test_content_is_frozen_once_submitted_reviewed_or_approved(desk: Desk) -> None:
    lesson_id = await desk.lesson()
    draft = await desk.draft(lesson_id)
    rid = draft["id"]
    body = {"title": "Changement tardif", "blocks": draft["blocks"], "questions": []}
    source_id = await desk.cleared_source()
    other_source = await desk.cleared_source()
    await desk.post(desk.author, f"/revisions/{rid}/sources", {"source_id": source_id})
    await desk.post(desk.author, f"/revisions/{rid}/submit")

    # in the review queue
    assert_error(await desk.put(desk.author, f"/revisions/{rid}", body), 409, "revision_in_review")
    assert_error(
        await desk.post(desk.author, f"/revisions/{rid}/sources", {"source_id": other_source}),
        409,
        "revision_in_review",
    )
    assert_error(
        await desk.post(desk.author, f"/revisions/{rid}/submit"), 409, "revision_not_draft"
    )

    # approved: the triggers refuse every change
    assert (
        await desk.post(desk.reviewer, f"/revisions/{rid}/reviews", {"verdict": "approved"})
    ).status_code == 201
    assert_error(await desk.put(desk.author, f"/revisions/{rid}", body), 409, "revision_immutable")
    assert_error(
        await desk.post(desk.author, f"/revisions/{rid}/sources", {"source_id": other_source}),
        409,
        "revision_already_reviewed",
    )
    detach = await desk.http.delete(
        f"{S}/revisions/{rid}/sources/{source_id}", headers=bearer(desk.author.token)
    )
    assert_error(detach, 409, "revision_already_reviewed")
    assert_error(
        await desk.post(desk.reviewer, f"/revisions/{rid}/reviews", {"verdict": "rejected"}),
        409,
        "revision_not_in_review",
    )
    final = (await desk.get(desk.author, f"/revisions/{rid}")).json()
    assert (final["title"], final["status"], len(final["sources"])) == (
        draft["title"],
        "approved",
        1,
    )


async def test_a_rejected_revision_stays_closed_and_a_new_revision_starts_again(desk: Desk) -> None:
    lesson_id = await desk.lesson()
    draft = await desk.draft(lesson_id)
    rid = draft["id"]
    await desk.post(
        desk.author, f"/revisions/{rid}/sources", {"source_id": await desk.cleared_source()}
    )
    await desk.post(desk.author, f"/revisions/{rid}/submit")
    review = await desk.post(
        desk.reviewer,
        f"/revisions/{rid}/reviews",
        {"verdict": "changes_requested", "notes": "Étape 2 à revoir."},
    )
    assert review.status_code == 201
    assert review.json()["revision"]["status"] == "rejected"
    assert review.json()["revision"]["approved_by"] is None

    body = {"title": "Corrigé", "blocks": draft["blocks"], "questions": []}
    assert_error(
        await desk.put(desk.author, f"/revisions/{rid}", body), 409, "revision_already_reviewed"
    )
    assert_error(
        await desk.post(desk.author, f"/revisions/{rid}/submit"), 409, "revision_not_draft"
    )
    assert_error(
        await desk.post(
            desk.author, "/packs", {"pack_key": slug(), "locale": "fr", "revision_ids": [rid]}
        ),
        409,
        "pack_item_not_approved",
    )
    again = await desk.draft(lesson_id, title="Corrigé")
    assert (again["revision"], again["status"]) == (2, "draft")
    creole = await desk.draft(lesson_id, locale="ht", title="Leson an kreyòl")
    assert creole["revision"] == 1, "revision numbers are per language"


async def test_an_unreviewed_revision_cannot_enter_a_pack(desk: Desk, admin: asyncpg.Pool) -> None:
    lesson_id = await desk.lesson()
    approved = await desk.approved(lesson_id)
    draft = await desk.draft(lesson_id)
    in_review = await desk.draft(await desk.lesson())
    await desk.post(
        desk.author,
        f"/revisions/{in_review['id']}/sources",
        {"source_id": await desk.cleared_source()},
    )
    await desk.post(desk.author, f"/revisions/{in_review['id']}/submit")
    pack_key = slug()

    for ids in ([draft["id"]], [in_review["id"]], [approved["id"], draft["id"]]):
        refused = await desk.post(
            desk.author, "/packs", {"pack_key": pack_key, "locale": "fr", "revision_ids": ids}
        )
        assert_error(refused, 409, "pack_item_not_approved")
    # wrong language
    assert_error(
        await desk.post(
            desk.author,
            "/packs",
            {"pack_key": pack_key, "locale": "ht", "revision_ids": [approved["id"]]},
        ),
        409,
        "pack_item_not_approved",
    )
    # nothing was left behind by the refused builds
    assert (
        await admin.fetchval("SELECT count(*) FROM app.pack_releases WHERE pack_key = $1", pack_key)
        == 0
    )
    assert_error(
        await desk.post(
            desk.author,
            "/packs",
            {"pack_key": pack_key, "locale": "fr", "revision_ids": [str(uuid.uuid4())]},
        ),
        404,
        "revision_not_found",
    )
    assert_error(
        await desk.post(
            desk.author,
            "/packs",
            {"pack_key": pack_key, "locale": "fr", "revision_ids": [approved["id"]] * 2},
        ),
        422,
        "pack_items_duplicated",
    )


async def test_withdrawn_rights_stop_a_build_and_a_release(desk: Desk) -> None:
    lesson_id = await desk.lesson()
    draft = await desk.draft(lesson_id)
    rid = draft["id"]
    source_id = await desk.cleared_source()
    await desk.post(desk.author, f"/revisions/{rid}/sources", {"source_id": source_id})
    await desk.post(desk.author, f"/revisions/{rid}/submit")
    await desk.post(desk.reviewer, f"/revisions/{rid}/reviews", {"verdict": "approved"})
    ready = await desk.post(
        desk.author, "/packs", {"pack_key": slug(), "locale": "fr", "revision_ids": [rid]}
    )
    assert ready.status_code == 201

    blocked = await desk.put(
        desk.reviewer, f"/sources/{source_id}/rights", {"rights_status": "blocked"}
    )
    assert blocked.status_code == 204
    assert_error(
        await desk.post(desk.author, f"/packs/{ready.json()['id']}/release"),
        409,
        "sources_not_cleared",
    )
    assert_error(
        await desk.post(
            desk.author, "/packs", {"pack_key": slug(), "locale": "fr", "revision_ids": [rid]}
        ),
        409,
        "sources_not_cleared",
    )


@pytest.mark.parametrize(
    ("mutate", "where"),
    [
        (lambda b: b.update(title=""), "title"),
        (lambda b: b.update(title="x" * 201), "title"),
        (lambda b: b.update(locale="en"), "locale"),
        (lambda b: b.update(blocks=[]), "blocks"),
        (lambda b: b["blocks"].append({"key": "h", "type": "html", "text": "<b>x</b>"}), "blocks"),
        (
            lambda b: b["blocks"].append({"key": "Bad Key", "type": "paragraph", "text": "x"}),
            "blocks",
        ),
        (lambda b: b["blocks"].append({"key": "intro", "type": "paragraph", "text": "x"}), "body"),
        (lambda b: b["blocks"][0].update(extra="field"), "blocks"),
        (lambda b: b["blocks"][3].update(tone="shout"), "blocks"),
        (lambda b: b["questions"][0].update(kind="numeric"), "questions"),
        (lambda b: b["questions"][0]["answer_key"].update(correct_choice_id="z"), "questions"),
        (
            lambda b: b["questions"][0]["response_spec"].update(choices=[{"id": "a", "text": "1"}]),
            "questions",
        ),
        (lambda b: b["questions"][1].update(question_key="q1"), "body"),
        (lambda b: b["questions"][0]["prompt"].update(html="<script>"), "questions"),
        (lambda b: b.update(status="approved"), "status"),
        (lambda b: b.update(created_by=str(uuid.uuid4())), "created_by"),
    ],
)
async def test_content_that_breaks_the_published_format_is_refused(
    desk: Desk, admin: asyncpg.Pool, mutate: Any, where: str
) -> None:
    lesson_id = await desk.lesson()
    body = json.loads(json.dumps(sample_revision_body()))
    mutate(body)
    refused = await desk.post(desk.author, f"/lessons/{lesson_id}/revisions", body)
    assert_error(refused, 422, "validation_error")
    locations = [".".join(detail["loc"]) for detail in refused.json()["error"]["details"]]
    assert any(where in location for location in locations), locations
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.lesson_revisions WHERE lesson_id = $1", uuid.UUID(lesson_id)
        )
        == 0
    )


async def test_unknown_objects_and_bad_states_have_clear_errors(desk: Desk) -> None:
    missing = uuid.uuid4()
    author, reviewer = desk.author, desk.reviewer
    assert_error(
        await desk.post(author, "/lessons", {"unit_id": str(missing), "slug": slug()}),
        404,
        "unit_not_found",
    )
    taken = slug()
    assert (
        await desk.post(author, "/lessons", {"unit_id": str(SEED_UNIT), "slug": taken})
    ).status_code == 201
    assert_error(
        await desk.post(author, "/lessons", {"unit_id": str(SEED_UNIT), "slug": taken}),
        409,
        "lesson_slug_taken",
    )
    assert_error(
        await desk.post(author, f"/lessons/{missing}/revisions", sample_revision_body()),
        404,
        "lesson_not_found",
    )
    assert_error(await desk.get(author, f"/revisions/{missing}"), 404, "revision_not_found")
    assert_error(await desk.post(author, f"/revisions/{missing}/submit"), 404, "revision_not_found")
    assert_error(
        await desk.post(reviewer, f"/revisions/{missing}/reviews", {"verdict": "approved"}),
        404,
        "revision_not_found",
    )
    assert_error(
        await desk.put(reviewer, f"/sources/{missing}/rights", {"rights_status": "cleared"}),
        404,
        "source_not_found",
    )
    assert_error(
        await desk.post(author, f"/packs/{missing}/release"), 404, "pack_release_not_found"
    )
    assert_error(
        await desk.post(author, f"/packs/{missing}/rollback"), 404, "pack_release_not_found"
    )

    draft = await desk.draft(await desk.lesson())
    assert_error(
        await desk.post(author, f"/revisions/{draft['id']}/sources", {"source_id": str(missing)}),
        404,
        "source_not_found",
    )
    assert_error(
        await desk.http.delete(
            f"{S}/revisions/{draft['id']}/sources/{missing}", headers=bearer(author.token)
        ),
        404,
        "source_not_attached",
    )
    assert_error(
        await desk.post(reviewer, f"/revisions/{draft['id']}/reviews", {"verdict": "approved"}),
        409,
        "revision_not_in_review",
    )
    for bad in (
        {"verdict": "maybe"},
        {"verdict": "approved", "notes": "x" * 4001},
        {"verdict": "approved", "reviewer_id": str(missing)},
    ):
        assert_error(
            await desk.post(reviewer, f"/revisions/{draft['id']}/reviews", bad),
            422,
            "validation_error",
        )
    assert_error(
        await desk.post(
            author, "/sources", {"source_title": "x", "source_uri": "javascript:alert(1)"}
        ),
        422,
        "validation_error",
    )
    assert_error(
        await desk.post(author, "/sources", {"source_title": "x", "rights_status": "cleared"}),
        422,
        "validation_error",
    )
    assert_error(await desk.get(author, "/revisions", status="published"), 422, "validation_error")
    assert_error(await desk.get(author, "/revisions/not-a-uuid"), 422, "validation_error")


async def test_a_revoked_reviewer_role_stops_reviews_at_once(
    desk: Desk, make_staff: MakeStaff, admin: asyncpg.Pool
) -> None:
    reviewer = await make_staff("reviewer")
    lesson_id = await desk.lesson()
    rid = (await desk.draft(lesson_id))["id"]
    await desk.post(
        desk.author, f"/revisions/{rid}/sources", {"source_id": await desk.cleared_source()}
    )
    await desk.post(desk.author, f"/revisions/{rid}/submit")
    await set_role_active(admin, reviewer.user_id, "reviewer", False)
    assert_error(
        await desk.post(reviewer, f"/revisions/{rid}/reviews", {"verdict": "approved"}),
        403,
        "forbidden",
    )
    assert (await desk.get(desk.author, f"/revisions/{rid}")).json()["status"] == "in_review"
