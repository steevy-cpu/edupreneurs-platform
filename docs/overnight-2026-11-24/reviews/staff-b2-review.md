# Security review — staff B2 (commit 642ab5c) — public version

Reviewer: independent QA (qa2 stack only). Branch `overnight/staff-worker`, range 7c3d2fb..642ab5c.

**Verdict: APPROVE WITH FIXES.** The B1 HIGH finding is closed. One new MEDIUM (M-B2-1, a single admin can publish
content nobody else reviewed) should be fixed before merge; it is a small change. Everything else is LOW/NOTE.

Suites observed on qa2 at 642ab5c after `make db-reset`: pgTAP 593 tests in 11 files, PASS; pytest 376 passed;
`make lint` clean; `make typecheck` clean (41 files). These match the author's numbers.

## Priority 1 — re-check of the B1 HIGH finding (H1, pg_temp type shadowing)

**Status: CLOSED on 642ab5c for all three real logins.**

Evidence (qa2 stack, after `make db-reset` at 642ab5c; the original reproduction was re-run as each of the three real
logins, in rolled-back transactions):

- None of `edu_api_login`, `edu_staff_login`, `edu_worker_login` holds TEMP on the database; every attempt to create a
  temporary object of any kind is refused (42501), so the precondition of the original finding is gone. The functions
  that carried the weakness (baseline `app.sync_apply_operation`, `ops.audit_write`, `staff.actor_roles`,
  `staff.require_role`, `ops.session_kind`) then behave normally.
- Other ways to create a shadowing object were tried and refused for all three logins: creating a schema, creating
  objects in `public`, `app`, `ops`, `staff`, `extensions`, switching role or session authorization, granting the
  privilege to oneself.
- Catalog sweep: PUBLIC has CONNECT only. TEMP is false for `edu_api`, `edu_staff`, `edu_worker`, their three logins,
  `anon`, `authenticated`, `authenticator`, `service_role`. It remains only with the owner, the platform superuser
  and one NOLOGIN dashboard role that no API-facing role is a member of. No API-facing role has CREATE on any schema.
- Each login is a member of exactly its own group.
- All 51 functions in `ops`/`staff` carry `search_path = pg_catalog, pg_temp`. The 15 baseline `app` functions keep
  their original setting and are protected by the TEMP revoke alone.
- No role-level or database-level `search_path` setting exists for an API-facing role.
- Local Auth after `make db-reset`: health 200, password sign-in issues tokens (new accounts were created and signed in
  by the probes and by the 376 pytest tests).
- Regression tests exist: `supabase/tests/100_platform_structure.sql:33-39,155` and
  `tests/integration/test_staff_hardening.py:49-110`.

**Answer for the owner about `main`:** the weakness on `main` (baseline `app.sync_apply_operation` /
`app.current_actor_id` reachable by `edu_api_login`) is closed by this branch's migration
`20261124010400_revoke_temp_and_search_path.sql` part (a) alone, without changing any baseline function. `main` itself
stays exposed until that migration (or the same one-statement revoke) is merged there.

Residual points (NOTE level):
- N-P1a. The protection of the `app` functions rests on one database-level privilege. Anything that later re-grants
  TEMP to PUBLIC or to an API role (a hosted-platform default, a restore into a new database, a dashboard action)
  silently reopens it for `app`. The pgTAP assertion catches it only where the tests run. Recommend the same assertion
  as a deploy-time/readiness check on the hosted project, and — when the baseline is unfrozen — moving `app` functions
  to `pg_catalog, pg_temp` too.
- N-P1b. The three logins still hold TEMP in the separate local database `_supabase` (PUBLIC default there). Temporary
  objects are per database, so this cannot shadow anything in the application database; mentioned for completeness.
- N-P1c. Not examined: whether Supabase Storage / Realtime / Studio (not exercised here) need TEMP through the revoked
  roles on a hosted project.


## Other B1 findings — status at 642ab5c

| Finding | Status | Evidence |
|---|---|---|
| M1 unlimited denial rows | **Fixed** | `ops.audit_access_denied` (migration 010100) keeps one persisted row per actor per 60 s and counts the rest. Run: 400 concurrent refused requests with one learner token rotating over 8 routes and 4 methods, plus 1 from a second learner → all 403; exactly 1 audit row for the first learner, `suppressed` = 399, the second learner's single refusal recorded (2 new rows in total). A full sweep of every staff route × 5 methods wrote 1 row. Unmatched staff paths give 404 and write nothing. The bound is keyed by actor only, so it cannot hide another actor's refusals. Residual, NOTE: inside a window only the FIRST refusal's route/method is stored; later refusals on other (possibly more sensitive) routes are only counted. Storage is one row per account ever refused. |
| M2 audit details validator | **Fixed as recommended (structural guard only, by design)** | Strings capped at 64 chars (120 for `route`); function comment and `ops.audit_write` comment now say callers must never pass learner-typed values. Still accepted, as documented: `{"answer":"Paris"}`, a dotted name, a phone number, a date; a 71-char underscore sentence is now refused. All B2 callers I read pass ids/enums/numbers only. |
| L1 superuser labelled staff | **Fixed** | `ops.actor_kind_for('supabase_admin')` = `system`, `postgres` = `system`, `edu_staff_login` = `staff`. |
| L2 learner refusal indistinguishable | **Fixed** | Stored details now include `held_roles` (`[]` for the learner) and `check`; observed row: `{"check":"route","route":"/v1/staff/users/{user_id}/roles/{role}","method":"PUT","held_roles":[],"required_roles":["admin"]}`. |
| L3 odd route → 500 | **Fixed** (code + author's test, not re-reproduced by me) | `deps.py` `_route_template` falls back to `"unknown"`; `test_staff_hardening.py:159` passes. |
| L4 wrong credential/login → 500 | **Fixed** (code + author's test, not re-reproduced by me) | `verified_staff_db` requires `ops.session_kind() = 'staff'`, SQLSTATE 28xxx → 503; `test_staff_hardening.py:237` passes. |
| L5 test blind spot | **Fixed** | `100_platform_structure.sql:75-93` now uses `has_table_privilege` over `pg_class`. My own sweep: 0 relations in app/ops/staff/auth/public reachable by the staff or worker login. |

## New findings

### MEDIUM

**M-B2-1 — a single admin can put content in front of learners that no second person reviewed, under another person's name.**
- Where: `supabase/migrations/20261124010200_staff_editorial.sql:113-126` (`staff.require_author` lets any active admin
  through), used by `update_revision` (:279), `attach_source` (:359), `detach_source` (:384), `submit_revision` (:412).
- What is wrong: the baseline trigger compares the reviewer with `created_by`. An admin may replace the whole content of
  somebody else's draft; `created_by` stays the original editor, so the same admin then passes "reviewer ≠ author".
  Admin also holds every other step (clear rights, submit, review, build, release).
- Confirmed by a run through the API on the QA stack with one admin-only account and one editor's draft; the released
  lesson was visible to a learner, with the editor recorded as author and the admin as approver. Steps are in the
  private report.
- Impact: the product's central guarantee (independent review of what minors see) depends on no admin account being
  misused or compromised, and the record names an editor as author of words they never wrote. It needs the admin role
  and any existing draft by someone else.
- Control check: a person holding editor+reviewer+publisher+admin on their OWN draft is refused (409
  `author_cannot_review`), so only the "admin edits someone else's draft" path is open.
- Smallest fix: remove the admin exception from `staff.require_author` (author only). If admins must be able to correct
  drafts, have them create a new revision (they then are its author). Add a test "admin edits another's draft → 403"
  and "admin who edited cannot review".

### LOW

- **L-B2-1 — a NUL character in lesson text gives 500 instead of 422.** Creating a revision whose text contains one
  → `500 internal_error` (PostgreSQL refuses `\u0000` in jsonb; the Pydantic models in
  `staff/content.py` do not). Fails closed, nothing stored. Fix: reject control characters in the text constraints.
- **L-B2-2 — a pack may contain two revisions of the same lesson.** `staff.build_pack` (:555) checks duplicate revision
  ids, not duplicate lessons. Run: pack `[older, newer]` and `[newer, older]` both built (201) and released (200);
  the learner got the newer revision in both cases, the catalog listed the lesson once. Both revisions were approved,
  so no unreviewed content is exposed, but the pack no longer says unambiguously what learners get, and a rollback
  target can be misread. Fix: refuse two items with the same `lesson_id` in `build_pack`.
- **L-B2-3 — no way to take content down through the API.** Setting the source of LIVE content to `blocked` → 204 and the
  lesson stays readable (200). There is no route to revoke a release, and `rollback` needs an earlier retired release,
  so the first release of a pack cannot be withdrawn without direct SQL. Not required by the brief; for a platform
  for minors a takedown path (publisher/admin, audited) should exist before real use.
- **L-B2-4 — "last admin" counts role rows, not accounts that can still sign in.** By reasoning
  (`20261124010300_staff_role_admin.sql`, `revoke_role`): the check is "another active admin row exists"; it does not
  look at `auth.users` (deleted/banned). The last usable admin can therefore be revoked if a dead account still holds
  an active admin row. Fix: join `auth.users` (not deleted, not banned) in the check, as `check_role_target` does.

### NOTE

- The API's global body limit (20 480 bytes on the wire) is far below the database bounds (blocks 256 KB, questions
  128 KB); 200 × 4000-char blocks → 413. Safe, but a long lesson cannot be authored; the DB bounds are unreachable.
- A review is not bound to a content version. Content is frozen from `in_review` on (verified), so there is no
  change-after-read while in the queue; a reviewer who read the draft before submission could approve something edited
  just before submit. Race run 5×: every outcome was a legal ordering (edit before submit, or edit refused 409).
- Worker fencing token: all workers share `edu_worker_login`, and `p_worker_id` is caller-supplied. A second worker
  session that passes another worker's id can heartbeat/complete/fail its job (observed: heartbeat → true). Fine inside
  one trust domain; worth a line in the doc.
- `ops.enqueue_job` is granted to `edu_staff` but no staff route uses it; payload content is not validated (free text
  accepted). Least privilege: drop the grant until a staff route needs it.
- Admins can grant any role, including `admin`, to any non-anonymous account (also a learner's). Two colluding admins,
  or one admin with a second account, can still self-approve; that is inherent to the role model and is audited.
- Learner lesson responses contain `correct_choice_id` — baseline behaviour (`assessment_mode: offline_practice`, same
  for the seeded lesson), not introduced by this lane.
- Releasing an older `ready` release after a newer one is allowed (moves the pointer "backwards"); audited.

## Verified sound (tried to break, could not)

- **Self-approval:** holder of all four roles approving own draft → 409 `author_cannot_review`.
- **Frozen content:** edit while `in_review` (author and another admin) → 409; edit/attach/detach on rejected and on
  approved revisions → 409; resubmit or re-review of a rejected revision → 409.
- **Packs:** `in_review` or rejected revision in a pack → 409 `pack_item_not_approved`; approval with an uncleared
  source → 409 `sources_not_cleared`; approval racing with blocking the source ended "approved + blocked", and the
  build was then refused (409); source blocked after build → release refused (409).
- **Rights:** editor and reviewer cannot clear a source (403); only admin.
- **Release/rollback:** editor and reviewer → 403 on both. 6 concurrent releases of 3 ready releases and 6 concurrent
  rollbacks: always exactly one `active` release and one current pointer. Rollback of the active release → 409;
  rollback to and release of a `revoked` release → 409.
- **Learner view = released content:** blocks returned by `/v1/lessons/{id}` equal the blocks of the current release's
  revision; a newer unreleased draft, a never-released lesson (404, absent from `/v1/catalog`) and a built-but-unreleased
  pack (404) are invisible.
- **Staff routes:** all 16 route paths × 5 methods with a learner token → 403 (or 405), with no token → 401 (or 405);
  a valid body does not change that.
- **Validation:** unknown block type, extra property, 201 blocks, 4001-char text, 51 questions, correct choice not
  offered, duplicate choice ids, duplicate question keys, other question kind, other locale, wrong types → 422;
  12 MB and deeply nested bodies → 413; `javascript:` source URI, odd pack key, 501 pack items, bad list params → 422.
- **Definer functions (51 in ops/staff):** every `staff.*` definer starts with `staff.require_role` in its first
  declaration; all carry `search_path = pg_catalog, pg_temp`; no dynamic SQL from input (the only `EXECUTE format`
  are DDL in migrations over catalog names); audit details hold ids, enum codes and counts only (review notes, titles
  and rights notes are not audited). Executable by `edu_staff_login`: 27 intended functions; by `edu_worker_login`: 7;
  by `edu_api_login`, `anon`, `authenticated`, `service_role`: none. Internal helpers are not executable by any login.
- **Role administration:** admin self-grant → 403; sole admin self-revoke → 409 `last_admin`, also when the only other
  admin is inactive; deactivated admin → 403 on grant/list/self-reactivation; 8 rounds of two admins revoking each
  other concurrently and 6 rounds of a three-way cycle plus self-revokes → exactly 1 admin left every time;
  grant / repeat grant / revoke / repeat revoke / re-grant / revoke → 4 audit rows (one per real change), actor = the
  admin; revoked role stops working on the next request; bogus role 422, unknown user 404, non-admin 403.
- **Worker:** `edu_api_login` cannot reach `ops` at all; staff login can enqueue only; no login can read
  `app.background_jobs`. Another worker id cannot heartbeat/complete/fail a leased job; no second lease while leased;
  after expiry the job is re-leased (attempt 2) and the late worker's complete/fail/heartbeat return false/NULL/false;
  expiry on the last attempt → `dead`, `LeaseExpired`, one `job.dead` audit row (`actor_kind=worker`, codes only);
  free text as error class is stored as `UnnamedError`; 16 concurrent claimers over 120 jobs → 120 leases, 120 distinct,
  attempts = 1; 40 concurrent enqueues with one key → 1 row; out-of-range arguments refused. The runner logs job id,
  kind, attempt and exception class name only (`runner.py:141-172`). No `pg_cron`/`pg_net`/`pgmq`, no schedule; the
  job table was empty after the suites.
- **Mission rules:** nothing created, altered or granted in schema `app` (0 ACL entries for the new roles on app
  relations/functions); baseline migrations, seed, 0xx tests and `packages/` identical to `origin/main`; files outside
  the owned paths are only the five the brief allows; no secrets in the diff; the only table added
  (`ops.access_denial_windows`) has RLS on and no grants.

## Missing tests

- Admin editing/submitting another author's draft, then reviewing it (M-B2-1).
- Control characters / NUL in content text (L-B2-1).
- Two revisions of one lesson in a pack (L-B2-2).
- Last-admin check when the other admin's account is deleted or banned (L-B2-4).
- Concurrent release of several ready releases; rollback to a revoked release (behaviour is correct, not pinned).
- A deploy-time assertion of the TEMP revoke outside the test database (N-P1a).

## Not examined

- `staff/errors.py` message mapping in detail; `scripts/local_stack.py` changes; the lane doc's accuracy and the MFA
  design text; worker graceful shutdown and bounded concurrency (author's tests only).
- L3 and L4 were not re-reproduced independently (code read + author's passing tests).
- Hosted Supabase behaviour (default privileges, Supavisor, Storage/Realtime needing TEMP); `main` itself was not run.
- Performance/load, and anything after 642ab5c.

Probe scripts, outputs and step-by-step reproductions are in the private report (not committed).
