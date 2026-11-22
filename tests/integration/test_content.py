"""Catalog and lesson endpoints: only approved, currently published content."""

from __future__ import annotations

import uuid
from pathlib import Path

import asyncpg
import httpx
import jsonschema
import pytest

from tests.conftest import (
    approve_revision,
    create_lesson,
    create_revision,
    publish_new_lesson,
    release_pack,
)
from tests.helpers import (
    REVIEWER,
    SEED_LESSON,
    SEED_QUESTIONS_FR,
    SEED_REV_FR,
    SEED_REV_HT,
    STUDENT_A,
    answer_op,
    bearer,
    completed_op,
)

pytestmark = pytest.mark.integration
CONTRACTS = Path(__file__).resolve().parents[2] / "packages" / "contracts" / "content"


def all_lessons(catalog: dict) -> dict[str, dict]:  # type: ignore[type-arg]
    return {
        lesson["id"]: lesson
        for course in catalog["courses"]
        for unit in course["units"]
        for lesson in unit["lessons"]
    }


async def test_catalog_in_both_languages(client: httpx.AsyncClient, tokens: dict[str, str]) -> None:
    fr = (
        await client.get(
            "/v1/catalog", params={"locale": "fr"}, headers=bearer(tokens["student_a"])
        )
    ).json()
    ht = (
        await client.get(
            "/v1/catalog", params={"locale": "ht"}, headers=bearer(tokens["student_a"])
        )
    ).json()
    assert (fr["locale"], ht["locale"]) == ("fr", "ht")
    course_fr, course_ht = fr["courses"][0], ht["courses"][0]
    assert course_fr["title"] == "Mathématiques 9e AF" and course_ht["title"] == "Matematik 9èm AF"
    assert course_fr["grade"] == {"code": "9AF", "label": "9e année fondamentale"}
    assert course_ht["subject"] == {"slug": "mathematiques", "label": "Matematik"}
    assert course_ht["units"][0]["title"] == "Ekwasyon premye degre"
    seed_fr, seed_ht = all_lessons(fr)[str(SEED_LESSON)], all_lessons(ht)[str(SEED_LESSON)]
    assert (seed_fr["title"], seed_fr["revision_id"]) == (
        "Résoudre une équation simple",
        str(SEED_REV_FR),
    )
    assert (seed_ht["title"], seed_ht["revision_id"]) == (
        "Rezoud yon ekwasyon senp",
        str(SEED_REV_HT),
    )


@pytest.mark.parametrize(
    "params", [{}, {"locale": "en"}, {"locale": ""}, {"locale": "fr'; DROP TABLE app.lessons;--"}]
)
async def test_catalog_locale_is_validated(
    client: httpx.AsyncClient, tokens: dict[str, str], params: dict[str, str]
) -> None:
    response = await client.get("/v1/catalog", params=params, headers=bearer(tokens["student_a"]))
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"


async def test_lesson_content_and_offline_practice_questions(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await client.get(
        f"/v1/lessons/{SEED_LESSON}", params={"locale": "fr"}, headers=bearer(tokens["student_b"])
    )
    assert response.status_code == 200
    lesson = response.json()
    assert (lesson["revision_id"], lesson["locale"], lesson["revision"]) == (
        str(SEED_REV_FR),
        "fr",
        1,
    )
    assert lesson["assessment_mode"] == "offline_practice"
    assert [b["type"] for b in lesson["blocks"]] == [
        "paragraph",
        "heading",
        "paragraph",
        "example",
        "example",
        "callout",
    ]
    assert [q["position"] for q in lesson["questions"]] == [1, 2, 3, 4, 5]
    assert [(q["id"], q["answer_key"]["correct_choice_id"]) for q in lesson["questions"]] == [
        (str(qid), correct) for qid, correct in SEED_QUESTIONS_FR
    ]
    assert {q["kind"] for q in lesson["questions"]} == {"mcq"}

    ht = (
        await client.get(
            f"/v1/lessons/{SEED_LESSON}",
            params={"locale": "ht"},
            headers=bearer(tokens["student_b"]),
        )
    ).json()
    assert ht["revision_id"] == str(SEED_REV_HT) and ht["title"] == "Rezoud yon ekwasyon senp"
    assert not {q["id"] for q in ht["questions"]} & {q["id"] for q in lesson["questions"]}, (
        "each language has its own question revisions"
    )


async def test_unknown_or_invalid_lessons(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    headers = bearer(tokens["student_a"])
    missing = await client.get(
        f"/v1/lessons/{uuid.uuid4()}", params={"locale": "fr"}, headers=headers
    )
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "lesson_not_found")
    assert (
        await client.get("/v1/lessons/not-a-uuid", params={"locale": "fr"}, headers=headers)
    ).status_code == 422
    assert (await client.get(f"/v1/lessons/{SEED_LESSON}", headers=headers)).status_code == 422
    assert (await client.get("/v1/nothing-here", headers=headers)).json()["error"][
        "code"
    ] == "not_found"


async def test_unapproved_rejected_and_unpublished_revisions_are_never_served(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    headers = bearer(tokens["student_a"])
    hidden: dict[str, tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = {}

    # draft
    lesson = await create_lesson(admin)
    rev, questions = await create_revision(admin, lesson, revision=1)
    hidden["draft"] = (lesson, rev, questions[0])
    # in review
    lesson = await create_lesson(admin)
    rev, questions = await create_revision(admin, lesson, revision=1)
    await admin.execute("UPDATE app.lesson_revisions SET status = 'in_review' WHERE id = $1", rev)
    hidden["in_review"] = (lesson, rev, questions[0])
    # rejected
    lesson = await create_lesson(admin)
    rev, questions = await create_revision(admin, lesson, revision=1)
    await admin.execute("UPDATE app.lesson_revisions SET status = 'in_review' WHERE id = $1", rev)
    await admin.execute(
        "INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES ($1, $2, 'rejected')",
        rev,
        REVIEWER,
    )
    await admin.execute("UPDATE app.lesson_revisions SET status = 'rejected' WHERE id = $1", rev)
    hidden["rejected"] = (lesson, rev, questions[0])
    # approved but never put in a pack
    lesson = await create_lesson(admin)
    rev, questions = await create_revision(admin, lesson, revision=1)
    await approve_revision(admin, rev)
    hidden["approved_unpublished"] = (lesson, rev, questions[0])

    catalog = all_lessons(
        (await client.get("/v1/catalog", params={"locale": "fr"}, headers=headers)).json()
    )
    for state, (lesson_id, revision_id, question_id) in hidden.items():
        assert str(lesson_id) not in catalog, state
        response = await client.get(
            f"/v1/lessons/{lesson_id}", params={"locale": "fr"}, headers=headers
        )
        assert (response.status_code, response.json()["error"]["code"]) == (
            404,
            "lesson_not_found",
        ), state
        # ... and unpublished content cannot be exercised through sync either
        results = (
            await client.post(
                "/v1/sync/push",
                headers=headers,
                json={"ops": [answer_op(question_id, "b"), completed_op(revision_id)]},
            )
        ).json()["results"]
        assert [(r["status"], r["code"]) for r in results] == [
            ("rejected", "content_not_available")
        ] * 2, state

    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.practice_attempts WHERE learner_id = $1", STUDENT_A
        )
        == 0
    )
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM app.lesson_progress WHERE learner_id = $1", STUDENT_A
        )
        == 0
    )


async def test_a_newer_draft_does_not_replace_the_published_revision(
    client: httpx.AsyncClient, tokens: dict[str, str], admin: asyncpg.Pool
) -> None:
    headers = bearer(tokens["student_a"])
    published = await publish_new_lesson(admin)
    draft, _ = await create_revision(
        admin, published["lesson_id"], revision=2, title="UNAPPROVED DRAFT r2"
    )
    served = (
        await client.get(
            f"/v1/lessons/{published['lesson_id']}", params={"locale": "fr"}, headers=headers
        )
    ).json()
    assert served["revision_id"] == str(published["revision_id"]) and "DRAFT" not in served["title"]

    # once approved AND released, revision 2 takes over; revoking it un-publishes it
    await approve_revision(admin, draft)
    release = await release_pack(admin, published["pack_key"], draft, pack_revision=2)
    served = (
        await client.get(
            f"/v1/lessons/{published['lesson_id']}", params={"locale": "fr"}, headers=headers
        )
    ).json()
    assert served["revision_id"] == str(draft)
    await admin.execute("DELETE FROM app.pack_current WHERE release_id = $1", release)
    await admin.execute("UPDATE app.pack_releases SET status = 'revoked' WHERE id = $1", release)
    gone = await client.get(
        f"/v1/lessons/{published['lesson_id']}", params={"locale": "fr"}, headers=headers
    )
    assert gone.status_code == 404
    refused = (
        await client.post("/v1/sync/push", headers=headers, json={"ops": [completed_op(draft)]})
    ).json()
    assert refused["results"][0]["code"] == "content_not_available", (
        "revoked content is not syncable"
    )


async def test_seed_content_matches_the_published_json_schemas(admin: asyncpg.Pool) -> None:
    import json

    blocks_schema = json.loads((CONTRACTS / "lesson-blocks.schema.json").read_text())
    mcq_schema = json.loads((CONTRACTS / "question-mcq.schema.json").read_text())
    for schema in (blocks_schema, mcq_schema):
        jsonschema.Draft202012Validator.check_schema(schema)

    revisions = await admin.fetch(
        "SELECT id, locale, blocks FROM app.lesson_revisions WHERE id = ANY($1::uuid[])",
        [SEED_REV_FR, SEED_REV_HT],
    )
    assert {r["locale"] for r in revisions} == {"fr", "ht"}
    for revision in revisions:
        jsonschema.validate(json.loads(revision["blocks"]), blocks_schema)

    questions = await admin.fetch(
        "SELECT kind, prompt, response_spec, answer_key, explanation FROM app.question_revisions "
        "WHERE lesson_revision_id = ANY($1::uuid[])",
        [SEED_REV_FR, SEED_REV_HT],
    )
    assert len(questions) == 10
    for question in questions:
        document = {
            name: json.loads(question[name])
            for name in ("prompt", "response_spec", "answer_key", "explanation")
        }
        jsonschema.validate(document, mcq_schema)
        choice_ids = [c["id"] for c in document["response_spec"]["choices"]]
        assert document["answer_key"]["correct_choice_id"] in choice_ids
        assert len(set(choice_ids)) == len(choice_ids)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate([{"key": "x", "type": "html", "text": "<script>"}], blocks_schema)
