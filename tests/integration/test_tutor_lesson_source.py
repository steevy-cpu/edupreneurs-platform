"""Jude reads lessons as the learner: PostgreSQL row-level security decides what exists.

These tests use the real local stack (seeded, approved, published content) and the
application's own least-privileged connection. No tutor table exists in the
application database: the usage ledger here is the in-memory one, and the model
is the deterministic mock.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import asyncpg
import pytest
from fastapi import FastAPI

from edu_api.tutor.budget import InMemoryUsageStore
from edu_api.tutor.config import TutorSettings
from edu_api.tutor.content import SqlLessonSource
from edu_api.tutor.errors import LessonRevisionNotCurrent, LessonUnavailable
from edu_api.tutor.factory import build_tutor_service
from edu_api.tutor.governance import ConsentState, StaticConsent, StaticEntitlements
from edu_api.tutor.providers.mock import DeterministicMockProvider
from edu_api.tutor.types import ResponseStatus, TutorRequest
from tests.conftest import (
    approve_revision,
    create_lesson,
    create_revision,
    publish_new_lesson,
    release_pack,
)
from tests.helpers import SEED_LESSON, SEED_REV_FR, SEED_REV_HT, STUDENT_A, STUDENT_B

pytestmark = pytest.mark.integration


@pytest.fixture
def lessons(app: FastAPI) -> SqlLessonSource:
    return SqlLessonSource(app.state.db)


async def get(lessons: SqlLessonSource, lesson_id: uuid.UUID, **kwargs: object) -> object:
    options: dict[str, object] = {"learner_id": STUDENT_A, "locale": "fr", "revision_id": None}
    options.update(kwargs)
    return await lessons.get_approved_lesson(lesson_id=lesson_id, **options)  # type: ignore[arg-type]


async def test_published_seed_lesson_is_read_in_both_languages(lessons: SqlLessonSource) -> None:
    fr = await lessons.get_approved_lesson(
        learner_id=STUDENT_A, lesson_id=SEED_LESSON, locale="fr", revision_id=None
    )
    ht = await lessons.get_approved_lesson(
        learner_id=STUDENT_B, lesson_id=SEED_LESSON, locale="ht", revision_id=SEED_REV_HT
    )
    assert (fr.revision_id, fr.locale, fr.title) == (
        SEED_REV_FR,
        "fr",
        "Résoudre une équation simple",
    )
    assert (ht.revision_id, ht.locale) == (SEED_REV_HT, "ht")
    assert [b.key for b in fr.blocks] == [
        "intro",
        "regle-titre",
        "regle",
        "exemple-1",
        "exemple-2",
        "astuce",
    ]
    assert fr.block("exemple-1") is not None and "x = 7" in fr.block("exemple-1").text  # type: ignore[union-attr]
    assert len(fr.questions) == 5 and len(ht.questions) == 5
    assert all(q.correct_choice_id and q.choices and q.explanation for q in fr.questions)
    assert fr.assessment_mode == "offline_practice"


async def test_draft_in_review_and_unreleased_revisions_do_not_exist_for_the_tutor(
    lessons: SqlLessonSource, admin: asyncpg.Pool
) -> None:
    lesson_id = await create_lesson(admin)
    revision_id, _ = await create_revision(admin, lesson_id, revision=1)
    with pytest.raises(LessonUnavailable):  # draft
        await get(lessons, lesson_id)
    await admin.execute(
        "UPDATE app.lesson_revisions SET status = 'in_review' WHERE id = $1", revision_id
    )
    with pytest.raises(LessonUnavailable):  # in review
        await get(lessons, lesson_id)
    await approve_revision(admin, revision_id)
    with pytest.raises(LessonUnavailable):  # approved but not in any current pack
        await get(lessons, lesson_id)
    await release_pack(admin, f"it-{uuid.uuid4().hex[:12]}", revision_id, pack_revision=1)
    assert (await get(lessons, lesson_id)).revision_id == revision_id  # type: ignore[attr-defined]


async def test_unknown_lesson_and_missing_language_are_the_same_refusal(
    lessons: SqlLessonSource, admin: asyncpg.Pool
) -> None:
    with pytest.raises(LessonUnavailable):
        await get(lessons, uuid.uuid4())
    published = await publish_new_lesson(admin)  # French only
    with pytest.raises(LessonUnavailable):
        await get(lessons, published["lesson_id"], locale="ht")


async def test_a_replaced_revision_is_reported_and_a_newer_draft_is_invisible(
    lessons: SqlLessonSource, admin: asyncpg.Pool
) -> None:
    published = await publish_new_lesson(admin)
    lesson_id, first = published["lesson_id"], published["revision_id"]
    draft, _ = await create_revision(admin, lesson_id, revision=2, title="Brouillon non relu")
    current = await get(lessons, lesson_id, revision_id=first)
    assert current.revision_id == first  # type: ignore[attr-defined]  # the draft changes nothing

    await approve_revision(admin, draft)
    await release_pack(admin, published["pack_key"], draft, pack_revision=2)
    with pytest.raises(LessonRevisionNotCurrent):
        await get(lessons, lesson_id, revision_id=first)
    assert (await get(lessons, lesson_id)).revision_id == draft  # type: ignore[attr-defined]


async def test_tutor_answers_from_the_real_published_lesson_with_real_references(
    lessons: SqlLessonSource, admin: asyncpg.Pool
) -> None:
    settings = TutorSettings(_env_file=None, enabled=True)
    provider = DeterministicMockProvider()
    usage = InMemoryUsageStore(settings.budget_policy(), clock=lambda: datetime.now(UTC))
    service = build_tutor_service(
        settings,
        lessons=lessons,
        usage=usage,
        consent=StaticConsent({STUDENT_A: ConsentState.GRANTED}),
        entitlements=StaticEntitlements({STUDENT_A}),
        provider=provider,
    )
    response = await service.answer(
        STUDENT_A,
        TutorRequest(
            idempotency_key=uuid.uuid4(),
            lesson_id=SEED_LESSON,
            lesson_revision_id=SEED_REV_FR,
            locale="fr",
            intent="ask_question",  # type: ignore[arg-type]
            message="Pourquoi la balance reste en équilibre ?",
        ),
    )
    assert response.status is ResponseStatus.ANSWERED
    assert response.lesson_revision_id == SEED_REV_FR
    keys = {ref.key for ref in response.references}
    assert "regle" in keys
    stored_keys = await admin.fetchval(
        "SELECT array_agg(b ->> 'key') FROM app.lesson_revisions r, "
        "jsonb_array_elements(r.blocks) b WHERE r.id = $1",
        SEED_REV_FR,
    )
    assert keys <= set(stored_keys)
    assert {(ref.lesson_id, ref.lesson_revision_id, ref.locale) for ref in response.references} == {
        (SEED_LESSON, SEED_REV_FR, "fr")
    }
    assert len(provider.calls) == 1 and len(usage.records()) == 1


async def test_jude_01_adds_nothing_to_the_application_database(admin: asyncpg.Pool) -> None:
    assert await admin.fetchval("SELECT to_regnamespace('tutor') IS NULL")
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name ILIKE '%tutor%' OR table_name ILIKE '%jude%'"
        )
        == 0
    )
