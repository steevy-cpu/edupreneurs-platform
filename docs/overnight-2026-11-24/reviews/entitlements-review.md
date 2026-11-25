# Entitlements lane — independent security and correctness review (QA-1, public version)

- Under review: `overnight/entitlements` at `43ca9b9` (billing work only: `git diff 7c3d2fb 43ca9b9 -- . ':!docs'`), brief `briefs/entitlements.md`, lane doc `lanes/entitlements.md` (section 0).
- Environment: QA worktree `qa1` at detached `43ca9b9`, `make db-reset`, disposable stack `supabase_db_edu-on-qa1`. Probes ran as the real logins `edu_api_login`, `edu_staff_login`, `edu_worker_login` and, for internal functions, as the local owner.
- Reviewer changed nothing in any lane worktree.

## Verdict: APPROVE WITH FIXES

No CRITICAL or HIGH finding. The privilege model holds: no learner-side or staff-side request or SQL could create, extend, un-revoke or read another learner's grant, order or provider event; the simulated provider path is unreachable over HTTP and from the API roles; the learning paths are untouched and unaffected. One MEDIUM and several LOW items should be fixed before any checkout work (PO-06) builds on this; none blocks integration of a dormant, flag-off feature.

## Suites observed at 43ca9b9

| Suite | Result |
|---|---|
| `make test-db` (pgTAP) | 745 tests, 11 files, PASS (author expected 745) |
| `uv run pytest -q` | 367 passed (author expected 367) |
| `make lint` | pass |
| `make typecheck` | pass (38 source files) |

## Findings

### M1 — MEDIUM — Staff idempotency keys and internal purchase keys share one namespace
- Where: `supabase/migrations/20261124070200_billing_functions.sql:235` (single `UNIQUE idempotency_key`, `ON CONFLICT DO NOTHING`), `:651` (purchase grant key `'order:' || order id`), `:653` (`RAISE … XX000`); `services/api/src/edu_api/billing/staff_schemas.py:40` (pattern allows `:`).
- Problem (class: key-namespace collision → denial of fulfilment): keys chosen by staff and keys derived internally for purchase grants live in one unique namespace. A colliding staff key makes the later payment message fail with an internal error that rolls everything back: the order stays `pending`, the provider event is **not stored** (contradicting "every authentic message is stored"), and every retry fails the same way. Impact: a paying learner would never be entitled and finance would see nothing.
- Evidence: reproduced on the QA stack at SQL level and through the staff HTTP route with a real admin token; the affected order stayed `pending`, no provider event row was stored and the learner was not entitled. Reproduction steps are in the private full report.
- Reach today: needs role `admin` and the id of a pending order; checkout and the event function are dormant (EXECUTE: nobody). Hence MEDIUM, not HIGH.
- Smallest fix: namespace the keys in SQL, e.g. `staff_grant_entitlement` stores `'staff:' || p_idempotency_key` (and/or refuses keys starting with `order:`); and in `apply_provider_event` do not raise on a grant conflict — store the event as `rejected / grant_conflict` so it is visible. Add a test.

### L1 — LOW — Replaying a key whose grant was revoked answers "granted" (grant after revoke)
- Where: `20261124070200_billing_functions.sql:244-258`; `routers/staff_billing.py:115-125`.
- Problem: same key + same request after a revocation returns `200 {"replayed": true}` with the revoked grant's id and dates and an audit row `billing.entitlement.grant / allowed / status granted`. Nothing tells the admin that the learner still has no access. Fails closed (no access is restored), but support will believe it was. Related: "same request" ignores `reason_code` and `starts_at` (only duration is compared), so a replay with a different reason code is reported as the same grant while the audit row records the new code.
- Evidence (HTTP, real admin token): grant key `qa-http-replay-0001` → 200; revoke → 200; same grant body → `200 replayed: true`, same `entitlement_id`; learner's `GET /v1/entitlements` → `[]`. Same key with `reason_code: "trial"` instead of `goodwill` → `200 replayed: true`; audit row shows `reason_code: trial`.
- Smallest fix: return the grant's current `state` (or `revoked_at`) in the outcome and the HTTP response, or answer 409 `grant_revoked` on replay of a revoked grant; include `reason_code` (source_ref) in the sameness comparison.

### L2 — LOW — An order snapshots the price but not what is bought
- Where: `20261124070200_billing_functions.sql:621-623, 647-651` (scope and `duration_days` read from `billing.plans` at payment time); `billing.plans` has no guard trigger.
- Problem: amount/currency are frozen on the order, scope and duration are not. A plan edited between order and payment grants the new scope/duration for the old price.
- Evidence: order created at 30 days / 50000 HTG; `UPDATE billing.plans SET duration_days = 3660`; correct payment message → `entitlement_granted`, `starts_at 2026-11-25`, `ends_at 2036-12-02`.
- Reach today: only the owner can write `billing.plans`. Smallest fix: copy `scope_kind`, scope id and `duration_days` to `billing.orders` in `create_order` and grant from the order; or make plans immutable once ordered (new plan code per change).

### L3 — LOW — Erasure is incomplete for data the lane itself writes
- Where: `20261124070200_billing_functions.sql:617` (unlinked events get `order_id NULL`), `:753-755` (erasure blanks only events linked to the learner's orders), `:359` (`learner_id` placed in audit *details*).
- Problem: (a) provider messages stored as `unknown_order`, `malformed_payload` or `unsupported_event_type` are never linked to an order, so their raw payload (which can carry payer data) survives `billing.erase_learner` — acknowledged in the lane doc's known gaps, but no test pins it and there is no retention rule; (b) grant audit rows keep the learner's id inside `details`, where an eraser keyed on `actor_id` / `target_id` will not find it.
- Evidence: three events with a `payer_phone` field (unknown order, malformed amount, unsupported type) → after `billing.erase_learner(B)` all three payloads still contain `payer_phone`; `app.audit_events` rows whose details or target name B after erasure: 11.
- Smallest fix: for unlinked events store only the digest plus a minimal whitelisted payload (or link `malformed`/`unsupported` events to the order when the id parses), and add a time-based purge; make the learner the audit *target* (`target_kind 'learner'`) or tell the erasure orchestrator to scan `details->>'learner_id'`.

### L4 — LOW — A refund message for an order that was never paid records a full refund
- Where: `20261124070200_billing_functions.sql:675-686, 700-702`.
- Problem: `payment.refunded` on a `pending` or `failed` order writes a `billing.refunds` row for the full expected amount although no payment was ever recorded. Access-wise this is safe (the order is closed, a late payment is ignored); for reconciliation it states money was returned that the ledger never saw arrive.
- Evidence: code path above (the refund branch has no status condition); author's test `test_refund_revokes_and_out_of_order_messages_cannot_restore_access` passes in my run and asserts the order becomes `refunded`.
- Smallest fix: record the refund row only when the order was `paid`, or add a column marking "refund received before payment" for finance.

### L5 — LOW — Test hygiene: a committed privilege change in the shared test database
- Where: `tests/integration/test_billing_entitlements_api.py:375` (`REVOKE USAGE ON SCHEMA billing FROM edu_api`, restored in `finally`).
- Problem: the brief asked for the schema to be made unreachable "inside a test transaction". The test commits the revoke; a killed run leaves `/v1/entitlements` answering 503 for every later run until `make db-reset` (documented by the author). Fixtures also `TRUNCATE` all billing tables, which is fine locally but would be destructive if the suite were ever pointed at a non-disposable database.
- Smallest fix: restore the privilege in the `billing_clean` fixture set-up as well (self-healing), and assert a local host before truncating.

### Notes (no action required for this merge)
- N1 — TEMP: at this sha all three API logins can still `CREATE TEMP TABLE` (observed). That is ruling R-03 item 1, owned by the staff lane, already ordered. All 14 billing functions carry `search_path=pg_catalog, pg_temp` (catalog check), are owned by `postgres`, use no dynamic SQL and qualify every non-catalog object, so I found no shadowing path through them.
- N2 — `MockProvider(environment=…)` checks a string supplied by the caller, not `Settings.environment`; it is a convention, not a control. The real controls are sound: no route, no EXECUTE for any API role, no provider row.
- N3 — Separation of duties: only a self-grant is refused. Two admins can grant to each other (observed 200 both ways). Policy decision for the owner.
- N4 — `edu_staff_login` and `edu_worker_login` can call `ops.audit_write` directly and write rows named `billing.entitlement.grant` (observed). Shared-interface property of the staff lane, not of billing; a stolen staff login could add misleading audit rows (it cannot delete any).
- N5 — Time: everything uses `now()` = transaction start. A read transaction that began before the revoking transaction still answers "entitled" until it ends; negligible for request-sized transactions.
- N6 — The `billing.erasing` marker lets the owner delete any grant or revocation, not only the erased learner's (observed on the QA stack). Only the owner has write privileges, so this is owner-mistake protection only.
- N7 — `ON DELETE RESTRICT` to `auth.users`: deleting an Auth user who has a grant or order fails until `billing.erase_learner` has run. No orchestrator calls it yet and no existing deletion path exists on `main`, so nothing breaks today.
- N8 — The lane doc sections 2 (function table), 3 ("mounted only when…") and 4 (staff seam) are stale; section 0 supersedes them but the stale text should be removed before the doc becomes reference.
- N9 — A JSON amount written `5e4` is accepted as 50000 (jsonb normalises it; it is an integer value). `50000.0`, strings, negatives and 1e30 are rejected.

## Verified sound (tried to break, could not)
- **Learner side, real `edu_api_login`** (with actor A and with no actor): every `SELECT *`/`DELETE`/`TRUNCATE` on all 8 tables, forged `INSERT`/`UPDATE` of grants and revocations, reading `idempotency_key`, `granted_by`, `order_id`, `source_ref`, `reason_code`, setting `billing.erasing` then deleting, and EXECUTE of all 13 other functions → `42501`. Allowed: 8 columns of own grants (A saw 1 row, B's grant invisible), 2 columns of own revocations (B's revocation invisible), `billing.is_entitled`. No actor → 0 rows, `false`.
- **Staff side, real `edu_staff_login`**: all table access and all non-staff functions → `42501`; the three staff functions with a non-admin or absent actor → `42501`. `edu_worker_login`: nothing in `billing`.
- **Catalog**: EXECUTE holders are exactly `is_entitled → edu_api` and three `staff_* → edu_staff`; no table privilege for any non-owner role except the column grants above; RLS enabled on all 8 tables; only `postgres` has CREATE on the schema; nothing created in `app`; no FK to the five learning tables (R-02) — FKs go to `auth.users`, `app.grades`, `app.courses` only.
- **HTTP role matrix** (author's tests, run by me, plus my probes): learner, editor, reviewer, publisher → 403 and audited; deactivated admin → 403 at once; self-grant → 403; flag off → 404 with or without token; unknown learner/course → 422; extra field `starts_at` → 422; `?learner_id=` ignored.
- **Idempotency**: 12 simultaneous identical grants on separate connections → 1 row (1 new, 11 replayed); same key + other learner → `conflict`; revoke twice → one revocation; append-only guards stop UPDATE/DELETE even as owner.
- **Provider events**: duplicate and replay → stored outcome; same id with other payload or type → `conflict`; amount −1, float, string, negative, 1e30, wrong currency, wrong plan, missing plan, unknown order, order of another provider → rejected, order untouched; unknown and disabled provider → `42501`, nothing stored; synthetic plan × real provider and real plan × simulated provider → refused; pay after refund cannot restore access; mixed race of 6 identical payments + 3 refunds + 3 other payments on one order → exactly 1 grant, 1 revocation, 1 refund, order `refunded`; oversize payload refused; event on an erased order → `order_erased`.
- **Simulated path reachability**: no module under `services/`, `scripts/`, seed or Makefile imports `mock_provider` or calls `apply_provider_event` / `create_order`; no route receives provider messages; no provider row ships.
- **Time**: active at `starts_at`, active at `ends_at − 1 µs`, inactive at exactly `ends_at`; future-start grant inactive; revocation effective in the same transaction; overlapping grant keeps access when another is revoked; bounds (start more than 24 h in the past, more than 366 d ahead, duration above 3660 d, `infinity`) refused; clock is always the server's.
- **`is_entitled` leaks**: for a grade-grant holder, published course of the grade → true; draft course of the same grade → false; unknown id → false; malformed scope → false.
- **No-paywall guarantee**: catalogue, lesson, sync and `/v1/me` code is byte-identical (`git diff` shows only `config.py` +7 and `main.py` +2 router registrations outside the lane's own files); baseline migrations, seed, contracts and baseline tests identical to `origin/main`. With the `billing` schema **renamed away** on my stack and the flag on, the full learning snapshot (catalog fr/ht, lesson fr/ht, push, pull, me) equals the reference, `/ready` = 200, `/v1/entitlements` and the staff routes = 503 `entitlements_unavailable` in the standard error shape. Author's tests for flag on/off × grant states and for revoked USAGE pass.
- **Money**: only `bigint` minor units + 3-letter currency; no numeric/float/money column; Python side rejects floats and bools; amounts bounded to 15 digits.
- **Audit content**: observed rows carry ids, enum codes and numbers only; the idempotency key is not audited. No secret, key or token in the diff.

## Missing tests
- Key-namespace collision between a staff grant and a purchase grant (M1).
- Replay of a key after its grant was revoked, at SQL and HTTP level (L1).
- Plan edited between order creation and payment (L2).
- Erasure behaviour for unlinked provider events and for audit rows naming the learner (L3) — the doc states the gap, nothing pins it.
- Refund row semantics when the order was never paid (L4).
- A temporary-object shadowing test against the billing definer functions (R-03 defence in depth is asserted structurally only).
- `erase_learner` called by a real orchestrator (none exists yet).

## Not examined
- Section 6 of the lane doc (offline lease specification) — not reviewed.
- The four pgTAP files were run and sampled, not read line by line; the Data API isolation test was run (passes) but not re-probed independently.
- Staff lane files (`7c3d2fb`), the mobile app, hosted poolers, load.
