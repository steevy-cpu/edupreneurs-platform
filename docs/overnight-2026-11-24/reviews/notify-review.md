# Independent security and integration review — NOTIFY lane

- Reviewed: `overnight/notify-security` at `d960cd3` (notify outbox, learner routes, rate limiter, token-verification memo, JSON logging).
- Reviewer environment: QA worktree `qa2` (own disposable stack), database reset from the reviewed commit. 2026-11-25, 04:39–04:47 EST.
- Method: code read at the reviewed sha; probes as the real `edu_api_login`, `edu_staff_login`, `edu_worker_login`; in-process ASGI probes; one run under real uvicorn in JSON-log mode.

## Verdict: APPROVE WITH FIXES

No CRITICAL or HIGH finding. With default settings the lane changes nothing in the request path. One MEDIUM and one LOW should be fixed before the corresponding opt-in flag is switched on in a hosted deployment; none blocks integration with flags off.

Suites observed at `d960cd3`: pgTAP **641 passed** (11 files), pytest **318 passed**, `make lint` clean, `make typecheck` clean (40 files). Matches the author's report.

## Findings

### MEDIUM

**M-1 — Forwarded-address handling reads only the first `X-Forwarded-For` header line** (`services/api/src/edu_api/ratelimit.py:234-238`, `:292-296`; only when `EDU_RATE_LIMIT_TRUSTED_PROXY_HOPS > 0`).
Class: trust of client-controlled header. HTTP allows a header to arrive as several lines; some proxies add their entry as a new line instead of appending to the existing one. The helper returns the first line only, so in such a deployment the address used for unauthenticated traffic is chosen by the client.
Impact: the per-address budget for unauthenticated/invalid-token requests can be avoided, and the anonymous key store can be filled at will (pushing other unauthenticated callers into the shared overflow bucket). Verified learners are not affected (separate store, keyed by verified id).
Evidence: reproduced in-process with `hops=1` (see private report). A single comma-joined header is handled correctly.
Smallest fix: join all `x-forwarded-for` values, in order, with `,` before taking `entries[-hops]`. Add a unit test with two header lines.

### LOW

**L-1 — JSON log mode still records client address, raw path and query string for WebSocket upgrade attempts** (`services/api/src/edu_api/logging_config.py:113-118`, `:171-177`).
uvicorn's own loggers are kept from INFO and only re-formatted. uvicorn writes an INFO record containing the peer address and the full request target for every WebSocket handshake it refuses. The module documents that raw paths, query strings and client addresses are never logged; in this case they are. The redaction backstop removes token- and e-mail-shaped strings only.
Impact: any unauthenticated caller can put arbitrary text and their address in the log. No legitimate client uses WebSockets, so learner data does not reach the log by itself; the stated guarantee is nevertheless false.
Evidence: reproduced under real uvicorn with `EDU_LOG_FORMAT=json` (see private report). All HTTP cases tried were clean (route template only, no body, no query, no token, no validation detail; invalid HTTP line logged without content).
Smallest fix: keep `uvicorn*` records from WARNING up as for other third parties (or allow-list the lifecycle messages), and/or run the server with WebSockets disabled. Add a test that drives a real uvicorn instance.

**L-2 — Delivery pass can attempt a delivery after its lease has run out** (`services/api/src/edu_api/notify/worker.py:151-156`).
All claimed rows share one lease clock (default 60 s) but are attempted one after another, each with a timeout of half the lease. After two slow attempts every remaining lease has expired while this pass still sends them; another pass can lease the same rows: duplicate push and attempts spent as `lease_lost`. Quiet hours are evaluated at claim time only, so a push can also leave up to one lease later than the window start. Latent: only the in-memory dummy adapter exists.
Smallest fix: before each attempt, skip rows whose remaining lease is shorter than the timeout (or claim one row at a time).

**L-3 — With the notifications flag off, two requests are not answered with the standard 404** (`services/api/src/edu_api/routers/notifications.py:3-5`, `:71-75`).
A `PUT /v1/me/notification-preferences` whose body is not valid JSON gets 422, and a wrong method on a notification path gets 405; an unknown path gets 404. The body IS looked at before the flag (the framework parses JSON before dependencies run). Reveals only that the route exists (the repository is public); contradicts the docstring and ruling R-01's "standard 404".
Evidence: reproduced in-process (table in private report). All other flag-off cases return the same 404 body as an unknown path, before authentication; the paths are absent from `/openapi.json`.
Smallest fix: decide the flag before body parsing (e.g. a custom `APIRoute` class for this router, or do not match the routes when the flag is off); add the two cases to the flag-off test.

**L-4 — One address-wide bucket for everything without a valid token (judgement on carrier NAT)** (`ratelimit.py:328-330`; defaults 30 burst, 60/min).
Verified learners behind a shared address are NOT affected — confirmed: with the address bucket empty, a request with a valid token from the same address is served. But a learner whose token has expired (the normal state after hours offline) is counted in the shared bucket and receives 429 instead of the 401 that tells the app to refresh. Behind carrier NAT, which is the norm in Haiti, one device sending one unauthenticated request per second keeps that bucket empty for everyone on the address.
Impact: depends on the mobile client. If it refreshes its session only on 401, such learners cannot recover while the flood lasts. The lane's document already says the client does not handle 429 yet.
Smallest fix (hand-over to the native lane, before the flag is enabled): refresh the session from the token's own expiry time, and on a 429 when the local token is past expiry; keep the limiter flag off until then.

**L-5 — Verified-store exhaustion moves NEW learners to one shared bucket** (`ratelimit.py:150-165`).
If the verified store is full of buckets that are not yet refilled, a learner without a bucket shares one overflow bucket (anonymous budget) with every other such learner. Needs on the order of `max_keys/2` real accounts kept busy (measured: 10 000 accounts, about 10 000 requests/s sustained with defaults). Existing learners keep their buckets; it recovers by itself within the refill time. "Never fails open" holds. Mass sign-up control belongs to the Auth side; `overflowed` is counted but exported nowhere.
Smallest fix: none required now; export the counter and size `max_keys` to several times the active learner count.

### NOTE

- **N-1 Memo window.** `MemoVerifier` can return a principal for up to 2 s after the real verifier would start refusing the same token (expiry, key withdrawn). Bounded and by design; see "verified sound".
- **N-2** The 429 body has the standard error shape but different JSON whitespace from every other error (`json.dumps` defaults, `ratelimit.py:340`). Cosmetic.
- **N-3** `notify/worker.py:7-14` docstring is stale: it says the worker grants do not exist yet; migration `20261124080200` grants them.
- **N-4** `tests/integration/test_notify_isolation.py` revokes `USAGE ON SCHEMA notify` from `edu_api` (committed) and restores it in `finally`. A hard kill between the two leaves the database with notification routes at 503 until `make db-reset`.
- **N-5** `notify.erase_learner` leaves an audit event whose target is the erased learner's id; log lines keep the actor pseudonym until the key is rotated. Both are cross-lane conventions — the identity lane should confirm they are intended.
- **N-6** "No free text" holds for every client- and worker-reachable path. It rests on review for one thing: `notify.kinds.kind` accepts any 3–41 character lower-case code, so a future migration could add a sentence-like kind. Reference values are canonical UUIDs (opaque, not human-readable).
- **N-7** Baseline property, not introduced here: SQL as `edu_api_login` may set `edu.actor_id` itself, and then sees that learner's in-app rows and may set that learner's preferences. Isolation between learners is enforced for the API (verified token), not against the login itself.
- **N-8** A learner whose own quiet window plus the platform window covers the whole day never receives a push; without `expires_at` the delivery stays `pending` indefinitely (re-examined once per window). Harmless, grows slowly.
- **N-9** With `hops=0` behind any reverse proxy, or on a socket without a peer address (`a:unknown`), all unauthenticated traffic shares one bucket. Documented in substance; worth one explicit line in the operations document.
- **N-10** `PUT preferences` calls `ensure_learner_profile` inside the notify transaction: for a learner's very first request, a stalled notify statement can hold the uncommitted profile insert for up to the 2 s statement timeout, delaying that same learner's concurrent first learning request by the same bound. Other learners are unaffected.

## Verified sound (tried to break, could not)

Priority 1
- Default settings: middleware stack is exactly `RequestIdMiddleware`, `BodyLimitMiddleware`; `app.state.token_verifier` is the plain `TokenVerifier`; no limiter, no JSON handler, no `notify_db` attribute (no second pool object at all). `main.py` diff read line by line: the only default-path changes are the staff lane's router/pool and the always-registered notification router.
- Memo: failures are never stored (invalid token after a valid one is refused, table unchanged); the key is the SHA-256 of the whole token, so another token cannot receive a stored principal; one memo wraps one verifier instance, so issuer/audience/algorithm settings cannot differ; no sliding window (age counted from the real verification); table capped at 2048 (5000 distinct valid tokens → 2048 entries); only installed when the limiter or the actor key is on.
- Limiter keys: only a token that verifies creates a learner key; junk, malformed, oversized, non-ASCII and wrong-scheme `Authorization` values all behave exactly as on the default app (401) and are counted by address. With `hops=0` the forwarded header is ignored. IPv6 counted per /64.
- 429: standard error shape with `request_id`, `Retry-After` ≥ 1, `Cache-Control: no-store`; produced without calling `receive` (body never read). `/health` and `/ready` are the only exemptions (`/docs`, `/health/` are limited).
- Bounded memory: stores never exceed `max_keys`; a flood cannot evict or reset a limited bucket; anonymous flood cannot touch the verified store.
- `take()` contains no `await`: atomic on one event loop. Per-process scope is stated plainly in the module, the config comment and the lane document.
- Isolation of learning from notify: separate pool (size 2, no overflow, 1 s pool timeout), statement and lock timeout 2 s; author's locked-table and unreachable-schema tests pass.

Priority 2 (as the real logins)
- `edu_api_login`: no actor → 0 rows; another learner's rows and preferences invisible; `dedupe_hash`, `deliveries`, `delivery_attempts` denied; INSERT/UPDATE/DELETE on every notify table denied; `enqueue`, `claim_due`, `record_attempt`, `erase_learner`, `_settle`, `_claim_due_at`, `quiet_until` denied; `set_preferences` refuses without an actor and writes only the actor's row; TEMP tables denied.
- `edu_staff_login`: no USAGE on the schema — everything denied.
- `edu_worker_login`: only `enqueue`, `claim_due`, `record_attempt`; no table access, no explicit-clock twins, no erase, no preference change; limit and channel validated; free-text error code refused.
- Free text: refused through refs (text value, unknown key, upper-case UUID, nested object, trailing newline, array), through kind, through a direct owner INSERT (CHECK), and through the dedupe column (must be a 32-byte digest).
- Claim under concurrency: 8 parallel sessions, 400 due rows → 400 leases, 0 duplicates, 0 errors, none left behind.
- Retry: 60/120/240/480 s backoff, terminal `failed/max_attempts` at attempt 5, outbox `settled`, stale token → `stale`, nothing re-claimed. Lease expiry: 5 `lease_lost` attempts then `failed/lease_expired`. Dedupe: same key returns the same id, one row.
- Preferences at delivery time: opt-out → `suppressed/push_not_enabled`; muted category → `suppressed/category_muted`; no row = off.
- Quiet hours (Haiti zone): 20:59:59 allowed, 21:00 → 06:00 next day, 23:59:59 and 00:00 → 06:00, 05:59:59 → 06:00, 06:00 allowed; spring-forward and fall-back nights end at 06:00 local; a window ending in the skipped hour and one in the repeated hour never produce an end in the past.
- Push payload: `v`, `id`, `kind`, `refs` only, validated twice; no recipient id, no title/body. No network library is imported anywhere in the lane's code.
- Erasure: `erase_learner` removed all 404 outbox rows, deliveries, attempts and the preference row; the profile could then be deleted.

Priority 3
- JSON mode over real HTTP: access line carries route template only; planted names, answers, phone-like digits, tokens and cursor text in path, query, body and headers did not appear, including 401, 422 and malformed-request paths. Exceptions are reduced to type and locations. `actor` is present only when a key (≥ 32 bytes) is configured.

Priority 4
- All 11 `notify` functions: `SET search_path = pg_catalog, pg_temp`, owner `postgres`, EXECUTE revoked from PUBLIC; grants exactly as documented. RLS enabled on all 6 tables. Nothing created in schema `app`. Only four pre-existing files are modified (`.env.example`, `scripts/local_stack.py`, `config.py`, `main.py`); no earlier migration touched. No secret in the diff. Router always registered, hidden from OpenAPI by the one constant.

## Missing tests

- Forwarded header split over several lines (M-1).
- JSON logging under a real uvicorn server, including a WebSocket handshake (L-1).
- Flag off: malformed JSON body and wrong method (L-3).
- Delivery pass where the adapter is slower than the lease (L-2).
- Concurrent `claim_due` from several sessions (sound when probed, but not covered by the suites as far as read).
- Valid-token learner still served while the address bucket is empty (sound when probed; the property the NAT judgement rests on).

## Not examined

Mobile client; the staff lane's code and `scripts/local_stack.py` beyond the fact of the diff; `operations-drill.md` and `notify.md` line by line (searched for the per-process and NAT statements only); the body of every test (names, destructive steps and clock use were checked); behaviour with several OS worker processes; the JWKS cache; Data API exposure of `notify` (author's test passes, not re-probed); performance.
