# Lane STAFF — staff boundary, audit writes, editorial slice, worker (F1 · M-03, M-04)

Worktree `/Volumes/EdupreneursDev/worktrees/overnight/staff` · branch `overnight/staff-worker` ·
stack API 56121 / DB 56122 · schemas `ops`, `staff` · migrations `2026112401xxxx_*` · pgTAP `100–119_*`.

Owned paths: `supabase/migrations/2026112401*`, `supabase/tests/10*.sql`, `supabase/tests/11*.sql`,
`services/api/src/edu_api/staff/**`, `services/api/src/edu_api/routers/staff*.py`,
`services/worker/**`, `tests/**/test_staff_*.py`, `tests/**/test_worker_*.py`, `tests/staff_fixtures.py`,
`docs/overnight-2026-11-24/lanes/staff.md`.
Shared files you alone may extend tonight (additively, keeping existing behaviour and tests intact):
`scripts/local_stack.py` (provision `edu_staff_login`, `edu_worker_login`; write their URLs to `.env`),
`.env.example`, `pyproject.toml` (only to package the worker), `services/api/src/edu_api/config.py`,
`main.py`. The check "edu_api_login belongs to no role other than edu_api" must keep passing.

## B1 — deliver FIRST, commit, and report back immediately (other lanes are waiting on it)

Implement exactly the "Shared platform interface" in `00-PLAN.md` §3:
- Migration `20261124010000_platform_roles_ops_staff.sql`: roles `edu_staff`, `edu_worker` (plain
  NOLOGIN, attribute self-check like `edu_api`), schemas `ops` and `staff` (private; revoke from
  PUBLIC/anon/authenticated), `ops.audit_write`, `staff.actor_has_role`, `staff.require_role`.
  Audit details must be bounded (size limit) and must never contain free text from learners.
- Local provisioning for the two login roles (random passwords in the git-ignored `.env`, same
  pattern as `edu_api_login`; each login is a member of exactly its own group).
- API: `Settings.staff_database_url` (optional; when unset every `/v1/staff` route answers 503 in the
  standard error shape), a second `Database` on `app.state.staff_db`, `edu_api/staff/deps.py` with
  `require_staff(*roles)` (verified token → role lookup through the staff pool → 403 `forbidden`
  for non-staff; decision audited as `denied`), and `GET /v1/staff/me` (roles of the caller).
- Test fixtures in `tests/staff_fixtures.py`: staff client/tokens for the seeded `editor` and
  `reviewer`, and helper(s) to create additional synthetic staff accounts (publisher, admin) through
  the local Auth admin API + admin pool — without editing `seed.sql`.
- Tests: pgTAP for roles/grants/negative cases (edu_api cannot execute anything in `ops`/`staff`,
  cannot see either schema; inactive role is refused; audit rows are append-only and correctly
  attributed); pytest proving a learner token is refused on staff routes, staff token accepted,
  Data API cannot reach `ops`/`staff`.
Run the full gate, commit, and **end your turn with the B1 report** so the director can merge it.

## B2 — after the director confirms B1 (you will be messaged)

1. **Editorial vertical slice through the API** (Platform-03 gate: "the editorial rules already
   enforced by triggers are exercised through the API, not fixtures"). All writes via `staff.*`
   definer functions that call `staff.require_role` and `ops.audit_write`; the existing `app`
   triggers (drafts only on insert, reviewer ≠ author, approved is immutable, cleared sources, pack
   rules) remain the enforcement of record — surface their errors as clean 409/422 API errors.
   Minimum endpoints (names may be refined; document them in your lane doc):
   create a draft revision with blocks + MCQ questions (validated against
   `packages/contracts/content/*.schema.json`), edit a draft, register a content source and attach
   it, submit for review, record a review (approve / reject / changes requested) by a different
   person holding `reviewer`, list drafts and the review queue, build a pack release from approved
   revisions, and **release** it (role `publisher`: activate, move the current pointer, retire the
   previous release — one audited action; rollback is one audited action too).
   End-to-end test: two synthetic staff take a synthetic lesson from blank to visible in the learner
   `GET /v1/catalog` and `GET /v1/lessons/{id}` **without any direct SQL**, and a learner then
   syncs an answer against it. Negative tests: author approving own work, editor releasing,
   learner on every route, editing after approval, unreviewed revision in a pack.
2. **Role administration**: `admin` grants/revokes roles through an audited function; nobody can
   grant themselves a role; last-admin lockout considered.
3. **Worker** (`services/worker`, Python package `edu_worker`): `ops.enqueue_job` (idempotency key),
   `ops.claim_jobs(worker_id, kinds, limit, lease_seconds)` with `FOR UPDATE SKIP LOCKED`,
   `ops.heartbeat_job`, `ops.complete_job`, `ops.fail_job` (bounded exponential backoff, `dead`
   after `max_attempts`, `error_class` only — no payload dumps), expired-lease reclaim. A small
   runner with a handler registry, bounded concurrency, graceful shutdown, and a `noop`/test handler.
   Tests (Platform-03 gate): two concurrent claimers never lease the same job; **a killed worker's
   job is retried exactly once**; dead-letter after max attempts; idempotent enqueue; `edu_api`
   cannot touch jobs. No schedules are installed, nothing runs unattended after the tests.
4. **MFA**: write the design (how `aal2` would be required for staff tokens, enrolment, recovery) in
   the lane doc. Do not implement or claim it.
