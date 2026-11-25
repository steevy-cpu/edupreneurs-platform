# Lane IDENTITY — profile edit, onboarding state, account lifecycle

Branch `overnight/identity-onboarding` · schema `account` · migrations `2026112402xxxx_*` ·
pgTAP `120–139_*`. Nothing here is merged to `main`, deployed, or run against real data: every
account in every test is synthetic and lives in a disposable local stack.

Three feature flags, **all off by default**. A disabled capability registers no route, so with
every flag off the API and `packages/contracts/openapi.json` are byte-identical to `main`.

| Setting (env) | Routes |
|---|---|
| `EDU_PROFILE_EDIT_ENABLED` | `PATCH /v1/me` |
| `EDU_ONBOARDING_ENABLED` | `GET /v1/me/onboarding`, `PUT /v1/me/onboarding` |
| `EDU_ACCOUNT_LIFECYCLE_ENABLED` | see slice 3 |

Because the committed OpenAPI document is generated with default settings, these routes are **not**
in `openapi.json` / `schema.d.ts` yet. The contracts below are the reference until an owner turns a
flag on by default (then `make openapi` and `npm run gen:api` pick them up).

## What did not change

- No object was created, altered, granted or dropped in schema `app`; the four verified migrations,
  `seed.sql` and the existing tests are untouched. `edu_api` still has **no** `UPDATE` privilege on
  `app.learner_profiles` (asserted again in `120_account_structure.sql`).
- `account` tables reference `auth.users`, not `app.learner_profiles`: a foreign key into `app`
  would install system triggers on an `app` table.
- `GET /v1/me` and its response are unchanged.

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
| 405 | `method_not_allowed` | the flag is off |
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
`postgres`, `search_path = ''`, actor = `app.current_actor_id()`, no user-id parameter, `EXECUTE`
to `edu_api` only. It re-validates everything the API validated (defence in depth) and refuses,
rather than repairs, a non-canonical display name.

### Audit — status: seam in place, **not wired**

Every change calls `account.audit_seam('account.profile_updated', 'learner_profile', <actor>,
'allowed', {"fields":[…names…]})`: who and **which fields**, never a value. `audit_seam` is the one
internal function to rewire: today its body is `RETURN NULL` (the staff lane's `ops.audit_write`
does not exist in this branch). When B1 is merged, a follow-up migration replaces the body with
`RETURN ops.audit_write(p_action, p_target_kind, p_target_id, p_outcome, p_details);` — no call
site changes. Until then **profile edits are not audited**; `121_account_profile.sql` proves the
call sites pass the right arguments by substituting the seam inside the test transaction.

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

## Tests

| File | What it proves |
|---|---|
| `supabase/tests/120_account_structure.sql` | schema private; RLS everywhere; read-only policies for `edu_api` only; no grant to PUBLIC / anon / authenticated / authenticator / service_role; functions pinned, owned by `postgres`, none callable by `edu_api` takes a user parameter; `edu_api` unchanged |
| `supabase/tests/121_account_profile.sql` | own row only; validation; rejection is atomic; B untouched; audit call arguments (field names only) |
| `tests/unit/test_account_schemas.py` | display-name normalisation; strict request models |
| `tests/integration/test_account_profile.py` | the route through the real API with real local Auth tokens; flags off = `main`; isolation; Data API cannot reach `account` |

## BLOCKED_BY_OWNER

| Id | Decision | Built instead |
|---|---|---|
| PO-04 | Personal data, consent, age band, who consents for minors | no consent data anywhere; consent unknown = not granted; all three flags off |
| PO-04 | May the display name value appear in a change feed / audit record | names of changed fields only |
| — | Turning the flags on by default (changes the published contract) | off; contracts documented here |

## Known gaps

- Profile edits are not audited until the B1 seam is wired (see above).
- No offline profile operation (design above); profile changes do not appear in `/v1/sync/pull`.
- Haitian Creole wording: this lane ships no user-facing strings.
