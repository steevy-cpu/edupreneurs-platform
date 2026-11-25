# Lane STAFF — B1: shared platform interface

Status: **B1 delivered and tested on the lane's local stack only.** Nothing here is deployed, linked
to a hosted project or merged into `main`. B2 (editorial slice, role administration, worker, MFA
design) is not started.

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
    `null`, booleans, numbers, strings matching `^[A-Za-z0-9_.:/{}+-]{0,120}$`, or arrays (≤ 24) of
    such strings / numbers / booleans. No nested objects, no whitespace, no `@`, no non-ASCII: a
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
| `PUT /revisions/{revision_id}` `{title, blocks, questions}` | author (or admin) | `update_revision` | `lesson_revision.update` |
| `POST /revisions/{revision_id}/sources` `{source_id}` | author (or admin) | `attach_source` | `lesson_revision.attach_source` |
| `DELETE /revisions/{revision_id}/sources/{source_id}` → 204 | author (or admin) | `detach_source` | `lesson_revision.detach_source` |
| `POST /revisions/{revision_id}/submit` | author (or admin) | `submit_revision` | `lesson_revision.submit` |
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
| 403 | `forbidden` (wrong role, or not the author; audited as `staff.access` / `denied`, `check` = `route` or `function`) |
| 404 | `unit_not_found`, `lesson_not_found`, `revision_not_found`, `source_not_found`, `source_not_attached`, `pack_release_not_found` |
| 409 from the functions | `lesson_slug_taken`, `revision_in_review`, `revision_not_draft`, `revision_has_no_source`, `revision_not_in_review`, `pack_release_not_ready`, `pack_release_not_retired` |
| 409 from the triggers | `author_cannot_review`, `revision_immutable`, `revision_already_reviewed`, `sources_not_cleared`, `approval_needs_independent_review`, `pack_item_not_approved`, `pack_finalized`, `pack_empty`, `pack_invalid_transition`, `source_in_use`, `editorial_rule_violation` (any trigger message without a translation) |
| 422 | `validation_error` (request shape), `pack_items_duplicated`, `invalid_content` and the `*_invalid` codes of the functions |

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

- No second factor for staff (design is a B2 item; nothing is implemented or claimed).
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
