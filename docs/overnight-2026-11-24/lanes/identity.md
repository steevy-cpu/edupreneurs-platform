# Lane IDENTITY — profile edit, onboarding state, account lifecycle

Branch `overnight/identity-onboarding` · schema `account` · migrations `2026112402xxxx_*` ·
pgTAP `120–139_*`. Nothing here is merged to `main`, deployed, or run against real data: every
account in every test is synthetic and lives in a disposable local stack.

Three feature flags, **all off by default**. The routes are always registered; while its flag is
off a route answers the standard `404 {"error":{"code":"not_found","message":"Not Found",…}}` —
before authentication, validation or any database access.

| Setting (env) | Routes |
|---|---|
| `EDU_PROFILE_EDIT_ENABLED` | `PATCH /v1/me` |
| `EDU_ONBOARDING_ENABLED` | `GET /v1/me/onboarding`, `PUT /v1/me/onboarding` |
| `EDU_ACCOUNT_LIFECYCLE_ENABLED` | `GET /v1/me/account-requests`, `POST` / `DELETE /v1/me/deletion-request`, `POST /v1/me/export` |

**Published contract (director ruling R-01).** `PATCH /v1/me` is a new method on an existing path:
it **is** in `packages/contracts/openapi.json` and `apps/student-native/src/core/api/schema.d.ts`
(both regenerated). The four **new paths** are registered but declared with
`include_in_schema=INCLUDE_IN_SCHEMA` (`INCLUDE_IN_SCHEMA = False`, one constant in
`services/api/src/edu_api/routers/account.py`), so the pinned path set of `main` is unchanged on
this branch; the director flips the constant once at integration. Until then the contracts below
are the reference for those paths. A test builds the application with the constant on and checks
that every operation carries bearer security and only the standard error shape.

**Function template (ruling R-03).** Every function in `account` has
`SET search_path = pg_catalog, pg_temp` (temporary schema explicitly last) and schema-qualifies
every non-catalog object; `120_account_structure.sql` pins it. No application code path creates a
temporary object.

**Ruling R-02.** No `account` table has a foreign key to any `app` table (pinned by test).

## What did not change

- No object was created, altered, granted or dropped in schema `app`; the four verified migrations,
  `seed.sql` and the existing tests are untouched. `edu_api` still has **no** `UPDATE` privilege on
  `app.learner_profiles` (asserted again in `120_account_structure.sql`).
- `account` tables reference `auth.users`, not `app.learner_profiles`: a foreign key into `app`
  would install system triggers on an `app` table.
- `GET /v1/me` and its response are unchanged (it is not behind any flag).

## Slice 1 — `PATCH /v1/me`

Request: a JSON object with **any** of the three fields; at least one is required; unknown fields
are rejected.

| Field | Type | Rule |
|---|---|---|
| `grade_code` | string | `^[A-Z0-9]{2,8}$`, must name an existing **active** grade. `null` is rejected (a grade cannot be cleared) |
| `preferred_locale` | `"fr"` \| `"ht"` | `null` is rejected |
| `display_name` | string \| null | NFC-normalised and trimmed by the server; then 1–80 characters, no control characters (Unicode `Cc`: tab, CR, LF, NEL, ESC, DEL …) and no line/paragraph separators (`Zl`, `Zp`). `null` clears it. An empty or whitespace-only string is an error |

Response `200`: exactly the `GET /v1/me` body (`MeResponse`), reflecting the change.

```json
PATCH /v1/me   {"grade_code":"9AF","preferred_locale":"ht","display_name":"  Elèv sentetik  "}
200 {"user_id":"…","preferred_locale":"ht","display_name":"Elèv sentetik",
     "grade":{"id":"b0000000-0000-4000-8000-000000000001","code":"9AF","label":"9èm ane fondamantal"},
     "created_at":"2026-11-24T…Z"}
```

Errors (standard shape `{"error":{"code","message","request_id","details"}}`):

| Status | `code` | When |
|---|---|---|
| 401 | `unauthenticated` | missing / invalid token |
| 404 | `not_found` | `EDU_PROFILE_EDIT_ENABLED` is off |
| 422 | `validation_error` | unknown field, wrong type, `null` grade or locale, invalid display name. `details[].loc` names the field; the submitted value is never echoed |
| 422 | `empty_patch` | body is `{}` |
| 422 | `grade_not_available` | the grade does not exist **or** is inactive (indistinguishable on purpose). Nothing in the request is applied |
| 503 | `dependency_unavailable` | database / key service down |

Behaviour:

- The row is always the caller's own: the user id comes from the verified token; a `user_id` in the
  body is an unknown field (422); in the query string or a header it is not an input.
- Idempotent: repeating a request changes nothing (no write, `updated_at` does not move, no audit).
- The request is atomic: if any field is refused, none is applied.
- First contact through `PATCH` creates the caller's profile exactly as `GET /v1/me` does.
- A learner whose current grade is later deactivated keeps it and can still edit other fields.
- The display name is a **private study setting** shown only to its owner (Platform-00 doc 04
  §4.1). It is not a public name and nothing in this lane exposes it to anyone else.

Database: `account.update_own_profile(p_patch jsonb) RETURNS jsonb` — `SECURITY DEFINER`, owned by
`postgres`, `search_path = pg_catalog, pg_temp`, actor = `app.current_actor_id()`, no user-id parameter, `EXECUTE`
to `edu_api` only. It re-validates everything the API validated (defence in depth) and refuses,
rather than repairs, a non-canonical display name.

### Audit — wired to `ops.audit_write` (B1)

Every change calls `account.audit_seam('account.profile_updated', 'learner_profile', <actor>,
'allowed', {"fields":[…names…]})`, and `audit_seam` (one internal function, `EXECUTE` to nobody)
forwards to the staff lane's `ops.audit_write` since `20261124020400_account_b1_wiring.sql`. The
event is in the caller's transaction; the actor and the actor kind (`user` for the learner API) are
decided by `ops.audit_write`, never passed in.

Ruling R-03, item 3: **no value typed by a person is ever passed** — not in the action, the target
kind or the details. Call sites pass literals, a row id, column names chosen by the function
(`grade_code`, `preferred_locale`, `display_name`) or counts. Tests search the whole audit table
for the submitted display name after an edit and find nothing. A repeated, refused or invalid
request writes no event.

| Action | Target | Details |
|---|---|---|
| `account.profile_updated` | `learner_profile`, the learner id | `{"fields":[names]}` |
| `account.deletion_requested` / `account.deletion_cancelled` | `deletion_request`, the request id | `{}` |
| `account.data_exported` | `export_request`, the export id | two counts |
| `account.learner_erased` | `learner`, **no id** | counts only |

### Design — future offline `profile_updated` sync operation (not built)

Why not tonight: an offline operation must go through `app.sync_apply_operation`, which is a
verified object in schema `app` (it rejects any kind other than `practice_answer` /
`lesson_completed`, and `app.account_change_feed.entity_type` has a `CHECK` that admits only
`lesson_progress` / `practice_attempt`). Supporting a third kind means changing both, i.e. a
reviewed migration of the verified sync boundary plus new vectors for `mep-canon-1`. That is out of
this mission's rules. Until then profile edits are **online-only**; the app should queue the intent
locally and call `PATCH /v1/me` when a connection returns (the endpoint is idempotent, so a retry
is safe), and refresh from `GET /v1/me`.

Proposed operation, for the owners' review:

- Kind `profile_updated`. Canonical payload (`mep-canon-1`: sorted keys, no insignificant
  whitespace, NFC strings), containing **only the fields the learner changed**:
  `{"display_name": "…" | null, "grade_code": "9AF", "preferred_locale": "ht"}`. Validation is the
  same as `PATCH /v1/me` (performed by the API before the digest is computed, so the digest covers
  the normalised value).
- Exactly-once: the existing `(learner, op_id)` receipt and digest check apply unchanged.
- Conflict rule: **per-field last-writer-wins in server acceptance order** (the order the server
  commits operations for that learner, already serialised by the `account_sync_state` row lock).
  The phone's clock is never used: `client_recorded_at` stays display metadata. Two devices editing
  different fields both win; two devices editing the same field → the one the server accepts last
  wins, and the other device learns the result from the change feed.
- Refusals are per operation and durable (`rejected` + `grade_not_available` /
  `invalid_display_name`), like `content_not_available` today; a refused field refuses the whole
  operation.
- Change feed: one entry, new `entity_type` `learner_profile`, `entity_id` = the learner id,
  `change_data` = the field **names** changed plus the resulting `grade_code` and
  `preferred_locale`. Whether the display name value may appear in the feed (it is the learner's
  own data on the learner's own feed) is a privacy decision to take with PO-04; the safe default is
  names only + "re-read `/v1/me`".
- Implementation sketch: `sync_apply_operation` delegates the write to
  `account.update_own_profile` so there stays one validator and one audit call site.

## Slice 2 — onboarding state

One row per learner in `account.onboarding_state` (created on first write):
`state` ∈ `new` → `profile_selected` → `downloads_informed` → `ready`, `onboarding_version`,
`tour_version_seen`, `tour_dismissed`, `completed_at`, `created_at`, `updated_at`. RLS: own-row
`SELECT` for `edu_api`; no write privilege — writes only through `account.advance_onboarding`.

### `GET /v1/me/onboarding`

```json
200 {"state":"new","onboarding_version":0,"tour_version_seen":0,"tour_dismissed":false,
     "completed_at":null,"updated_at":null}
```

Read-only (creates no row). `onboarding_version` is `0` and `updated_at` is `null` until a device
has reported. Errors: 401 `unauthenticated`, 404 `not_found` (flag off), 503.

### `PUT /v1/me/onboarding`

```json
PUT {"state":"downloads_informed","onboarding_version":1,"tour_version_seen":1,"tour_dismissed":false}
200 {"state":"downloads_informed","onboarding_version":1,"tour_version_seen":1,"tour_dismissed":false,
     "completed_at":null,"updated_at":"2026-11-24T…Z"}
```

| Field | Type | Rule |
|---|---|---|
| `onboarding_version` | integer 1–10000, **required** | version of the flow built into the calling app |
| `state` | one of the four states, optional / null | the furthest step this device reached |
| `tour_version_seen` | integer 0–10000, optional / null | highest tour version shown |
| `tour_dismissed` | boolean, optional / null | `true` = do not show the tour again |

Unknown fields are rejected (422 `validation_error`). Other errors: 401, 404 (flag off), 503.
The response is the state **after merging** — always 200 for a well-formed request, including a
stale one.

### Merge semantics (what makes it resumable and safe to replay)

Every field merges monotonically with what is stored, so requests commute: any number of devices
may send any of their updates, late, repeated and in any order, and the result is the same.

| Field | Merge |
|---|---|
| `state` | never moves backwards; forward jumps are allowed (an offline device may report only `ready`) |
| `onboarding_version` | greatest of stored and reported |
| `tour_version_seen` | greatest of stored and reported |
| `tour_dismissed` | logical OR — once true, stays true |
| `completed_at` | set by the server clock the first time the state is `ready`; never changes after |

A stale or repeated request is accepted (200) and changes nothing — not even `updated_at`.
Concurrent requests are serialised on the learner's onboarding row.

**Version rule.** A higher `onboarding_version` raises the stored version and nothing else: a
learner who is `ready` is never sent back through the flow by an app upgrade. A newer flow may only
add optional, non-blocking steps (announce them with the tour fields: offer a tour when
`tour_version_seen` is behind and `tour_dismissed` is false).

**Returning-learner rule.** The effective state is never below what the server already knows:

- a learner with accepted work (`app.account_sync_state.current_version > 0`) is `ready`, with or
  without an onboarding row — people who used the app before this flow existed, or who finished
  onboarding on another device, are not asked again;
- a learner who has a grade is at least `profile_selected`.

This is derived from usage facts only. **Onboarding never deletes, resets or modifies learning
data**; it does not even read answers.

The onboarding state records progress through the introduction, not profile truth: `ready` with
`grade: null` is possible (for example after an offline replay) and the app must simply show the
grade picker.

### Consent — not collected, not inferred

PO-04 (what personal data, on whose consent, which ages, who consents for a minor) is
**BLOCKED_BY_OWNER**. Therefore:

- no consent, age, birth date, guardian or school field exists in the `account` schema or in any
  request or response (a test fails if a column or response key looks like one, and
  `{"consent": true}` in a request is rejected as an unknown field);
- `tour_dismissed` means "do not show the product tour again" and nothing else; `state = ready`
  means "has seen the introduction", not "has agreed to anything";
- **safe behaviour for consent *unknown***: every consent-gated feature must treat it as **not
  granted**. Nothing in this lane may be used as a stand-in for a consent answer.

## Slice 3 — account lifecycle mechanics (synthetic users only)

Flag `EDU_ACCOUNT_LIFECYCLE_ENABLED`, default **off**. Everything below was exercised only with
synthetic accounts on a disposable local stack. It must stay off until PO-04 and legal advice say
who may request what, on whose authority (a minor's request? a guardian's?), and how long anything
is kept. **No retention period, grace period or deadline is stored or implied anywhere** — a test
fails if such a column appears.

### Learner routes

None of the four takes a body or a parameter, so none can name another user.

| Route | Response `200` |
|---|---|
| `GET /v1/me/account-requests` | `{"deletion_request": DeletionRequest \| null, "last_export": ExportRecord \| null}` (most recent of each) |
| `POST /v1/me/deletion-request` | `{"deletion_request": DeletionRequest}` — idempotent: while a request is open, the same request is returned. **Deletes nothing**; the learner keeps full use of the app |
| `DELETE /v1/me/deletion-request` | `{"deletion_request": DeletionRequest \| null}` — cancels the open request; with none open, returns the most recent one unchanged (or `null`) |
| `POST /v1/me/export` | `AccountExport` (below); each call is recorded as a processed export |

```json
DeletionRequest {"id":"…","status":"requested|cancelled|processed","requested_at":"…","cancelled_at":null}
ExportRecord    {"id":"…","status":"processed","requested_at":"…","processed_at":"…"}
AccountExport   {"format":"mep-account-export-1","export_id":"…","generated_at":"…","user_id":"…",
  "profile":{"grade_code":"9AF","preferred_locale":"fr","display_name":null,"created_at":"…","updated_at":"…"},
  "onboarding":{"state":"ready","onboarding_version":1,"tour_version_seen":0,"tour_dismissed":false,
                "completed_at":"…","created_at":"…","updated_at":"…"} | null,
  "lesson_progress":[{"lesson_id":"…","last_revision_id":"…","completed_at":"…","last_opened_at":null,"updated_at":"…"}],
  "practice_attempts":[{"id":"…","lesson_revision_id":"…","question_revision_id":"…","response":{"choice_id":"b"},
                        "score":1.0,"scoring_version":"mcq-v1","client_recorded_at":null,"accepted_at":"…"}],
  "counts":{"lesson_progress":1,"practice_attempts":2},
  "limits":{"lesson_progress":2000,"practice_attempts":2000},
  "truncated":{"lesson_progress":false,"practice_attempts":false}}
```

Errors: 401 `unauthenticated`, 404 `not_found` (flag off), 503 `dependency_unavailable`.

The export is **bounded**: at most 2000 progress rows and the 2000 most recent attempts (0.66 MB
measured with 2000 synthetic attempts); `counts` gives the true totals and `truncated` says what was cut. It
does not include sync receipts or the change feed (technical copies of the same attempts and
completions) nor data held by other modules.

Database: `account.deletion_requests`, `account.export_requests` (own-row `SELECT` under RLS, no
write privilege), `account.get_own_requests()`, `request_deletion()`, `cancel_deletion_request()`,
`export_own_data()` — all definer, actor from the transaction, no parameter, `EXECUTE` to `edu_api`.
Export rows are written directly as `processed` because the export is produced in the same
transaction; `requested` / `cancelled` exist for a later asynchronous path.

### Erasure — the problem

`app.practice_attempts`, `app.sync_receipts`, `app.account_change_feed` (and `app.audit_events`)
each carry a `BEFORE UPDATE OR DELETE … FOR EACH ROW` trigger whose function raises
unconditionally, for every role including the owner. `app.learner_profiles` cannot be deleted
while those rows exist (`ON DELETE RESTRICT`), and `auth.users` cannot be deleted while the profile
exists. So today a learner **cannot** be erased at all. The constraint for this lane: change no
object in `app`, and do not weaken the triggers for anyone else.

### Options considered

| | Option | Changes an `app` object? | Weakens protection for others? | Verdict |
|---|---|---|---|---|
| A | **`SET LOCAL session_replication_role = replica`** inside one definer function, only around the deletes of this learner's rows, then back to `origin` | No — no catalog row changes | No — the setting is local to one session and one transaction | **Chosen** |
| B | `ALTER TABLE … DISABLE TRIGGER`, delete, `ENABLE TRIGGER`, in one transaction | Yes (`pg_trigger`), even if the net change is nil | Not visibly (other writers block on the table lock until commit), but it takes a `SHARE ROW EXCLUSIVE` lock on three hot tables — every learner's sync stalls — and a crash-safe proof rests on DDL being transactional | Rejected: violates "no change in `app`", and stalls all sync |
| C | A **reviewed change to the trigger function** `app.prevent_append_only_change()` so that it lets one named, owner-only erasure path through (for example: only when the row's learner is flagged for erasure in a table that only the orchestrator can write) | Yes — rewrites a verified guard | Depends entirely on the design: a naive version (honour a custom setting) is strictly worse, because **any** role, including `edu_api`, can set a custom setting | Not allowed tonight. **This is the portable option** — it works on any PostgreSQL without a privileged setting — and needs owner approval and its own review |
| D | `TRUNCATE` / copy-the-others-out-and-back | No | Yes — rewrites every learner's history under an exclusive lock | Rejected |
| E | Keep the rows, overwrite or pseudonymise the learner id | — | — | Impossible: `UPDATE` is blocked by the same trigger, and the id is a foreign key to the profile |
| F | Do nothing in the database; leave rows and delete only the Auth account | No | No | Impossible (`RESTRICT`), and not an erasure |

### The chosen design

`account.erase_learner(p_user_id uuid) RETURNS jsonb` — `SECURITY DEFINER`, owned by `postgres`,
`search_path = pg_catalog, pg_temp`. In one transaction:

1. Refuse a `NULL` id, a session that is not in `origin` mode, and any account with staff records
   (erasing an author/reviewer is a different, undesigned procedure).
2. Lock the learner's profile and sync rows. A concurrent sync **for this learner** waits and then
   fails; no other learner is blocked (no table lock is taken).
3. **Hooks.** Call `<schema>.erase_learner(uuid)` for every schema registered in
   `account.erasure_hooks`, in `position` order (seeded: `notify`, `leaderboard`, `rewards`,
   `vocab`, `billing`; a registered schema without a hook is reported as `absent`). A hook must
   return `jsonb` and be owned by the migration owner. A function named `erase_learner` in a schema
   that is **not** registered stops the erasure — a new module cannot be skipped silently, and an
   unknown function is never executed as owner.
4. Remove this schema's own rows. The open deletion request becomes `processed` with
   `user_id = NULL`: the fact is kept, the identity is not.
5. **Pre-check.** Row-lock the learner's rows in the three append-only tables (so nothing can
   start referencing them meanwhile), then for every foreign key (in any schema) that references
   one of those tables, prove no row points at this learner's rows; otherwise stop. This is what
   makes step 6 safe, because foreign keys are also trigger-based.
6. **The window.** `SET LOCAL session_replication_role = replica`; delete the learner's rows from
   `account_change_feed`, `sync_receipts`, `practice_attempts`; de-identify (not delete) audit
   events that name the learner (`actor_id` / `target_id` set to `NULL`, `details` replaced by
   `{"redacted": true}` if they contain the id); `SET LOCAL session_replication_role = origin`.
7. With every trigger and foreign key enforced again: delete `lesson_progress`,
   `account_sync_state`, `learner_profiles`. Any child row the function did not know about aborts
   here.
8. **Postcondition.** Scan every `uuid` column of every table outside the Supabase-managed schemas
   for the id; if it is found anywhere, raise — everything rolls back.
9. Call the audit seam with `account.learner_erased`, **no target id**, counts only. Return the
   counts and hook results (the report never contains the id).

Why this does not weaken the triggers for anyone else: `session_replication_role` is a
per-session, transaction-local setting. No row of `pg_trigger` changes; a second session — even the
table owner — is refused throughout (tested with two real connections). Only a privileged role may
set it: the function's owner can, a caller cannot (tested: `edu_worker` is refused both `SET` and
`set_config`), and the function has no dynamic SQL built from caller input.

**This is the highest-risk function of the lane; its containment is explicit.**

- `SET LOCAL` lasts until the end of the **caller's transaction**, not of the function. The window
  is a block that sets the value back to `origin` after its last statement **and** in an exception
  handler, and the function re-checks the value before continuing. Tested: after the function
  returns, and after it fails *inside* the window (a test trigger that fires even in `replica`
  mode), `current_setting('session_replication_role')` is `origin` in the caller's still-open
  transaction, a `DELETE` on `app.practice_attempts` there is refused again, and the delete that
  had already run inside the window is rolled back.
- It refuses to start if the session is not in `origin` mode.
- Foreign keys are also trigger-based. Inside the window only leaf rows are deleted (after the
  pre-check of step 5); parents are deleted after it. A test scans **every** foreign key of the
  application schemas for orphans before and after an erasure.
- Every `DELETE` / `UPDATE` is scoped by the learner id; another learner's rows are compared
  byte for byte before and after.
- Concurrency (two real connections): a sync in flight for the same learner makes the erasure
  wait, and its rows are then erased too; a push that arrives during the erasure waits and can only
  start a brand-new account afterwards — it never lands inside erased history. Lock order is
  profile row, then sync row: the sync function touches the profile (foreign-key share lock)
  before it locks the sync row, so taking the sync row first could deadlock with it.

**Platform dependency, stated plainly.** This relies on Supabase's `supautils` extension allowing
`postgres` to set `session_replication_role` (`supautils.privileged_role_allowed_configs`). That is
true on the local image used tonight. **It is unverified on a hosted project.** If a platform
refuses, `erase_learner` fails with `42501` before deleting anything, and the alternative is
option C above (a reviewed change to the append-only trigger function), which needs owner approval.

**Executors (B1; changed by review fix M-2, see the review section below).** Originally `EXECUTE` on `account.erase_learner(uuid)` went to `edu_worker`; it is now owner-only and the worker uses `account.worker_process_deletion(request id)`.
`account.staff_erase_learner(uuid)` (`EXECUTE`: `edu_staff` only) starts with
`staff.require_role('admin')` and then calls the same orchestrator. Tested with the real roles and
over real connections of `edu_worker_login` / `edu_staff_login`: a learner (through `edu_api`), an
editor, a reviewer, a learner id on the staff channel and a session without an actor are all
refused; staff cannot call the orchestrator around the role check; the worker cannot use the staff
path; an administrator cannot erase a staff account or themselves. There is **no HTTP route** for
erasure and nothing calls it automatically.

**Hook registry — what other lanes must do.** A schema that stores per-learner rows ships
`<schema>.erase_learner(p_user_id uuid) RETURNS jsonb` (owner `postgres`, `EXECUTE` to nobody) and
must be listed in `account.erasure_hooks`. Registered today: `notify`, `leaderboard`, `rewards`,
`vocab`, `billing`, `content`, `staff`, `ops`. A hook in an unlisted schema blocks every erasure
(fail closed) until one `INSERT INTO account.erasure_hooks` is added by migration. A schema with
learner rows and **no** hook is caught by the postcondition scan (uuid columns) and also blocks.

### What is proven, and what is only designed

Proven by tests on the local stack (`124_account_erasure.sql`,
`tests/integration/test_account_lifecycle.py`):

- A synthetic learner with attempts, progress, receipts (accepted and rejected), change feed,
  onboarding, an open and a cancelled deletion request, an export record and audit events is erased;
  afterwards the id appears in **no** `uuid`, `text` or JSON column of `app`, `account`, `public`
  or a test module — and the orchestrator's own scanner agrees.
- Another learner's rows in every one of those tables are byte-identical before and after; they
  keep syncing and their change version stays gap-free.
- The 16 `app` triggers are the same catalog rows with the same definitions and enabled state, and
  every `app` function is unchanged (source, settings, ACL). After the erasure, `DELETE` / `UPDATE`
  on the append-only tables is refused again, including for the owner, and foreign keys bite again.
- It runs when called by **`edu_worker`** (pgTAP, and a real `edu_worker_login` connection) and by
  a staff administrator through the wrapper. Neither role can do anything else in this schema.
- Fail-closed cases, each leaving everything in place: unknown module holding the id; unregistered
  hook; foreign key onto an append-only row that a hook forgot; staff account; session already in
  `replica`.
- After the erasure the **local Auth server deletes the account** (`DELETE /auth/v1/admin/users/…`
  → 200); before it, the same call is refused.
- Idempotent: erasing again, or erasing an unknown id, succeeds with zero counts.
- All 209 baseline database tests and 144 baseline API tests still pass, unmodified.

Designed, **not** built or not proven:

- **No caller yet.** No worker job and no staff route calls the erasure; the worker path does not
  require an open deletion request for the id it is given (a guard worth adding with the job).
- **Hosted Supabase.** The design depends on the migration owner being allowed to set
  `session_replication_role`. On the local image this is granted to `postgres` by the `supautils`
  extension (`supautils.privileged_role_allowed_configs` lists it); the hosted platform is believed
  to be configured the same way but **this was not verified** (no hosted project may be touched).
  On plain PostgreSQL a superuser would run `GRANT SET ON PARAMETER session_replication_role TO
  <owner>`. If a platform refuses, `erase_learner` fails with `42501` before deleting anything.
- **Auth.** Deleting or disabling the `auth.users` account is Supabase Auth's job and must be
  orchestrated with the erasure: a still-valid access token (up to one hour) lets the erased
  learner's device create a fresh, empty profile on its next request (tested: no old data comes
  back). Order for the future worker: revoke sessions / ban → `erase_learner` → delete the Auth
  user → run `erase_learner` once more if a shell profile reappeared.
- **Other modules' hooks** do not exist in this branch; only the calling convention is tested
  (with a test module).
- **Scale.** The postcondition scan and the audit de-identification read whole tables (one
  existence query per `uuid` column). Fine for a rare, worker-run job; needs indexes or a narrower
  scan before large volumes.
- **Device copies.** Erasure on the server does not wipe a phone's local database; the app must
  clear local data when the account is gone (native lane).
- **Backups / logs** are outside the database and outside this lane.

## Independent review of 4699a8a — fixed and open

Fixed in `20261124020500_account_review_fixes.sql` (tests: `125_account_review_fixes.sql`, updated
`124`, two-connection tests in `tests/integration/test_account_lifecycle.py`). Where this section
differs from the text above, this section is current.

| Finding | Fix |
|---|---|
| H-1 onboarding / export racing an erasure left the id behind | both functions lock the caller's profile (`FOR KEY SHARE`); a racing call waits and is refused (`42501`). Proven with two connections |
| M-1 the erasure record could store the erased id | refused when the session actor is the erased learner; the "id is nowhere" check now runs **after** the audit write |
| M-2 the worker could erase any id | `erase_learner(uuid)` is owner-only again. `edu_worker` may execute only `account.worker_process_deletion(p_request_id uuid)`: needs an **open** deletion request, takes the user from it; unknown / cancelled / processed id → error `P0002`, nothing erased, no audit event. Staff path refuses an id with no learner profile (`P0002`) |
| L-1 temporary function blocked erasure | hook discovery ignores `pg_*` schemas |
| L-2 hook contract | a registered schema whose `erase_learner` has another signature blocks; the replication role is checked after every hook |
| L-3 (part) | the postcondition also covers unlogged tables and `uuid[]` columns |
| L-4 lock order | sync row, then profile (same as `app.sync_apply_operation`), then the sync row again |

**Open review findings**

- **M-3 — Auth ordering / re-creation after erasure (needs PO-04).** The Auth account cannot be
  deleted before the erasure (foreign keys refuse), so the order is always: ban the Auth user and
  revoke sessions → erase → delete the Auth user. Nothing here does the ban, and until the access
  token expires (≤ 1 hour) a request through the API re-creates an empty profile and can file new
  requests, which puts the id back in the database. Options: make the executor do the ban, or keep
  a non-identifying, time-limited tombstone that refuses profile creation.
- **M-2, remainder.** No cooling-off period before a request may be processed (PO-04); the staff
  path takes no reason code.
- **L-3, remainder.** The postcondition does not look inside `text` / `jsonb` columns. Hook
  contract: a module must not store learner ids as text or JSON, or must erase them in its hook.
  Test 124 does sweep text / JSON columns of every application schema present.
- **L-4, remainder.** The erasure is not retried on a deadlock (`40P01`); a sync push that queues
  behind an erasure fails with a raw foreign-key error (HTTP 500) instead of a clean refusal —
  that mapping is in the verified sync path.
- **L-5.** The display name accepts invisible and direction-changing characters (Unicode `Cf`),
  including a name made only of zero-width characters. Private to its owner today; must be fixed
  before the name is shown to anyone else.
- **L-2, remainder.** A registered schema that ships no hook is indistinguishable from a lane that
  forgot one; only the postcondition catches it.

## Tests

| File | What it proves |
|---|---|
| `supabase/tests/120_account_structure.sql` | schema private; RLS everywhere; read-only policies for `edu_api` only; no grant to PUBLIC / anon / authenticated / authenticator / service_role; functions pinned, owned by `postgres`, none callable by `edu_api` takes a user parameter; `edu_api` unchanged |
| `supabase/tests/121_account_profile.sql` | own row only; validation; rejection is atomic; B untouched; audit call arguments (field names only) |
| `supabase/tests/122_account_onboarding.sql` | forward-only; version rule; tour merges; isolation; no direct writes; returning-learner rule; learning data untouched |
| `supabase/tests/123_account_lifecycle.sql` | requests are own-row, idempotent, delete nothing; no retention column; export isolation and size bound; audit call arguments |
| `supabase/tests/124_account_erasure.sql` | the erasure proof described above |
| `tests/unit/test_account_schemas.py` | display-name normalisation; strict request models |
| `tests/integration/test_account_profile.py` | the route through the real API with real local Auth tokens; flags off = `main`; isolation; Data API cannot reach `account` |
| `tests/integration/test_account_onboarding.py` | resumability, parallel replays, account switch, returning learner, no consent-like field |

| `tests/integration/test_account_lifecycle.py` | lifecycle routes through the real API; export isolation; end-to-end erasure including deletion of the Auth account; session-locality of the trigger suspension |

## BLOCKED_BY_OWNER

| Id | Decision | Built instead |
|---|---|---|
| PO-04 | Personal data, consent, age band, who consents for minors | no consent data anywhere; consent unknown = not granted; all three flags off |
| PO-04 | May the display name value appear in a change feed / audit record | names of changed fields only |
| PO-04 / legal | Who may request deletion or export (a minor? a guardian? a school?), identity checks, response deadlines | request mechanics only, flag off, no deadline stored |
| PO-04 / legal | Retention: how long requests, the de-identified "processed" record, audit events and backups are kept | nothing is purged or scheduled; no retention value exists in code |
| PO-04 / legal | Audit history versus erasure: delete, keep, or de-identify audit events about an erased learner | de-identify (keep the event, drop the id); reversible choice inside `erase_learner` |
| PO-04 / legal | Whether an export must also contain data of other modules, receipts, the change feed | profile, onboarding, progress, attempts only |
| owner | Running any erasure on a real account; approving option C if the hosted platform refuses the setting | no caller exists; flags off |
| — | Turning the flags on by default (changes the published contract) | off; contracts documented here |

## Known gaps

- No offline profile operation (design above); profile changes do not appear in `/v1/sync/pull`.
- Onboarding state changes are not audited (not required by the brief; they carry no personal data).
- Lifecycle: see "Designed, not built or not proven" above (executor wiring, hosted check, Auth
  orchestration, other modules' hooks, scale, device copies).
- No rate limit on `POST /v1/me/export`, and no "one export per N hours" rule (each call reads up
  to 4000 rows and writes one record and one audit event). Documented gap; belongs with rate limiting.
- A token that outlives its deleted Auth account makes `GET /v1/me` answer 500 (the profile insert
  violates the foreign key to `auth.users`). This is existing behaviour of `main`, not introduced
  here; mapping it to 401 belongs to the API foundation.
- Haitian Creole wording: this lane ships no user-facing strings.
