"""Put a few DEMO words of the day into the LOCAL disposable database.

    uv run python scripts/seed_vocab_demo.py            # words + 14 days of schedule
    uv run python scripts/seed_vocab_demo.py --days 30

Then run the API with ``EDU_DAILY_WORD_ENABLED=true`` and call
``GET /v1/daily-word?locale=fr`` (or ``ht``).

WHAT THIS CONTENT IS
    Synthetic demonstration text written for local testing. It has NOT been
    reviewed by an educator or a native Haitian Creole speaker and must never be
    shown to real learners. Every word is created under a source record whose
    title and licence say so. Two words deliberately have no Creole revision, to
    demonstrate the French fallback.

HOW IT IS CREATED
    Through the real workflow functions, with the two synthetic seed staff
    accounts: the seed editor writes and submits, the seed reviewer approves
    (reviewer != author is enforced by the database). No recording is attached.
    Two things are arranged directly by the local database owner, because the
    seed data has no ``publisher``: the demo source's rights are marked
    ``cleared`` and ``vocab.ensure_assignments`` is called directly.

SAFETY
    Refuses to run against anything that is not on this machine. Idempotent:
    existing demo words are left alone and only unassigned days are filled.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any
from urllib.parse import urlsplit

import asyncpg

from local_stack import LOCAL_HOSTS, read_env_file

SEED_EDITOR = "a0000000-0000-4000-8000-000000000003"
SEED_REVIEWER = "a0000000-0000-4000-8000-000000000004"

DEMO_SOURCE_TITLE = "DEMO - synthetic words for local testing (NOT reviewed by an educator)"
DEMO_LICENCE = "synthetic-demo-unreviewed"

#: slug, part of speech, then per locale: term, pronunciation, definition, example, gloss.
DEMO_WORDS: list[dict[str, Any]] = [
    {
        "slug": "demo-courage",
        "part_of_speech": "noun",
        "fr": (
            "courage",
            "cou-rage",
            "Force intérieure qui aide à faire face à une difficulté ou à la peur.",
            "Il faut du courage pour poser une question devant toute la classe.",
            "kouraj",
        ),
        "ht": (
            "kouraj",
            "kou-raj",
            "Fòs anndan ki ede yon moun fè fas ak yon difikilte oswa ak laperèz.",
            "Li gen kouraj pou l poze yon kesyon devan tout klas la.",
            "courage",
        ),
    },
    {
        "slug": "demo-perseverance",
        "part_of_speech": "noun",
        "fr": (
            "persévérance",
            "per-sé-vé-rance",
            "Qualité d'une personne qui continue ses efforts malgré les obstacles.",
            "Grâce à sa persévérance, elle a fini par comprendre les fractions.",
            "pèseverans",
        ),
        "ht": (
            "pèseverans",
            "pè-se-ve-rans",
            "Kalite yon moun ki kontinye fè efò malgre obstak yo.",
            "Ak pèseverans, li rive konprann fraksyon yo.",
            "persévérance",
        ),
    },
    {
        "slug": "demo-curiosite",
        "part_of_speech": "noun",
        "fr": (
            "curiosité",
            "cu-rio-si-té",
            "Envie d'apprendre, de découvrir et de comprendre des choses nouvelles.",
            "Sa curiosité la pousse à lire un peu chaque jour.",
            None,
        ),
    },
    {
        "slug": "demo-solidarite",
        "part_of_speech": "noun",
        "fr": (
            "solidarité",
            "so-li-da-ri-té",
            "Entraide entre des personnes qui se sentent responsables les unes des autres.",
            "Par solidarité, les élèves ont partagé leurs notes avec leur camarade absent.",
            "solidarite",
        ),
        "ht": (
            "solidarite",
            "so-li-da-ri-te",
            "Antrèd ant moun ki santi yo responsab youn pou lòt.",
            "Elèv yo montre solidarite lè yo pataje nòt yo ak kanmarad ki te absan an.",
            "solidarité",
        ),
    },
    {
        "slug": "demo-partager",
        "part_of_speech": "verb",
        "fr": (
            "partager",
            "par-ta-ger",
            "Diviser quelque chose pour en donner une partie à d'autres personnes.",
            "Elle partage son repas avec son petit frère.",
            "pataje",
        ),
        "ht": (
            "pataje",
            "pa-ta-je",
            "Divize yon bagay pou bay lòt moun yon pati ladan l.",
            "Li pataje manje l ak ti frè l.",
            "partager",
        ),
    },
    {
        "slug": "demo-horizon",
        "part_of_speech": "noun",
        "fr": (
            "horizon",
            "o-ri-zon",
            "Ligne où le ciel et la terre, ou la mer, semblent se rejoindre.",
            "Le soleil disparaît lentement derrière l'horizon.",
            None,
        ),
    },
    {
        "slug": "demo-recolte",
        "part_of_speech": "noun",
        "fr": (
            "récolte",
            "ré-colte",
            "Action de ramasser les produits de la terre ; ce qui a été ramassé.",
            "Toute la famille participe à la récolte du maïs.",
            "rekòt",
        ),
        "ht": (
            "rekòt",
            "re-kòt",
            "Aksyon ranmase sa tè a bay; sa yo ranmase a.",
            "Tout fanmi an patisipe nan rekòt mayi a.",
            "récolte",
        ),
    },
]


async def _act_as(conn: Any, actor: str) -> None:
    await conn.execute("SELECT set_config('edu.actor_id', $1, true)", actor)


async def _demo_source(conn: Any) -> Any:
    source_id = await conn.fetchval(
        "SELECT id FROM vocab.sources WHERE source_title = $1", DEMO_SOURCE_TITLE
    )
    if source_id is None:
        async with conn.transaction():
            await _act_as(conn, SEED_EDITOR)
            source_id = await conn.fetchval(
                "SELECT vocab.register_source($1, NULL, $2, $3)",
                DEMO_SOURCE_TITLE,
                DEMO_LICENCE,
                "Local demonstration only. A real educator must review real words.",
            )
    # Local-owner arrangement (see module docstring): no publisher exists in the seed data.
    await conn.execute(
        "UPDATE vocab.sources SET rights_status = 'cleared' "
        "WHERE id = $1 AND rights_status <> 'cleared'",
        source_id,
    )
    return source_id


async def _create_word(conn: Any, source_id: Any, word: dict[str, Any]) -> bool:
    if await conn.fetchval("SELECT 1 FROM vocab.words WHERE slug = $1", word["slug"]):
        return False
    async with conn.transaction():
        await _act_as(conn, SEED_EDITOR)
        word_id = await conn.fetchval("SELECT vocab.create_word($1)", word["slug"])
        revisions = []
        for locale in ("fr", "ht"):
            if locale not in word:
                continue
            term, pronunciation, definition, example, gloss = word[locale]
            revision_id = await conn.fetchval(
                "SELECT vocab.create_draft($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                word_id,
                locale,
                term,
                pronunciation,
                word["part_of_speech"],
                definition,
                example,
                gloss,
                source_id,
            )
            await conn.execute("SELECT vocab.submit_revision($1)", revision_id)
            revisions.append(revision_id)
        await _act_as(conn, SEED_REVIEWER)
        for revision_id in revisions:
            await conn.execute(
                "SELECT vocab.review_revision($1, 'approved', $2)",
                revision_id,
                "DEMO approval by the synthetic seed reviewer; not an educator's review.",
            )
    return True


async def seed(admin_url: str, days: int) -> None:
    conn = await asyncpg.connect(admin_url, timeout=10)
    try:
        if not await conn.fetchval("SELECT to_regnamespace('vocab') IS NOT NULL"):
            raise SystemExit("error: schema vocab does not exist. Run `make db-reset` first.")
        source_id = await _demo_source(conn)
        created = 0
        for word in DEMO_WORDS:
            created += await _create_word(conn, source_id, word)
        today = await conn.fetchval("SELECT vocab.haiti_date(clock_timestamp())")
        async with conn.transaction():
            await conn.execute("SELECT set_config('edu.actor_id', '', true)")
            filled = await conn.fetch("SELECT * FROM vocab.ensure_assignments($1, $2)", today, days)
        calendar = await conn.fetch(
            "SELECT a.haiti_date, string_agg(a.locale, '+' ORDER BY a.locale) AS locales, "
            "       min(r.term) FILTER (WHERE a.locale = 'fr') AS term "
            "FROM vocab.daily_assignments a "
            "JOIN vocab.word_revisions r ON r.id = a.word_revision_id "
            "WHERE a.haiti_date >= $1 GROUP BY a.haiti_date ORDER BY a.haiti_date LIMIT $2",
            today,
            days,
        )
    finally:
        await conn.close()
    print(
        f"demo words created: {created} (of {len(DEMO_WORDS)}); "
        f"schedule rows created: {len(filled)}"
    )
    print(f"today in Haiti: {today}")
    for row in calendar:
        print(f"  {row['haiti_date']}  {row['locales']:5}  {row['term']}")
    print("DEMO CONTENT - synthetic, unreviewed. Never show it to real learners.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=14, help="days to schedule, 1-62 (default 14)")
    args = parser.parse_args()
    if not 1 <= args.days <= 62:
        raise SystemExit("error: --days must be between 1 and 62")
    admin_url = read_env_file().get("LOCAL_ADMIN_DATABASE_URL")
    if not admin_url:
        raise SystemExit("error: .env has no LOCAL_ADMIN_DATABASE_URL. Run `make setup` first.")
    if urlsplit(admin_url).hostname not in LOCAL_HOSTS:
        raise SystemExit(
            "error: LOCAL_ADMIN_DATABASE_URL is not this machine. Refusing to continue."
        )
    asyncio.run(seed(admin_url, args.days))


if __name__ == "__main__":
    main()
