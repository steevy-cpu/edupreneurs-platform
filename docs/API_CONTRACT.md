# API contract (v1)

Machine-readable version: `packages/contracts/openapi.json` (also served at
`/openapi.json`, with interactive docs at `/docs`). This page explains behaviour
that a schema cannot.

Base URL locally: `http://127.0.0.1:8000`. All examples use synthetic seed data;
tokens are shown as `<token>`.

## Authentication

Every `/v1` route requires `Authorization: Bearer <access token>`, where the
token is the **Supabase Auth access token** of a signed-in user.
`/health`, `/ready`, `/docs` and `/openapi.json` need no token.

The API checks: signature (ES256, public key from Auth's JWKS), expiry, issuer,
audience (`authenticated`), and that it is a *user* token (`role` is
`authenticated`, `sub` is a UUID, not an anonymous session). Project API keys
(`anon`, `service_role`, `sb_publishable_…`, `sb_secret_…`) are refused.

**The caller's identity comes only from the token.** No endpoint accepts a
`user_id` or `learner_id`; sending one is a validation error.

When a token expires (after 1 hour) the app must refresh it with Supabase Auth and retry.

## Errors

Every error has the same shape:

```json
{"error": {"code": "unauthenticated", "message": "A valid access token is required.",
           "request_id": "2f8e4400fa554a9b8d8403045f8b5ae6"}}
```

`details` (a list of `{loc, msg, type}`) is added for validation errors. The
`X-Request-ID` response header carries the same id; quote it in bug reports.

| HTTP | `code` | Meaning | What the app should do |
|---|---|---|---|
| 400 | `bad_request` | Unreadable body (e.g. broken gzip) | Fix the request |
| 401 | `unauthenticated` | Token missing, expired or invalid (the reason is never disclosed) | Refresh the token; if that fails, sign in again |
| 404 | `not_found` / `lesson_not_found` | No such route / no **published** lesson with that id + locale | Remove it from local lists |
| 410 | `sync_cursor_invalid` | The pull cursor cannot be used | Discard the cursor, pull again without one |
| 413 | `payload_too_large` / `batch_too_large` | Body over the size limit / more than 50 ops | Send smaller batches |
| 415 | `unsupported_media_type` | `Content-Encoding` other than gzip | Use gzip or none |
| 422 | `validation_error` / `empty_batch` / `duplicate_op_id_in_batch` | The request shape is wrong | A client bug: fix it, do not retry unchanged |
| 500 | `internal_error` | Unexpected server error. Nothing was committed | Retry later with the same `op_id`s |
| 503 | `dependency_unavailable` | Database or Auth key service unreachable (`Retry-After: 5`) | Retry later with the same `op_id`s |

## Endpoints

### `GET /health`
`200 {"status":"ok"}` — the process is running. Checks nothing else.

### `GET /ready`
`200 {"status":"ready","checks":{"database":"ok"}}` or
`503 {"status":"not_ready","checks":{"database":"unavailable"}}`.

### `GET /v1/me`
The caller's profile. Created automatically on first contact.

```json
{"user_id":"a0000000-0000-4000-8000-000000000001","preferred_locale":"fr",
 "display_name":"Élève A (synthétique)",
 "grade":{"id":"b0000000-0000-4000-8000-000000000001","code":"9AF","label":"9e année fondamentale"},
 "created_at":"2026-11-22T04:13:38.360073Z"}
```

`grade` is `null` until a grade is chosen (there is no profile-editing endpoint yet).

### `GET /v1/catalog?locale=fr|ht`
Everything the learner can open in that language, as one compact tree. Only
lessons with a published revision in `locale` are listed. Labels fall back to
French if a Creole label is missing.

```json
{"locale":"ht","courses":[{"id":"b0000000-0000-4000-8000-000000000003","slug":"mathematiques-9af",
 "title":"Matematik 9èm AF","grade":{"code":"9AF","label":"9èm ane fondamantal"},
 "subject":{"slug":"mathematiques","label":"Matematik"},
 "units":[{"id":"b0000000-0000-4000-8000-000000000004","slug":"equations-premier-degre","position":1,
  "title":"Ekwasyon premye degre",
  "lessons":[{"id":"b0000000-0000-4000-8000-000000000005","slug":"resoudre-une-equation-simple","position":1,
   "title":"Rezoud yon ekwasyon senp","revision_id":"c0000000-0000-4000-8000-000000000002","revision":1}]}]}]}
```

`revision_id` lets the app notice that its downloaded copy is out of date.

### `GET /v1/lessons/{lesson_id}?locale=fr|ht`
The currently published revision: `blocks` (format:
`packages/contracts/content/lesson-blocks.schema.json`) and its practice questions.

```json
{"lesson_id":"b0000000-…0005","revision_id":"c0000000-…0001","revision":1,"locale":"fr",
 "title":"Résoudre une équation simple",
 "blocks":[{"key":"intro","type":"paragraph","text":"Une équation est une égalité …"}, "…"],
 "questions":[{"id":"d0000000-0000-4000-8000-000000000101","question_key":"addition","position":1,"kind":"mcq",
   "prompt":{"text":"Résous : x + 5 = 12"},
   "response_spec":{"choices":[{"id":"a","text":"x = 5"},{"id":"b","text":"x = 7"},{"id":"c","text":"x = 12"},{"id":"d","text":"x = 17"}]},
   "answer_key":{"correct_choice_id":"b"},
   "explanation":{"text":"On retire 5 de chaque côté : x = 12 − 5 = 7."}}, "…"],
 "assessment_mode":"offline_practice"}
```

- `answer_key` is included on purpose so the phone can give feedback with no
  network. That makes these questions **practice only** — never an exam. The
  server still re-scores every synced answer itself.
- Drafts, rejected revisions, approved-but-unreleased revisions and unknown ids all return the same `404 lesson_not_found`.
- French and Creole revisions have different `revision_id`s and different question ids.

### `POST /v1/sync/push`
Upload offline operations.

```json
{"ops":[
  {"op_id":"65f874f1-9826-4a47-a47f-2543ea4638a4","kind":"practice_answer",
   "client_recorded_at":"2026-11-21T14:03:11-05:00",
   "payload":{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}},
  {"op_id":"0d3c1c2e-7a7e-4b55-9a52-3f1c6f1e8a10","kind":"lesson_completed",
   "payload":{"lesson_revision_id":"c0000000-0000-4000-8000-000000000001"}}
]}
```

| Field | Rule |
|---|---|
| `ops` | 1 to 50 operations, applied in order. No `op_id` twice in one batch |
| `op_id` | UUID generated by the app **once**, when the action happens; identical on every retry |
| `kind` | `practice_answer` (multiple-choice only) or `lesson_completed` |
| `client_recorded_at` | Optional, must include a UTC offset. Stored for display only; never used for ordering or scoring |
| `payload` | Exactly the fields shown for the kind. Any extra field (`score`, `learner_id`, …) makes that operation `invalid_payload` |
| Body size | ≤ 20 KB on the wire. `Content-Encoding: gzip` is accepted (≤ 128 KB after decompression). A full 50-op batch is about 12 KB uncompressed |

Response (`200`):

```json
{"results":[
  {"op_id":"65f874f1-…","status":"accepted","replayed":false,"code":null,
   "result":{"attempt_id":"516b6564-80b1-4ebf-9b16-90ecb60cf455","question_revision_id":"d0000000-…0101",
             "is_correct":true,"score":1.0,"scoring_version":"mcq-v1","change_version":1}},
  {"op_id":"0d3c1c2e-…","status":"accepted","replayed":false,"code":null,
   "result":{"lesson_id":"b0000000-…0005","lesson_revision_id":"c0000000-…0001",
             "completed_at":"2026-11-22T04:19:54.074096+00:00","already_completed":false,"change_version":2}}],
 "server_version":2,"canon_version":"mep-canon-1"}
```

**HTTP 200 means "the batch was processed", not "everything was accepted".** Read each result:

| `status` | `replayed` | Meaning | App action |
|---|---|---|---|
| `accepted` | `false` | Applied now | Mark the op synced |
| `accepted` | `true` | Already applied on an earlier attempt; this is the stored result. Nothing new was created | Mark the op synced |
| `rejected` | any | Permanently refused (see `code`). Retrying the same `op_id` gives the same answer | Mark the op "needs attention"; do not retry |
| `conflict` | `false` | This `op_id` was already used with **different content**. Nothing changed | A client bug (op_id reuse). Never "fix" an op by resending a different body under the same id |

Rejection codes:

| `code` | Cause | Stored as a receipt? |
|---|---|---|
| `unsupported_kind` | Unknown `kind` | No — a newer server may accept it later |
| `invalid_payload` | Payload does not match the kind's schema (includes non-multiple-choice answer shapes) | No |
| `content_not_available` | Question / lesson revision unknown, not approved, never released, or revoked (deliberately indistinguishable) | Yes |
| `unsupported_question_kind` | The question is not multiple choice | Yes |
| `invalid_choice` | `choice_id` is not one of the question's choices | Yes |
| `op_id_reused_with_different_payload` | (status `conflict`) | n/a |

#### Retry rules (the important part)

- If you get **no response, a 5xx, or a timeout: resend the exact same batch.**
  The whole batch is one database transaction: on a 5xx nothing was applied; if
  the server did commit but the reply was lost, the retry returns the stored
  results with `replayed: true`. Either way each operation takes effect exactly once.
- Keep an operation in the outbox until you have a result for its `op_id`.
- Operations are scoped per account: two accounts may use the same `op_id` independently.
- Work done offline against an **older** lesson revision is still accepted after
  a newer one is published (as long as the old pack was not revoked).
- `lesson_completed` merges: the first completion wins and keeps its revision;
  a later one returns `already_completed: true` and creates no change.

#### What "same content" means (`mep-canon-1`)

The server stores a SHA-256 digest per `op_id`, computed over a canonical form of
`{"kind", "payload"}`: validated fields only, UUIDs lower-case, text in Unicode
NFC, keys sorted, no whitespace, UTF-8. So key order, spacing and UUID letter
case do not matter. `op_id` and `client_recorded_at` are **not** part of the
digest: a retry with a different clock reading is still the same operation.
Full rule: `services/api/src/edu_api/sync/canonical.py`.

### `GET /v1/sync/pull?cursor=&limit=`
The account's server-authoritative changes, oldest first.

```json
{"changes":[
  {"version":1,"entity_type":"practice_attempt","entity_id":"516b6564-80b1-4ebf-9b16-90ecb60cf455","is_tombstone":false,
   "data":{"op_id":"65f874f1-…","lesson_id":"b0000000-…0005","lesson_revision_id":"c0000000-…0001",
           "question_revision_id":"d0000000-…0101","choice_id":"b","is_correct":true,"score":1.0,"scoring_version":"mcq-v1"},
   "created_at":"2026-11-22T04:19:54.074096Z"}],
 "next_cursor":"eyJhIjoiZDM2YjAxYjRjZWJiMjM2MiIsIm4iOjEsInYiOjF9","has_more":false,"server_version":1}
```

- `limit`: 1–200 (default 100). While `has_more` is true, call again with `next_cursor`.
- **Apply the changes and save `next_cursor` in the same local (SQLite) transaction.** If the app crashes in between, it re-pulls the same page, which is harmless: applying a change twice must be idempotent (upsert by `entity_type` + `entity_id`).
- Versions are per account, start at 1, and have no gaps. A change with `version` N is never delivered before N−1.
- `is_tombstone: true` means "delete your local copy of this entity". Nothing produces tombstones yet; the app must still handle them.
- `data.op_id` tells the phone which of its own outbox operations produced the change (useful to reconcile after a lost response and on a second device).
- The cursor is opaque. Do not build or edit it.

#### Cursor reset (`410 sync_cursor_invalid`)

Returned when the cursor is malformed, belongs to another account (account
switch on a shared phone), or is ahead of the server (restored backup, wrong
environment). **Recovery:** discard the cursor, call pull with no cursor, and
replace local server-derived state with what comes back. **Never discard the
outbox** when resetting — unsent operations are still valid and must still be pushed.

The feed is currently kept forever, so a cursor never expires from age. If feed
compaction is added later, an old cursor will produce this same 410.

## Limits (defaults)

| Limit | Value | Setting |
|---|---|---|
| Operations per push | 50 | `EDU_SYNC_MAX_OPS` |
| Request body on the wire | 20 KB | `EDU_MAX_WIRE_BODY_BYTES` |
| Request body after gzip | 128 KB | `EDU_MAX_DECODED_BODY_BYTES` |
| Pull page size | 100 (max 200) | `EDU_PULL_DEFAULT_LIMIT`, `EDU_PULL_MAX_LIMIT` |
| Access token length | 4096 chars | fixed |

There is **no rate limiting yet** (see `docs/SECURITY.md`).
