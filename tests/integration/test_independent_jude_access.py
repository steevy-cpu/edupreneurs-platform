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


@pytest.mark.integration
async def test_signed_sessions_have_independent_status_and_only_own_identity(settings, tokens):
    import httpx

    from edu_api.main import create_app
    from edu_api.tutor.router import build_tutor_router
    from tests.helpers import bearer
    from tests.unit.tutor.conftest import ask, build_harness

    # Private ASGI instance only. Its ordinary verifier uses this runner's JWKS.
    isolated = create_app(settings)
    fixture = build_harness(learners=(STUDENT_A, STUDENT_B))
    isolated.include_router(build_tutor_router(lambda: fixture.service))
    async with (
        isolated.router.lifespan_context(isolated),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=isolated), base_url="http://qa.test"
        ) as client,
    ):
        identity_a = bearer(tokens["student_a"])
        identity_b = bearer(tokens["student_b"])
        body = ask().model_dump(mode="json")
        url = "/v1/jude/requests"
        status = "/v1/jude/status"
        assert (await client.post(url, json=body, headers=identity_a)).status_code == 200
        assert (await client.get(status, headers=identity_a)).json()["daily_requests_used"] == 1
        assert (await client.get(status, headers=identity_b)).json()["daily_requests_used"] == 0
        assert (
            await client.post(url, json=dict(body, learner_id=str(STUDENT_A)), headers=identity_b)
        ).status_code == 422
        assert (await client.get(status, headers=identity_b)).json()["daily_requests_used"] == 0
