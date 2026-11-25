# Lane NOTIFY — notification outbox with a dummy adapter (Part A)

Branch `overnight/notify-security` · schema `notify` · migration
`20261124080100_notify_outbox.sql` · pgTAP `240–242` · flag
`EDU_NOTIFICATIONS_ENABLED` (default **off**).

**Nothing is sent to anyone.** There is no push provider, no e-mail, no SMS, no
device-token table and no network call in this lane. The only adapter is
`DummyLocalAdapter`, which appends to a bounded in-memory list. No process runs
the delivery pass: it is a library function exercised by tests.

Part B (rate limiting, logs, readiness, restore drill) is in
[`operations-drill.md`](operations-drill.md) and the second half of this file.

## What exists

| Object | Purpose |
|---|---|
| `notify.kinds` | Allow-list of kinds and their category. Seeded: `daily_word_available` (learning), `sync_reminder` (reminders), `entitlement_expiring` (account). No marketing category exists |
| `notify.policy` | One row: platform quiet hours (21:00–06:00), `max_attempts` 5, backoff base 60 s, cap 3600 s |
| `notify.preferences` | Per learner: `push_enabled` (default false), `muted_categories`, optional own quiet window |
| `notify.outbox` | One row per event per recipient: `kind`, `refs` (ids only), `channels`, `deliver_after`, `expires_at`, `dedupe_hash`, `state` |
| `notify.deliveries` | One row per (event, worker-delivered channel): `pending → leased → delivered / failed`, or `suppressed` / `expired` |
| `notify.delivery_attempts` | Append-only log, one row per attempt |

Rules enforced **in the database**:

- **Only server code creates a notification.** `notify.enqueue` is executable by
  nobody but the owner; `edu_api` has no INSERT/UPDATE/DELETE anywhere in the
  schema. Producers call `enqueue` from their own definer functions.
- **Ids only, no free text.** `refs` must satisfy `notify.refs_are_ids`: at most
  four entries, keys from a fixed list (`word_id`, `lesson_id`, `unit_id`,
  `course_id`, `subject_id`, `grant_id`), values canonical lower-case UUIDs. Every
  other text column is an allow-list; the dedupe key is stored only as SHA-256.
  A structure test fails if a new text column is added.
- **Dedupe.** `UNIQUE (recipient_id, kind, dedupe_hash)`; `enqueue` is idempotent
  and returns the existing id.
- **Push is opt-in** (no preferences row = off; consent unknown = not granted,
  PO-04) and preferences are read **at delivery time**, so a learner who opts out
  stops already-queued pushes.
- **Quiet hours** are evaluated in `America/Port-au-Prince` including daylight
  saving. The platform window always applies; a learner's own window is *added*
  to it (a learner can lengthen quiet time, never shorten the platform's). A push
  falling in quiet hours is put off to the end of the window without spending an
  attempt.
- **Retry:** exponential backoff `base × 2^(attempt−1)` capped at
  `backoff_cap_seconds`; after `max_attempts` the delivery is `failed` for good.
  A lease that runs out (worker died) is logged as `lease_lost` and retried; a
  late report with the old lease token returns `stale` and writes nothing.
- **In-app list** = the outbox rows themselves (pull only). Muting a category
  suppresses its push, not its in-app row.

## Functions and who may execute them

| Function | EXECUTE today | Intended caller |
|---|---|---|
| `notify.set_preferences(boolean, text[], time, time) → void` | `edu_api` | Student API; actor from `app.current_actor_id()` |
| `notify.enqueue(p_recipient uuid, p_kind text, p_refs jsonb, p_dedupe_key text, p_channels text[] = '{in_app}', p_deliver_after timestamptz = now, p_expires_at timestamptz = null) → uuid` | **nobody** | Other schemas' definer functions (run as owner; need no grant) |
| `notify.claim_due(p_channel text, p_limit int = 20, p_lease_seconds int = 60) → setof notify.claimed` | **nobody** — awaiting `edu_worker` | Delivery worker |
| `notify.record_attempt(p_outbox_id uuid, p_channel text, p_lease_token uuid, p_outcome text, p_error_code text = null) → text` | **nobody** — awaiting `edu_worker` | Delivery worker |
| `notify.erase_learner(p_user_id uuid) → jsonb` | **nobody** | `account` erasure orchestrator (as owner) |
| `notify._claim_due_at`, `notify._record_attempt_at`, `notify._settle` | nobody, **never to be granted** | Internal; the `_at` twins take an explicit clock for tests |
| `notify.quiet_until`, `notify.window_end`, `notify.refs_are_ids` | nobody | Internal helpers |

**Search path (ruling R-03).** All 11 functions pin
`search_path = pg_catalog, pg_temp` and qualify every non-catalog object;
`240_notify_structure.sql` asserts it and that every function is owned by
`postgres`. No application code path creates a temporary object.

**Seam, in one place.** The staff lane's roles do not exist in this branch. When
they are merged, a second migration in this block (`20261124080200_…`) adds
exactly the three statements quoted under `SEAM(notify-worker-role)` at the end
of the migration, the expectation marked with the same tag in
`240_notify_structure.sql` gains two pairs, and `owner_engine` in
`tests/notify_fixtures.py` switches to `EDU_WORKER_DATABASE_URL`. No Python in
`edu_api/notify/` changes. `ops.audit_write` is not called anywhere yet (it does
not exist here): erasure and preference changes are not audited — see gaps.

## API contract (only when `EDU_NOTIFICATIONS_ENABLED=true`)

The three routes are always registered (director ruling R-01). With the flag off
each answers the same 404 as an unknown path — before authentication, whatever
the body — and no extra database pool exists. They are declared with
`include_in_schema=INCLUDE_IN_SCHEMA` (one constant, `False`, in
`routers/notifications.py`), so `packages/contracts/openapi.json` and the mobile
`schema.d.ts` are byte-identical to `main`; the director flips the constant at
integration. `test_contract_of_the_routes_once_the_constant_is_on` proves the
documented operations then carry bearer security and only the standard error shape.

All routes need the learner's access token; the learner is taken from the token.
Errors use the standard shape.

### `GET /v1/me/notification-preferences` → 200
```json
{"push_enabled": false, "muted_categories": [], "quiet_hours": null,
 "platform_quiet_hours": {"start": "21:00", "end": "06:00"},
 "time_zone": "America/Port-au-Prince",
 "categories": ["account", "learning", "reminders"], "updated_at": null}
```
Writes nothing. `updated_at` is `null` until the first save.

### `PUT /v1/me/notification-preferences` → 200 (same shape)
Body, all three fields required, unknown fields rejected (422):
```json
{"push_enabled": true, "muted_categories": ["reminders"],
 "quiet_hours": {"start": "20:00", "end": "07:30"}}
```
`quiet_hours` may be `null`; times are `HH:MM` wall-clock in `time_zone`; the
window may wrap midnight; `start` ≠ `end`. Full replacement, safe to repeat.
Creates the caller's learner profile on first contact, like `GET /v1/me`.

### `GET /v1/notifications?cursor=&limit=` → 200
```json
{"items": [{"id": "…", "kind": "daily_word_available", "category": "learning",
            "refs": {"word_id": "…"}, "available_at": "…", "expires_at": null}],
 "next_cursor": null}
```
Newest first (`available_at` desc). `limit` 1–50, default 20. `next_cursor` gets
**older** items; to see new ones, ask again without a cursor. Only the caller's
own rows whose channel policy includes `in_app`, that are due and not expired.
No title, no body: the app renders the words from `kind` + `refs`.

| HTTP | `code` | When |
|---|---|---|
| 401 | `unauthenticated` | as everywhere |
| 404 | `not_found` | flag off |
| 422 | `validation_error` | bad body / `limit` / over-long cursor |
| 422 | `notification_cursor_invalid` | cursor unreadable or from another account → restart without a cursor |
| 503 | `notifications_unavailable` (`Retry-After: 30`) | any database trouble on these routes. **Not** a reason to stop syncing |

## Python (`services/api/src/edu_api/notify/`)

- `adapter.py` — `build_push_payload` returns exactly
  `{"v": 1, "id": <outbox id>, "kind": <kind>, "refs": {…uuid}}`;
  `assert_content_free` rejects anything else (also called by the sink). Age is
  unknown to the platform, so every recipient is treated as a minor: there is no
  code path that adds a title or body. `DummyLocalAdapter` records in memory.
- `worker.py` — `deliver_due(port, adapter)`: one pass, at-least-once, an adapter
  crash or timeout becomes a retry. `SqlOutboxPort(engine)` is the seam.
- `service.py`, `schemas.py`, `cursor.py`, `routers/notifications.py` — the
  learner routes, on their **own 2-connection pool** (`app.state.notify_db`,
  2 s statement timeout) so a slow `notify` cannot starve lessons and sync.

## Tests (Part A)

| File | Assertions / tests | Covers |
|---|---|---|
| `supabase/tests/240_notify_structure.sql` | 42 | tables, RLS on all, no text columns, grants, EXECUTE lists, search_path, Data API roles |
| `supabase/tests/241_notify_outbox.sql` | 89 | client cannot enqueue/claim/report/erase; dedupe; bounded inputs; no-free-text constraints; preferences; isolation; erasure |
| `supabase/tests/242_notify_delivery.sql` | 105 | quiet hours across Haiti midnight and both DST changes; opt-in/opt-out; lease; backoff; cap; terminal failure; expiry |
| `tests/unit/test_notify_payload_and_cursor.py` | 20 | content-free payload, dummy sink, no network import, worker pass, cursor, strict body |
| `tests/integration/test_notify_api.py` | 13 | flag off = 404; contract; auth; preferences; list; pagination; arbitrary SQL as the API role |
| `tests/integration/test_notify_delivery.py` | 7 | dummy delivery through real functions; opt-out; quiet hours on the real clock; retries to terminal; 8 concurrent passes; erasure |
| `tests/integration/test_notify_isolation.py` | 5 | learning works with `notify` unreachable and with every notify table locked; `/ready`; Data API |

## Decisions taken without the owner (all reversible, all behind the flag)

| Decision | Chosen | Status |
|---|---|---|
| Quiet hours | 21:00–06:00 Haiti time, platform-wide floor | `BLOCKED_BY_OWNER` PO-10 — synthetic |
| Which messages exist | three service kinds from the brief; no marketing | `BLOCKED_BY_OWNER` PO-10 |
| Push default | off; the learner's own switch turns it on | `BLOCKED_BY_OWNER` PO-04/PO-10 — whether a minor's own switch is sufficient consent is not decided. Nothing is sent either way |
| May a learner shorten the platform quiet window | no (own window only adds) | `BLOCKED_BY_OWNER` PO-10 |
| Retry bounds | 5 attempts, 60 s base, 1 h cap | engineering default |
| Wording of notifications (fr/ht) | none stored server-side; app renders | Creole wording pending native-speaker review (plan §7) |

## Deviations from the brief

1. **Resolved by ruling R-01** (was: routes mounted only when the flag is on).
   The routes are now always registered and kept out of the OpenAPI document by
   `INCLUDE_IN_SCHEMA = False`.
2. **No `notify.push_tokens` table** (Platform-00 doc 04 lists one). The brief
   forbids device tokens tonight; the table belongs with the first real channel.
3. **Extra table `notify.delivery_attempts`, `notify.kinds`, `notify.policy`.**
   The brief names three tables; the attempt log is separate from the per-channel
   state so that retry state is one row and history is append-only.
4. **Foreign keys to `app.learner_profiles`** (not `auth.users`). Nothing is
   created in `app`; the 209 baseline assertions are unchanged. No foreign key
   points at any of the five learning tables (ruling R-02).
5. **`edu_api` gained privileges in `notify`** (USAGE, SELECT on four tables,
   EXECUTE on `set_preferences`). Its privileges in `app` are untouched.

## Known gaps

- No worker process, no schedule, no real channel, no device tokens.
- No audit event on preference change or erasure (`ops.audit_write` not present).
- No "read/unread" state and no way to dismiss an in-app item.
- No retention job: outbox rows and attempt logs grow until `erase_learner`.
- `deliver_after` further than 90 days ahead is refused by `enqueue`.
- Delivery is at-least-once (a crash between adapter success and the report
  repeats the push); the payload carries the notification id for de-duplication
  on the device, which no client implements yet.
- The in-app list and preferences are not part of offline sync; the app must
  cache them itself.
- Quiet hours use one product time zone; a learner abroad gets Haiti hours.

---

# Part B — security and operations basics

Everything here is **opt-in and off by default**. With default settings no
middleware is added, no handler is installed, and the API behaves exactly as on
`main` (asserted by `test_default_settings_have_no_limiter_at_all` and
`test_default_settings_leave_logging_exactly_as_it_was`: the middleware stack is
still exactly `RequestIdMiddleware`, `BodyLimitMiddleware`).

## Rate limiting — `services/api/src/edu_api/ratelimit.py`

A token bucket per key, in the memory of one API process.

| Setting (`EDU_…`) | Default | Meaning |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `false` | Master switch |
| `RATE_LIMIT_READ_BURST` / `_READ_PER_MINUTE` | 60 / 240 | Verified learner, safe methods (`GET` …) |
| `RATE_LIMIT_WRITE_BURST` / `_WRITE_PER_MINUTE` | 20 / 60 | Verified learner, other methods except sync push |
| `RATE_LIMIT_SYNC_PUSH_BURST` / `_SYNC_PUSH_PER_MINUTE` | 40 / 120 | Verified learner, `POST /v1/sync/push` (40 × 50 ops = a 2000-operation backlog at once) |
| `RATE_LIMIT_ANONYMOUS_BURST` / `_ANONYMOUS_PER_MINUTE` | 30 / 60 | Any request **without a verified token**, per client address, all routes together |
| `RATE_LIMIT_MAX_KEYS` | 20000 | Buckets kept in memory; least recently used are dropped |
| `RATE_LIMIT_TRUSTED_PROXY_HOPS` | 0 | 0 = ignore `X-Forwarded-For`; N = trust the N-th entry from the right |

The numbers are engineering placeholders, not measured against real usage.

- **Key = verified principal.** The middleware verifies the access token itself
  (same verifier, cached keys). Only a token that verifies is counted per
  learner. An unverified token is never a key: a forged token naming another
  learner cannot spend that learner's budget, and invented subjects do not mint
  new buckets — such requests share the address's `anonymous` bucket.
- **`/health` and `/ready` are never limited.**
- **429** in the standard error shape, code `rate_limited`, with `Retry-After`
  (whole seconds, ≥ 1) and `X-Request-ID`. The request is rejected **before its
  body is read**.
- Order: request id → (access log) → rate limit → body limit → routes.

### Client retry contract for sync (so that a limit is never data loss)

1. `429` means **nothing was read and nothing was applied**.
2. Wait at least `Retry-After` seconds (add a little jitter), then send the
   **same batch with the same `op_id`s**. Never drop operations, never generate
   new `op_id`s for them, never split them into different ids.
3. A batch that *was* applied but whose response was lost is answered with
   `replayed: true` per operation — same rule as before, unchanged.
4. Retrying early is harmless: it is refused again and does not push the wait
   further away. `GET /v1/sync/pull` is in a different route class, so a limited
   upload never blocks the download.

`test_a_limited_sync_batch_is_neither_lost_nor_applied_twice` proves 1–4 against
the real sync function (row counts in `practice_attempts` and `sync_receipts`).
The mobile client does not handle `429` yet (native lane to pick up).

### Stated limits — this is not the production limiter

- **Per process, in memory.** N processes or instances give a caller N times the
  budget; a restart forgets everything. **A hosted, multi-instance deployment
  still needs a limiter at the gateway or in a shared store (Platform-02).**
- **Nothing is stopped before it reaches the process**: connection floods, slow
  bodies and TLS cost are a gateway's job.
- **Fails open under key floods.** Above `RATE_LIMIT_MAX_KEYS` the least recently
  used bucket is dropped and its owner starts with a full bucket (bounded memory
  was preferred to unbounded memory; tested).
- **Token verification happens twice** per request when the limiter is on (once
  here, once in the route dependency; about a tenth of a millisecond with a
  cached key). Removing that needs a small change in the shared `deps.py`, which
  this lane does not own.
- **Address-keyed limiting is coarse** behind carrier NAT or a school network.
  It only applies to requests without a valid token; signed-in learners behind
  one address are counted separately (tested). Behind a reverse proxy the socket
  peer is the proxy: set `RATE_LIMIT_TRUSTED_PROXY_HOPS` correctly or all
  anonymous traffic shares one bucket. IPv6 is counted per /64.
- **No per-route cost, no global ceiling, no ban list, no sign-in protection**
  (sign-in goes to Supabase Auth, not through this API).
- `429` is not in the OpenAPI document (the middleware is off by default and the
  committed contract is that of the default app).

## Structured logs — `services/api/src/edu_api/logging_config.py`

| Setting | Default | Meaning |
|---|---|---|
| `EDU_LOG_FORMAT` | `text` | `text` = unchanged. `json` = one JSON line per record + one line per request |
| `EDU_LOG_ACTOR_HASH_KEY` | unset | ≥ 32 bytes. Set = add a pseudonymous `actor` to request lines |

A request line:

```json
{"ts":"2026-11-25T04:05:46.369+00:00","level":"INFO","logger":"edu_api.access",
 "event":"http_request","request_id":"32718726a535461892cd9acf94f82aa9",
 "method":"GET","route":"/v1/lessons/{lesson_id}","status":200,"duration_ms":1.4}
```

- `route` is the route **template**; a request that matched no route (or was
  refused before routing, e.g. 429) is `unmatched`. The raw path and the query
  string are never logged.
- **Never logged:** tokens, any header, request or response bodies, answers,
  names, e-mail addresses, client addresses, the raw user id.
- **Actor: omitted by default; keyed hash when a key is configured** (first 16
  hex digits of HMAC-SHA-256(key, user id), verified tokens only). Reason: a
  user id is personal data about a probably-minor learner, and logs usually have
  wider access and longer retention than the database. The request id is enough
  to follow one request. Following one learner (abuse, a stuck sync) is a real
  need, so it is possible — but only with a key, because an unkeyed hash of an
  id that can be enumerated from the database is reversible by anyone holding
  both. Rotating the key unlinks old logs.
- Exceptions are logged as type + code locations; the exception **message** is
  dropped (it can contain submitted values).
- A redaction filter is a backstop for careless future log calls (bearer values,
  JWT-shaped strings, Supabase keys, e-mail addresses, database URLs).
- Third-party library records are kept from WARNING up only (an HTTP client
  logs whole URLs at INFO). uvicorn's own access log is switched off in JSON
  mode because it prints the raw path and query string.

`tests/integration/test_logging_privacy.py` plants a real token, a forged token,
a project key, an e-mail address, an answer and a name in headers, paths, query
strings, bodies and an exception, and greps the captured output for each of
them, the learner's display name, both user ids, the question id, the `op_id`
and the client address. Checked once against a real local `uvicorn` process too.

Limits: only what goes through Python `logging` is covered — a reverse proxy's
or the platform's own access logs are outside this code and must be configured
separately; the redaction filter is pattern-based and not a guarantee; there is
no log shipping, retention or access policy (Platform-02).

## Health and readiness rules

| Probe | Means | Depends on | Must NOT depend on |
|---|---|---|---|
| `GET /health` | The process is running | nothing | anything |
| `GET /ready` | This process can serve lessons and sync from its database | the **main** database pool (`SELECT 1`, read-only, 3 s) | notifications, billing, rewards, any other optional schema or pool; the Auth key service; any external HTTP call; rate limiting; a token |

Why the Auth key service is not a readiness dependency: already-trusted keys
keep verifying tokens during an outage, and taking instances out of rotation (or
restarting them, which empties the key cache) would turn a partial outage into a
total one. An unknown key still fails closed with 503 on the request itself.

Rule for every later lane: **a new optional domain gets its own pool and its own
503; it is never added to `/ready`.** If an optional domain needs a probe, add a
separate one (e.g. `/ready/notifications`) that no orchestrator uses for routing.

| Rule | Test |
|---|---|
| `/ready` 503 when the main database is down, `/health` still 200 | existing `test_database_outage_has_clear_error_behaviour` |
| `/ready` stays 200 with `notify` unreachable; opens no notify connection | `test_readiness_does_not_look_at_notifications` |
| `/ready` stays 200 with the Auth key service down, limiter on, no token | `test_readiness_depends_on_the_database_and_on_nothing_else` |
| Probes are never rate limited | `test_probes_are_never_limited` |
| Lessons, catalog, sync answer normally with `notify` revoked / locked | `test_learning_answers_normally_when_the_notify_schema_is_unreachable`, `…while_notify_tables_are_locked` |

Not covered: billing and rewards do not exist in this branch, so "learning stays
up when they are down" is a rule for those lanes to test the same way.

## Backup / restore drill

Performed for real on this lane's disposable database; commands, timings, sizes
and limits are in [`operations-drill.md`](operations-drill.md).

## Tests (Part B)

| File | Tests | Covers |
|---|---|---|
| `tests/unit/test_ratelimit_buckets.py` | 19 | burst, refill, cap, no penalty growth, isolation, eviction, route classes, address handling |
| `tests/integration/test_ratelimit_api.py` | 8 | default off; 429 shape; per-learner keys behind one address; forged tokens; probes; sync retry contract; rejected before body; proxy hops |
| `tests/integration/test_logging_privacy.py` | 7 | default unchanged; fields and templates; planted values; exceptions; redaction; actor hash; with limiter + notifications on |
| `tests/integration/test_notify_isolation.py` | +1 (6 in the file) | readiness rules |

## `BLOCKED_BY_OWNER` / not decided here

- Real rate budgets and who operates the gateway limiter (Platform-02).
- Log retention, who may read logs, whether an `actor` pseudonym may be kept at
  all for minors (PO-04; legal).
- Backup policy: objectives, storage location, retention, erasure from backups
  (PO-04; Platform-02).
- Staff second factor: not implemented, not claimed (plan §7).
