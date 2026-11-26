"""Offline migration contract and a read-only release/restore gate."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import ssl
import subprocess

import asyncpg

from disposable import verify
from edu_api.config import Settings, require_canonical_settings
from edu_api.db.staging import SECURITY_SQL, validate_hosted_dsn, validate_runtime
from local_stack import ROOT, read_env_file

MANIFEST = ROOT / "docs/infra/staging-00/migrations.sha256"


def versions() -> list[str]:
    files = sorted((ROOT / "supabase/migrations").glob("*.sql"))
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT)}" for p in files]
    ids = [p.name.split("_")[0] for p in files]
    if (
        not ids
        or len(set(ids)) != len(ids)
        or any(not re.fullmatch(r"\d{14}", v) for v in ids)
        or lines != MANIFEST.read_text().splitlines()
    ):
        raise ValueError("migration files differ from the reviewed ordered manifest")
    return ids


def pending_versions(expected: list[str], applied: list[str]) -> list[str]:
    if applied != expected[: len(applied)]:
        raise ValueError("migration ledger is not a reviewed prefix")
    return expected[len(applied) :]


async def check_session(
    db: asyncpg.Connection, login: str, expected: list[str], *, plan: bool = False
) -> None:
    if await db.fetchval("SELECT current_user") != login:
        raise ValueError("unexpected audit session identity")
    if login == "edu_staging_auditor" and not await db.fetchval("""
        SELECT NOT (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole
                    OR rolreplication)
            AND NOT EXISTS (SELECT FROM pg_auth_members WHERE member = r.oid)
            AND NOT has_database_privilege(r.oid, current_database(), 'CREATE,TEMP')
            AND NOT has_schema_privilege(r.oid, 'app', 'USAGE')
            AND NOT has_schema_privilege(r.oid, 'auth', 'USAGE')
            AND NOT has_schema_privilege(r.oid, 'supabase_migrations', 'CREATE')
            AND NOT has_table_privilege(r.oid, 'supabase_migrations.schema_migrations',
                                        'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
            AND NOT has_any_column_privilege(r.oid, 'supabase_migrations.schema_migrations',
                                             'INSERT,UPDATE,REFERENCES')
            AND NOT EXISTS (
                SELECT FROM pg_attribute a
                WHERE a.attrelid = 'supabase_migrations.schema_migrations'::regclass
                  AND a.attnum > 0 AND NOT a.attisdropped
                  AND (has_column_privilege(r.oid, a.attrelid, a.attnum, 'SELECT WITH GRANT OPTION')
                       OR (a.attname <> 'version'
                           AND has_column_privilege(r.oid, a.attrelid, a.attnum, 'SELECT'))))
        FROM pg_roles r WHERE rolname = current_user
    """):
        raise ValueError("excessive audit login privileges")
    rows = await db.fetch(
        "SELECT version FROM supabase_migrations.schema_migrations ORDER BY version"
    )
    applied = [r["version"] for r in rows]
    pending = pending_versions(expected, applied)
    if plan:
        print("Pending versions:", *pending)
        return
    if pending:
        raise ValueError("pending migrations")
    result = await db.fetchrow(SECURITY_SQL)
    failed = [key for key, value in result.items() if value is not True]
    if failed:
        raise ValueError("database assertions failed: " + ", ".join(failed))


async def audit(environment: str, *, plan: bool = False) -> None:
    expected = versions()
    tls: ssl.SSLContext | bool = False
    if environment == "local":
        local = read_env_file()
        verify(env=local)
        url = local["LOCAL_ADMIN_DATABASE_URL"]
        login = "postgres"
    else:
        if os.environ.get("EDU_ENVIRONMENT") != "staging":
            raise ValueError("explicit staging environment required")
        require_canonical_settings(os.environ)
        settings = Settings(_env_file=None)
        validate_runtime(settings)
        url = os.environ["STAGING_AUDIT_DATABASE_URL"]
        login = "edu_staging_auditor"
        validate_hosted_dsn(url, settings.staging_project_ref or "", login, "postgresql")
        tls = ssl.create_default_context(cafile=settings.db_ca_file)
    db = await asyncpg.connect(url, ssl=tls, timeout=5, command_timeout=8)
    try:
        async with db.transaction(readonly=True, isolation="repeatable_read"):
            await check_session(db, login, expected, plan=plan)
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["manifest", "audit", "plan"])
    parser.add_argument("--environment", choices=["local", "staging"])
    parser.add_argument("--base", help="base commit for append-only migration verification")
    args = parser.parse_args()
    if args.action == "manifest":
        versions()
        if args.base:
            if not re.fullmatch(r"[0-9a-f]{40}", args.base):
                parser.error("expected a full base SHA")

            def tree(ref: str) -> list[str]:
                return subprocess.check_output(
                    ["git", "ls-tree", "-r", ref, "--", "supabase/migrations"], text=True
                ).splitlines()

            old = tree(args.base)
            if tree("HEAD")[: len(old)] != old:
                parser.error("migrations must append after the last immutable migration")
    elif args.environment is None:
        parser.error("audit requires --environment")
    else:
        try:
            asyncio.run(audit(args.environment, plan=args.action == "plan"))
        except Exception as exc:
            # Some connection/configuration errors include user input or the DSN.
            raise SystemExit(
                f"verification failed ({type(exc).__name__}); check target, ledger and policy"
            ) from None
    print("verification passed")
