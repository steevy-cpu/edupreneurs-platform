"""Restore synthetic data into a newly created database in a verified disposable stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

from disposable import verify
from edu_api.db.staging import SECURITY_SQL
from local_stack import ROOT
from staging_verify import versions


def drill() -> None:
    project = verify(check_env=True)
    expected = versions()
    container = f"supabase_db_{project}"
    target = "drill_" + uuid.uuid4().hex
    docker = ["docker", "exec", "-i", container]

    def query(db: str, sql: str) -> str:
        return subprocess.check_output(
            [*docker, "psql", "-XqAt", "-v", "ON_ERROR_STOP=1", "-U", "supabase_admin", "-d", db],
            input=sql,
            text=True,
        ).strip()

    def checks(db: str) -> dict[str, bool]:
        row: dict[str, bool] = json.loads(
            query(db, f"SELECT row_to_json(q) FROM ({SECURITY_SQL}) q")  # noqa: S608 - checked-in SQL
        )
        return row

    def ledger(db: str) -> list[str]:
        return query(
            db, "SELECT version FROM supabase_migrations.schema_migrations ORDER BY version"
        ).splitlines()

    def fingerprint(db: str) -> str:
        # Only digests cross the container boundary. Names come from pg_catalog and are SQL-quoted.
        return query(
            db,
            r"""
            SELECT format('SELECT %L, count(*), md5(coalesce(string_agg(h, %L ORDER BY h), %L))
                FROM (SELECT md5(to_jsonb(t)::text) h FROM %I.%I t) rows',
                schemaname || '.' || tablename, '', '', schemaname, tablename)
            FROM pg_tables WHERE schemaname IN ('auth','app','supabase_migrations')
            ORDER BY schemaname, tablename
            \gexec
        """,
        )

    def require(ok: bool, reason: str) -> None:
        if not ok:
            raise RuntimeError(reason)

    source = "postgres"
    source_checks = checks(source)
    require(
        all(source_checks.values()),
        "source drift: " + ", ".join(k for k, v in source_checks.items() if not v),
    )
    require(ledger(source) == expected, "unexpected source ledger")
    original = fingerprint(source)
    require(bool(original), "empty source fingerprint")

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "synthetic.dump"
        with archive.open("wb") as output:
            subprocess.run(
                [
                    *docker,
                    "pg_dump",
                    "-U",
                    "supabase_admin",
                    "-Fc",
                    "-n",
                    "auth",
                    "-n",
                    "app",
                    "-n",
                    "supabase_migrations",
                    source,
                ],
                stdout=output,
                check=True,
            )
        with archive.open("rb") as data:
            digest = hashlib.file_digest(data, "sha256").hexdigest()
        subprocess.run(
            [*docker, "createdb", "-U", "supabase_admin", "-T", "template0", target], check=True
        )
        try:
            with archive.open("rb") as data:
                require(
                    hashlib.file_digest(data, "sha256").hexdigest() == digest,
                    "archive checksum mismatch",
                )
                data.seek(0)
                subprocess.run(
                    [
                        *docker,
                        "pg_restore",
                        "--exit-on-error",
                        "--single-transaction",
                        "-U",
                        "supabase_admin",
                        "-d",
                        target,
                    ],
                    stdin=data,
                    check=True,
                )
            require(ledger(target) == expected, "restored migration ledger mismatch")
            require(fingerprint(target) == original, "restored row counts or digests differ")
            # A filtered logical backup omits database ACLs, even when the ledger includes PR #20.
            require(not checks(target)["temp_revoked"], "expected the fresh database TEMP default")
            repair = (
                ROOT / "supabase/migrations/20261125100000_revoke_temp_from_api_roles.sql"
            ).read_text()
            query(target, repair)
            after = checks(target)
            require(
                all(after.values()),
                "restore policy: " + ", ".join(k for k, v in after.items() if not v),
            )
            query(target, f"GRANT TEMP ON DATABASE {target} TO edu_api_login")
            require(not checks(target)["temp_revoked"], "missed direct login grant")
            query(target, f"REVOKE TEMP ON DATABASE {target} FROM edu_api_login")
            query(target, "CREATE EXTENSION hstore")
            require(not checks(target)["extensions"], "missed unreviewed extension")
            query(target, "DROP EXTENSION hstore")
            require(
                all(checks(target).values()) and fingerprint(target) == original,
                "final restore verification failed",
            )
        finally:
            subprocess.run([*docker, "dropdb", "-U", "supabase_admin", target], check=True)
    print(
        "Restore passed: data digests, migration ledger, role policy and drift."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=["local"], required=True)
    parser.parse_args()
    drill()
