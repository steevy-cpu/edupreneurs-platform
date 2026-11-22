# Mon Edupreneur 2.0 — Database Schema v0.2

**Status:** Architecture + runnable SQL *draft* for review and staging execution only.  
**Date:** November 21, 2026  
**Database:** PostgreSQL in an **Edupreneur-owned Supabase project**; Supabase Auth manages `auth.users`.  
**Backend:** FastAPI is the only application-data API. The `app` PostgreSQL schema is **private**, and is **not** included in Supabase Data API's exposed schemas.  
**Scope:** Fresh-start accounts and a first vertical slice (catalog → downloaded lesson → offline practice → sync). No schema migration from Lovable is assumed.

## 1. Decision summary

- **22 application tables in one private `app` schema**, grouped by domain; no premature microservices.
- **No tables for payments, multiplayer, social, chat, or arbitrary AI conversations yet.** Add them when there is a validated feature contract.
- Course metadata can be revised, but **approved lesson revisions, questions in those revisions, and finalized pack payloads cannot be changed in place**.
- **French (`fr`) and Haitian Creole (`ht`) are independent lesson revisions**. They can use the same stable `lesson_id` without forcing translations to share revision numbers or publication dates.
- **Lessons are structured blocks (`jsonb`)**, not arbitrary HTML. `question_revisions` has machine-readable prompts, response schema, answer key and reviewed explanation. Pydantic/JSON-Schema validation is mandatory in addition to basic PostgreSQL JSON shape checks.
- **Study on native is local-first.** The server accepts eligible practice answers, retains durable receipts, and emits a per-learner ordered change feed. No official high-stakes grades from offline answer keys.
- **Read-only student Jude** and **draft-only lesson-generation agents** will use future restricted services, not unrestricted SQL agents.

## 2. Tables and fields (source of truth: 0001_core_schema.sql)

| # | Domain | Table | Key fields and rule |
|---:|---|---|---|
| 1 | Identity | `learner_profiles` | `user_id` PK/FK to `auth.users`, `grade_id`, `preferred_locale`, optional `display_name` |
| 2 | Identity | `staff_roles` | PK `(user_id, role)`; editor, reviewer, publisher, admin; active flag |
| 3 | Curriculum | `grades` | `id` PK, unique `code`, unique `sort_order`, localized `labels` |
| 4 | Curriculum | `subjects` | `id` PK, unique `slug`, localized `labels` |
| 5 | Curriculum | `courses` | `id` PK, FK `grade_id`, FK `subject_id`, `slug`, `titles`, `visibility`; unique grade+subject+slug |
| 6 | Curriculum | `units` | `id` PK, `course_id` FK, unique course+`slug` and course+`position` |
| 7 | Curriculum | `lessons` | `id` PK, `unit_id` FK, unique unit+`slug` and unit+`position` |
| 8 | Curriculum | `lesson_revisions` | `id` PK, `lesson_id` FK, `revision`, `locale`, `title`, `blocks`, `status`, authors/approval; unique lesson+locale+revision |
| 9 | Curriculum | `question_revisions` | `id` PK, `lesson_revision_id` FK, stable `question_key`, `position`, `kind`, `prompt`, `response_spec`, `answer_key`, `explanation` |
| 10 | Publication | `content_sources` | `id` PK, title, URI, `rights_status`, verification notes/time |
| 11 | Publication | `lesson_revision_sources` | PK `(lesson_revision_id, source_id)`; many-to-many source provenance |
| 12 | Publication | `editorial_reviews` | `id` PK, lesson revision, reviewer, verdict, notes, time; append-only |
| 13 | Publication | `pack_releases` | `id` PK, unique pack+locale+revision; manifest object path/hash/bytes, lifecycle |
| 14 | Publication | `pack_items` | PK `(pack_release_id, lesson_revision_id)`; unique release+position |
| 15 | Publication | `pack_current` | PK `(pack_key, locale)` → active release pointer, matching composite FK |
| 16 | Learning | `lesson_progress` | PK `(learner_id, lesson_id)`; completion, reading position, last content revision, change version |
| 17 | Learning | `practice_attempts` | `id` PK; unique `(learner_id, op_id)`; question revision, response, score, scorer version; append-only |
| 18 | Learning | `account_sync_state` | `learner_id` PK, monotonic per-learner `current_version` |
| 19 | Learning | `sync_receipts` | PK `(learner_id, op_id)`; SHA-256 request digest, canonical result; append-only |
| 20 | Learning | `account_change_feed` | PK `(learner_id, version)`; entity, delta/tombstone, created time; append-only |
| 21 | Operations | `background_jobs` | `id` PK; kind, payload, idempotency key, queue status, attempt limit, scheduling and lease fields |
| 22 | Operations | `audit_events` | `id` PK; actor/action/outcome/target and minimal metadata; append-only |

**IDs:** UUIDs throughout. `auth.users` remains owned by Supabase Auth and is **not** counted in the 22 application tables. `gen_random_uuid()` creates most server IDs. Offline clients create immutable UUID `op_id` values for retry safety.

**Content locale strategy:** `grades.labels`, `subjects.labels`, `courses.titles` and `units.titles` are small, validated translation maps. The actual lesson body is separately versioned per locale; this avoids French updates silently overwriting Haitian Creole content.

**Question identity:** `question_key` identifies the same conceptual question inside successive revisions of the same lesson. Each revision has its own UUID. Attempt history records the exact `question_revision_id`, never merely a mutable question key.

## 3. Main relationships

- `auth.users` 1→0..1 `learner_profiles`, and 1→0..many `staff_roles`.
- `grades` 1→many `courses` and `subjects` 1→many `courses`.
- `courses` 1→many `units` → many `lessons` → many locale-specific `lesson_revisions` → many `question_revisions`.
- `lesson_revisions` many↔many `content_sources` through `lesson_revision_sources`.
- `lesson_revisions` 1→many `editorial_reviews`; only a qualified reviewer can approve, and source rights must be cleared.
- `pack_releases` many↔many approved `lesson_revisions` via `pack_items`; `pack_current` points to exactly one active release for each `(pack_key,locale)`.
- `learner_profiles` 1→many `practice_attempts`, `sync_receipts`, `account_change_feed` and `lesson_progress`.
- `practice_attempts` reference exact `question_revision_id` and matching `lesson_revision_id` through a composite FK (prevents cross-lesson mismatches).

## 4. Essential integrity and publication rules

### Content workflow

1. Educator or agent creates a **draft** lesson revision and its questions.
2. References to `content_sources` identify what can legally be reused. All referenced sources must be marked `cleared` before approval.
3. An **active editor-independent reviewer** records an approval review. The revising author cannot approve their own draft. A review freezes that exact draft and its questions: subsequent corrections require a new revision and new review. The API checks staff roles; the database approval trigger rechecks the **latest verdict**, reviewer status and source rights.
4. The lesson revision changes to `approved`. Its fields and attached questions are now immutable.
5. The pack worker creates a release in `building`, attaches *approved, locale-matching* lesson revisions, uploads a versioned immutable object to R2 and records the exact SHA-256 and byte count.
6. Publishing changes release state to `ready` and then `active`, updating `pack_current` in a single PostgreSQL transaction after the object has been validated. The previous release stays available for rollback or offline readers unless explicitly revoked.
7. A rights withdrawal/revocation is a dedicated audited flow, not an in-place edit of downloaded objects.

**Important deferred invariant:** The publisher must verify pack manifest cryptographic authenticity/signature and object existence in R2 before switching the DB pointer; SQL can check metadata but cannot prove R2 object bytes exist.

### Learning / sync

- A mobile action is saved locally with `op_id` before attempting network upload.
- FastAPI uses the **verified** Auth token's subject for `learner_id`; it must not trust a user ID in the request JSON.
- In one PostgreSQL transaction: check duplicate receipt/attempt; validate question/version access and operation payload; record canonical attempt; update progress if needed; increment the per-learner change counter; insert the account feed item; insert the durable receipt; commit.
- The unique `(learner_id, op_id)` key plus SHA-256 digest makes retries safe. Same ID+same payload returns the old result. Same ID+different payload is a `409 Conflict`.
- A lost server response triggers retry with the *same* `op_id`. Never mark an event synced until ACK arrives.
- A pull cursor is `(account scope, version)` and never a bare global Postgres sequence. `next_change_version()` updates the account state row transactionally to preserve per-account commit order.
- The first release supports ordinary practice, lesson completion and read positions. More conflict policies must be defined before bookmarks, collaborative features or paid offline access.
- Receipt retention must exceed the supported offline retry window. Proposed **keep receipts until an explicit retention/deletion policy exists**; the append-only attempt table also keeps permanent operation uniqueness for practice attempts.

## 5. Security model

1. **Private DB schema** `app`; **never** list it in Supabase Data API's exposed schemas. The React Native client uses Supabase for Auth only, and FastAPI for application data.
2. All 22 tables have RLS **enabled**. Migration `0001` denies access by default. Migration `0002` creates the **non-login, non-BYPASSRLS** `edu_api` privilege group with limited grants and actor-scoped row policies.
3. A **separate database login role** inheriting `edu_api` must be created securely outside source control, with a secret managed by Render. **Do not put a password in SQL migrations or GitHub.** Confirm the chosen Supabase connection/pooling mode supports it in staging.
4. For every user request, FastAPI verifies JWT issuer/audience/signature/expiry and resolves the actor. Inside a PostgreSQL **transaction**, execute `SET LOCAL edu.actor_id = '<verified-id>'` (parameterize safely), and perform only that actor's authorized operations. Clear on transaction end; test pooled connections and account switching.
5. **The DB actor setting is not a replacement for FastAPI authorization**: it is trusted server context, not a client-supplied or independently authenticated database claim. Use parameterized queries, checked inputs, narrow SQL privileges, and additional domain checks for every mutation.
6. Staff approval/publishing, job workers and billing will use **distinct roles and APIs**, not the student API role. Migration `0002` intentionally does **not** grant `edu_api` any editorial, pack-publication, staff-mutation or worker-table write rights.
7. Security-definer **trigger functions** inspect approval and publication state so ordinary application RLS cannot hide rows from the database's integrity checks. The functions have a locked search path and explicit schema-qualified names.
8. Published practice `answer_key` is not a secret once a pack is downloaded; official high-stakes exams must use a separate online assessment contract.
9. Do not store birth dates, precise location, unnecessary school identifiers, model API credentials or full AI chat logs in this MVP schema.

**Operations prerequisite:** Deleting a learner requires an approved deletion procedure that handles progress, attempts, offline tokens and legally retained records *before* deleting their Auth record; foreign keys intentionally restrict accidental cascading deletion.

## 6. Database migration files

- `migrations/0001_core_schema.sql`: 22 tables, PKs/FKs, checks, unique/indexes, immutable triggers, RLS enablement and denied public grants.
- `migrations/0002_api_role_and_policies.sql`: limited API role, grants, user-scoped RLS read/write policies, published-only content reads.
- `tests/schema_introspection.sql`: read-only structural smoke checks for a **staging** database after applying both migrations.

**Supabase CLI integration:** These files use short design names for readability. During implementation, create **timestamped** migration files in `supabase/migrations/` using `supabase migration new`, copy SQL into those files, run `supabase db reset` on a local disposable database, and only then test in an Edupreneur-owned staging project. Do **not** copy changes into production by hand. See [Supabase migrations](https://supabase.com/docs/guides/local-development/database-migrations).

## 7. Testing before Fable marks the schema complete

| Test | Expected result |
|---|---|
| Introspection | Exactly 22 application tables; RLS enabled on all; app schema not exposed via Data API |
| Missing actor identity | No private learner records returned, inserts denied |
| Forged learner ID | Access to another learner's profile/progress/attempts denied |
| Draft visibility | Student role cannot read unapproved lesson/question revisions |
| Reviewer approval | Self-approval or uncleared sources cannot mark revision approved |
| Approved revision | Modifying/deleting approved lesson or its questions raises DB error |
| Pack creation | Mismatched locale/unapproved lesson/empty finalized pack rejected |
| Pack pointer | Pointer to a non-active or different locale release rejected |
| Offline duplicate | Same `(learner_id, op_id)` and payload returns the exact prior result, one attempt |
| Same op, different body | 409 conflict, no extra attempt or reward |
| ACK lost after commit | Retry gets prior receipt and does not duplicate attempt/feed entry |
| Two-device concurrent sync | Ordered per-account feed; no skipped committed version |
| Actor isolation after pooled connection reused | No cross-user data leakage |
| Lesson change after completion | Historical attempt still references original immutable question revision |
| Recovery | Backup restore includes DB state and independently recovered R2 assets |

**Current validation status:** The files were authored and structurally checked in this chat. **No PostgreSQL instance or Supabase project has been used to apply or integration-test them yet.** They must pass `supabase db reset`, connection-role validation and the above security tests before being considered ready to deploy.

## 8. Feature extensions (NOT tables in v0.2)

- **Jude:** `jude_sessions`, bounded tool audit, per-cohort request/usage budgets, RAG index metadata and learner consent policy, added after privacy and tutoring evaluation.
- **Agentic curriculum:** `generation_runs`, `generation_artifacts`, step checkpoints, model configurations, review assignments. Start with `background_jobs` as generic durable transport; agents only produce drafts.
- **Business:** `payment_orders`, provider callbacks, `entitlements`, verified refunds and store-billing reconciliation (separate payments architecture and storefront gate).
- **Gamification:** `xp_ledger`, `achievements`, `review_schedules`, `streak_records`. Never accept a mobile-generated authoritative XP value.
- **School rollout:** `organizations`, `memberships`, classrooms, teacher assignments and tenant-scoped authorization — not yet needed for the 65-student pilot.
- **Social and real-time games:** separate moderation/reporting schema and network-performance gates.

## 9. Decisions to confirm before locking v1

- First curriculum fixture: **9AF Mathematics**, with `fr` and `ht` as separate checked translations (suggested, not a confirmed production content choice).
- Is the first release completely free, or does it include paid entitlements? The first migration assumes only authorized free practice, no payment state.
- Who are the first staff editors and **independent curriculum reviewers**? Avoid granting all rights to every developer.
- Privacy and retention: how long are practice attempts, audit records, and optional AI interactions kept? Set the policy before production.
- Future official exams require a different secure answer/grading model than downloaded offline practice packs.

## 10. Fable / Claude Code handoff prompt

> You are the database architect for a new Edupreneur-owned Supabase/PostgreSQL project. Review `SCHEMA_DESIGN.md`, `0001_core_schema.sql`, `0002_api_role_and_policies.sql`, and the ERD files. **Do not connect to or change production.** Create timestamped local Supabase migrations, boot a disposable Supabase stack, run all migrations, inspect the final schema, and implement a repeatable automated test suite for foreign keys, RLS actor isolation, approved revision immutability, pack publication, exact-once offline retries and per-learner ordered sync. Do not invent missing billing or Jude tables. If any DDL fails, correct it in a reviewed new draft. Report the exact test commands, executed outputs, limitations, and security risks; do not claim deployment readiness without passing tests. Keep secrets out of source control.
