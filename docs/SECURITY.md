# Security model (Foundation-01)

Scope: the local development foundation. This is **not** a statement of
production readiness; the open items at the end must be closed first.

## Database roles

| Role | Can log in | Used by | Privileges |
|---|---|---|---|
| `edu_api` | No | (group role) | Everything the student API may do — see below |
| `edu_api_login` | Yes | The FastAPI service | Member of `edu_api` **only**. No SUPERUSER / BYPASSRLS / CREATEROLE / CREATEDB |
| `postgres` | Yes | Migrations, seed, test fixtures | Owns the `app` schema. Has BYPASSRLS on Supabase. **Never used to serve a request** |
| `anon`, `authenticated`, `authenticator`, `service_role` | (Supabase) | Supabase Data API | **No** rights on schema `app` at all |

What `edu_api` holds, in full (asserted by `supabase/tests/010_structure.sql`):

| Object | Privilege | Row filter (RLS) |
|---|---|---|
| `learner_profiles` | `SELECT`, `INSERT (user_id)` | own row only |
| `grades`, `subjects` | `SELECT` | active only |
| `courses`, `units`, `lessons` | `SELECT` | published course / active lesson |
| `pack_current`, `pack_releases`, `pack_items` | `SELECT` | current, active releases only |
| `lesson_revisions`, `question_revisions` | `SELECT` | approved, in a current pack, lesson visible |
| `lesson_progress`, `practice_attempts`, `account_sync_state`, `sync_receipts`, `account_change_feed` | `SELECT` | own rows only |
| `app.current_actor_id()`, `app.sync_apply_operation(...)` | `EXECUTE` | — |
| `staff_roles`, `content_sources`, `lesson_revision_sources`, `editorial_reviews`, `background_jobs`, `audit_events` | none | — |

There is no UPDATE, DELETE or TRUNCATE privilege anywhere, and no table-level INSERT.

### Login model and connection pooling

- Migrations create only the `NOLOGIN` group role, so **no password ever appears in SQL**.
- Locally, `scripts/local_stack.py provision` creates `edu_api_login` with a
  random password stored only in the git-ignored `.env`.
- Verified locally: the API connects directly to Postgres as `edu_api_login`
  (`current_user` and `session_user` are both `edu_api_login`).
- **Not verified:** a hosted pooler. The design is compatible with a
  *transaction-mode* pooler (Supavisor/PgBouncer) because identity is set per
  transaction, never per session — but that must be tested in staging with
  `EDU_DB_DISABLE_STATEMENT_CACHE=true`. The API also sends `statement_timeout`,
  `lock_timeout` and `idle_in_transaction_session_timeout` as connection
  parameters; if a pooler rejects those, set them on the role instead
  (`ALTER ROLE edu_api_login SET statement_timeout = ...`).

## Actor context lifecycle

1. FastAPI verifies the access token → `user_id`.
2. `Database.transaction(user_id)` opens a transaction and runs
   `SELECT set_config('edu.actor_id', :actor_id, true)` with a **bound parameter**.
3. Policies and `sync_apply_operation` read it through `app.current_actor_id()`.
4. At COMMIT or ROLLBACK PostgreSQL discards the value (`true` = transaction-local).
   The pool additionally rolls back every connection it takes back.

Tested (`tests/integration/test_isolation_and_operations.py`) with a pool of
exactly one connection: A → nobody → B on the same backend PID; after an SQL
error; after a Python exception; and with 30 interleaved concurrent requests of
two accounts. In a mutation check, changing `true` to `false` (session-wide)
made 3 tests fail.

**What this is not.** `edu.actor_id` is an ordinary setting: any SQL session can
set it. It is trustworthy only because (a) the API is the sole user of
`edu_api_login`, (b) the API sets it only from a verified token, and (c) no
request text is ever concatenated into SQL (all queries are static with bound
parameters). If an attacker could run arbitrary SQL on the API's connection they
could impersonate any learner — but, because of the grants above, still could
not write a score, edit history, read staff data, or reach `auth.users`.

## Token verification

| Check | Detail |
|---|---|
| Algorithm | Allow-list (`ES256` locally). Only asymmetric algorithms can be configured; `HS256` and `none` are impossible |
| Key | Looked up by `kid` in Auth's JWKS. Symmetric (`oct`) and non-signature keys in a JWKS are ignored. The algorithm must be the one that key is for (blocks algorithm-confusion) |
| Claims | `exp`, `iat`, `sub`, `aud`, `iss` required; issuer and audience must match configuration; 30 s clock leeway |
| Token type | `role == "authenticated"`, `sub` is a UUID, `is_anonymous` is not true |
| Key cache | 10 min TTL; unknown `kid` triggers at most one refresh per 30 s; if Auth is unreachable an already-trusted key keeps working, an unknown key fails closed (503) |
| Disclosure | The client always gets the same generic 401; the reason is logged server-side without the token |

The API holds **no signing secret**. It cannot mint tokens.

## Threat cases and what stops them

| # | Threat | Control | Evidence |
|---|---|---|---|
| T1 | Student A reads Student B's profile, attempts, progress, receipts or feed | Identity only from the token; RLS own-row policies; explicit `learner_id` filters | `020_rls_isolation.sql`; `test_two_students_two_devices_concurrent_sync`; `test_pull_pagination_cursor_and_reset_rules` |
| T2 | Client sends `learner_id` / `user_id` of someone else | Not an input anywhere; unknown fields are rejected | `test_identity_cannot_be_chosen_by_the_client`; `test_score_and_identity_in_the_request_are_never_trusted` |
| T3 | Client sends its own `score` / `is_correct` | No such field; the database function computes the score from the stored key | same test; `050_sync_function.sql` |
| T4 | Bug or injection in the API lets someone run SQL as the API role | Role has no write privilege on learning tables, no access to staff/audit/auth | `test_even_arbitrary_sql_on_the_api_connection_cannot_forge_state` (11 statements, all 42501) |
| T5 | Forged, expired, altered, wrong-issuer, wrong-audience token; `alg: none`; HS256 signed with the public key; project API key used as a user token | Verifier checks above | `tests/unit/test_token_verifier.py`; `tests/integration/test_auth_and_identity.py` |
| T6 | Identity of the previous request leaks through a pooled connection | Transaction-local setting; pool resets on return | see "Actor context lifecycle" |
| T7 | Replay / duplicate / concurrent retries create extra attempts or points | Per-learner lock + receipt lookup inside the write function | `test_twenty_concurrent_identical_retries`; `test_commit_succeeds_but_ack_is_lost_then_retry_is_exactly_once` |
| T8 | Reusing an `op_id` to overwrite an earlier answer | Digest comparison → `conflict`, nothing written | `test_same_op_id_with_different_body_conflicts_without_side_effects` |
| T9 | Student reads a draft / rejected / unreleased lesson or its answer key | RLS chain on revisions and questions; sync function refuses unreleased content with an answer identical to "unknown" | `030_content_visibility.sql`; `test_unapproved_rejected_and_unpublished_revisions_are_never_served` |
| T10 | Staff member approves their own lesson, approves without a review, or with uncleared rights; published content edited in place | Triggers (apply to every role, including the owner) | `040_integrity_guards.sql` (62 assertions) |
| T11 | `app` data reachable through Supabase's auto-generated REST API | `app` not in exposed schemas; `anon`/`authenticated`/`authenticator` have no USAGE | `test_app_schema_is_not_reachable_through_the_supabase_data_api` (also with the secret service key) |
| T12 | Oversized bodies / gzip bombs exhaust memory | Wire and decompressed limits enforced before parsing | `test_batch_and_body_size_limits`; `test_gzip_bodies_and_decompression_bombs` |
| T13 | Errors leak internals | One error shape; DB errors logged by type/SQLSTATE only; bound values hidden (`hide_parameters`); validation errors do not echo input | `test_database_outage_has_clear_error_behaviour`; `test_empty_and_malformed_batches` |
| T14 | Probing which lesson/question ids exist as drafts | Same response for unknown and unpublished | `030_content_visibility.sql`; content tests |

## Secrets handling

| Item | Where it lives | In git? |
|---|---|---|
| API database password | generated by `scripts/local_stack.py`, stored in `.env` (mode 600) | No |
| Local Auth signing key (private) | `supabase/signing_keys.json` (mode 600), generated by `make setup` | No |
| Local Supabase keys | read from `supabase status` into `.env` | No |
| Seed account passwords | **do not exist**; `scripts/dev_token.py` sets a random one per run via the local admin API | No |
| Anything hosted | nothing: no cloud project is linked | — |

`.env.example` contains placeholders only. `scripts/` refuse to act on any host
other than `127.0.0.1`/`localhost`. The local Postgres superuser password
(`postgres`) is the Supabase CLI's fixed local default, reachable only on the
loopback interface; it is read from `supabase status`, not stored in the repository.

## Unresolved vulnerabilities and limitations

Ordered by how much they matter before any real student uses this.

1. **No rate limiting or abuse controls.** Nothing limits requests per account or
   IP. A signed-in user can create unlimited receipts/attempts. Needs a limiter
   (API gateway or in-app) before exposure to the internet.
2. **Access tokens are not checked for revocation.** A token stays valid until it
   expires (1 hour) even after sign-out or a ban. Acceptable for practice data;
   revisit for staff actions (shorter expiry or a session check).
3. **Arbitrary SQL on the API connection means impersonation.** See "What this is
   not". Mitigated by static parameterised SQL and minimal grants, not eliminated.
4. **SECURITY DEFINER functions are owned by `postgres`**, which has BYPASSRLS. A
   bug inside `sync_apply_operation` would run with owner rights. Mitigations:
   empty `search_path`, no dynamic SQL, EXECUTE limited to `edu_api`, typed
   arguments. Hardening option: move ownership to a dedicated NOLOGIN role with narrow grants.
5. **Hosted pooler behaviour is untested** (see "Login model").
6. **Concurrency guards for editorial races (C08) are reasoned, not reproduced by tests.**
7. **Answer keys are delivered to the device.** By design for offline practice;
   scores are therefore not proof of knowledge. Never use this path for graded exams.
8. **Rejected operations are permanent** for that `op_id`, and
   `content_not_available` is stored. If content is published later the app must
   submit a new operation.
9. **No retention or deletion.** Receipts, feed rows and attempts grow forever;
   there is no account-deletion procedure (deleting an `auth.users` row with
   learning data is blocked by foreign keys). Required before collecting real data on minors.
10. **Pack manifests are placeholders.** `manifest_sha256` in the seed is a
    labelled synthetic value; nothing verifies an object in storage (R2 does not exist yet).
11. **No audit trail is written yet.** `audit_events` exists and is protected, but
    nothing inserts into it; sync conflicts are only logged by the API.
12. **Staff roles are data, not an API.** There is no staff authentication, MFA,
    or endpoint; the editorial workflow is exercised only by fixtures.
13. **Local transport is plain HTTP.** Hosted environments must use HTTPS for the API and for the JWKS URL.
14. **Stale signing key during an Auth outage.** If Auth is unreachable, a
    previously trusted key keeps verifying tokens past the cache TTL. A key revoked
    during an outage would be honoured until Auth is reachable again.
15. **Any signed-in account becomes a learner on first contact** (including
    staff accounts). Intended for now; revisit when enrolment rules exist.
