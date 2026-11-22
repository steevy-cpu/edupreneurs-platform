# FABLE TASK 01 — MON EDUPRENEUR 2.0
## Foundation: PostgreSQL + Supabase Auth + FastAPI + Offline Sync

You are the lead backend engineer, database architect, and security reviewer for Mon Edupreneur 2.0, a new educational platform serving Haitian learners (7AF–NS4) on unreliable networks and older phones.

**This is an implementation assignment. Write and test code, not just a design document.** Explain important decisions in plain English because the founder is learning React Native and backend architecture while working with AI coding agents.

### Source material and starting state

I will provide the archive `Mon-Edupreneur-Database-Schema-v0.2.zip`. Extract it and read **all** of these before editing code:

- `mon-edupreneur-schema-v0.2/SCHEMA_DESIGN.md`
- `mon-edupreneur-schema-v0.2/README.md`
- `mon-edupreneur-schema-v0.2/migrations/0001_core_schema.sql`
- `mon-edupreneur-schema-v0.2/migrations/0002_api_role_and_policies.sql`
- `mon-edupreneur-schema-v0.2/tests/schema_introspection.sql`
- The three editable ERD files in `diagrams/`.

Treat v0.2 as a **reviewable draft**, not as proven SQL or a rigid schema. Its static check reported 22 unique tables, 27 policies, and 14 guards, but **PostgreSQL execution, auth integration, RLS behavior, transaction concurrency, and runtime API security have not been verified**. Correct substantive issues when tests expose them; document each change and its rationale. Keep a copy of the original drafts under `docs/reference/schema-v0.2/` for comparison.

The Lovable website is an unrelated, existing proof of concept. The new backend is a **clean start**. Do not connect to, scrape, alter, or migrate its cloud/database. Do not assume access to its credentials or records. All development data must be synthetic.

### Non-negotiable restrictions

1. **Local-only** for this assignment. Do not connect or link to any remotely hosted Supabase project, Render service, Cloudflare account, production domain, or Apple/Google service. No deployment or DNS changes.
2. Do not run `supabase db reset` with `--linked`, `--remote`, or a remote `--db-url`. Use the local target only. Before any destructive command, identify the target and ensure it is disposable.
3. No hard-coded passwords, JWT secrets, service-role keys, model credentials, student PII, or external API keys. Provide `.env.example`; ignore real `.env` files.
4. No owner/superuser, `service_role`, or `BYPASSRLS` database role in normal student API request handling. The private `app` schema must never be exposed through the Supabase Data API.
5. Never trust `user_id`, `learner_id`, actor settings, or privileges claimed in mobile JSON. Resolve identity from a cryptographically verified access token and authorize every operation server-side.
6. Staff editorial publication, Jude AI, billing, community, games, and actual mobile app implementation are explicitly out of scope. Do not create speculative tables for those future modules.
7. Do not push commits to any remote repository or initiate paid cloud services. Work in a local branch, and prepare a clean handoff for review.
8. If a required CLI, Docker-compatible runtime, or dependency is unavailable, do not claim that tests passed. Implement what you can; report the exact blocker and commands needed to validate it.

### Preferred technology choices

- **Repository:** `mon-edupreneur` monorepo, clear separation between `services/api`, `supabase`, `tests`, and shared contracts. Reserve empty/doc-only spaces for future `apps/student-native`, `apps/lite-web`, `apps/staff-web`, and AI workers; do not scaffold these applications yet.
- **Database and Auth:** Supabase local stack; PostgreSQL, `auth.users`, default-deny RLS; private `app` schema; timestamped Supabase migrations.
- **API:** Python FastAPI, Pydantic v2, SQLAlchemy 2 async + asyncpg (or a rigorously justified equivalent), dependency injection, explicit transaction boundaries.
- **Testing:** pgTAP via `supabase test db` for database structure/policies and pytest for application/integration/concurrency testing. Keep tool versions reproducible.
- **Content:** JSON schema-validated, versioned French (`fr`) and Haitian Creole (`ht`) learning material. Only synthetic, original sample lessons and questions.

## WORKSTREAM A — Repository and reproducible local environment

1. Inspect supplied files; identify incomplete or contradictory requirements and any critical SQL vulnerabilities before implementation.
2. Initialize a clean repository/project layout with an informative `README.md`, `.gitignore`, `.env.example`, `Makefile` or equivalent task runner, `pyproject.toml`, and `supabase/config.toml`.
3. Convert the two v0.2 SQL drafts into **ordered, timestamped migration files** under `supabase/migrations/`. Do not maintain conflicting schema sources of truth.
4. Configure local-only Supabase Auth and an isolated local PostgreSQL instance. Write deterministic **synthetic** seed data: two students, an editor, an independent reviewer, 9AF Mathematics, one original lesson with independent `fr` and `ht` revisions, and a five-question multiple-choice practice fixture. If reviewer/publisher permissions are not yet implemented as services, seed only what's necessary for direct database integrity tests using a dedicated test fixture role.
5. Ensure the documented setup can be run from a clean clone. No developer should need a pre-existing cloud project, copied secrets, or manual production dashboard edits.

## WORKSTREAM B — Database correctness and security audit

Apply migrations to a fresh local database and verify actual execution. Fix faults with reviewed migrations or revised draft migrations as appropriate (this is an unshipped new project). Explicitly evaluate:

- All 22 intended domain tables, PKs, FKs, unique constraints, indexes and RLS settings; document any count changes if fixing a design issue requires them.
- `auth.users` integration and account-delete restrictions.
- Least-privilege `edu_api` role and whether its login/connection model works with Supabase and the chosen pooler; if not, present and implement a secure alternative **without turning off authorization**.
- `SET LOCAL` / transaction-local actor context and connection reuse. Remember that a Postgres custom session variable is not cryptographic proof of identity; FastAPI must be the sole trusted setter after JWT verification.
- Grants plus RLS policy behavior for anonymous, Student A, Student B, and staff; check both denied reads and denied writes.
- `SECURITY DEFINER` trigger ownership, fixed `search_path`, function execution grants, and any privilege escalation paths.
- Published versus draft lesson visibility; independent editorial approval; frozen reviewed question contents and source attribution; cleared content rights; pack/revision locale mismatches; pack lifecycle and active-pointer integrity.
- Whether a normal student-facing connection could forge scores, final progress, sync receipts, authoritative audit events or change feed entries. Prefer an explicit server-controlled atomic mutation boundary over trusting arbitrary writes from client-facing code.
- Any subtle RLS policy recursion, bypass through joined tables, duplicate role rows, concurrent update, or SQL privilege problems.

**Security rule:** Where a source-draft policy or grant contradicts safe API operations, fix the implementation and document the deviation. Do not preserve insecurity merely to keep the original count of 27 policies.

## WORKSTREAM C — Working FastAPI vertical slice

Implement a small real backend, not stub-only endpoints:

- `GET /health` — process health (no secrets).
- `GET /ready` — database readiness; safely report unavailable dependencies.
- `GET /v1/me` — verified student's own profile.
- `GET /v1/catalog?locale=fr|ht` — published grade/subject/course/unit/lesson metadata in a compact response.
- `GET /v1/lessons/{lesson_id}?locale=fr|ht` — a learner-authorized, approved and published lesson revision with question metadata appropriate for **offline practice only**; never expose unapproved drafts.
- `POST /v1/sync/push` — accept a bounded batch of eligible offline practice answers and lesson completion events, persisting canonical results and per-operation responses.
- `GET /v1/sync/pull?cursor=...` — read a page of server-authoritative per-account changes, with a safe opaque cursor and documented reset behavior.

Use route versioning under `/v1` except the health checks. Generate `/openapi.json` and keep error response schemas consistent. Use parameterized SQL through the ORM/driver; no dynamically concatenated user input in SQL.

Use JWT validation that checks expected issuer, audience, signature, expiry and token type as appropriate for the configured local Supabase Auth signing method. Retrieve signing keys from trusted configuration/JWKS with sensible caching/rotation handling; never decode an unverified token as authentication. Test failure modes (missing, expired, altered, wrong issuer, wrong audience). No secret-bearing logs.

For every authenticated operation, create a fresh DB transaction context, set the actor from the verified token *transaction-locally*, and verify rollback or exit cleans it up. Do not leak a previous learner's identity through pooled connections.

### Offline synchronization contract — required behavior

- Client-generated UUID `op_id` persists across retries. The learner ID comes from the verified token, not a request field.
- Initial eligible events: `practice_answer` (for the synthetic multiple-choice fixture only) and `lesson_completed`. Define and validate schemas; reject unsupported event kinds cleanly.
- Normalize/canonicalize payloads **before** hashing so the same logical operation has a stable digest; document the canonicalization rule and version.
- Enforce small batch limits (starting target max 50 operations / about 20 KB compressed on the wire); validate request size and per-field caps server-side.
- In **one database transaction**, ensure operation deduplication, validated answer scoring on the server, canonical progress, ordered per-learner change version, receipt and feed update. Prevent race conditions for two devices or parallel identical retries.
- Repeating an `op_id` with identical canonical content returns the previous receipt without creating another attempt, score, or change event.
- Reusing `op_id` with a different payload returns a conflict (HTTP 409 or per-operation conflict with unambiguous semantics) and makes no extra mutation.
- Simulate the server committing and the ACK disappearing. Retry must be exact-once in canonical state.
- Do not use client wall-clock timestamps to decide authoritative event order or score; persist them only as untrusted display metadata if needed.
- Pull must use commit-consistent **per-learner** ordering, preserve tombstone semantics, and not leak progress from another account.
- Use a genuine sync algorithm and tests. Do not return fake success, and do not silently drop rejected or pending operations.

## WORKSTREAM D — Automated tests and CI

Implement both positive and negative test cases. At minimum:

1. Clean local DB reset and migration replay succeed.
2. The intended tables, constraints, indexes, private schema exposure settings and RLS protections exist.
3. Student A cannot read/write Student B's profile, attempts, progress, receipts or feed; anonymous cannot reach private records.
4. Unapproved, rejected and unpublished revisions cannot be read through student API or role.
5. Invalid self-review, missing reviewer role, uncleared rights, changed approved content, invalid pack pointer and incorrect locale are rejected.
6. The same answer sent twice (including 20 concurrent identical retries) creates one canonical attempt and one corresponding progress/change event.
7. Same op ID + different body conflicts without side effects.
8. Forced API failure after database commit but before HTTP response, followed by retry, remains idempotent.
9. Two students and two simulated devices can sync concurrently without skipped per-user change versions or cross-account leakage.
10. Connection-pool reuse/account switch doesn't retain the wrong transaction actor.
11. Bad JWT signature, expired token, incorrect issuer/audience, missing token and malformed inputs are rejected.
12. Completing a lesson against a prior approved revision still points to that revision after a new one is published.
13. Empty/invalid offline batch, unknown lesson, unsupported answer type, excessive payload and DB outage have clear error behavior.

Add a GitHub Actions workflow that can run local database and Python tests on pull requests. CI must not require a paid cloud project or production credentials. Add lint/format/type checks for Python; keep CI execution time reasonable.

Prefer `supabase start`, `supabase db reset`, `supabase test db`, and `pytest` with real local DB integration tests. Mock only external boundaries, not the database semantics you're claiming to prove.

## WORKSTREAM E — Documentation and handoff

Provide:

- `README.md`: prerequisites for macOS + Linux, setup, local start/stop, db reset, seed, API launch, tests, troubleshooting.
- `docs/ARCHITECTURE.md`: component trust boundaries and why PostgreSQL/RLS/FastAPI responsibilities are separated.
- `docs/SCHEMA_CHANGELOG.md`: source v0.2 assumptions, discovered defects, corrections and their justification.
- `docs/API_CONTRACT.md`: endpoint request/response examples, auth, errors, cursor and sync behavior.
- `docs/SECURITY.md`: role permissions, actor-context lifecycle, threat cases, secrets handling and unresolved vulnerabilities.
- `docs/TEST_REPORT.md`: exact commands actually executed, observed results and tests that could not run. Do not write "PASS" without evidence.
- `docs/NEXT_STEPS.md`: what is ready for mobile integration, what remains before cloud deployment, and what should be deferred to Jude / curriculum agents.

### Mandatory completion gate

This assignment is complete only if:

- A fresh local clone can recreate the DB from migrations with no manual schema editing.
- Tests demonstrate that students cannot access one another's data or drafts.
- The API authenticates real local Supabase-issued tokens and reads authorized lesson data.
- An offline answer can be submitted, retried without duplication, and pulled back with correct account scope and order.
- No third-party production resources were accessed or modified; no secrets were committed.
- You can show the actual commands and test output proving the above.

If any gate is not met, report **PARTIAL** or **BLOCKED**, including exact failure and a safe next action. Never call it production-ready just because the code compiles.

### Final response format

1. **What you built**, in plain English.
2. **Repository tree** and concise explanation of the main files.
3. **Differences from schema v0.2**, with security or correctness reasons.
4. **Commands run and observed test outcomes**, with counts (pass/fail/skip).
5. **A sample verified local API call and result** using synthetic test data, with tokens redacted.
6. **Risks, blockers and deployment prerequisites**.
7. **Suggested next engineering task** (mobile client integration, not full Jude implementation yet).

Start by inspecting the attached bundle and environment. Then implement in order, testing after each workstream. Do not ask the founder for decisions already fixed here; if a required credential/cloud resource is unavailable, stay local and document the constraint.
