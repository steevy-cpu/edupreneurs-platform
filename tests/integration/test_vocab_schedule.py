"""Word of the Day: the schedule under concurrency, and who can reach schema ``vocab``.

The single-connection rules (order, idempotence, immutability of opened days)
are in supabase/tests/162_vocab_schedule.sql. Here: several connections at
once, the API's real database login, and the Supabase Data API.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

import asyncpg
import httpx
import pytest

from tests import vocab_fixtures
from tests.helpers import EDITOR
from tests.vocab_fixtures import approved_word, assign, haiti_today, schedule_rows

clean_vocab = vocab_fixtures.clean_vocab

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_vocab")]

DAYS = 30
WORKERS = 8


async def _fill(dsn: str, start: date, days: int, barrier: asyncio.Event) -> int:
    """One independent connection running the fill; returns the rows IT created."""
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        await barrier.wait()
        rows = await conn.fetch("SELECT * FROM vocab.ensure_assignments($1, $2)", start, days)
        return len(rows)
    finally:
        await conn.close()


async def test_concurrent_daily_publication_yields_one_schedule(
    admin: asyncpg.Pool, local_env: dict[str, str]
) -> None:
    for index in range(5):
        # Words 0, 2, 4 have a Creole translation; 1 and 3 are French only.
        await approved_word(
            admin, term=f"MOT{index}", locales=("fr", "ht") if index % 2 == 0 else ("fr",)
        )
    start = await haiti_today(admin)  # today is empty, so it is part of the fill

    # Reference: ONE serial run on an empty schedule.
    serial_created = len(
        await admin.fetch("SELECT * FROM vocab.ensure_assignments($1, $2)", start, DAYS)
    )
    reference = await schedule_rows(admin)
    assert len(reference) == serial_created
    assert {day for day, _, _ in reference} == {start + timedelta(days=n) for n in range(DAYS)}
    await vocab_fixtures.truncate_vocab(admin, "vocab.daily_assignments")

    # Same starting point, eight connections released at the same instant.
    barrier = asyncio.Event()
    tasks = [
        asyncio.create_task(_fill(local_env["LOCAL_ADMIN_DATABASE_URL"], start, DAYS, barrier))
        for _ in range(WORKERS)
    ]
    await asyncio.sleep(0.2)  # let every connection reach the barrier
    barrier.set()
    created = await asyncio.gather(*tasks)

    assert sum(created) == serial_created, created
    assert sorted(created)[:-1] == [0] * (WORKERS - 1), "exactly one run did the work"
    assert await schedule_rows(admin) == reference, "concurrent runs gave the serial schedule"
    per_day = await admin.fetch(
        "SELECT haiti_date, count(*) FILTER (WHERE locale = 'fr') AS fr, "
        "count(DISTINCT word_id) AS words FROM vocab.daily_assignments GROUP BY haiti_date"
    )
    assert all(row["fr"] == 1 and row["words"] == 1 for row in per_day)

    # Idempotent afterwards, from any connection, with overlapping windows.
    again = await asyncio.gather(
        *(
            _fill(local_env["LOCAL_ADMIN_DATABASE_URL"], start - timedelta(days=5), 20, barrier)
            for _ in range(3)
        )
    )
    assert again == [0, 0, 0]
    assert await schedule_rows(admin) == reference


async def test_fill_racing_with_a_staff_choice_never_gives_a_day_two_words(
    admin: asyncpg.Pool, local_env: dict[str, str]
) -> None:
    words = [await approved_word(admin, term=f"COURSE{index}") for index in range(3)]
    today = await haiti_today(admin)
    target = today + timedelta(days=3)

    async def choose(word_id: uuid.UUID) -> None:
        conn = await asyncpg.connect(local_env["LOCAL_ADMIN_DATABASE_URL"], timeout=10)
        try:
            async with conn.transaction():
                await conn.execute("SELECT vocab._lock_schedule()")
                await conn.execute(
                    "DELETE FROM vocab.daily_assignments WHERE haiti_date = $1", target
                )
                await conn.execute("SELECT vocab._assign_word($1, $2, 'auto')", target, word_id)
        finally:
            await conn.close()

    barrier = asyncio.Event()
    barrier.set()
    results = await asyncio.gather(
        _fill(local_env["LOCAL_ADMIN_DATABASE_URL"], today + timedelta(days=1), 7, barrier),
        choose(words[2]["word_id"]),
        _fill(local_env["LOCAL_ADMIN_DATABASE_URL"], today + timedelta(days=1), 7, barrier),
        choose(words[1]["word_id"]),
        return_exceptions=True,
    )
    assert not [r for r in results if isinstance(r, Exception)], results
    rows = await admin.fetch(
        "SELECT haiti_date, count(DISTINCT word_id) AS words, "
        "array_agg(locale ORDER BY locale) AS locales "
        "FROM vocab.daily_assignments GROUP BY haiti_date ORDER BY haiti_date"
    )
    assert [row["haiti_date"] for row in rows] == [today + timedelta(days=n) for n in range(1, 8)]
    assert all(row["words"] == 1 and row["locales"] == ["fr", "ht"] for row in rows)


async def test_opened_day_survives_everything_a_writer_can_try(admin: asyncpg.Pool) -> None:
    first = await approved_word(admin, term="OUVERT")
    other = await approved_word(admin, term="AUTRE")
    today = await assign(admin, first["word_id"])
    before = await schedule_rows(admin)

    attempts = (
        ("UPDATE vocab.daily_assignments SET word_id = $2, word_revision_id = $3 "
         "WHERE haiti_date = $1 AND locale = 'fr'", (today, other["word_id"], other["revisions"]["fr"])),
        ("DELETE FROM vocab.daily_assignments WHERE haiti_date = $1", (today,)),
        ("SELECT vocab._assign_word($1::date - 1, $2, 'auto')", (today, other["word_id"])),
    )  # fmt: skip
    for statement, arguments in attempts:
        with pytest.raises(asyncpg.RaiseError):
            await admin.execute(statement, *arguments)
    assert await admin.fetch("SELECT * FROM vocab.ensure_assignments($1, 1)", today) == []
    assert await schedule_rows(admin) == before


async def test_translation_approved_later_cannot_be_added_to_an_opened_day(
    admin: asyncpg.Pool,
) -> None:
    word = await approved_word(admin, term="MATIN", locales=("fr",))
    today = await assign(admin, word["word_id"])
    creole = await vocab_fixtures.create_revision(
        admin, word["word_id"], "ht", word["source_id"], term="MATEN"
    )
    before = await schedule_rows(admin)
    with pytest.raises(asyncpg.RaiseError, match="translation cannot be added"):
        await admin.execute(
            "INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, "
            "assigned_via) VALUES ($1, 'ht', $2, $3, 'auto')",
            today,
            word["word_id"],
            creole,
        )
    with pytest.raises(asyncpg.RaiseError, match="translation cannot be added"):
        await admin.execute("SELECT vocab._assign_word($1, $2, 'auto')", today, word["word_id"])
    assert await admin.fetch("SELECT * FROM vocab.ensure_assignments($1, 1)", today) == []
    assert await schedule_rows(admin) == before


async def test_worker_login_can_run_the_fill_and_nothing_else(
    admin: asyncpg.Pool, local_env: dict[str, str]
) -> None:
    from tests.staff_fixtures import staff_url, worker_url

    await approved_word(admin, term="OUVRIER")
    today = await haiti_today(admin)
    worker = await asyncpg.connect(worker_url(local_env), timeout=10)
    try:
        assert await worker.fetchval("SELECT session_user::text") == "edu_worker_login"
        # The guards' test clock (review F3) is the owner login's only: pinned a
        # year ahead here, it would make the fill below fail ("A past day ...").
        await worker.execute(
            "SELECT set_config('vocab.test_clock', (now() + interval '1 year')::text, false)"
        )
        created = await worker.fetch("SELECT * FROM vocab.ensure_assignments($1, 3)", today)
        assert len(created) == 6
        for statement in (
            "SELECT count(*) FROM vocab.daily_assignments",
            "SELECT * FROM vocab.daily_word('fr')",
            "SELECT * FROM vocab.daily_word_at('fr', now())",
            "SELECT vocab._clock()",
            "SELECT vocab.create_word('from-the-worker')",
            "SELECT vocab.schedule_word(current_date + 5, gen_random_uuid())",
            "SELECT * FROM vocab.staff_ensure_assignments(current_date, 3)",
            "SELECT vocab._assign_word(current_date + 5, gen_random_uuid(), 'auto')",
            "DELETE FROM vocab.daily_assignments",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await worker.execute(statement)
    finally:
        await worker.close()
    # The staff login without a verified staff actor: every function refuses.
    staff = await asyncpg.connect(staff_url(local_env), timeout=10)
    try:
        for statement in (
            "SELECT vocab.create_word('no-actor')",
            "SELECT * FROM vocab.review_queue()",
            "SELECT * FROM vocab.staff_ensure_assignments(current_date, 3)",
            "SELECT * FROM vocab.ensure_assignments(current_date, 3)",
            "SELECT * FROM vocab.daily_word('fr')",
            "SELECT count(*) FROM vocab.words",
            "SELECT vocab._audit('vocab.forged.event', NULL, NULL)",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await staff.execute(statement)
    finally:
        await staff.close()


# ------------------------------------------------- the API's real database login
async def test_api_database_login_reaches_one_function_only(
    admin: asyncpg.Pool, local_env: dict[str, str]
) -> None:
    """Not SET ROLE: the actual ``edu_api_login`` credentials the API uses."""
    word = await approved_word(admin, term="LOGIN")
    await assign(admin, word["word_id"])
    dsn = local_env["EDU_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        assert await conn.fetchval("SELECT session_user::text") == "edu_api_login"
        denied = (
            "SELECT count(*) FROM vocab.words",
            "SELECT count(*) FROM vocab.word_revisions",
            "SELECT count(*) FROM vocab.daily_assignments",
            "SELECT count(*) FROM vocab.audio_assets",
            "SELECT count(*) FROM vocab.reviews",
            "SELECT count(*) FROM vocab.sources",
            "SELECT * FROM vocab.daily_word_at('fr', now() + interval '1 day')",
            "SELECT * FROM vocab.ensure_assignments(current_date, 3)",
            "SELECT vocab.create_word('from-the-api-role')",
            "SELECT vocab.submit_revision(gen_random_uuid())",
            "SELECT vocab.review_revision(gen_random_uuid(), 'approved')",
            "SELECT vocab.schedule_word(current_date + 2, gen_random_uuid())",
            "SELECT vocab.retire_word(gen_random_uuid())",
            "SELECT vocab.set_source_rights(gen_random_uuid(), 'cleared')",
            "SELECT * FROM vocab.review_queue()",
            "SELECT * FROM vocab.calendar(current_date, 7)",
            "SELECT vocab._assign_word(current_date + 2, gen_random_uuid(), 'auto')",
            "SELECT vocab._audit('forged.event', 'x', NULL)",
            "SELECT vocab.erase_learner(gen_random_uuid())",
            "DELETE FROM vocab.daily_assignments",
            "TRUNCATE vocab.daily_assignments",
            "CREATE TABLE vocab.sneaky (id int)",
        )
        for statement in denied:
            # Even with a STAFF actor placed in the transaction, as the API would.
            async with conn.transaction():
                await conn.execute("SELECT set_config('edu.actor_id', $1, true)", str(EDITOR))
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await conn.execute(statement)
        async with conn.transaction():
            await conn.execute("SELECT set_config('edu.actor_id', $1, true)", str(EDITOR))
            row = await conn.fetchrow("SELECT * FROM vocab.daily_word('fr')")
        assert row is not None and row["term"] == "LOGIN-fr"
        with pytest.raises(asyncpg.InsufficientPrivilegeError):  # no actor in the transaction
            await conn.fetchrow("SELECT * FROM vocab.daily_word('fr')")
    finally:
        await conn.close()


# -------------------------------- the private schema is not in the Data API
async def test_vocab_schema_is_not_reachable_through_the_supabase_data_api(
    admin: asyncpg.Pool, local_env: dict[str, str], tokens: dict[str, str]
) -> None:
    word = await approved_word(admin, term="PRIVE")
    await assign(admin, word["word_id"])
    rest = local_env["LOCAL_SUPABASE_URL"] + "/rest/v1"
    credentials = {
        "publishable key only": {"apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"]},
        "signed-in student": {
            "apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"],
            "Authorization": f"Bearer {tokens['student_a']}",
        },
        "signed-in staff account": {
            "apikey": local_env["LOCAL_SUPABASE_PUBLISHABLE_KEY"],
            "Authorization": f"Bearer {tokens['editor']}",
        },
        "SECRET service key": {"apikey": local_env["LOCAL_SUPABASE_SECRET_KEY"]},
    }
    async with httpx.AsyncClient(timeout=10) as http:
        for label, headers in credentials.items():
            for table in (
                "words",
                "word_revisions",
                "daily_assignments",
                "reviews",
                "audio_assets",
                "sources",
            ):
                for profile in ({"Accept-Profile": "vocab"}, {}):
                    response = await http.get(
                        f"{rest}/{table}", params={"select": "*"}, headers={**headers, **profile}
                    )
                    assert response.status_code >= 400, (label, table, profile, response.text[:200])
                    assert "PRIVE" not in response.text
            for function, arguments in (
                ("daily_word", {"p_locale": "fr"}),
                ("daily_word_at", {"p_locale": "fr", "p_now": "2030-01-01T00:00:00Z"}),
                ("ensure_assignments", {"p_from": "2030-01-01", "p_days": 3}),
                ("create_word", {"p_slug": "from-the-data-api"}),
                ("erase_learner", {"p_user_id": str(uuid.uuid4())}),
            ):
                for profile in ({"Content-Profile": "vocab"}, {}):
                    rpc = await http.post(
                        f"{rest}/rpc/{function}", headers={**headers, **profile}, json=arguments
                    )
                    assert rpc.status_code >= 400, (label, function, profile, rpc.text[:200])
                    assert "PRIVE" not in rpc.text
        exposed = (await http.get(f"{rest}/", headers=credentials["SECRET service key"])).text
    for name in ("daily_assignments", "word_revisions", "daily_word", "ensure_assignments"):
        assert name not in exposed
    assert (
        await admin.fetchval("SELECT count(*) FROM vocab.words WHERE slug = 'from-the-data-api'")
        == 0
    )


# ------------------------------------- review findings F1 / F3 (two sessions, real COMMIT)
_CHANGE = (
    "UPDATE vocab.daily_assignments SET word_id = $2, word_revision_id = $3 "
    "WHERE haiti_date = $1 AND locale = 'fr'"
)
_PIN = "SELECT set_config('vocab.test_clock', $1::timestamptz::text, false)"
_READ = "SELECT term FROM vocab.daily_word_at('fr', $1)"


async def test_plain_commit_after_midnight_is_refused(
    admin: asyncpg.Pool, local_env: dict[str, str]
) -> None:
    """A change accepted at 23:30 whose transaction COMMITs after the day opened
    is refused by the commit-time check; the day keeps its word. The owner-only
    clock seam moves the guards' clock of the writing session."""
    old = await approved_word(admin, term="ANCIEN", locales=("fr",))
    new = await approved_word(admin, term="NOUVEAU", locales=("fr",))
    day = await haiti_today(admin) + timedelta(days=4)
    await assign(admin, old["word_id"], day)
    opens = await admin.fetchval("SELECT vocab.haiti_day_start($1)", day)

    writer = await asyncpg.connect(local_env["LOCAL_ADMIN_DATABASE_URL"], timeout=10)
    try:
        await writer.execute(_PIN, opens - timedelta(minutes=30))
        transaction = writer.transaction()
        await transaction.start()
        await writer.execute(_CHANGE, day, new["word_id"], new["revisions"]["fr"])
        await writer.execute(_PIN, opens + timedelta(seconds=1))
        with pytest.raises(asyncpg.RaiseError, match="The day opened before this schedule change"):
            await transaction.commit()
    finally:
        await writer.close()
    assert await admin.fetchval(_READ, opens + timedelta(seconds=1)) == "ANCIEN-fr"


async def test_change_held_open_across_midnight_is_never_seen_as_a_changed_word(
    admin: asyncpg.Pool, local_env: dict[str, str]
) -> None:
    """Review F1. A session changes a FUTURE day at 23:30, fires the commit-time
    check early (SET CONSTRAINTS ALL IMMEDIATE), keeps its transaction open until
    the day has opened and commits. The commit goes through, but no reader of the
    opened day can have received the old word first: while that transaction is
    open the day serves nothing (the day's advisory lock)."""
    old = await approved_word(admin, term="ANCIEN", locales=("fr",))
    new = await approved_word(admin, term="NOUVEAU", locales=("fr",))
    day = await haiti_today(admin) + timedelta(days=4)
    await assign(admin, old["word_id"], day)
    eve = await approved_word(admin, term="VEILLE", locales=("fr",))
    await assign(admin, eve["word_id"], day - timedelta(days=1))
    opens = await admin.fetchval("SELECT vocab.haiti_day_start($1)", day)
    opened = opens + timedelta(seconds=1)

    writer = await asyncpg.connect(local_env["LOCAL_ADMIN_DATABASE_URL"], timeout=10)
    try:
        await writer.execute(_PIN, opens - timedelta(minutes=30))
        transaction = writer.transaction()
        await transaction.start()
        await writer.execute(_CHANGE, day, new["word_id"], new["revisions"]["fr"])
        await writer.execute("SET CONSTRAINTS ALL IMMEDIATE")
        # ... the day opens while the transaction is still open ...
        await writer.execute(_PIN, opened)
        assert await admin.fetchval(_READ, opened) is None, "nothing is served meanwhile"
        # Only that day is held: the day before is served as usual.
        assert await admin.fetchval(_READ, opened - timedelta(days=1)) == "VEILLE-fr"
        await transaction.commit()
    finally:
        await writer.close()
    assert await admin.fetchval(_READ, opened) == "NOUVEAU-fr"


async def test_refused_attempt_on_an_opened_day_does_not_hide_its_word(
    admin: asyncpg.Pool, local_env: dict[str, str]
) -> None:
    """The day's lock is taken only by an ACCEPTED change: a session that tries to
    change today (refused) and stays open does not make today answer "no word"."""
    word = await approved_word(admin, term="STABLE", locales=("fr",))
    today = await assign(admin, word["word_id"])
    now = await admin.fetchval("SELECT clock_timestamp()")
    writer = await asyncpg.connect(local_env["LOCAL_ADMIN_DATABASE_URL"], timeout=10)
    try:
        transaction = writer.transaction()
        await transaction.start()
        await writer.execute("SAVEPOINT attempt")
        with pytest.raises(asyncpg.RaiseError, match="already opened"):
            await writer.execute("DELETE FROM vocab.daily_assignments WHERE haiti_date = $1", today)
        await writer.execute("ROLLBACK TO SAVEPOINT attempt")
        assert await admin.fetchval(_READ, now) == "STABLE-fr"
        await transaction.rollback()
    finally:
        await writer.close()


async def test_truncate_is_refused_even_for_the_owner(admin: asyncpg.Pool) -> None:
    for table in ("daily_assignments", "word_revisions", "reviews"):
        with pytest.raises(asyncpg.RaiseError, match="cannot be truncated"):
            await admin.execute(f"TRUNCATE vocab.{table} CASCADE")
