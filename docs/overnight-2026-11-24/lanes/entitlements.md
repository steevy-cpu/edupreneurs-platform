# Lane ENTITLEMENTS — grant model, read API, mock provider, offline-lease specification

Branch `overnight/entitlements` · schema `billing` · migrations `2026112407xxxx_*` · pgTAP `220–223`.
Status of this document: describes what is **built and tested locally** on a disposable stack with
synthetic accounts. Nothing here was deployed, linked to a hosted project, or run against real data.

**There is no paywall.** No lesson, catalogue or sync code path reads `billing`. No payment provider
is contacted, no provider SDK is installed, no price has been decided.

## 1. What exists

| Piece | Where | State |
|---|---|---|
| `billing` schema: 8 tables, RLS, guards | `supabase/migrations/20261124070100_billing_schema.sql` | tested (pgTAP 220–223) |
| Functions, policies, grants, staff seam | `supabase/migrations/20261124070200_billing_functions.sql` | tested (pgTAP 220–223) |
| `GET /v1/entitlements` (flag `EDU_ENTITLEMENTS_ENABLED`, default **off**) | `services/api/src/edu_api/routers/entitlements.py`, `edu_api/billing/` | tested through the real API with real local Auth tokens |
| Simulated provider (pure, in-process) | `services/api/src/edu_api/billing/mock_provider.py` | unit + integration tested |
| Staff grant / revoke / list | `billing.staff_*` SQL functions | tested at SQL level; **EXECUTE granted to nobody**; no HTTP route yet |
| Offline lease | section 6 of this file | **specification only — nothing implemented** |

Not built: HTTP staff routes (`/v1/staff/billing`, waits for the staff lane's B1), checkout, any
real provider, entitlement-aware catalogue or pack download, lease signing or verification.

## 2. Model

```
billing.providers                who may send payment events          (no row ships; tests add 'mock')
billing.plans / plan_prices      scope + duration / price per currency (no row ships; tests add synthetic ones)
billing.orders                   one attempt to pay: plan, expected amount, provider, state
billing.provider_events          every provider message, raw, UNIQUE (provider, provider_event_id)
billing.refunds                  one row per refunded order
billing.entitlements             ONE ROW PER GRANT — never edited
billing.entitlement_revocations  revocation is a new record, one per grant
```

- **Money** is `bigint` minor units + a 3-letter currency code everywhere. A test fails if a
  `numeric`, floating-point or `money` column appears in the schema. A missing price in a currency is
  refused, never converted.
- **Scope** is `all` | `grade` (+ grade id) | `course` (+ course id), on plans and on grants, from day
  one. Matching: an `all` grant covers everything; a grade grant covers that grade and every course
  of it; a course grant covers that course only; a request for `all` needs an `all` grant.
- **Active** means `starts_at <= t < ends_at` (half-open: at exactly `ends_at` the grant is over) and
  no revocation. Overlapping grants are allowed; access is *any* active grant. Extending is adding a
  row. A day of a grant is exactly 24 hours (no time-zone or daylight-saving arithmetic).
- **Idempotency**: `entitlements.idempotency_key` is UNIQUE. Same key + same request returns the
  *original* grant (original dates) with `replayed: true`; same key + a different learner, scope,
  source or duration returns `conflict` and writes nothing. A purchase grant is additionally unique
  per order.
- **Sources**: `purchase` (only from a verified provider event), `gift`, `promo`, `school_licence`,
  `trial`, `staff_grant`, `migration`.
- **History guards** (triggers, apply to the owner too): grants and revocations cannot be updated or
  deleted; provider events and refunds cannot be changed; an order's plan, provider, amount and
  currency never change and its state only moves forward (`pending → paid|failed|refunded`,
  `failed → paid|refunded`, `paid → refunded`). The only exception is the erasure hook.

### Who can do what

| Role | In `billing` |
|---|---|
| `edu_api` (student API) | `USAGE`; `SELECT` on 8 columns of its **own** grants and 2 columns of their revocations (RLS); `EXECUTE` on `billing.is_entitled`. No write privilege, no other function |
| `PUBLIC`, `anon`, `authenticated`, `authenticator`, `service_role` | nothing (schema not exposed in the Data API **and** no privilege) |
| anyone else | nothing. Every function that grants, revokes, orders, applies an event or erases is executable by its owner only |

"No client request can create or extend a grant" is therefore a privilege fact. It is tested with
arbitrary SQL on the API's own connection, through every HTTP verb, through sync, and through the
Supabase Data API with the publishable key, a learner token and the secret service key.

### Functions

| Function | EXECUTE | Purpose |
|---|---|---|
| `billing.is_entitled(p_scope_kind text DEFAULT 'all', p_scope_id uuid DEFAULT NULL) → boolean` | `edu_api` | The **caller's** answer now (actor from `app.current_actor_id()`, server clock). STABLE. Nothing calls it to lock content |
| `billing.learner_is_entitled_at(learner, kind, id, at)` | nobody | Internal reader with an explicit time (boundary tests) |
| `billing.grant_entitlement(...)`, `billing.revoke_entitlement(...)` | nobody | Internal writers (exactly-once) |
| `billing.staff_grant_entitlement(p_learner_id, p_scope_kind, p_scope_id, p_duration_days, p_source, p_reason, p_idempotency_key, p_starts_at DEFAULT NULL) → jsonb` | nobody — **awaiting staff wiring** | Role `admin`; sources other than `purchase`; 1–366 days; reason 3–500 characters; not to oneself; audited |
| `billing.staff_revoke_entitlement(p_entitlement_id, p_reason) → jsonb` | nobody — **awaiting staff wiring** | Role `admin`; audited; idempotent; unknown id raises `P0002` |
| `billing.staff_list_entitlements(p_learner_id) → jsonb` | nobody — **awaiting staff wiring** | Role `admin`; every grant with `state` (`active`/`scheduled`/`expired`/`revoked`); audited |
| `billing.create_order(p_plan_code, p_currency, p_provider, p_idempotency_key) → jsonb` | nobody — awaits PO-06 | Order for the **caller**; amount copied from `plan_prices` on the server |
| `billing.apply_provider_event(p_provider, p_provider_event_id, p_event_type, p_payload) → jsonb` | nobody — awaits a webhook role | Exactly-once application (section 5) |
| `billing.erase_learner(p_user_id) → jsonb` | nobody (called by the `account` orchestrator as owner) | Erasure hook (section 7) |
| `billing._require_staff(VARIADIC text[]) → uuid`, `billing._audit(action, target_kind, target_id, outcome, details)` | nobody | **The staff seam** (section 4) |

Staff SQL errors a future HTTP layer should map: `42501` → 403, `22023` → 422, `P0002` → 404;
`status: "conflict"` in the returned JSON → 409.

## 3. `GET /v1/entitlements`

Mounted only when `EDU_ENTITLEMENTS_ENABLED=true`. With the flag off (the default) the route does not
exist (standard 404), `packages/contracts/openapi.json` is byte-identical to `main`, and the API
behaves exactly as before. Because the generated contract is produced with flags off, **this route is
not in `openapi.json` / `schema.d.ts` yet**; the contract below is asserted by
`tests/integration/test_billing_entitlements_api.py` against the live OpenAPI document with the flag on.

Request: `GET /v1/entitlements` with `Authorization: Bearer <Supabase Auth access token>`. No
parameters. The learner is the token's subject; query parameters such as `learner_id` are ignored.

`200` (header `Cache-Control: private, no-store`):

```json
{
  "server_time": "2026-11-24T05:12:33.123456Z",
  "free_content_always_available": true,
  "entitlements": [
    {
      "id": "0b9f2f4e-5f2b-4c1e-9a57-1d6c0e8a4f10",
      "scope": {"kind": "grade", "id": "b0000000-0000-4000-8000-000000000001"},
      "starts_at": "2026-11-24T05:00:00Z",
      "ends_at": "2027-02-22T05:00:00Z",
      "source": "school_licence"
    },
    {
      "id": "6c1d7a52-8a0e-4f43-b0c9-52b7f6f3a2d1",
      "scope": {"kind": "all", "id": null},
      "starts_at": "2026-11-24T05:00:00Z",
      "ends_at": "2026-12-24T05:00:00Z",
      "source": "staff_grant"
    }
  ]
}
```

- `entitlements`: the caller's own grants that are active **now** — started, not expired, not
  revoked — latest `ends_at` first. Future, expired and revoked grants and other learners' grants are
  never listed. Overlapping grants are all listed. At most 200 items.
- `scope.kind` ∈ `all` | `grade` | `course`; `scope.id` is the grade or course id, `null` for `all`.
- `source` ∈ `purchase` | `gift` | `promo` | `school_licence` | `trial` | `staff_grant` | `migration`.
- `ends_at` is exclusive. Compare it with `server_time`, never with the device clock.
- `free_content_always_available` is the constant `true` (OpenAPI `const: true`).
- Internal fields (idempotency key, source reference, order id, who granted) are not returned; the
  API's database role cannot even read those columns.

Errors (always the standard shape `{"error": {"code", "message", "request_id"}}`):

| HTTP | `code` | When | What the app should do |
|---|---|---|---|
| 401 | `unauthenticated` | Token missing, expired or invalid | Refresh the token |
| 404 | `not_found` | The flag is off (route not mounted) | Treat as "no entitlement feature"; everything is free |
| 405 | `method_not_allowed` | Any verb other than GET | A client bug |
| 503 | `entitlements_unavailable` (`Retry-After: 30`) | The `billing` schema cannot be used by the API | Keep the last known status; free content is unaffected; retry later |
| 503 | `dependency_unavailable` (`Retry-After: 5`) | Database or Auth key service unreachable | Retry later |
| 500 | `internal_error` | Unexpected error | Retry later |

## 4. The staff seam

`billing.staff_*` call exactly two internal functions, marked `>>> STAFF SEAM` in the migration:

- `billing._require_staff(VARIADIC p_roles text[]) → uuid` — today: an active row in
  `app.staff_roles` for `app.current_actor_id()`, else `42501`.
- `billing._audit(p_action, p_target_kind, p_target_id, p_outcome, p_details)` — today: inserts into
  `app.audit_events` as the function owner (actor from `app.current_actor_id()`; `actor_kind` is
  `staff`, `user` or `system`).

Wiring after the staff lane's B1 is merged (a follow-up migration in this lane's block, e.g.
`20261124070300_billing_staff_wiring.sql`):

1. `CREATE OR REPLACE` the two bodies with `RETURN staff.require_role(VARIADIC p_roles);` and
   `PERFORM ops.audit_write(p_action, p_target_kind, p_target_id, p_outcome, p_details);`
2. `GRANT USAGE ON SCHEMA billing TO edu_staff;` and `GRANT EXECUTE` on the three `billing.staff_*`
   functions to `edu_staff`.
3. Add `routers/staff_billing.py` under `/v1/staff/billing` with `require_staff("admin")`.
4. Update the two pinned lists in `supabase/tests/220_billing_structure.sql` ("no other role can
   execute any billing function").

Audit actions written: `billing.entitlement.grant` (outcome `allowed`, or `denied` for an idempotency
conflict), `billing.entitlement.revoke`, `billing.entitlement.list`,
`billing.provider_event.entitlement_granted`, `billing.provider_event.order_refunded`.

## 5. Provider events and the simulated provider

`billing.apply_provider_event` treats every call as an authentic message (the caller verified the
signature), stores it raw with a decided outcome, and applies it at most once:

| Situation | Outcome | Effect |
|---|---|---|
| Same event id, same content | stored outcome, `replayed: true` | none |
| Same event id, different content or type | `conflict` | none, nothing stored |
| Unknown order, or an order of another provider | `rejected / unknown_order` | none |
| Amount, currency or plan differs from the order | `rejected / amount_mismatch` · `currency_mismatch` · `plan_mismatch` | none; order stays as it was |
| Amount not an integer JSON number, missing fields | `rejected / malformed_payload` | none |
| `payment.succeeded` on a pending or failed order | `applied / entitlement_granted` | order `paid`; one `purchase` grant of the plan's scope for `duration_days × 24 h` from the server clock |
| `payment.succeeded` on a paid order | `ignored / order_already_paid` | none |
| `payment.failed` on a pending order | `applied / order_failed` | order `failed` |
| `payment.failed` on a paid order (stale) | `ignored / order_already_paid` | none |
| `payment.refunded` on a paid order | `applied / order_refunded` | order `refunded`; grant revoked (reason `refund`); refund row |
| `payment.refunded` before the payment message (out of order) | `applied / order_refunded` | order `refunded`; the late payment message is then `ignored / order_already_refunded` |
| Anything on a refunded order | `ignored / order_already_refunded` | none |
| Unknown event type | `ignored / unsupported_event_type` | none |
| Provider not registered or not enabled | SQL error `42501` | none, nothing stored |

Concurrent deliveries are serialised per event (advisory lock) and per order (row lock); tested with
20 simultaneous deliveries of one message and with 6 different success messages for one order.

### The simulated provider and how it is kept out of non-local environments

`edu_api.billing.mock_provider` is pure Python (standard library only): it builds and verifies
HMAC-SHA256-signed message bodies and, if a message is authentic, hands it to a *sink* supplied by the
caller. Four independent layers keep it away from any hosted environment:

1. **No route.** No HTTP route receives a provider message in any environment, with any flag. (The
   brief allowed a route in `local`/`test`; none was mounted — see Deviations.) Tested against the
   OpenAPI document for `local`, `test`, `staging` and `production`.
2. **Constructor guard.** `MockProvider(secret, environment=…)` raises `SimulatedProviderDisabled`
   unless the environment is exactly `local` or `test`.
3. **No capability in the API process.** The module holds no database connection and ships no sink.
   The API's role has no `EXECUTE` on `billing.apply_provider_event`; a test builds a sink on the
   API's own connection and PostgreSQL refuses it (`42501`). The only sink that works is test code
   connected as the owner of the disposable local database.
4. **No provider row.** The database only accepts events for a provider that is registered and
   enabled in `billing.providers`. No migration and no seed registers one; tests insert `mock` and
   remove it again. Synthetic plans can only be ordered through a simulated provider, and a simulated
   provider can never pay for a non-synthetic plan.

The signing secret is `secrets.token_bytes(32)` generated per test; it is never read from
configuration, logged, or written to a file. A unit test parses the package and fails on any import of
a network library or payment SDK.

## 6. Offline lease — SPECIFICATION ONLY (not implemented; security design not approved)

Nothing in this section exists in code. No key was generated, no statement is signed or verified.
It is written so that a security review can approve, change or reject it before any implementation.

### 6.1 Purpose and honest limits

The phone cannot ask the server while offline. At each successful sync the server gives the app a
short signed statement of what the learner may open, and the app honours it for a bounded time.

The phone belongs to the learner. A determined person with a modified app or a rooted phone can read
downloaded content regardless of any lease. The lease is **an honesty mechanism with a bounded
exposure window, not copy protection**. Its job: an expired, refunded or revoked entitlement stops
working at most one lease length after the last sync on an unmodified app, and nobody can *mint*
access (that needs the server's private key).

### 6.2 The statement

A compact signed token (recommended: JWS compact serialisation, algorithm ES256 — the backend
already depends on `pyjwt[crypto]`, so no new server dependency; the device-side verifier needs a
reviewed library choice). Claims:

| Claim | Meaning |
|---|---|
| `v` | Format version (`1`). An unknown version is treated as "no lease" |
| `kid` (header) | Which signing key |
| `jti` | Lease id (uuid), for support and audit |
| `sub` | Learner id. A lease for another account is ignored |
| `iat` | Server time of issue, `T` |
| `exp` | `min(latest coverage end among scopes, T + lease length)` |
| `scopes` | List of `{kind, id, until}`: for each scope the learner holds, the end of **continuous** coverage starting at `T` (active grants and grants that start before the current coverage ends are merged; revoked grants do not count) |
| `free` | Constant `true`: free content never depends on the lease |

The app honours a scope until `min(until, T + lease length)`. Lease length is PO-07 (suggested 30
days) — a server setting, never a client value.

The server always answers an authenticated refresh with a lease, including an **empty one**
(`scopes: []`) when nothing is active. The app replaces the stored lease on every successful
(HTTP 200, signature valid) refresh, and keeps the previous lease on any failure (offline, 5xx, bad
signature) — a failed refresh must never shorten or extend access.

Open point for the review: bind the lease to one app installation (`device` claim checked against an
install id). It stops copying a lease file between phones but adds a device registry and a personal
identifier; the recommendation is **not** to bind in v1.

### 6.3 Keys

- A dedicated signing key pair, separate from the Auth service's token key. The private key lives
  only in the hosting platform's secret manager and in the API process memory; never in the
  database, the repository, a log line or an error message. The API signs; nothing else can.
- The app verifies with a **public key set pinned in the app bundle** (`kid → key`). Only asymmetric
  algorithms are accepted, and the algorithm is fixed by the app, not read from the token header
  (same rule as the API's token verifier). An unknown `kid`, a wrong algorithm or a bad signature
  means "no new lease": the old one is kept.
- **Rotation**: the next public key ships in an app release *before* the server starts signing with
  it (the bundle always holds current + next). The server switches after the adoption threshold is
  met; the old public key stays in the bundle for at least one lease length plus a grace period, so
  every lease in the field can still be verified until it expires on its own.
- **Compromise**: a release removes the compromised `kid`. Affected learners get a fresh lease at
  their next sync. Worst case for an honest learner: paid content locks until they sync once; free
  content is never affected. A leaked signing key lets an attacker mint leases for modified or old
  apps until those apps update — which is why the key is separate, short-lived (rotate at least
  yearly) and why server-side pack downloads must keep checking the real grant.
- Fetching keys from the network instead of pinning them is rejected for v1: whoever controls the
  connection or a proxy setting could supply their own key.

### 6.4 Time and clock rollback

The device clock is untrusted. The app keeps, per account, in protected storage:

- `T` (server time from the lease) and the lease itself;
- a monotonic anchor: the device's elapsed-since-boot counter at the moment the lease was stored,
  with a boot identifier;
- a high-water mark: the largest "effective now" it has ever computed.

`effective_now = max(high-water mark, T + elapsed since the anchor [same boot only], wall clock)`.
The high-water mark only moves forward between syncs and is reset to the server's `T` at every
successful refresh (the server is the authority, so a phone whose clock was wrongly set to the far
future recovers by syncing).

- Clock set **back**: the wall clock is below the high-water mark, so it is ignored. Access is not
  extended.
- Clock set **forward**: the lease looks expired early. Paid content locks until the next sync; the
  message says so; free content is unaffected. Accepted as the safe failure.
- Reboot: the monotonic anchor is lost; the high-water mark still holds. After a reboot, time spent
  with the clock held back cannot be measured — a learner who keeps the clock frozen can stretch a
  lease on that device until the next sync. Known and accepted residual risk: the gain is bounded by
  the fact that every sync replaces the lease, and it is detectable server-side only as "has not
  synced for longer than the lease length".
- The server never trusts a device-reported time for any entitlement decision.

### 6.5 What the phone does

| Situation | Paid content | Free content | Downloaded files |
|---|---|---|---|
| Lease valid | open | open | kept |
| Lease expired or absent, offline | **locked**, with a clear message that going online once restores access | **open — always** | **kept on the phone**, not deleted |
| Next successful sync, grant still active | unlocks immediately (new lease) | open | kept, no re-download |
| Next sync, grant revoked / refunded / expired | locked; the message offers the next step, never a dead end | open | kept (decision needed on eventual cleanup) |
| Signed out / another account signs in | that account's own lease applies | open | per-account storage rules of the app |

Further rules: sync is never blocked by lease state (work done offline is still uploaded and
accepted); the app never deletes content because a lease lapsed; a lesson already open when the
lease lapses can be finished (recommendation, needs product confirmation); lock messages are written
in French and Haitian Creole and reviewed by a native speaker before release.

Server side (future, behind its own flag, default off): a lease endpoint for the signed-in learner
that reads the same rows as `GET /v1/entitlements`; pack download for paid packs checks the real
grant, not the lease.

### 6.6 Test list for the future implementation

Server:
1. Lease for a learner with no grant has `scopes: []` and a valid signature.
2. `exp` = `min(coverage end, T + lease length)` for: one grant shorter than the lease, one longer,
   overlapping grants, back-to-back grants, a gap between grants, a revoked grant in the middle.
3. A revoked or refunded grant is absent from the next lease.
4. Only the caller's grants appear; no parameter selects another learner.
5. The private key is absent from responses, logs, error bodies and the OpenAPI document; the API
   refuses to start with a missing or symmetric lease key.
6. Rotation: leases signed with the old and the new key both verify against a bundle holding both.
7. Lease endpoint unavailable or billing unreachable → learning endpoints unchanged.

Device (unit tests with an injected clock, plus device tests in airplane mode):
8. Valid lease → paid opens offline until exactly `min(until, T + lease length)`, locks at that instant.
9. Free content opens with no lease, an expired lease, a corrupt lease, a lease for another account.
10. Tampered payload, wrong key, unknown `kid`, algorithm `none` / symmetric algorithm, unknown `v`
    → rejected; the previous lease is kept unchanged.
11. Failed refresh (offline, 5xx) neither shortens nor extends the stored lease.
12. Empty lease from the server replaces a previously valid one (revocation takes effect at sync).
13. Clock moved back by a day / a year → no extension. Clock moved forward past expiry → locks, and
    unlocks after a sync without re-downloading.
14. Reboot with the clock held back → access is bounded by the high-water mark.
15. Downloaded files are byte-identical before lock, during lock and after unlock.
16. Offline work done before and after the lease lapsed is accepted at the next sync.
17. Account switch on one phone: each account sees only its own lease state.
18. Lock message present in `fr` and `ht`, with a working "go online" path.

## 7. Erasure hook

`billing.erase_learner(p_user_id) → jsonb` (EXECUTE: nobody; the `account` orchestrator calls it as
owner). It deletes the learner's grants and their revocations, sets `learner_id = NULL` on their
orders (amount, plan, state and dates are kept), and blanks the raw payload of every provider event
linked to those orders. Returns, for example:

```json
{"schema": "billing", "entitlements_deleted": 2, "revocations_deleted": 1,
 "orders_anonymised": 0, "provider_event_payloads_blanked": 0}
```

It is idempotent, leaves other learners untouched, and afterwards the `auth.users` row is no longer
referenced by `billing` (tested by deleting a billing-only synthetic account). A payment message for
an erased order is ignored (`order_erased`).

## 8. Decisions that are not engineering's (`BLOCKED_BY_OWNER`)

| Id | Question | Synthetic default used tonight |
|---|---|---|
| PO-01 | Free or paid launch | No paywall. Nothing reads `billing.is_entitled` |
| PO-05 | What paying unlocks | `scope` modelled as all / grade / course; no real plan exists. Test plans are flagged `is_synthetic` and named `synthetic-*` |
| PO-05 | Prices and currencies | None. Test amounts (e.g. 50 000 minor units "HTG") are fixture numbers, not prices |
| PO-06 | Checkout from the app, provider choice | `create_order` and `apply_provider_event` exist but are executable by nobody; only the simulated provider's tests reach them |
| PO-07 | Offline lease length | Not implemented; the specification suggests 30 days as a server setting |
| PO-04 / legal | What billing records must be retained after an account is erased, and for how long | Hook keeps amounts and dates without the person; deletes grants |
| PO-13 | Schools | Source `school_licence` exists; no tenant or class model |
| — | Does an early renewal start now or after the current grant ends? | Now (grants may overlap) |
| — | Largest staff grant; may an admin grant to themself | 366 days per grant; self-grant refused |
| — | Partial refunds, chargebacks | Not modelled; a refund must equal the order amount |
| — | Lease design, device binding, verifier library | Specification awaiting security review |
| — | Haitian Creole lock messages | Not written |

## 9. Deviations from the brief, and why

1. **No HTTP route for simulated provider events, even in `local`/`test`.** A route on the student
   API would need its database role to execute `billing.apply_provider_event`, which would make "no
   client request can create a grant" depend on application code instead of privileges. The event
   path is exercised in-process by tests through the owner connection instead.
2. **The route is mounted only when the flag is on, so it is absent from the generated
   `openapi.json` / `schema.d.ts`.** The existing contract test pins the exact set of paths and the
   generator runs with flags off; mounting it unconditionally would change both.
   `main.py` gained one import name and one line: `app.include_router(entitlements.build_router(settings))`.
3. **Extra tables beyond the four named**: `providers`, `plan_prices`, `refunds` (doc 04 lists
   refunds; prices per currency need their own rows) and `entitlement_revocations` ("revocation is a
   new record").
4. **Foreign keys from `billing` to `app.grades`, `app.courses` and `auth.users`.** No object is
   created in `app`; PostgreSQL adds its internal referential triggers on the referenced tables (the
   existing structure test counts non-internal triggers only and still passes). The schema can be
   dropped without touching `app` — a test does exactly that.
5. **The audit seam writes `app.audit_events` directly for now** (plan §3 allows a definer function
   in the lane's schema to write an existing `app` table). It is replaced by `ops.audit_write` at wiring.
6. **Staff HTTP routes are not built** (per the director's instruction for this turn).

## 10. Known gaps

- A *refused* staff attempt (`42501`) raises, so its transaction rolls back and no `denied` audit
  record survives. The HTTP layer / `ops` must record denials when the routes are added.
- No reconciliation job, receipts, expiry reminders, partial refunds or chargebacks (Platform-07).
- One trial per learner is a naming convention for the idempotency key (`trial:<learner id>`), not a rule.
- Erasure cannot blank provider events that were never linked to an order (`unknown_order`,
  `malformed_payload`); and `granted_by` / `revoked_by` keep the id of a staff account that is later erased.
- `billing.is_entitled('course', <id>)` resolves the course's grade as the function owner, so the
  holder of a grade grant could learn whether a guessed course id (published or not) belongs to that
  grade. Low value (ids are random UUIDs); noted for the security review.
- `SECURITY DEFINER` functions are owned by `postgres` (same limitation as `docs/SECURITY.md` item 4).
- The "billing unreachable" API test commits a `REVOKE USAGE` on the local database and restores it
  in a `finally`; if the test process is killed in between, run `make db-reset`.
- Simulated provider tests leave append-only rows in the local `app.audit_events`.
- Not tested: a hosted pooler, real concurrency on grant idempotency beyond the unique index, load.

## 11. How to run

```sh
export UV_CACHE_DIR=/Volumes/EdupreneursDev/caches/uv npm_config_cache=/Volumes/EdupreneursDev/caches/npm
make lint && make typecheck && uv run python scripts/export_openapi.py --check
make db-reset && make test-db && uv run pytest -q && make test-db
```

Last full run on the lane's own stack (ports 56621/56622), log
`/Volumes/EdupreneursDev/logs/overnight-2026-11-24/entitlements-gate-2.log`:

| Check | Result | Baseline on `main` | New in this lane |
|---|---|---|---|
| `make lint`, `make typecheck`, `export_openapi.py --check` | pass (`openapi.json` unchanged) | — | — |
| `make test-db` (pgTAP), before and after pytest | 568 passed, 0 failed, both runs | 209 | 359 (220: 54 · 221: 79 · 222: 127 · 223: 99) |
| `uv run pytest -q` | 249 passed, 0 failed | 144 | 105 (unit 52 · API 42 · provider events 11) |

Not run: `apps/student-native` `npm run gen:api` / Jest (no route was added to the generated contract;
the mobile app is untouched).
