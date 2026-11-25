"""`GET` / `PUT /v1/me/onboarding` — resumable, forward-only onboarding state (slice 2)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import asyncpg
import httpx
import pytest

from tests.helpers import SEED_QUESTIONS_FR, SEED_REV_FR, answer_op, completed_op

if TYPE_CHECKING:
    from tests.account_fixtures import SyntheticLearner

pytestmark = pytest.mark.integration
#: Registers the lane's fixtures (account_app, account_client, learners, ...).
pytest_plugins = ["tests.account_fixtures"]

URL = "/v1/me/onboarding"
RESPONSE_KEYS = {
    "state",
    "onboarding_version",
    "tour_version_seen",
    "tour_dismissed",
    "completed_at",
    "updated_at",
}
STORED = "SELECT * FROM account.onboarding_state WHERE user_id = $1"


async def put(client: httpx.AsyncClient, learner: SyntheticLearner, **body: Any) -> dict[str, Any]:
    response = await client.put(URL, json=body, headers=learner.headers)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    assert set(data) == RESPONSE_KEYS
    return data


async def get(client: httpx.AsyncClient, learner: SyntheticLearner) -> dict[str, Any]:
    response = await client.get(URL, headers=learner.headers)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    assert set(data) == RESPONSE_KEYS
    return data


# ------------------------------------------------------------ the happy path
async def test_new_learner_walks_forward_through_onboarding(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    x = learners["x"]
    assert await get(account_client, x) == {
        "state": "new",
        "onboarding_version": 0,
        "tour_version_seen": 0,
        "tour_dismissed": False,
        "completed_at": None,
        "updated_at": None,
    }
    # Reading creates nothing.
    assert await admin.fetchrow(STORED, x.user_id) is None

    for state in ("profile_selected", "downloads_informed"):
        step = await put(account_client, x, state=state, onboarding_version=1)
        assert step["state"] == state and step["completed_at"] is None
        assert await get(account_client, x) == step

    done = await put(account_client, x, state="ready", onboarding_version=1)
    assert done["state"] == "ready" and done["completed_at"] is not None
    assert await get(account_client, x) == done


async def test_an_offline_device_may_report_only_the_final_state(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner]
) -> None:
    done = await put(
        account_client,
        learners["x"],
        state="ready",
        onboarding_version=2,
        tour_version_seen=1,
        tour_dismissed=True,
    )
    assert (done["state"], done["onboarding_version"]) == ("ready", 2)
    assert (done["tour_version_seen"], done["tour_dismissed"]) == (1, True)


# ----------------------------------------------- forward-only and idempotent
async def test_stale_and_repeated_requests_are_accepted_and_change_nothing(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    x = learners["x"]
    reached = await put(account_client, x, state="downloads_informed", onboarding_version=1)
    stored = await admin.fetchrow(STORED, x.user_id)

    for stale in ("new", "profile_selected", "downloads_informed"):
        again = await put(account_client, x, state=stale, onboarding_version=1)
        assert again == reached, stale
    assert await put(account_client, x, onboarding_version=1) == reached  # no state at all
    assert await admin.fetchrow(STORED, x.user_id) == stored  # not even updated_at moved

    done = await put(account_client, x, state="ready", onboarding_version=1)
    for stale in ("new", "profile_selected", "downloads_informed", "ready"):
        assert await put(account_client, x, state=stale, onboarding_version=1) == done
    assert done["completed_at"] is not None


async def test_tour_fields_merge_monotonically(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner]
) -> None:
    x = learners["x"]
    first = await put(account_client, x, onboarding_version=1, tour_version_seen=3)
    assert (first["state"], first["tour_version_seen"], first["tour_dismissed"]) == (
        "new",
        3,
        False,
    )

    lower = await put(account_client, x, onboarding_version=1, tour_version_seen=1)
    assert lower["tour_version_seen"] == 3  # an older device cannot lower it

    dismissed = await put(account_client, x, onboarding_version=1, tour_dismissed=True)
    assert dismissed["tour_dismissed"] is True and dismissed["tour_version_seen"] == 3

    # A device that has not heard about the dismissal cannot undo it.
    late = await put(
        account_client, x, onboarding_version=1, tour_version_seen=4, tour_dismissed=False
    )
    assert late["tour_dismissed"] is True and late["tour_version_seen"] == 4


async def test_an_app_upgrade_never_sends_a_ready_learner_back(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner]
) -> None:
    """The version rule: a higher onboarding_version raises the stored version
    and nothing else. Older apps reporting a lower version change nothing."""
    x = learners["x"]
    done = await put(account_client, x, state="ready", onboarding_version=1)

    upgraded = await put(account_client, x, state="new", onboarding_version=2)
    assert upgraded["state"] == "ready"
    assert upgraded["onboarding_version"] == 2
    assert upgraded["completed_at"] == done["completed_at"]

    old_device = await put(account_client, x, state="profile_selected", onboarding_version=1)
    assert (old_device["state"], old_device["onboarding_version"]) == ("ready", 2)


async def test_parallel_replays_from_several_devices_converge(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    x = learners["x"]
    bodies = [
        {"state": state, "onboarding_version": version, "tour_version_seen": tour}
        for state in ("new", "profile_selected", "downloads_informed", "ready")
        for version, tour in ((1, 0), (2, 5), (3, 2))
    ]
    responses = await asyncio.gather(
        *(account_client.put(URL, json=body, headers=x.headers) for body in bodies)
    )
    assert {response.status_code for response in responses} == {200}
    final = await get(account_client, x)
    assert (final["state"], final["onboarding_version"], final["tour_version_seen"]) == (
        "ready",
        3,
        5,
    )
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM account.onboarding_state WHERE user_id = $1", x.user_id
        )
        == 1
    )


# ----------------------------------------------------- returning learners
async def test_a_learner_who_already_has_a_grade_is_past_profile_selection(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner]
) -> None:
    x = learners["x"]
    await account_client.patch("/v1/me", json={"grade_code": "9AF"}, headers=x.headers)
    assert (await get(account_client, x))["state"] == "profile_selected"
    merged = await put(account_client, x, state="new", onboarding_version=1)
    assert merged["state"] == "profile_selected"


async def test_a_learner_with_accepted_work_is_never_forced_through_onboarding(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    """Someone who used the app before this flow existed has learning data and
    no onboarding row. They are `ready`, and nothing they send can undo that."""
    x, y = learners["x"], learners["y"]
    question_id, correct = SEED_QUESTIONS_FR[0]
    push = await account_client.post(
        "/v1/sync/push",
        json={"ops": [answer_op(question_id, correct), completed_op(SEED_REV_FR)]},
        headers=x.headers,
    )
    assert push.status_code == 200
    assert [result["status"] for result in push.json()["results"]] == ["accepted", "accepted"]

    assert (await get(account_client, x))["state"] == "ready"
    assert await admin.fetchrow(STORED, x.user_id) is None
    first = await put(account_client, x, state="new", onboarding_version=1)
    assert first["state"] == "ready" and first["completed_at"] is not None
    assert (await get(account_client, y))["state"] == "new"  # Y is unaffected


async def test_onboarding_never_touches_learning_data(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    x = learners["x"]
    question_id, correct = SEED_QUESTIONS_FR[1]
    await account_client.post(
        "/v1/sync/push",
        json={"ops": [answer_op(question_id, correct), completed_op(SEED_REV_FR)]},
        headers=x.headers,
    )
    snapshot_sql = (
        "SELECT (SELECT count(*) FROM app.practice_attempts WHERE learner_id = $1), "
        "(SELECT count(*) FROM app.lesson_progress WHERE learner_id = $1), "
        "(SELECT count(*) FROM app.sync_receipts WHERE learner_id = $1), "
        "(SELECT count(*) FROM app.account_change_feed WHERE learner_id = $1), "
        "(SELECT current_version FROM app.account_sync_state WHERE learner_id = $1), "
        "(SELECT updated_at FROM app.learner_profiles WHERE user_id = $1)"
    )
    before = await admin.fetchrow(snapshot_sql, x.user_id)
    assert tuple(before)[:5] == (1, 1, 2, 2, 2)
    for state in ("new", "profile_selected", "downloads_informed", "ready", "new"):
        await put(account_client, x, state=state, onboarding_version=1, tour_dismissed=True)
    await get(account_client, x)
    assert await admin.fetchrow(snapshot_sql, x.user_id) == before
    pull = await account_client.get("/v1/sync/pull", headers=x.headers)
    assert len(pull.json()["changes"]) == 2


# ---------------------------------------------------------------- isolation
async def test_account_switch_isolation(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    x, y = learners["x"], learners["y"]
    await put(account_client, x, state="ready", onboarding_version=4, tour_dismissed=True)
    # Same client object, next request is another account: nothing carries over.
    assert await get(account_client, y) == {
        "state": "new",
        "onboarding_version": 0,
        "tour_version_seen": 0,
        "tour_dismissed": False,
        "completed_at": None,
        "updated_at": None,
    }
    y_state = await put(account_client, y, state="profile_selected", onboarding_version=1)
    assert (y_state["state"], y_state["onboarding_version"]) == ("profile_selected", 1)
    x_state = await get(account_client, x)
    assert (x_state["state"], x_state["onboarding_version"]) == ("ready", 4)

    # Naming another user in the request is rejected outright (unknown field)...
    forged = await account_client.put(
        URL,
        json={"state": "ready", "onboarding_version": 9, "user_id": str(x.user_id)},
        headers=y.headers,
    )
    assert forged.status_code == 422
    # ...and in the query string or a header it is simply not an input.
    ignored = await account_client.put(
        URL,
        params={"user_id": str(x.user_id)},
        json={"onboarding_version": 1, "tour_version_seen": 7},
        headers={**y.headers, "X-User-Id": str(x.user_id)},
    )
    assert ignored.status_code == 200
    rows = {
        row["user_id"]: (row["state"], row["onboarding_version"], row["tour_version_seen"])
        for row in await admin.fetch(
            "SELECT * FROM account.onboarding_state WHERE user_id = ANY($1::uuid[])",
            [x.user_id, y.user_id],
        )
    }
    assert rows == {x.user_id: ("ready", 4, 0), y.user_id: ("profile_selected", 1, 7)}


# --------------------------------------------------------------- validation
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"state": "ready"},
        {"state": "done", "onboarding_version": 1},
        {"state": "ready", "onboarding_version": 0},
        {"state": "ready", "onboarding_version": 10001},
        {"onboarding_version": 1, "tour_version_seen": -1},
        {"onboarding_version": 1, "tour_dismissed": "yes please"},
        {"onboarding_version": 1, "reset": True},
        {"onboarding_version": 1, "consent": True},
        {"onboarding_version": 1, "guardian_consent": "granted"},
        {"onboarding_version": 1, "birth_date": "2012-01-01"},
        {"onboarding_version": 1, "completed_at": "2020-01-01T00:00:00Z"},
        ["ready"],
    ],
)
async def test_invalid_updates_are_422_and_store_nothing(
    account_client: httpx.AsyncClient,
    learners: dict[str, SyntheticLearner],
    admin: asyncpg.Pool,
    body: object,
) -> None:
    x = learners["x"]
    response = await account_client.put(URL, json=body, headers=x.headers)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    assert await admin.fetchrow(STORED, x.user_id) is None


async def test_nothing_in_onboarding_looks_like_a_consent_answer(
    account_client: httpx.AsyncClient, learners: dict[str, SyntheticLearner], admin: asyncpg.Pool
) -> None:
    """PO-04 is undecided: no consent is collected, stored, inferred or exposed."""
    done = await put(
        account_client, learners["x"], state="ready", onboarding_version=1, tour_dismissed=True
    )
    for key in done:
        assert not any(word in key for word in ("consent", "agree", "accept", "age", "birth"))
    columns = await admin.fetch(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'account'"
    )
    assert columns
    for column in columns:
        name = f"{column['table_name']}.{column['column_name']}"
        assert not any(
            word in name for word in ("consent", "agree", "guardian", "parent", "birth", "age_")
        ), name


async def test_onboarding_requires_a_token(account_client: httpx.AsyncClient) -> None:
    for response in (
        await account_client.get(URL),
        await account_client.put(URL, json={"state": "ready", "onboarding_version": 1}),
    ):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"
