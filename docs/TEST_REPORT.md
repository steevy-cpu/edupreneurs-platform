# Test report — Foundation-01

> **Mobile-01 (2026-11-22):** the mobile app's results are reported separately in
> `apps/student-native/docs/MOBILE_01_REPORT.md`. The backend suites below were
> re-run unchanged after that work: 209 pgTAP + 144 pytest, all passing.

Everything below was **actually executed** on 2026-11-21 (evening, US Eastern;
timestamps in outputs are UTC, hence 2026-11-22). Nothing is reported as passing
that was not run. Items that could not be run are listed at the end.

## Environment

| Item | Value |
|---|---|
| Machine | macOS (Darwin 25.3.0), Apple Silicon, OrbStack as Docker runtime (Docker 29.4.0) |
| Supabase CLI | 3.2.0 (pinned in `package.json`) |
| PostgreSQL | 17.12 (`supabase/postgres:17.12.0.000`) |
| Supabase Auth | GoTrue v2.198.0, ES256 signing key generated locally |
| Data API | PostgREST v16.5 behind Kong 2.8.1 (kept only to test that `app` is NOT exposed) |
| Python | 3.13.5 · FastAPI 0.165.0 · SQLAlchemy 2.0.58 · Pydantic 2.14.4 · asyncpg 0.32.0 · PyJWT 2.15.1 |
| Target | Local Docker stack only (`127.0.0.1`). No hosted project was linked, read or modified |

## Result summary

| Suite | Command | Passed | Failed | Skipped |
|---|---|---:|---:|---:|
| Database tests (pgTAP) | `make test-db` | **209** | 0 | 0 |
| Python unit tests | `uv run pytest tests/unit` | **71** | 0 | 0 |
| Python integration tests (real local Postgres + Auth) | `uv run pytest tests/integration` | **73** | 0 | 0 |
| Python total | `uv run pytest` | **144** | 0 | 0 |
| Lint + format check | `make lint` | clean | | |
| Type check (mypy strict, 25 files) | `make typecheck` | clean | | |
| Contract freshness | `uv run python scripts/export_openapi.py --check` | up to date | | |

pgTAP by file: `010_structure` 42 · `020_rls_isolation` 47 · `030_content_visibility` 22 · `040_integrity_guards` 62 · `050_sync_function` 36.
pytest by file: `test_token_verifier` 31 · `test_canonical_and_cursor` 31 · `test_jwks_cache` 9 · `test_auth_and_identity` 25 · `test_content` 10 · `test_isolation_and_operations` 19 · `test_sync` 19.

## 1. Clean-clone rebuild (completion gate)

All local data was destroyed first, then the committed repository was cloned
into an empty directory and built with the documented command only.

```text
$ npx supabase stop --no-backup
{"project_id_filter":"mon-edupreneur","backup":false,"message":"Stopped supabase local development setup."}
$ docker volume ls | grep -i edupreneur        → (none: all local data wiped)
$ git clone . <empty dir> && cd <empty dir>    → commit fce2d57
$ make setup
Starting database...
Applying migration 20261121000100_core_schema.sql...
Applying migration 20261121000200_integrity_guards.sql...
Applying migration 20261121000300_api_role_and_policies.sql...
Applying migration 20261121000400_sync_functions.sql...
Seeding data from supabase/seed.sql...
>> Target: LOCAL disposable database only (no --linked / --remote).
npx --no-install supabase db reset
Target: local stack (127.0.0.1:54322)
Resetting local database...
Applying migration 20261121000100_core_schema.sql...  (… all four again …)
Seeding data from supabase/seed.sql...
Finished supabase db reset on branch foundation-01.
wrote .env (git-ignored)
database login role 'edu_api_login' is ready (member of edu_api, no BYPASSRLS)
make setup exit=0        (18 s; Docker images were already cached on this machine)
```

Then, in that clone, in this order:

```text
### make lint                              All checks passed!                       exit=0
### make typecheck                         Success: no issues found in 25 source files   exit=0
### openapi --check                        openapi.json is up to date               exit=0
### make test-db (fresh database)          Files=5, Tests=209   Result: PASS        exit=0
### pytest tests/unit                      71 passed in 0.14s                       exit=0
### pytest (all)                           144 passed in 2.95s                      exit=0
### make test-db (after API tests)         Files=5, Tests=209   Result: PASS        exit=0
### pytest (second run, same database)     144 passed in 2.28s                      exit=0
```

The suites were run twice and in both orders to show they do not depend on each
other's leftovers. The same commands were then repeated in the working
directory after rebuilding its stack: 209 pgTAP pass, 144 pytest pass.

Migration replay therefore succeeded **four times** on an empty database (start
+ reset, in the clone and again in the working directory) with no manual step.

## 2. Requirement-by-requirement evidence (Workstream D)

| # | Requirement | Where it is tested | Result |
|---|---|---|---|
| 1 | Clean DB reset and migration replay | Section 1 above | pass |
| 2 | Tables, constraints, indexes, private-schema exposure, RLS exist | `010_structure.sql` (42); `test_app_schema_is_not_reachable_through_the_supabase_data_api` | pass |
| 3 | A cannot read/write B's profile, attempts, progress, receipts, feed; anonymous reaches nothing | `020_rls_isolation.sql` (47); `test_two_students_two_devices_concurrent_sync`; `test_pull_pagination_cursor_and_reset_rules`; `test_missing_token_is_401_everywhere` | pass |
| 4 | Unapproved, rejected, unpublished revisions unreadable via API or role | `030_content_visibility.sql` (22); `test_unapproved_rejected_and_unpublished_revisions_are_never_served`; `test_a_newer_draft_does_not_replace_the_published_revision` | pass |
| 5 | Self-review, missing reviewer role, uncleared rights, changed approved content, invalid pack pointer, wrong locale are rejected | `040_integrity_guards.sql` (62) | pass |
| 6 | Same answer twice, incl. 20 concurrent identical retries → one attempt, one change | `test_same_answer_sent_twice_creates_one_attempt`; `test_twenty_concurrent_identical_retries`; `test_twenty_concurrent_identical_lesson_completions`; `050_sync_function.sql` | pass |
| 7 | Same op_id + different body conflicts with no side effects | `test_same_op_id_with_different_body_conflicts_without_side_effects`; `050_sync_function.sql` | pass |
| 8 | Failure after commit but before the HTTP response, then retry, is idempotent | `test_commit_succeeds_but_ack_is_lost_then_retry_is_exactly_once` (the app commits, the response is discarded, the client sees a connection error, then retries) ; also `test_failed_transaction_applies_nothing` (failure *before* commit rolls back everything) | pass |
| 9 | Two students × two devices concurrently: no skipped versions, no leakage | `test_two_students_two_devices_concurrent_sync` (48 single-op pushes fired together; each account's versions are exactly 1..24) | pass |
| 10 | Pool reuse / account switch keeps no wrong actor | `test_actor_is_cleared_between_transactions_on_one_connection`; `test_account_switch_over_a_single_pooled_connection` (pool size 1, same backend PID) | pass |
| 11 | Bad signature, expired, wrong issuer/audience, missing token, malformed input rejected | `tests/unit/test_token_verifier.py` (31); `tests/integration/test_auth_and_identity.py` (25, real local tokens) | pass |
| 12 | Completion against a prior approved revision still points to it after a new one is published | `test_completion_keeps_pointing_at_the_revision_that_was_studied` | pass |
| 13 | Empty/invalid batch, unknown lesson, unsupported answer type, excessive payload, DB outage | `test_empty_and_malformed_batches`; `test_mixed_batch_reports_every_operation`; `test_batch_and_body_size_limits`; `test_gzip_bodies_and_decompression_bombs`; `test_database_outage_has_clear_error_behaviour`; `test_auth_key_service_outage_fails_closed` | pass |

Additional checks beyond the list: OpenAPI contract and single error shape
(`test_openapi_contract`); seed content validates against the JSON Schemas
(`test_seed_content_matches_the_published_json_schemas`); the API really
connects as a least-privilege role (`test_api_connects_with_a_least_privilege_role`);
arbitrary SQL on the API connection cannot forge state (11 statements).

## 3. Do the tests actually detect problems? (mutation checks)

Two deliberate regressions were applied, the tests run, and the change reverted.

**Mutation 1 — give the API role write access to attempts**
(`GRANT INSERT, UPDATE ON app.practice_attempts TO edu_api` + a permissive INSERT policy):

```text
010_structure.sql      Failed tests 23, 26, 35, 36  ("17 policies exist", "the only INSERT policy is …",
                       "edu_api has no table-level INSERT/UPDATE/DELETE/TRUNCATE anywhere", …)
020_rls_isolation.sql  Failed tests 21, 22  ("A cannot insert a self-scored attempt", "A cannot insert an attempt for B")
pytest                 FAILED test_even_arbitrary_sql_on_the_api_connection_cannot_forge_state[UPDATE app.practice_attempts SET score = 1]
```

**Mutation 2 — make the actor session-wide instead of transaction-local**
(`set_config(..., true)` → `false` in `db/session.py`):

```text
FAILED test_actor_is_cleared_between_transactions_on_one_connection
FAILED test_account_switch_over_a_single_pooled_connection
FAILED test_even_arbitrary_sql_on_the_api_connection_cannot_forge_state[UPDATE app.practice_attempts SET score = 1]
3 failed, 16 passed
```

Both were reverted (the database was later destroyed and rebuilt; the source
file was restored and the full suite re-run green).

## 4. Defects demonstrated in the unmodified v0.2 drafts

The original files were applied, unchanged, to a throw-away database
(`docs/reference/v02_defect_probe.sql` explains how to repeat this). Both applied
without error; the probe then printed:

```text
0001 draft: applied without error
0002 draft: applied without error
tables=22
policies=27
triggers=14
C02 v0.2: rows approved with no review, no source, self-approved=1
C03 v0.2: EMPTY pack inserted as active and made current=1
C04 v0.2: items remaining in the finalized pack after the move=0
C05 v0.2: author erased on a draft (independence check then skipped)=1
next_version=1
next_version=2
C01 v0.2: attempts with score 1 forged by the student role (DRAFT question, wrong answer)=1
C01 v0.2: change version after the student role rewound it=0
C01 v0.2: audit rows with actor_kind=staff written by the student role=1
C10 v0.2: existing app functions executable by PUBLIC=0
C10 v0.2: a NEW app function is executable by PUBLIC=true
```

Each of these is impossible in the Foundation-01 schema and covered by a test
(see `docs/SCHEMA_CHANGELOG.md`).

## 5. Sample verified API session (synthetic data, tokens redacted)

Real token issued by local Supabase Auth for `student.a@edupreneur.test`
(754 characters, ES256), API running with `make api`:

```text
$ curl -s -H "Authorization: Bearer <token-A>" http://127.0.0.1:8000/v1/me
{"user_id":"a0000000-0000-4000-8000-000000000001","preferred_locale":"fr","display_name":"Élève A (synthétique)",
 "grade":{"id":"b0000000-0000-4000-8000-000000000001","code":"9AF","label":"9e année fondamentale"},
 "created_at":"2026-11-22T04:39:01.129493Z"}

$ curl -s -X POST …/v1/sync/push  -d '{"ops":[{"op_id":"7c1d3f6a-2f0b-4e0e-9a51-5b7d0c9e1a01","kind":"practice_answer",
        "payload":{"question_revision_id":"d0000000-0000-4000-8000-000000000103","response":{"choice_id":"c"}}}]}'
{"results":[{"op_id":"7c1d3f6a-…","status":"accepted","replayed":false,"code":null,
  "result":{"score":1.0,"attempt_id":"e3774f3a-8dbe-464c-ab39-30a976154367","is_correct":true,"change_version":3,
            "scoring_version":"mcq-v1","question_revision_id":"d0000000-0000-4000-8000-000000000103"}}],
 "server_version":3,"canon_version":"mep-canon-1"}

$ (same request again — a retry)
{"results":[{"op_id":"7c1d3f6a-…","status":"accepted","replayed":true, … same attempt_id e3774f3a-… , "change_version":3 …}],
 "server_version":3, …}

$ curl -s -H "Authorization: Bearer <token-A>" …/v1/sync/pull
{"changes":[ {"version":1,…}, {"version":2,…},
  {"version":3,"entity_type":"practice_attempt","entity_id":"e3774f3a-8dbe-464c-ab39-30a976154367","is_tombstone":false,
   "data":{"op_id":"7c1d3f6a-2f0b-4e0e-9a51-5b7d0c9e1a01","score":1.0,"choice_id":"c","is_correct":true, …}, …}],
 "next_cursor":"eyJhIjoiZDM2YjAxYjRjZWJiMjM2MiIsIm4iOjMsInYiOjF9","has_more":false,"server_version":3}

$ curl -s -H "Authorization: Bearer <token-B>" …/v1/sync/pull          ← the other student
{"changes":[],"next_cursor":"eyJhIjoiODYyNjk3MjQ1Nzg2NGExYyIsIm4iOjAsInYiOjF9","has_more":false,"server_version":0}

$ curl -s …/v1/me                                                      ← no token
{"error":{"code":"unauthenticated","message":"A valid access token is required.","request_id":"90e451ef…"}} [HTTP 401]
```

Versions 1–2 in student A's feed were left by the last test of the suite that
had just run; the operation sent here received version 3. After the two
identical pushes the database held exactly one new attempt and one new feed row.

## 6. Not run / not verified

| Item | Why | How to verify |
|---|---|---|
| **GitHub Actions workflow** (`.github/workflows/ci.yml`) | Nothing was pushed (by instruction). The YAML parses and every command in it was run locally, but the workflow itself has never executed on a runner | Push the branch to a private repository and open a pull request |
| **Linux** | Only macOS (Apple Silicon) was available | Run `make setup && make check` on Ubuntu, or let CI do it |
| **First-ever setup with no cached Docker images** | Images were already downloaded when the clean-clone test ran | `docker system prune -a` (careful: affects other projects) then `make setup`, or rely on CI |
| **Hosted Supabase / connection pooler (Supavisor)** | Local-only assignment | Staging project; see `SECURITY.md` → "Login model" |
| **Editorial race guards (C08)** | Timing-dependent; need two coordinated database sessions | Add two-session tests (backlog in `NEXT_STEPS.md`) |
| **Load / performance** | Out of scope | Load test the sync path before a pilot |
| **Token expiry with a really expired Auth-issued token** | Would need to wait an hour; expiry is tested with tokens signed by a test key through the same verifier and HTTP path | Optional: lower `jwt_expiry` locally and re-test |

## How to reproduce

```bash
make setup        # first time only
make check        # lint + types + database tests + API tests
```
