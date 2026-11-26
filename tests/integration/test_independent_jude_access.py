"""Exercise normal publication/withdrawal transitions on synthetic content only."""

import pytest

from edu_api.tutor.content import SqlLessonSource
from edu_api.tutor.errors import LessonUnavailable
from tests.conftest import publish_new_lesson
from tests.helpers import STUDENT_A, STUDENT_B


@pytest.mark.integration
async def test_withdrawn_pack_is_invisible_to_both_learners(app, admin):
    source = SqlLessonSource(app.state.db)
    published = await publish_new_lesson(admin)
    target = {
        "lesson_id": published["lesson_id"],
        "locale": "fr",
        "revision_id": published["revision_id"],
    }
    for learner in (STUDENT_A, STUDENT_B):
        before = await source.get_approved_lesson(learner_id=learner, **target)
        assert before.revision_id == published["revision_id"]
    async with admin.acquire() as conn, conn.transaction():
        release = await conn.fetchval(
            "DELETE FROM app.pack_current WHERE pack_key=$1 RETURNING release_id",
            published["pack_key"],
        )
        await conn.execute("UPDATE app.pack_releases SET status='revoked' WHERE id=$1", release)
    for learner in (STUDENT_A, STUDENT_B):
        for revision in (None, published["revision_id"]):
            with pytest.raises(LessonUnavailable):
                await source.get_approved_lesson(
                    learner_id=learner,
                    lesson_id=published["lesson_id"],
                    locale="fr",
                    revision_id=revision,
                )
