# Backup / restore drill — lane NOTIFY (Part B)

**What this is:** one real `pg_dump` → `pg_restore` round trip, performed on
2026-11-24 (23:06–23:08 Haiti time) on the lane's own disposable local Supabase
stack, with synthetic data only.

**What this is not:** a backup system, a tested recovery of a hosted project, or
evidence about recovery time at real size. Platform-02's gate ("a restore from
backup has been performed and timed" against staging) is **still open**.

## Scope and safety

| | |
|---|---|
| Instance | Docker container `supabase_db_edu-on-notify` (PostgreSQL 17.12), database `postgres`, port 56722 on loopback |
| Only container touched | `supabase_db_edu-on-notify` (`docker exec` / `docker cp`). No other container was named |
| Data | Seed accounts (4 synthetic `auth.users`), the seed course, plus rows created for the drill: 11 sync operations through the real API (10 attempts, 1 completion) and 3 notifications, 2 deliveries, 1 preferences row |
| Dump location | `/Volumes/EdupreneursDev/logs/overnight-2026-11-24/notify-drill/` (outside the repository) |
| Scratch databases | `drill_restore_scratch`, `drill_restore_scratch2` on the same instance — **both dropped** at the end |
| Network | none: no cloud, no `--db-url`, no `supabase link` |

## Commands, in order

`C=supabase_db_edu-on-notify`, `D=/Volumes/EdupreneursDev/logs/overnight-2026-11-24/notify-drill`.

```sh
# 0. A list of facts to compare before and after (row counts of every table in
#    app, notify, auth, supabase_migrations; RLS flags; policies with their
#    expressions; table and column grants; schema ACLs; functions with their
#    ACL, SECURITY DEFINER flag, settings and md5 of the body; triggers;
#    constraints; indexes) — $D/facts.sql, 761 output lines.
docker cp $D/facts.sql $C:/tmp/drill_facts.sql
docker exec $C psql -U postgres -d postgres -q -f /tmp/drill_facts.sql > $D/facts-source.txt

# 1. Dump (custom format), inside the container, as the migration owner.
docker exec $C pg_dump -U postgres -d postgres -Fc -f /tmp/drill_postgres.dump
docker cp $C:/tmp/drill_postgres.dump $D/edu-on-notify-postgres.dump

# 2. Scratch database on the same instance, from the empty template.
docker exec $C psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c "CREATE DATABASE drill_restore_scratch TEMPLATE template0"

# 3a. Restore as the migration owner (what an application operator has).
docker exec $C pg_restore -U postgres -d drill_restore_scratch /tmp/drill_postgres.dump

# 3b. Restore again, into a second scratch database, as the platform superuser.
docker exec $C psql -U postgres -d postgres -c "CREATE DATABASE drill_restore_scratch2 TEMPLATE template0"
docker exec $C pg_restore -U supabase_admin -d drill_restore_scratch2 /tmp/drill_postgres.dump

# 4. Same facts from each restored database, then compare.
docker exec $C psql -U postgres -d drill_restore_scratch  -q -f /tmp/drill_facts.sql > $D/facts-restored-as-postgres.txt
docker exec $C psql -U postgres -d drill_restore_scratch2 -q -f /tmp/drill_facts.sql > $D/facts-restored-as-supabase_admin.txt
diff $D/facts-source.txt $D/facts-restored-as-postgres.txt
diff $D/facts-source.txt $D/facts-restored-as-supabase_admin.txt

# 5. Behaviour, not only catalogue rows: the same script in the source and in both
#    restores, inside a transaction that is rolled back ($D/behaviour.sql). It acts
#    as the student API role for Student A, Student B and "no actor", and as anon.
docker exec $C psql -U postgres -d <database> -q -f /tmp/drill_behaviour.sql

# 6. Roles are not in a database dump. Their definitions, without passwords:
docker exec $C pg_dumpall -U postgres --roles-only --no-role-passwords > $D/roles-only.sql

# 7. Clean up.
docker exec $C psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE drill_restore_scratch" -c "DROP DATABASE drill_restore_scratch2"
docker exec $C rm -f /tmp/drill_postgres.dump /tmp/drill_facts.sql /tmp/drill_behaviour.sql
#    ... and TRUNCATE of the notify and learning rows created for the drill.
```

## Measurements

Wall-clock time of each `docker exec`, measured on the host (MacBook Air, Docker
VM with 7.8 GiB, other lanes running at the same time). One machine, one run
each unless stated; treat as order of magnitude.

| Step | Result |
|---|---|
| Source database size (`pg_database_size`) | 14,317,235 bytes (14 MB) — almost all of it platform schemas and catalogues |
| `pg_dump -Fc` | 0.13 s, 0.14 s, 0.13 s, 0.21 s (four runs); exit 0; nothing on stderr |
| Dump file | **370,291 bytes**, 775 archive entries; SHA-256 `78ada83a…a89f201` |
| `CREATE DATABASE … TEMPLATE template0` | 0.10 s |
| `pg_restore` as `postgres` | **1.48 s**, exit 1, **90 errors — all on platform-owned objects** (see below) |
| `pg_restore` as `supabase_admin` | **1.52 s**, exit 0, **0 errors** |
| Restored size | 12,760,755 bytes / 12,695,219 bytes |
| `pg_dumpall --roles-only --no-role-passwords` | 0.07 s, 6,134 bytes, 0 occurrences of `PASSWORD` |
| Drop both scratch databases | 0.55 s |

## Verification

**Row counts.** 57 tables in `app`, `notify`, `auth` and `supabase_migrations`,
284 rows in total: identical in the source and in both restores (e.g.
`app.practice_attempts` 10, `app.sync_receipts` 11, `app.account_change_feed`
11, `notify.outbox` 3, `notify.deliveries` 2, `auth.users` 4).

**RLS, policies, grants, functions, triggers, constraints, indexes.** Of 761
compared lines, **760 are identical** in both restores. The one difference:

```
notify.outbox | outbox_channels_check
source  : CHECK ((((cardinality(channels) >= 1) AND (cardinality(channels) <= 2)) AND (channels <@ ARRAY[...])))
restored: CHECK (((cardinality(channels) >= 1) AND (cardinality(channels) <= 2) AND (channels <@ ARRAY[...])))
```

Same meaning: `BETWEEN 1 AND 2 AND …` is stored nested when first written and
flat when re-parsed from the dump. Worth knowing because a schema-diff tool
would report it after any restore.

So, surviving unchanged: RLS enabled on all 28 `app` + `notify` tables; all 21
policies with their expressions; every table and column grant; the schema ACLs
(no `anon` / `authenticated` usage); all 26 functions (15 `app`, 11 `notify`) with `SECURITY DEFINER`,
`search_path=""`, their ACLs and byte-identical bodies; the 16 integrity
triggers.

**Behaviour.** The script gave the same output in the source and both restores:

| Check (as `edu_api`, unless stated) | Result |
|---|---|
| Student A reads attempts: own / others' | 5 / 0 |
| Student B reads attempts: own / others' | 5 / 0 |
| No actor reads attempts | 0 |
| Student A reads notifications: own / others' | 2 / 0 |
| Student B reads A's preferences row | 0 |
| A inserts a self-scored attempt | `42501` |
| A calls `notify.enqueue` | `42501` |
| A reads `notify.deliveries` / `app.staff_roles` | `42501` / `42501` |
| Owner edits an approved lesson revision | refused by trigger (`P0001`) |
| `anon` reads `notify.outbox` / `app.learner_profiles` | `42501` / `42501` |

## What the 90 errors as `postgres` mean

On Supabase, `postgres` is **not** a superuser. The dump contains objects owned
by `supabase_auth_admin` (41 errors), `supabase_admin` (15) and `pgbouncer` (1):
`ALTER … OWNER TO` those roles fails with *must be able to SET ROLE*, as do 21
`ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin / supabase_auth_admin`, 5
grant-option statements, 4 statements on schema `supabase_functions`, 1 `COPY`
into `vault.secrets` and 2 function grants. **No error concerned an object in
`app` or `notify`**, and the comparison above passed for that restore too — but
the `auth` tables it produced are owned by the wrong role, so that database
would not be usable by the Auth service.

Consequence for the real runbook: a logical dump taken as `postgres` restores
*our* schemas faithfully but is **not** a complete restore of a Supabase project.
A hosted project must rely on the platform's own backups (or a restore run by a
role that may assume the platform roles) for `auth`, `storage` and `vault`.

## Limits of this drill (do not over-read it)

1. **Same instance.** Roles are cluster-wide, so the grants "survived" partly
   because `edu_api` already existed. On a new cluster the roles must be created
   first (step 6 shows the definitions; `edu_api_login`'s password is provisioned
   out of band and is in no dump). This was **not** exercised.
2. **Tiny, synthetic data** (284 rows). The timings say nothing about real size.
3. **No point-in-time recovery, no WAL, no schedule, no retention, no
   encryption of the dump, no off-machine copy.** None exists.
4. **Consistency under load was not tested**: nothing was writing during the dump.
5. **The dump file contains the whole database**, including `auth.users`
   (synthetic here). With real data it would be personal data of minors and would
   need the same access control, encryption and retention as the database.
6. **Restore was not followed by the application test-suite** against the
   restored database; behaviour was checked with the script above only.
7. The local CLI stack differs from a hosted project (extensions, pooler,
   storage); nothing here was run against a hosted service.

## Still required before real learners (`BLOCKED_BY_OWNER` / Platform-02)

- A hosted staging project owned by Edupreneurs, with the platform's backups
  switched on and a restore performed **there**, timed, by a named person.
- Decisions: recovery-time and recovery-point objectives; who may hold a dump;
  where it may be stored; how long it is kept (ties into the retention and
  erasure decisions of PO-04 — an erased learner must also leave the backups
  within a stated period).
