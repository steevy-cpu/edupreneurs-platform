# Mon Edupreneur 2.0 — Database and Backend Blueprint

**Status:** Proposed architecture for design review, not implemented  
**Version:** 0.1 — 21 November 2026  
**Scope:** New, Edupreneur-owned backend and database. Lovable is proof of concept, **not** the source of truth for the new production system.  
**Primary constraints:** Older/low-memory phones; unreliable, costly Haitian mobile internet; students who may share devices; French and Haitian Creole; AI-assisted content with educator approval.

## 1. Architecture decisions

| ID | Decision | Rationale / limits |
|---|---|---|
| ADR-001 | A single, modular Python FastAPI backend and one PostgreSQL database initially | Easier deployment, transactions, consistent policy and troubleshooting at current scale |
| ADR-002 | Supabase **under the Edupreneur organization** manages PostgreSQL and Auth | Ownership of project, schema, credentials, backups and migrations; avoid hosting Auth ourselves |
| ADR-003 | Render runs API and a separately scaling job worker; Cloudflare R2 stores immutable lesson packs | Separate interactive requests from long AI jobs; allow caching at distribution edge |
| ADR-004 | Mobile calls FastAPI for **business** APIs; it may call Supabase Auth for login / refresh only | Domain-specific authorization and a stable versioned interface without exposing table APIs as product contracts |
| ADR-005 | Native is offline-first: SQLite local user progress + transactional outbox; separate file storage for packs | Reliable work when offline; safe retries and small app downloads |
| ADR-006 | Student Jude receives approved read-only tools by default; editor agents write drafts only | Minimize risk of accidental modifications, cross-account leaks and unreviewed publications |
| ADR-007 | Published lesson/question revisions and pack releases are immutable | Stable attribution of attempts and downloadable content; avoid changing historical answers |
| ADR-008 | Start from a fresh database and new account model | No assumed automatic migration; if older accounts are offered a voluntary migration later, design and verify it separately |
| ADR-009 | No hard dependency on AI, live presence, payments or notifications for core lessons and offline practice | Educating students remains possible during provider and network outages |

## 2. Execution and trust boundaries

### Student native app (React Native)
- **Owns:** screen presentation, local SQLite state, downloaded content files, unsubmitted/offline operations, optional on-device grading of approved practice content.
- **Can request:** published catalog/packs, own progress, quiz attempt sync, own entitlement status and approved Jude responses.
- **Cannot do:** direct privileged SQL queries; change staff roles, published curriculum, billing status or authoritative online grade records.
- **Tokens:** platform Keychain/Keystore through a compatible secure-storage implementation; no service credentials in mobile bundles.

### Edupreneur Lite (older mobile browsers)
- **Owns:** lightweight HTML interactions; optional progressive enhancements on tested browsers.
- **Can request:** accessible public lesson pages; authenticated functions on security-supported browsers.
- **Cannot promise:** robust offline sync on ancient browsers; authenticated service on insecure/TLS-incompatible devices.

### API (FastAPI on Render)
- **Owns:** authentication verification, authorization, input/output schemas, request limits, content access, progress/sync transactions, AI tool mediation, entitlements and staff operations.
- **Execution:** one deployed service, organized into modules (`identity`, `catalog`, `learning`, `sync`, `editorial`, `jude`, `billing`, `operations`).
- **Identity:** validate Supabase-signed JWTs against issuer/JWKS, allowed algorithm, audience, subject, expiry and revocation-sensitive checks. Confirm object ownership or staff permission on each operation.
- **Database access:** use least-privileged Postgres roles; don't use service-role or owner connections for normal student requests. Apply RLS where appropriate as defense in depth, plus explicit API authorization. If implementing per-request RLS identity via SQL settings, do it with transaction-scoped context and test that pooled connections cannot leak identity between requests.

### PostgreSQL (Supabase-owned by Edupreneur)
- **Owns:** canonical accounts/profiles, curriculum metadata and revisions, attempts, progress, synchronization receipts, reviewed content, roles, jobs, and billing entitlements.
- **Does not own:** large images/videos/PDF bytes or native offline file blobs.
- **Control:** migrations in GitHub, separately provisioned development/staging/production, encrypted backup and tested restore procedures.

### Cloudflare R2 and CDN
- **Owns:** immutable objects for *published* lesson packs, images/audio/PDFs, and optionally generated files.
- **Privacy rule:** public bucket only for content cleared for public distribution. Premium/private content requires verified, short-lived download authorization and no shared-cache leaks. Private agent draft artifacts stay in restricted storage.
- **Data integrity:** content-addressed or versioned object path, declared byte size/hash, atomic activation by reader and no in-place replacement of published files.

### Worker processes (Render, separate from API service)
- **Owns:** long-running content generation, ingestion, validation, pack builds, retryable delivery, payment reconciliation and bounded AI jobs.
- **Queue:** start with Postgres-backed durable jobs; use claim/lease/retry/dead-letter state and idempotent results. Split into a dedicated queue service only once measured need warrants it.
- **AI provider calls:** server-side only; avoid handling student PII without established purpose, permissions and safeguards.

## 3. Recommended logical DB domains

PostgreSQL is one physical database. Use private application schemas (or one private `app` schema with module names) so internal tables are **not** automatically exposed via PostgREST. Do not create a separate microservice database for each domain. `auth.users` is managed by Supabase Auth; new tables refer to its stable UUID.

### Core foundation / first vertical slice

| Domain | Proposed table | Most important columns / invariants |
|---|---|---|
| Identity | `learner_profiles` | `user_id UUID PK` references Auth subject; `grade_id`, `preferred_locale` (fr/ht), `display_name` optional; minimal PII |
| Identity | `staff_roles` | `(user_id, role)` unique; only admin-managed grants; explicit active/inactive status |
| Curriculum | `grades` | `id`, `code` unique (`7AF`, `8AF`, `9AF`, `NS1`…`NS4`), `sort_order` |
| Curriculum | `subjects` | `id`, `slug` unique, localized display titles |
| Curriculum | `courses` | `id`, `grade_id`, `subject_id`, publish state; natural uniqueness decided with localization |
| Curriculum | `units` | `id`, `course_id`, `position`, localized title |
| Curriculum | `lessons` | `id`, `unit_id`, `position`, stable logical identity |
| Curriculum | `lesson_revisions` | `id`, `lesson_id`, `revision`, `locale`, structured `blocks JSONB`, `status`, `created_by`; unique `(lesson_id, revision, locale)` |
| Assessment | `questions` | `id`, `lesson_id` or topic owner, stable logical identity |
| Assessment | `question_revisions` | `id`, `question_id`, `revision`, `locale`, question data and vetted scoring/explanation; unique `(question_id, revision, locale)` |
| Assessment | `practice_sets` | `id`, `course_id/lesson_id`, type=`practice`, title, locale, published revision identifier |
| Assessment | `practice_items` | `(set_id, position)` unique; fixed `question_revision_id` and scoring weight |
| Publication | `content_sources` | `id`, `source_title`, `url/reference`, rights/license/usage permission and verification metadata |
| Publication | `editorial_reviews` | `id`, subject revision, reviewer, verdict, timestamp, notes stored privately |
| Publication | `pack_releases` | `id`, `pack_key`, `revision`, locale, `manifest_object_key`, checksum, size, `released_at`, state; never mutate released contents |
| Publication | `pack_items` | `pack_release_id`, immutable lesson/question revision IDs included in release |
| Learning | `lesson_progress` | `(learner_id, lesson_id)` unique; `completed_at`, last read position, revision provenance, server update version |
| Learning | `practice_attempts` | `id UUID PK`, `learner_id`, `client_op_id UUID`, `practice_set_id`, immutable revision refs, submitted answers, score/provenance, server acceptance; unique `(learner_id, client_op_id)` |
| Sync | `sync_receipts` | `(learner_id, op_id)` unique; request body digest + canonical stored outcome; duplicate same body returns original result |
| Sync | `account_sync_state` | `learner_id PK`, `current_version BIGINT`; increment inside locked transaction, not with non-commit-ordered global sequence |
| Sync | `account_change_feed` | `(learner_id, version)` unique; event kind, entity, delta/tombstone and server transaction provenance |
| Operations | `background_jobs` | `id`, kind, payload reference, status, attempts, next retry, lease owner/expiration, idempotency key, error classification |
| Operations | `audit_events` | actor, action, target, timestamp, result; no raw passwords/tokens/student prompt dumps |

**Important refinement:** Published lesson and question revisions must not be updated in place. Drafts may change until approved; publication creates immutable revision records and reproducible pack manifests. Ensure references to source rights and reviewer sign-off before release.

### Later (create only when those features are scoped)
- Personalization: `review_schedules`, `mastery_estimates`, `achievements`, `reward_ledger` (derive XP/streaks on server; don't trust client-calculated authoritative points).
- School tenancy: `organizations`, `memberships`, `classes`, `teacher_assignments` (only if school rollout actually requires them; tenant scope on every relevant query).
- Jude: `jude_threads`, `jude_messages` (with strict retention/consent; consider ephemeral by default), `ai_runs`, `tool_audits`, `model_usage`.
- Generation: `generation_jobs`, `generation_artifacts`, `generation_checks`, `publish_approvals` (separate from authored lesson tables and from general job queue).
- Commerce: `plans`, `payment_orders`, `provider_events`, `entitlements`, `refund_records`; never grant paid access from client-provided 'paid' flags.
- Privacy: `consent_records`, `data_deletion_requests`, retention policies, export requests. Add the applicable minimal data-rights workflows before collecting or processing sensitive learner data.

## 4. Canonical relationships (simplified)

```text
auth.users (Supabase-owned)
  ├─ 1:1 learner_profiles
  ├─ 0:N staff_roles
  ├─ 1:N practice_attempts
  ├─ 0:N lesson_progress
  ├─ 0:N sync_receipts
  └─ 0:N account_change_feed

grades ── courses ── units ── lessons ── lesson_revisions
subjects ─┘                      └───── questions ── question_revisions
practice_sets ── practice_items ── question_revisions
pack_releases ── pack_items ── immutable lesson/question revisions
content_sources ── attribution / rights for content revisions
```

Avoid storing every question as a single giant lesson HTML blob. Use structured JSON blocks and independent question revisions so one-question-at-a-time learning, accessibility, local scoring and future exercises remain possible.

## 5. API modules, endpoints and authority

All business API routes are under `/v1`; versioned OpenAPI schema drives TypeScript client generation. Use compact payloads, validation, pagination, ETag/304 and rate limiting as appropriate.

| Module | MVP endpoints | Who may call | Who may change canonical state |
|---|---|---|---|
| Identity | `GET /v1/me`, `PATCH /v1/me/preferences`, `POST /v1/me/deletion-request` | Signed-in learner | Learner only for allowed preferences; server handles account deletion workflow |
| Catalog | `GET /v1/bootstrap`, `/v1/catalog`, `/v1/courses/{id}`, `/v1/lessons/{id}` | Public for cleared published content; authenticated for gated content | Staff publishing workflow only |
| Packs | `GET /v1/packs/{pack_key}/manifest`, download grants | Public or entitled learner | Publisher sets available immutable release; no student writes |
| Learning | `POST /v1/sync/push`, `GET /v1/sync/pull?cursor=...`, `GET /v1/me/progress` | Signed-in learner | Server validates and commits learner's eligible operation |
| Jude (later) | `POST /v1/jude/requests` | Eligible learner with permissions | Jude may read authorized data; tools cannot modify billing/roles/publications |
| Editorial (later) | `POST /v1/staff/generation-jobs`, `/v1/staff/reviews`, `/v1/staff/publish` | Explicit staff roles | Editor drafts; reviewer signs off; authorized publisher releases |
| Commerce (later) | `GET /v1/entitlements`, `/v1/billing/*`, provider webhooks | Learner for own status; verified provider endpoints | Server validates provider transaction; never client-authoritative |

**Auth:** Student signs in through Edupreneur-owned Supabase Auth. API verifies JWT signature via JWKS, allowed algorithms, issuer, audience, expiry and subject; it then checks app permissions before database mutations. Staff must use stronger role checks and MFA. Do not assume that a browser route guard or possession of a user ID proves authorization.

## 6. Offline synchronization contract (design priority)

1. Download an immutable manifest and objects into temporary files. Check content permissions, file size, SHA-256 and schema; activate a complete pack atomically and retain last known-good pack.
2. An eligible action (e.g., answer submitted) writes a `practice_attempt` projection **and** an outbox operation in one SQLite transaction. Assign a random stable `op_id` for retries.
3. On verified connectivity, `POST /v1/sync/push` sends a small batch (initial target at most 50 ops / 20 KB compressed), with the account identity taken from auth token, **never** from the request body.
4. Server rechecks authorization, validates payload and immutable content revision, then within **one PostgreSQL transaction** records a unique `(learner_id, op_id)` receipt, persists the canonical attempt, updates progress and appends an account change-feed item. Existing ID + identical body returns prior result; existing ID + different body is a conflict.
5. If a server commit succeeded but the response was lost, mobile retries the **same op ID** until receiving acknowledgment. Never discard an unacknowledged event.
6. `GET /v1/sync/pull?cursor=...` returns account-scoped, commit-ordered changes. SQLite applies changes **and advances its cursor in one transaction**. On expired cursor, fetch a snapshot and preserve unacknowledged local events.
7. Conflicts: attempts append; lesson completion merges monotonically; last reading location is separate; bookmarks need server version checks; paid entitlements are strictly server-authoritative.
8. UI shows distinct states: **Saved on this phone**, **Waiting to sync**, **Synced**, **Needs attention**. Device/account switch stops in-flight operations and protects another learner's data.

**Out of scope for first offline promise:** high-stakes official exam grading, paid purchases, social messages and arbitrary Jude conversations. Offline practice can expose answer keys; do not treat it as a secured exam.

## 7. Jude harness: security and API boundary

- Student request enters `POST /v1/jude/requests` with a minimal prompt, requested course/topic context and optional request ID.
- API checks identity, cohort permissions, limits and rate budgets before invoking Jude.
- Jude chooses from an **allowlist** of typed tools. Tools call application services; never run arbitrary SQL or unrestricted HTTP requests on behalf of the model.
- Initial tools: `search_approved_lessons`, `get_published_lesson`, `get_my_progress`, `get_my_weak_topics`, `recommend_practice`, `explain_practice_question`.
- Tool results enforce the caller's own data scope and return only minimal, needed fields. No staff-role mutation, subscription mutation, draft publication, unreviewed teacher content or other students' data.
- Retrieval must cite an approved source/revision. A model is a tutor, not the source of record for answers, enrollment or grades.
- Disable or limit retention of free-text prompts for minors unless an explicit reviewed policy and appropriate consent require otherwise. Keep cost/event metrics separate from prompt content. Rate limits and kill switch required.
- Streaming and model-provider outage are optional: lessons, practice and sync continue without Jude.

## 8. Agentic lesson production: distinct trust boundary

1. Staff editor starts a generation job for grade + subject + topic + locale + approved source list.
2. Worker performs deterministic **planner → draft writer → exercise builder → factual/format validator → language reviewer** tasks, with typed schemas and explicit retries/checkpoints.
3. All intermediate work is `draft`, stored privately with provenance, generation configuration, source rights and quality checks.
4. An actual authorized educator approves or rejects the lesson/question revision. Model self-review does **not** count as human approval.
5. Pack publisher validates approval and schema, builds and hashes an immutable release, uploads to R2, writes release records and atomically advances the published pointer.
6. On a failed publish, the previous version stays available. Republishing uses a new release ID. Emergency withdrawal is an explicit signed/audited action.
7. Editor-facing workers cannot access raw learner histories by default; use aggregated anonymized gap reports if future personalization requires them.

## 9. Suggested Python repository modules

```text
mon-edupreneur/
  apps/
    student-native/             # React Native; UI + SQLite/outbox
    lite-web/                   # Tiny HTML-first student experience
    staff-web/                  # Editor + review dashboard (after MVP)
  services/
    api/
      app/main.py
      app/core/                   # config, auth verification, errors, rate limiting
      app/modules/identity/
      app/modules/catalog/
      app/modules/learning/
      app/modules/sync/
      app/modules/jude/
      app/modules/editorial/
      app/modules/billing/
      app/db/                     # repositories, transactions, db models
    worker/
      jobs/                       # bounded AI, pack, reconciliation tasks
      pipelines/                  # content workflow stages
  packages/
    contracts/                    # OpenAPI, JSON Schema; generated TS client
    learning-fixtures/            # canonical score / sync test vectors
  infra/
    supabase/migrations/
    render/
    cloudflare/
  tools/
    pack-builder/
  tests/
    api/
    db/
    sync-replay/
    authz/
    device-fixtures/
```

**Contract principle:** API owns canonical Python domain logic and publishes OpenAPI/JSON Schema. Mobile uses generated TypeScript clients and the same test fixtures; don't assume that TypeScript grading functions can be directly imported into Python.

## 10. Security and operational gates

- Separate development, staging and production projects; fake student records only outside production.
- Staff MFA, least-privilege database credentials, audit trails for publish/permissions/billing, secrets managed in hosting environment, no secrets in repositories or mobile bundles.
- RLS on learner-owned tables where practical, plus mandatory application-level authorization. Test cross-account queries and forged IDs.
- Secure auth account recovery under low-bandwidth conditions. Shared-device logout must warn about pending work then purge private local state and tokens in supported flows.
- Age-appropriate privacy and permissions review before capturing student free text, AI tutoring, analytics or community features. Collect grade and language, not unnecessary DOB/location/school identifiers.
- Backups **and restore drills** for PostgreSQL, plus independent R2 object recovery, monitoring of queue age and sync failures.
- Reconnection replay test: app killed before local save; killed after local commit; server accepted but ACK lost; duplicated batches; second device; account switch; expired token; corrupt pack; storage full.
- Complete source/license checks before redistributing original MENFP exams or third-party materials.

## 11. Build order and acceptance gates

**Sprint A — Design and fixtures (no production resources):** Confirm user/account model, grades, locale convention, content hierarchy, schema v0.1, operation types, code ownership, rights policy and approval workflow. Build ERD, OpenAPI skeleton and reproducible fixtures.

**Sprint B — Database and basic API (staging only):** Write reviewed migrations with keys/constraints/indexes and test seed data; integrate auth verification; implement read-only catalog and lesson fetching; test student ID isolation and publication visibility.

**Sprint C — Local learning:** Mobile SQLite + pack download, one French/Creole mathematics lesson and five practice questions. Test oldest supported physical phones, low memory and offline launch.

**Sprint D — Durable sync:** Implement receipt/dedupe/feed/snapshot contract. Test at least 100 controlled replay events and assure no loss or duplicates. Run 400/100 kbps and 128/64 kbps constrained profiles.

**Sprint E — Staff review and publishing:** Read-only preview → draft/review → authenticated publish → immutable pack; check rollback. Then add Jude read-only tools in an isolated pilot; full generation and billing after separate approval.

### Must decide before code generation
1. Initial grade/subject and target language(s) for the pilot; propose 9AF Mathematics with French and Haitian Creole labels if content is available.
2. Whether existing prototype accounts are explicitly **not** migrated; prepare user communication and don't assume users will keep their old progress.
3. Product model for release 1: free sample packs vs protected paid packs (store policies and offline leases deferred).
4. Whether staff users and students use the same Auth provider with database roles (recommended initially), and who holds security/curriculum publication approvals.
5. Data retention, consent and child privacy gates for Jude messages and analytics.

## 12. Fable task brief — design review only

> Act as a senior PostgreSQL, FastAPI and offline-first React Native architect. Read this architecture blueprint and the earlier Mon Edupreneur mobile report. **Do not implement anything or connect to production.** Review table ownership, relationships, immutability, `auth.users` integration, least-privilege/RLS, sync ledger semantics, AI tool authorization and publisher workflow. Return (1) ERD, (2) recommended column types/indexes/uniques and FK action rules, (3) API OpenAPI 3.1 draft including error states, (4) database migration plan in small stages, (5) threat model and test matrix, and (6) unresolved architecture decisions. Explicitly flag unsafe designs rather than silently changing assumptions. Avoid unnecessary tables and dependencies. Treat privacy and offline correctness as release blockers.

## External references (verified 21 Nov 2026)
- Supabase JWT verification / JWKS: https://supabase.com/docs/guides/auth/jwts
- Supabase RLS / bypass credentials: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase database migrations: https://supabase.com/docs/guides/deployment/database-migrations
- FastAPI modular applications: https://fastapi.tiangolo.com/tutorial/bigger-applications/
- Cloudflare R2 public bucket and custom domain model: https://developers.cloudflare.com/r2/buckets/public-buckets/
