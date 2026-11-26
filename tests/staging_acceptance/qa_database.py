"""Independent QA against the verified disposable stack. ACL changes roll back."""

import re
import subprocess
from contextlib import asynccontextmanager

import pytest

import restore_drill
from disposable import verify
from edu_api.db.staging import SECURITY_SQL
from staging_verify import check_session, versions


class ControlMiss(AssertionError):
    """A single documented false green, distinguished from a setup failure."""


@asynccontextmanager
async def rollback_connection(pool):
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            yield conn
        finally:
            await tx.rollback()


@pytest.mark.xfail(
    strict=True, raises=ControlMiss, reason="QA-2: audit accepts a writable migration ledger"
)
async def test_metadata_reader_must_be_read_only(admin):
    async with rollback_connection(admin) as db:
        await db.execute("CREATE ROLE edu_staging_auditor LOGIN")
        await db.execute("GRANT USAGE ON SCHEMA supabase_migrations TO edu_staging_auditor")
        await db.execute(
            "GRANT SELECT(version), UPDATE(version) ON supabase_migrations.schema_migrations TO edu_staging_auditor"
        )
        await db.execute("GRANT edu_staging_auditor TO CURRENT_USER WITH SET TRUE")
        await db.execute("SET LOCAL ROLE edu_staging_auditor")
        assert await db.fetchval(
            "SELECT has_column_privilege(current_user, 'supabase_migrations.schema_migrations', 'version', 'UPDATE')"
        )
        try:
            await check_session(db, "edu_staging_auditor", versions())
        except ValueError:
            return
        raise ControlMiss("audit passed for the auditor with UPDATE(version); no update issued")


@pytest.mark.xfail(
    strict=True,
    raises=ControlMiss,
    reason="QA-3: policy misses a missing permission used by catalog",
)
async def test_catalog_read_grant_required_for_ready(admin):
    async with rollback_connection(admin) as db:
        await db.execute("REVOKE SELECT ON app.courses FROM edu_api")
        assert not await db.fetchval(
            "SELECT has_table_privilege('edu_api_login','app.courses','SELECT')"
        )
        row = await db.fetchrow(SECURITY_SQL)
        if all(row.values()):
            raise ControlMiss("all readiness flags true after loss of catalog SELECT")


async def test_known_effective_column_and_temp_grants_are_detected(admin):
    async with rollback_connection(admin) as db:
        await db.execute("GRANT SELECT (id) ON app.content_sources TO edu_api_login")
        row = await db.fetchrow(SECURITY_SQL)
        assert not row["private_tables"]
        await db.execute("GRANT TEMP ON DATABASE postgres TO edu_api")
        row = await db.fetchrow(SECURITY_SQL)
        assert not row["temp_revoked"]


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("version", "restored migration ledger mismatch"),
        ("name", "restored row counts or digests differ"),
    ],
)
def test_restore_rejects_corrupt_scratch_metadata(kind, expected, monkeypatch):
    project = verify(check_env=True)
    container = f"supabase_db_{project}"
    run = subprocess.run
    scratch = []

    # Fault injection only AFTER pg_restore, into the newly allocated drill database.
    def after_restore(cmd, *args, **kwargs):
        result = run(cmd, *args, **kwargs)
        if isinstance(cmd, list) and cmd[:5] == ["docker", "exec", "-i", container, "pg_restore"]:
            db = cmd[cmd.index("-d") + 1]
            assert re.fullmatch(r"drill_[0-9a-f]{32}", db) and not scratch
            scratch.append(db)
            change = (
                "DELETE FROM supabase_migrations.schema_migrations"
                if kind == "version"
                else "UPDATE supabase_migrations.schema_migrations SET name='qa-edited-name'"
            )
            sql = f"WITH changed AS ({change} WHERE version='20261125100000' RETURNING version) SELECT count(*) FROM changed"
            out = run(
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "psql",
                    "-XqAt",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-U",
                    "supabase_admin",
                    "-d",
                    db,
                ],
                input=sql,
                text=True,
                capture_output=True,
                check=True,
            )
            assert out.stdout.strip() == "1"
        return result

    monkeypatch.setattr(restore_drill.subprocess, "run", after_restore)
    with pytest.raises(RuntimeError, match=expected):
        restore_drill.drill()
    assert len(scratch) == 1
    # Verify cleanup even though the restore verification failed.
    check = run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-XqAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "supabase_admin",
            "-d",
            "postgres",
        ],
        text=True,
        capture_output=True,
        input=f"SELECT count(*) FROM pg_database WHERE datname='{scratch[0]}'",
        check=True,
    )
    assert check.stdout.strip() == "0"
