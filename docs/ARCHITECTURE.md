# Architecture (Foundation-01)

This explains **who is trusted with what**, and why the work is split between
Supabase Auth, FastAPI, and PostgreSQL the way it is.

## Components

```
 Phone / browser (untrusted)
   │  1. sign in ───────────────►  Supabase Auth (GoTrue)
   │  ◄─── access token (JWT, signed with Auth's PRIVATE key, 1 hour)
   │
   │  2. HTTPS + "Authorization: Bearer <token>"
   ▼
 FastAPI service  (services/api)
   • verifies the token with Auth's PUBLIC key (JWKS)
   • validates and limits every input
   • opens ONE database transaction per request and sets the verified user id in it
   │
   │  3. SQL as role edu_api_login (member of edu_api): no BYPASSRLS, almost no write rights
   ▼
 PostgreSQL  (schema `app`, private)
   • row-level security: a transaction only sees its own user's rows
   • app.sync_apply_operation(): the only way learning data is written
   • triggers: publication and immutability rules nobody can skip
```

Not built yet (reserved): mobile app, lite web, staff web, workers, Jude, pack storage (R2).

## Trust boundaries

| Boundary | What crosses it | What we assume | What enforces it |
|---|---|---|---|
| Phone → API | JSON + access token | **Nothing is trusted.** Not the user id, not a score, not the phone's clock | Token signature check; strict schemas (unknown fields rejected); size limits |
| API → Auth | Fetch of public keys | Auth's JWKS endpoint is authentic (HTTPS in hosted environments) | Only asymmetric keys accepted; cached; fails closed if unknown |
| API → Database | SQL + "current user is X" | The API has verified X. The database cannot check this itself | The API role can do very little even if the API is buggy (see below) |
| Staff/worker → Database | (future) | Separate roles, separate APIs | Triggers still apply to every writer, including the owner |
| Supabase Data API → `app` schema | Nothing | The auto-generated REST API must not see app data | `app` is not in the exposed schemas **and** `anon`/`authenticated` have no rights on it |

## Why three layers instead of one

**Why not let the phone use Supabase's auto-generated table API directly?**
Because offline sync needs rules that are about *several rows at once*: "apply this
operation exactly once, score it, give it the next version number, and record a
receipt — all or nothing". That cannot be expressed as per-row permissions on
tables. A hand-written API is also a stable contract: we can change tables
without breaking installed phones.

**Why keep row-level security if the API already checks everything?**
Defence in depth. If one endpoint forgets a `WHERE learner_id = ...`, the
database still returns only the caller's rows. The API's queries on learner data
filter explicitly *and* RLS filters again.

**Why put the sync write logic in a database function rather than Python?**
Two reasons:

1. *Atomicity you can see.* De-duplication, scoring, version allocation, the
   change-feed row and the receipt happen in one function inside one transaction.
   There is no code path that does half of it.
2. *A real privilege boundary.* The API's database role has **no** INSERT/UPDATE
   right on attempts, progress, receipts or the change feed. Even if an attacker
   could run arbitrary SQL through the API, they could not write a score: the
   function computes it from the stored answer key and takes no score parameter.

Python still owns everything about the outside world: token verification,
request validation, size limits, canonicalisation and hashing of payloads, error
shapes, and the HTTP contract.

**Why triggers for publication rules?**
"An approved lesson can never change", "the reviewer cannot be the author",
"a pack can only contain approved lessons of its own language" must hold for
every future writer (staff API, pack worker, a person in a SQL console).
Triggers are the only place that sees all of them.

## Request lifecycle (authenticated)

1. `RequestIdMiddleware` assigns a request id (returned as `X-Request-ID`).
2. `BodyLimitMiddleware` bounds the body (20 KB on the wire, 128 KB after gzip).
3. `get_principal` verifies the token → `Principal(user_id)`. On failure: 401, no database work.
4. The handler calls `db.transaction(user_id)`:
   `BEGIN` → `set_config('edu.actor_id', <user id>, true)` → queries → `COMMIT` (or `ROLLBACK` on any exception).
   The `true` makes the setting **transaction-local**; PostgreSQL erases it at the end of the transaction, so the next request that reuses the pooled connection starts with no identity.
5. Errors are converted to one JSON shape (`docs/API_CONTRACT.md`).

## Offline sync in one page

*Push* (`POST /v1/sync/push`): the phone sends up to 50 operations, each with a
UUID `op_id` it generated when the action happened offline.

For each operation, inside one transaction for the batch:

1. **Lock** the learner's row in `account_sync_state`. Everything for *this
   learner* now happens one at a time (other learners are unaffected). This is
   what makes 20 simultaneous retries safe, and what keeps version numbers gap-free.
2. **Look up the receipt** for `(learner, op_id)`.
   - Found, same payload digest → return the stored result (`replayed: true`). Nothing is written.
   - Found, different digest → `conflict`. Nothing is written.
3. Otherwise **validate** the content (approved and genuinely released), **score** the answer, **insert** the attempt or progress row, take the **next version**, append the **change-feed** row, and store the **receipt**.

If the response is lost on the way back, the phone resends the same batch; step 2 answers.

*Pull* (`GET /v1/sync/pull?cursor=`): returns the learner's change-feed rows with
`version` greater than the cursor, oldest first. Because versions are handed out
while holding the learner's lock and the lock is released only at commit, a
reader can never see version 6 before version 5 is visible — so a cursor never skips anything.

## Content model

- `grades → courses ← subjects`, `courses → units → lessons` are stable identities.
- A lesson's text lives in `lesson_revisions`, **one row per language per revision**.
  French and Haitian Creole are separate revisions, reviewed separately.
- Questions belong to exactly one lesson revision. Attempts reference that exact
  question revision, so history stays meaningful after content is updated.
- Publication: `draft → in_review → approved` (needs an independent reviewer and
  rights-cleared sources) → put into a `pack_release` → `ready → active` →
  `pack_current` pointer moves to it. Students see only approved revisions in a
  *current* pack of a *published* course.

## Repository layout

```
supabase/            config.toml, migrations/ (schema), seed.sql, tests/ (pgTAP)
services/api/src/edu_api/
  main.py            application factory
  config.py          settings (env vars, prefix EDU_)
  middleware.py      request id, body limits
  errors.py          the single error shape
  deps.py            FastAPI dependencies (principal, db, locale)
  auth/              jwks.py (public-key cache), verifier.py (token checks)
  db/session.py      engine + transaction-scoped actor
  identity.py        learner profile
  routers/           health, me, catalog (+lesson), sync
  sync/              canonical.py, cursor.py, schemas.py, service.py
packages/contracts/  openapi.json, content JSON Schemas
tests/               unit/, integration/ (pytest)
scripts/             local_stack.py, dev_token.py, export_openapi.py
```
