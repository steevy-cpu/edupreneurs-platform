# Lane STAFF — B1: shared platform interface

Status: **B1 and B2 (editorial workflow, role administration, worker leasing) delivered and tested on
the lane's local stack only.** Nothing here is deployed, linked to a hosted project or merged into
`main`. A second factor for staff is **designed below and not implemented**.

## What exists after B1

| Piece | Where |
|---|---|
| Group roles `edu_staff`, `edu_worker`; schemas `ops`, `staff`; 7 functions | `supabase/migrations/20261124010000_platform_roles_ops_staff.sql` |
| Login roles `edu_staff_login`, `edu_worker_login` (local, random passwords in `.env`) | `scripts/local_stack.py` (`env`, `provision`) |
| Staff pool, `require_staff`, `StaffDb` | `services/api/src/edu_api/staff/` |
| `GET /v1/staff/me` | `services/api/src/edu_api/routers/staff.py` |
| Fixtures and helpers for tests | `tests/staff_fixtures.py` |
| Tests | `supabase/tests/100_platform_structure.sql`, `supabase/tests/101_staff_boundary_and_audit.sql`, `tests/integration/test_staff_boundary.py`, `tests/unit/test_staff_settings.py` |

Nothing was created, altered or granted in schema `app`; the four verified migrations, `seed.sql`
and the existing tests are untouched.

## Database interface

```
ops.audit_write(p_action text, p_target_kind text, p_target_id uuid,
                p_outcome text, p_details jsonb DEFAULT '{}') RETURNS uuid      EXECUTE: edu_staff, edu_worker
staff.actor_roles() RETURNS text[]                                              EXECUTE: edu_staff
staff.actor_has_role(VARIADIC p_roles text[]) RETURNS boolean                   EXECUTE: edu_staff
staff.require_role(VARIADIC p_roles text[]) RETURNS uuid                        EXECUTE: edu_staff
internal, EXECUTE granted to nobody:
ops.actor_kind_for(p_role name) RETURNS text
ops.check_audit_details(p_details jsonb) RETURNS void
staff.check_role_names(p_roles text[]) RETURNS void
```

All four callable functions are `SECURITY DEFINER`, owned by `postgres`, `SET search_path = ''`.
`edu_staff` and `edu_worker` have `USAGE` on their schema(s) and **nothing else**: no `USAGE` on
`app`, no table or column privilege anywhere. `edu_api` has nothing in `ops` or `staff`.

### `ops.audit_write`

- `actor_id` is `app.current_actor_id()`; `actor_kind` comes from the session's database login
  (`session_user`): a login using `edu_staff` → `staff`, `edu_worker` → `worker`, `edu_api` → `user`,
  anything else (for example `postgres`) → `system`. Neither can be passed in, and neither `SET ROLE`
  nor a definer function changes `session_user`. A definer function of another schema calls
  `ops.audit_write` as its owner and the event is still attributed to the real login.
- `actor_kind` names the **channel**, not the person: a learner refused on a staff route is recorded
  with `actor_kind = 'staff'`, `outcome = 'denied'` and the learner's id.
- A staff session without an actor cannot write an event (`42501`). Worker events have no actor.
- Input limits (violations raise `22023`, and the message never repeats the rejected value):
  - `p_action`: dotted lower-case code, 2–6 segments, ≤ 100 characters (`lesson_revision.submit`).
  - `p_target_kind`: `NULL` or snake_case, 2–40 characters; `p_target_id` needs a target kind.
  - `p_outcome`: `allowed`, `denied` or `error`.
  - `p_details`: a **flat** JSON object, ≤ 2048 bytes, ≤ 24 keys, snake_case keys; values are
    `null`, booleans, numbers, strings matching `^[A-Za-z0-9_.:/{}+-]*$` of at most **64**
    characters (120 for the key `route` only), or arrays (≤ 24) of such strings / numbers / booleans. No nested objects, no whitespace, no `@`, no non-ASCII: a
    sentence, a name or an e-mail address typed by a learner is rejected by shape. Put identifiers,
    status codes, counts and timestamps here; point at the row with `p_target_kind` / `p_target_id`.
- The row is part of the caller's transaction. If the transaction rolls back (for example because
  `staff.require_role` raised), the row is gone too. A refusal that must be remembered is therefore
  written by the API in its own committed transaction (`require_staff` does this).
- `app.audit_events` stays append-only (existing trigger) and unreadable for all three API roles.
  There is no read path for audit events yet.

### `staff.*` role checks

- Roles are the active rows of `app.staff_roles` for the transaction's actor.
- `staff.require_role('editor', 'admin')` returns the actor id or raises `42501` with a message that
  does not say which roles were needed. No actor → `42501`.
- A role name outside `editor | reviewer | publisher | admin`, a `NULL` name, or an empty list raises
  `22023` instead of silently never matching.
- Every later `staff.*` workflow function must start with `staff.require_role(...)` and every
  migration that adds a function to `ops`/`staff` must end with
  `REVOKE ALL ON ALL FUNCTIONS IN SCHEMA … FROM PUBLIC, anon, authenticated` followed by exact
  `GRANT`s. `100_platform_structure.sql` pins the list of functions and who may execute them, so it
  has to be updated in the same change (staff lane only).

## API interface

```python
from edu_api.staff.deps import AnyStaff, StaffDb, StaffPrincipal, require_staff, STAFF_ROLES


@router.post("/v1/staff/things", responses=error_responses(401, 403, 503))
async def create_thing(
    staff: Annotated[StaffPrincipal, Depends(require_staff("editor", "admin"))],
    db: StaffDb,
) -> ...:
    async with db.transaction(staff.user_id) as conn:
        await conn.execute(text("SELECT staff.some_function(...)"))
```

- `require_staff(*roles)` → dependency returning `StaffPrincipal(user_id, roles, principal)`.
  No argument = any active staff role (`AnyStaff` is that, ready to use). Unknown role names raise
  `ValueError` when the route is defined.
- Order of checks: token (401 `unauthenticated`) → staff side configured (503 `staff_unavailable`)
  → active roles read through the staff pool **on every request** → 403 `forbidden`, with one
  `staff.access` / `denied` audit event whose details are `method`, `route` (the route template,
  never the raw URL) and `required_roles`.
- `StaffDb` is the `Database` on `app.state.staff_db` (`None` when not configured). Same
  `transaction(actor_id)` contract as the student pool.
- Settings: `EDU_STAFF_DATABASE_URL` (optional, `postgresql+asyncpg://…`),
  `EDU_STAFF_DB_POOL_SIZE` (2), `EDU_STAFF_DB_MAX_OVERFLOW` (3).

### Contract: `GET /v1/staff/me`

Request: `Authorization: Bearer <Supabase Auth access token>`; no parameters, no body.

`200`:

```json
{"user_id": "a0000000-0000-4000-8000-000000000003", "roles": ["editor"]}
```

`roles` is sorted and is a non-empty subset of `editor`, `reviewer`, `publisher`, `admin`.

Errors, always `{"error": {"code", "message", "request_id"}}`:

| Status | `code` | When |
|---|---|---|
| 401 | `unauthenticated` | missing or invalid token (`WWW-Authenticate: Bearer`) |
| 403 | `forbidden` | signed in, but no active staff role (or not the role a route needs); audited |
| 503 | `staff_unavailable` | `EDU_STAFF_DATABASE_URL` is not set on this deployment |
| 503 | `dependency_unavailable` | staff database or auth key service unreachable (`Retry-After: 5`) |

```json
{"error": {"code": "forbidden", "message": "You do not have access to this resource.", "request_id": "…"}}
```

## Hardening after the security review of B1 (ruling R-03)

Migration `20261124010400_revoke_temp_and_search_path.sql` (the number `…010100` named in the ruling
was already taken by the access-denial window; the content is what the ruling asks for).

| Finding | What changed | Proof |
|---|---|---|
| **H1** pg_temp type shadowing | `REVOKE TEMPORARY ON DATABASE … FROM PUBLIC` (and from anon, authenticated, authenticator, service_role); every function in `ops`/`staff` now has `search_path = pg_catalog, pg_temp`; all later functions are created that way | `100_platform_structure.sql` (no `edu_*`, anon, authenticated, authenticator, service_role holds TEMP; search_path pinned); `test_staff_hardening.py` runs ten kinds of temporary-object creation and the reviewer's reproduction as each of the three real logins — all refused, nothing gained |
| **M1** unbounded denial rows | `ops.audit_access_denied`: one persisted denial per actor per 60 s, the rest counted (`suppressed_before`) | `102_access_denial_window.sql`, `test_repeated_refusals_do_not_grow_the_audit_log` |
| **M2** details are not a privacy filter | strings ≤ 64 characters (`route` ≤ 120); function comment and this document say so; personal-data-shaped values that still pass are **pinned as accepted** in `101_…sql` so nobody reads "validated" as "safe" | `101_staff_boundary_and_audit.sql` |
| **L1** superuser labelled staff | `ops.actor_kind_for` returns `system` first for a superuser | `101_…sql` |
| **L2** learner refusals look like staff | denial details carry `held_roles` (empty for a learner) and `check`; `actor_kind` is the channel | boundary / editorial / roles tests |
| **L3** odd route → 500 | the route template is rebuilt from path parameters and falls back to `unknown` | `test_a_route_with_unusual_characters_is_still_refused_and_audited` |
| **L4** wrong staff login → 500 | on first use the pool must report `ops.session_kind() = 'staff'`; wrong password → 503 `dependency_unavailable`; student / worker / owner login → 503 `staff_unavailable`, nothing written | `test_a_staff_pool_with_the_wrong_login_refuses_to_work` |
| **L5** information_schema blind spot | structure test uses `has_table_privilege` / `has_sequence_privilege` over `pg_class` | `100_platform_structure.sql` |
| Note: env leak into `openapi.json` | covered by `INCLUDE_IN_SCHEMA` | `test_an_exported_staff_url_does_not_change_the_published_contract` |

**Rule for every caller of `ops.audit_write`:** never pass a value typed by a learner (answer, name,
message, search term) in the action, the target kind or the details — only ids, enum codes, numbers
and server-made timestamps. The input check is a structural guard, not a privacy filter.

Still open from the review: `dashboard_user` (a Supabase platform role, not an API login) keeps TEMP;
`CONNECTION LIMIT 10` for the staff login allows two API processes with the default pool, a third
gets 503; a multi-dimensional role array raises `0A000` instead of `22023` (fails closed); a login
can change its own password (standard PostgreSQL).

## B2.1 — Editorial workflow through the API

Migration `20261124010200_staff_editorial.sql` (schema `staff` only), router
`services/api/src/edu_api/routers/staff_editorial.py`, request models
`edu_api/staff/content.py`, error translation `edu_api/staff/errors.py`.

Each route calls one `staff.*` definer function. That function checks the role again
(`staff.require_role`), writes, and records one audit event in the same transaction. **The triggers
of schema `app` stay the enforcement of record** for the editorial rules: the functions do not
re-implement "reviewer ≠ author", "approved is immutable", "cleared sources" or the pack lifecycle;
when a rule is broken the trigger raises and the API answers 409 with a stable code.

| Method and path (under `/v1/staff`) | Role | Function | Audit action |
|---|---|---|---|
| `POST /lessons` `{unit_id, slug}` → 201 `{lesson_id}` | editor, admin | `create_lesson` | `lesson.create` |
| `POST /lessons/{lesson_id}/revisions` `{locale, title, blocks, questions}` → 201 revision | editor, admin | `create_revision` | `lesson_revision.create` |
| `GET /revisions?status=&mine=&limit=` | any | `list_revisions` | — |
| `GET /revisions/{revision_id}` | any | `get_revision` | — |
| `PUT /revisions/{revision_id}` `{title, blocks, questions}` | author only (an admin is not an exception) | `update_revision` | `lesson_revision.update` |
| `POST /revisions/{revision_id}/sources` `{source_id}` | author only (an admin is not an exception) | `attach_source` | `lesson_revision.attach_source` |
| `DELETE /revisions/{revision_id}/sources/{source_id}` → 204 | author only (an admin is not an exception) | `detach_source` | `lesson_revision.detach_source` |
| `POST /revisions/{revision_id}/submit` | author only (an admin is not an exception) | `submit_revision` | `lesson_revision.submit` |
| `POST /revisions/{revision_id}/reviews` `{verdict, notes?}` → 201 | reviewer, admin — never the author | `review_revision` | `lesson_revision.review` |
| `POST /sources` `{source_title, source_uri?}` → 201 `{source_id}` | editor, admin | `create_source` | `content_source.create` |
| `GET /sources?limit=` | any | `list_sources` | — |
| `PUT /sources/{source_id}/rights` `{rights_status, rights_notes?}` → 204 | admin | `set_source_rights` | `content_source.set_rights` |
| `POST /packs` `{pack_key, locale, revision_ids}` → 201 release (`ready`) | editor, publisher, admin | `build_pack` | `pack_release.build` |
| `GET /packs?pack_key=&locale=&limit=` | any | `list_pack_releases` | — |
| `POST /packs/{release_id}/release` | publisher, admin | `release_pack` | `pack_release.release` |
| `POST /packs/{release_id}/rollback` | publisher, admin | `rollback_pack` | `pack_release.rollback` |

Behaviour worth knowing:

- **Content format.** `blocks` and `questions` are validated by Pydantic models that mirror
  `packages/contracts/content/lesson-blocks.schema.json` and `question-mcq.schema.json`
  (`tests/unit/test_staff_content_models.py` runs 64 vectors through both and requires the same
  verdict). Three rules go beyond the schemas: unique block keys, unique question keys / choice ids,
  and a correct choice that exists. Only `mcq` questions are accepted. Unknown fields are refused
  (a client cannot send `status`, `created_by`, …).
- **Workflow.** `draft` → `submit` → `in_review` → review. `approved` approves the revision
  (`approved_by` = the reviewer). `rejected` **and** `changes_requested` both set `rejected`: a
  review freezes the content it looked at (trigger), so a correction is a new revision (next number).
  A draft needs at least one source to be submitted; it can be approved only when every attached
  source is `cleared` (trigger).
- **Rights decision** on a source is `admin` only, so an author cannot clear the rights of their own
  material. Who really decides on rights is an owner question (PO-17/18): `BLOCKED_BY_OWNER`,
  synthetic default = any admin.
- **Release** is one transaction and one audit event: activate the release, move
  `app.pack_current`, retire the previous release. **Rollback** is the same switch towards an
  earlier `retired` release of the same pack. Both run under a per-(pack_key, locale) advisory lock.
- **Manifest.** No pack file is produced or stored. The manifest columns hold a deterministic
  object key and the SHA-256 / byte length of the canonical item list. A real pack builder is not
  part of tonight's work.

Error codes (standard error shape):

| Status | Codes |
|---|---|
| 403 | `forbidden` (wrong role, or not the author; audited as `staff.access` / `denied` with `check` = `route` or `function` and `held_roles`) |
| 404 | `unit_not_found`, `lesson_not_found`, `revision_not_found`, `source_not_found`, `source_not_attached`, `pack_release_not_found` |
| 409 from the functions | `lesson_slug_taken`, `revision_in_review`, `revision_not_draft`, `revision_has_no_source`, `revision_not_in_review`, `pack_release_not_ready`, `pack_release_not_retired` |
| 409 from the triggers | `author_cannot_review`, `revision_immutable`, `revision_already_reviewed`, `sources_not_cleared`, `approval_needs_independent_review`, `pack_item_not_approved`, `pack_finalized`, `pack_empty`, `pack_invalid_transition`, `source_in_use`, `editorial_rule_violation` (any trigger message without a translation) |
| 422 | `validation_error` (request shape, control characters in text), `pack_items_duplicated`, `pack_lesson_duplicated`, `invalid_content` and the `*_invalid` codes of the functions |

Example — create a draft:

```json
{
  "locale": "fr",
  "title": "Additionner de petits nombres",
  "blocks": [
    {"key": "intro", "type": "paragraph", "text": "…"},
    {"key": "exemple", "type": "example", "title": "Exemple", "steps": ["2 + 2 = 4"]}
  ],
  "questions": [
    {
      "question_key": "q1",
      "kind": "mcq",
      "prompt": {"text": "Combien font 2 + 2 ?"},
      "response_spec": {"choices": [{"id": "a", "text": "3"}, {"id": "b", "text": "4"}]},
      "answer_key": {"correct_choice_id": "b"},
      "explanation": {"text": "2 + 2 = 4."}
    }
  ]
}
```

The answer is the revision: `id`, `lesson_id`, `revision`, `locale`, `title`, `status`, `blocks`,
`created_by`, `created_at`, `approved_by`, `approved_at`, `questions[]`, `sources[]`, `reviews[]`.

Known gaps of this part:

- Courses and units cannot be created or published through the API (lessons go into existing units).
- A lesson cannot be deactivated or moved, a pack release cannot be revoked, through the API.
- Request bodies are subject to the API-wide limits (20 KiB on the wire, 128 KiB after gzip), which
  is small for a long lesson; the limit is a setting shared with the learner routes and was not changed.
- Review notes are free text written by staff; they are stored in `app.editorial_reviews.notes`
  and never copied to the audit log.
- List endpoints have a `limit` (≤ 200) but no cursor.

## B2.2 — Role administration

Migration `20261124010300_staff_role_admin.sql`, router `routers/staff_roles.py`.

| Method and path (under `/v1/staff`) | Role | Function | Audit action |
|---|---|---|---|
| `GET /roles?limit=` → `{assignments: [{user_id, role, is_active, granted_by, granted_at}]}` | admin | `list_role_assignments` | — |
| `PUT /users/{user_id}/roles/{role}` → `{user_id, role, is_active: true, changed}` | admin | `grant_role` | `staff_role.grant` (target `user`) |
| `DELETE /users/{user_id}/roles/{role}` → `{user_id, role, is_active: false, changed}` | admin | `revoke_role` | `staff_role.revoke` (target `user`) |

Rules enforced in SQL (the API gate is in front, not instead):

- Only an active admin grants or revokes.
- **Nobody grants a role to themselves**, admin included: 403 `forbidden`, audited as a denial.
  Two admins give each other roles.
- **The last active admin cannot be revoked**: 409 `last_admin`. An admin may step down while
  another active admin remains. All role changes take one advisory lock and re-check the caller's
  admin role after getting it, so two admins revoking each other at the same moment end with one
  admin (tested five times over real concurrent requests: one 200, one 403).
- The target must be an existing, permanent, non-deleted Auth account (404 `user_not_found`).
- Revoking keeps the row with `is_active = false`; granting again reactivates it and records the new
  grantor. Both are idempotent: a call that changes nothing answers `changed: false` and writes no
  audit event.
- A change takes effect on the account's very next request (roles are read per request).
- The listing returns account ids only — no e-mail address. Finding an account by e-mail is not
  offered (it would expose learner addresses to staff; owner decision).

**First admin.** No API can create the first admin of an environment. The database owner inserts it
once: `INSERT INTO app.staff_roles (user_id, role) VALUES ('<auth user id>', 'admin');`. Locally the
tests do this through `make_staff("admin")`. The seed contains no admin.

## B2.3 — Worker and job leasing

Migration `20261124010500_ops_job_queue.sql` (schema `ops`; the existing `app.background_jobs` table
is reached only through these definer functions), package `services/worker/src/edu_worker`.

```
ops.enqueue_job(p_kind text, p_payload jsonb DEFAULT '{}', p_idempotency_key text DEFAULT NULL,
                p_run_after timestamptz DEFAULT NULL, p_max_attempts integer DEFAULT 5) RETURNS uuid
                                                                  EXECUTE: edu_worker, edu_staff
ops.claim_jobs(p_worker_id text, p_kinds text[], p_limit integer, p_lease_seconds integer)
    RETURNS TABLE (job_id, kind, payload, attempt, max_attempts, lease_until)   EXECUTE: edu_worker
ops.heartbeat_job(p_job_id uuid, p_worker_id text, p_lease_seconds integer) RETURNS boolean
ops.complete_job(p_job_id uuid, p_worker_id text) RETURNS boolean
ops.fail_job(p_job_id uuid, p_worker_id text, p_error_class text) RETURNS text  -- 'queued' | 'dead' | NULL
```

- **At-least-once with a lease.** `claim_jobs` uses `FOR UPDATE SKIP LOCKED` and counts the attempt.
  A dead worker's lease runs out and the next claim takes the job again. `heartbeat` / `complete` /
  `fail` act only for the worker id that holds the lease (unique per process); anyone else gets
  `false` / `NULL`. Handlers must be idempotent.
- **Backoff and dead letter.** A failed attempt is re-queued after 5 s, 10 s, 20 s … (cap 15 min).
  After `max_attempts` — by failure or by a lease running out on the last attempt — the job is
  `dead` and one audit event `job.dead` is written. Only an error **class name** is stored; a
  malformed name becomes `UnnamedError`.
- **Idempotent enqueue.** The same `p_idempotency_key` always returns the first job, in any state.
- **Payloads** are JSON objects ≤ 8192 bytes and must hold ids and codes only. Other lanes' definer
  functions call `ops.enqueue_job` as owner; `edu_api` has no access to jobs at all.
- **Runner** (`edu_worker.Worker`): handler registry, bounded concurrency, lease renewal while a
  handler runs (a lost lease cancels the handler and reports nothing), graceful `stop()` with a
  grace period. `uv run python -m edu_worker --kinds noop --exit-when-idle` runs one process; it
  refuses to start unless `ops.session_kind()` says `worker`. The only production handler is `noop`.
  **No schedule or service is installed; nothing runs unless someone starts it.**

Tests: `supabase/tests/105_job_queue.sql`; `tests/integration/test_worker_queue.py` — 300 jobs and
8 concurrent claimers (no job leased twice), a real worker process killed with SIGKILL mid-job whose
job is then run exactly once more (attempt 2) while its old identity is fenced off, dead-lettering
after `max_attempts`, idempotent enqueue under concurrency, `edu_api` refused on every function.

Known gaps: no handler timeout (a handler that hangs keeps renewing its lease); no way to cancel or
re-queue a dead job through an API; no metrics; no retention for completed jobs; the worker has no
deployment unit (process manager, container) yet.

## B2.4 — Second factor for staff (design only — NOT implemented, nothing is claimed)

Today a staff member signs in with one factor, exactly like a learner. No code in this branch
checks, requires or enrols a second factor. This section is the proposal to review.

**Goal.** Every `/v1/staff` request must come from a session in which the person proved a second
factor, so that a stolen password alone cannot edit, approve or publish content or change roles.

**Mechanism (Supabase Auth MFA, TOTP).**

1. *Token claim.* Supabase access tokens carry `aal` (`aal1` after a password, `aal2` after a
   verified second factor) and `amr` (the methods used, with times). `edu_api.auth.verifier` already
   verifies the token; `Principal` would gain `aal` and the time of the latest second-factor entry.
2. *Enforcement in one place.* `require_staff` refuses a principal whose `aal` is not `aal2` with
   **403 `mfa_required`** before any role lookup, and records the refusal (bounded, like other
   denials). A setting `EDU_STAFF_REQUIRE_MFA` (default on outside `local`/`test`) controls it; the
   learner routes are untouched.
3. *Defence in depth in the database.* The API would also set a transaction-local `edu.actor_aal`
   next to `edu.actor_id`, and `staff.require_role` would refuse unless it is `aal2`. A bug in one
   route then cannot skip the check. (Same trust model as `edu.actor_id`.)
4. *Step-up for dangerous actions.* Releasing or rolling back a pack and granting or revoking roles
   would additionally require that the second factor was entered recently (proposal: 15 minutes),
   answered with **403 `mfa_step_up_required`**.
5. *Enrolment.* The staff client uses the Auth API directly (`/factors` enrol → QR code → verify).
   An account can be given a staff role before it has a factor; it then gets `mfa_required` until it
   enrols. Two factors per person are recommended (phone + spare).
6. *Recovery.* No self-service recovery. A person who lost their device is identified out of band
   by an admin, who removes the factor through an audited staff function (`staff.reset_mfa`, to be
   written; it needs the Auth admin API, so it belongs to a server-side component that holds the
   service key — not to the staff pool). The last admin's recovery is a database-owner procedure.
7. *Sessions.* Shorter session lifetime and inactivity timeout for staff than for learners
   (Auth project settings), and sign-out everywhere when a role is revoked.

**What has to be decided by the owners (`BLOCKED_BY_OWNER`).** TOTP only, or also passkeys/WebAuthn;
the step-up window; who may reset a factor and how identity is checked; whether a hosted Supabase
plan with the needed MFA options is used; staff session lifetime.

**Tests that would prove it** (none exist): an `aal1` token of a real staff member gets 403 on every
staff route and 200 on learner routes; an `aal2` token passes; a forged `aal` claim cannot exist
(signature); step-up window honoured; `staff.require_role` refuses without `edu.actor_aal = aal2`
even when called directly on the staff connection; reset is audited and admin-only.

## Open review findings

Independent review of B2 at `642ab5c` (verdict: approve with fixes). Fixed in migration
`20261124010600_staff_editorial_review_fixes.sql` and `edu_api/staff/content.py`; tests in
`supabase/tests/106_staff_editorial_review_fixes.sql`, `tests/integration/test_staff_review_fixes.py`
and `tests/unit/test_staff_content_models.py`.

**Fixed**

- **M-B2-1 (medium) — an admin could publish content nobody else reviewed, under an editor's name.**
  `staff.require_author` had an admin exception, so an admin could rewrite another person's draft
  (`created_by` unchanged) and then approve it. Now only the author changes a draft, attaches or
  detaches its sources, or submits it: anyone else, admin included, gets 403 `forbidden`
  (`42501 not_the_author`, audited as a denial). An admin who wants different content writes a new
  revision, is its author, and cannot review it (409 `author_cannot_review`, baseline trigger).
  An admin may still approve a revision whose text is entirely the author's.
- **L-B2-2 — a pack could contain two revisions of the same lesson.** `staff.build_pack` now refuses
  it: 422 `pack_lesson_duplicated` (a pack has one locale, so this is one revision per lesson and
  locale). Releases built before this fix are not changed.
- **L-B2-1 — a NUL character in lesson text gave 500.** Every text of a revision (title, heading,
  paragraph, callout, example title and steps, question prompt, choices, explanation) and the
  free-text fields `source_title`, `rights_notes` and review `notes` refuse control characters
  (Unicode category Cc: U+0000–U+001F, U+007F–U+009F) with 422 `validation_error`. Tab and line
  feed stay allowed. **Carriage return is refused**, so a client must send `\n`, not `\r\n`.
  This is stricter than the published JSON schemas, which do not express it.

**Open (not fixed)**

- **L-B2-3 — no way to take content down through the API.** Setting the source of live content to
  `blocked` returns 204 and the lesson stays readable. There is no route to revoke a release, and
  `rollback` needs an earlier retired release, so the first release of a pack cannot be withdrawn
  without direct SQL. Review's note: not required by the brief; for a platform for minors a takedown
  path (publisher/admin, audited) should exist before real use.
- **L-B2-4 — "last admin" counts role rows, not accounts that can still sign in.** `revoke_role`
  (`20261124010300_staff_role_admin.sql`) checks that another active admin row exists; it does not
  look at `auth.users` (deleted or banned). The last usable admin can therefore be revoked if a dead
  account still holds an active admin row. Review's suggested fix: join `auth.users` (not deleted,
  not banned) in the check, as `check_role_target` does. Found by reasoning, not reproduced.
- Review notes on test coverage still open: last-admin check with a deleted/banned other admin;
  concurrent release of several ready releases and rollback to a revoked release (behaviour correct,
  not pinned by a test); a deploy-time assertion of the TEMP revoke outside the test database
  (N-P1a).
- Not examined by the review: `staff/errors.py` message mapping in detail, `scripts/local_stack.py`,
  this document's accuracy and the MFA design text, worker graceful shutdown and bounded
  concurrency, hosted Supabase behaviour, performance.

## Local environment

`make db-reset` (or `uv run python scripts/local_stack.py env` followed by `… provision`) now also
writes `EDU_STAFF_DATABASE_URL`, `EDU_WORKER_DATABASE_URL`, `LOCAL_STAFF_DB_PASSWORD` and
`LOCAL_WORKER_DB_PASSWORD` to the git-ignored `.env` and creates the two login roles, each a member
of exactly its own group. Existing passwords in `.env` are kept.

## Tests

See the module docstring of `tests/staff_fixtures.py` for the fixtures (`staff_app`, `staff_client`,
`staff_tokens`, `make_staff`) and helpers (`create_account`, `create_staff_account`,
`set_role_active`, `remove_account`, `build_staff_settings`, `staff_url`, `worker_url`).

## Deviations from the brief, and why

1. **Staff routes are not in the OpenAPI document on this branch (director ruling R-01).**
   `routers/staff.py` declares its router with the module-level constant `INCLUDE_IN_SCHEMA = False`.
   The routes are registered and work; `packages/contracts/openapi.json` and the mobile
   `schema.d.ts` are byte-identical to `main`. The director flips the constant at integration.
   With the staff side unset the routes answer **503 `staff_unavailable`** (as the staff brief
   specifies), not 404.
2. **`staff.actor_roles()` was added** to the interface (one extra function) so that
   `GET /v1/staff/me` and `require_staff` need a single round trip.
3. **`pg_has_role(…, 'USAGE')` instead of plain membership** for `actor_kind`: in PostgreSQL 16+ the
   role that creates a group (here `postgres`) automatically holds an ADMIN-only membership in it,
   which must not make owner sessions count as `staff`.
4. **Unconfigured staff side answers 503 with code `staff_unavailable`** (no `Retry-After`), not
   `dependency_unavailable`: retrying does not help. A configured but unreachable staff database
   answers the usual 503 `dependency_unavailable` with `Retry-After: 5`.

## Known gaps (B1)

- No second factor for staff: designed in B2.4, **not implemented**.
- No rate limit on refused staff requests: every refusal appends one audit row, so a signed-in
  account can grow `app.audit_events` by repeating a refused call. Belongs with the rate-limiting
  work of the notify/security lane.
- No read path, retention rule or export for audit events.
- Role checks do not look at the Auth account state (banned / deleted) beyond the access token being
  valid; an already issued token of a banned account keeps its roles until the token expires or the
  role row is deactivated.
- The "no free text" rule for audit details is structural (shape and character set). It cannot stop
  a caller from deliberately encoding text into an allowed token.
- Hosted provisioning of `edu_staff_login` / `edu_worker_login` is not written (local only).
