"""Adversarial effective-privilege cases for the migration auditor (`edu_staging_auditor`).

Each case builds the auditor inside a rolled-back transaction on the disposable database, first PROVES that the
privilege is effective according to PostgreSQL itself (`has_*_privilege` includes PUBLIC and inherited roles), and then
requires `check_session` to reject the login. A version-only control proves the legitimate auditor is still admitted.

PostgreSQL facts these cases rely on (verified on 17.12, see docs/infra/staging-00/environment.md):
* a fresh role holds CREATE in no namespace (pg_catalog, information_schema, pg_toast, temp schemas and public included),
  so the policy needs no system-schema exception;
* PUBLIC cannot receive a grant option, so "PUBLIC WITH GRANT OPTION" cannot exist;
* a base privilege granted to PUBLIC IS effective for every role, and grant options are inherited through membership.
"""

import asyncpg
import pytest

from staging_verify import check_session, versions

LEDGER = "supabase_migrations.schema_migrations"
AUDITOR = "edu_staging_auditor"


def on_database(grant_to: str) -> str:
    """CONNECT WITH GRANT OPTION on whichever disposable database this runs in."""
    return (
        "DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO "
        + grant_to
        + " WITH GRANT OPTION', current_database()); END $$"
    )


async def build_auditor(db: asyncpg.Connection, extra: tuple[str, ...] = ()) -> None:
    await db.execute(f"CREATE ROLE {AUDITOR} LOGIN")
    await db.execute(f"GRANT USAGE ON SCHEMA supabase_migrations TO {AUDITOR}")
    await db.execute(f"GRANT SELECT(version) ON {LEDGER} TO {AUDITOR}")
    for statement in extra:
        await db.execute(statement)
    # PG17 gives a CREATEROLE creator ADMIN, but not necessarily SET membership. Only the test operator
    # assumes the narrow role, inside this rolled-back fixture.
    await db.execute(f"GRANT {AUDITOR} TO CURRENT_USER WITH SET TRUE")
    await db.execute(f"SET LOCAL ROLE {AUDITOR}")


async def audit(db: asyncpg.Connection) -> None:
    await check_session(db, AUDITOR, versions(), plan=True)


async def test_version_only_auditor_is_still_admitted(admin: asyncpg.Pool) -> None:
    async with admin.acquire() as db:
        tx = db.transaction()
        await tx.start()
        try:
            await build_auditor(db)
            await audit(db)  # the legitimate metadata-only login: CONNECT, USAGE, SELECT(version)
            assert await db.fetchval(
                f"SELECT has_column_privilege(current_user, '{LEDGER}', 'version', 'SELECT')"
            )
            assert not await db.fetchval(
                "SELECT has_database_privilege(current_user, current_database(), 'CONNECT WITH GRANT OPTION')"
            )
            assert not await db.fetchval(
                "SELECT has_schema_privilege(current_user, 'supabase_migrations', 'USAGE WITH GRANT OPTION')"
            )
        finally:
            await tx.rollback()


# (id, statements run as the operator before assuming the auditor, probe that must be TRUE for the auditor)
CASES = [
    (
        "create-migration-schema-direct",
        ("GRANT CREATE ON SCHEMA supabase_migrations TO edu_staging_auditor",),
        "has_schema_privilege(current_user, 'supabase_migrations', 'CREATE')",
    ),
    (
        "create-other-schema-direct",
        ("CREATE SCHEMA audit_other", "GRANT CREATE ON SCHEMA audit_other TO edu_staging_auditor"),
        "has_schema_privilege(current_user, 'audit_other', 'CREATE')",
    ),
    (
        "create-other-schema-public",
        ("CREATE SCHEMA audit_other", "GRANT CREATE ON SCHEMA audit_other TO PUBLIC"),
        "has_schema_privilege(current_user, 'audit_other', 'CREATE')",
    ),
    (
        "create-public-schema-public",
        ("GRANT CREATE ON SCHEMA public TO PUBLIC",),
        "has_schema_privilege(current_user, 'public', 'CREATE')",
    ),
    (
        "create-via-schema-ownership",
        # Creating a schema for another role needs SET membership first (the CI operator is not a superuser).
        (
            "GRANT edu_staging_auditor TO CURRENT_USER WITH SET TRUE",
            "CREATE SCHEMA audit_other AUTHORIZATION edu_staging_auditor",
        ),
        "has_schema_privilege(current_user, 'audit_other', 'CREATE')",
    ),
    (
        "create-other-schema-inherited",
        (
            "CREATE ROLE audit_parent",
            "CREATE SCHEMA audit_other",
            "GRANT CREATE ON SCHEMA audit_other TO audit_parent",
            "GRANT audit_parent TO edu_staging_auditor",
        ),
        "has_schema_privilege(current_user, 'audit_other', 'CREATE')",
    ),
    (
        "connect-with-grant-option-direct",
        (on_database("edu_staging_auditor"),),
        "has_database_privilege(current_user, current_database(), 'CONNECT WITH GRANT OPTION')",
    ),
    (
        "connect-with-grant-option-inherited",
        (
            "CREATE ROLE audit_parent",
            on_database("audit_parent"),
            "GRANT audit_parent TO edu_staging_auditor",
        ),
        "has_database_privilege(current_user, current_database(), 'CONNECT WITH GRANT OPTION')",
    ),
    (
        "migration-usage-with-grant-option-direct",
        ("GRANT USAGE ON SCHEMA supabase_migrations TO edu_staging_auditor WITH GRANT OPTION",),
        "has_schema_privilege(current_user, 'supabase_migrations', 'USAGE WITH GRANT OPTION')",
    ),
    (
        "migration-usage-with-grant-option-inherited",
        (
            "CREATE ROLE audit_parent",
            "GRANT USAGE ON SCHEMA supabase_migrations TO audit_parent WITH GRANT OPTION",
            "GRANT audit_parent TO edu_staging_auditor",
        ),
        "has_schema_privilege(current_user, 'supabase_migrations', 'USAGE WITH GRANT OPTION')",
    ),
    (
        "usage-with-grant-option-other-schema",
        (
            "CREATE SCHEMA audit_other",
            "GRANT USAGE ON SCHEMA audit_other TO edu_staging_auditor WITH GRANT OPTION",
        ),
        "has_schema_privilege(current_user, 'audit_other', 'USAGE WITH GRANT OPTION')",
    ),
]


@pytest.mark.parametrize(("case", "setup", "probe"), CASES, ids=[c[0] for c in CASES])
async def test_overprivileged_auditor_is_rejected(
    admin: asyncpg.Pool, case: str, setup: tuple[str, ...], probe: str
) -> None:
    async with admin.acquire() as db:
        tx = db.transaction()
        await tx.start()
        try:
            await build_auditor(db, setup)
            assert await db.fetchval(f"SELECT {probe}"), (
                f"{case}: the privilege must be effective for the auditor"
            )
            with pytest.raises(ValueError, match="audit login privileges"):
                await audit(db)
        finally:
            await tx.rollback()


async def test_public_can_never_hold_a_grant_option(admin: asyncpg.Pool) -> None:
    """PostgreSQL itself forbids it, so no PUBLIC grant-option case exists for the policy to miss."""
    async with admin.acquire() as db:
        tx = db.transaction()
        await tx.start()
        try:
            with pytest.raises(
                asyncpg.PostgresError, match="grant options can only be granted to roles"
            ):
                await db.execute(
                    "GRANT USAGE ON SCHEMA supabase_migrations TO PUBLIC WITH GRANT OPTION"
                )
        finally:
            await tx.rollback()


async def test_policy_has_no_system_schema_exception(admin: asyncpg.Pool) -> None:
    """A fresh version-only auditor holds CREATE in no namespace at all, so the policy may reject any CREATE."""
    async with admin.acquire() as db:
        tx = db.transaction()
        await tx.start()
        try:
            await build_auditor(db)
            holders = await db.fetch(
                "SELECT nspname FROM pg_namespace n WHERE has_schema_privilege(current_user, n.oid, 'CREATE')"
            )
            assert holders == [], [r["nspname"] for r in holders]
        finally:
            await tx.rollback()
