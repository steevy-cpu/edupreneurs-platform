# Lane ENTITLEMENTS — grant model, read API, staff grants, mock provider (F4 · M-08; no live payments)

Worktree `/Volumes/EdupreneursDev/worktrees/overnight/entitlements` · branch `overnight/entitlements` ·
stack API 56621 / DB 56622 · schema `billing` · migrations `2026112407xxxx_*` · pgTAP `220–239_*`.

Owned paths: `supabase/migrations/2026112407*`, `supabase/tests/22*.sql`, `supabase/tests/23*.sql`,
`services/api/src/edu_api/billing/**`, `services/api/src/edu_api/routers/entitlements.py`,
`services/api/src/edu_api/routers/staff_billing.py`, `tests/**/test_billing_*.py`,
`tests/billing_fixtures.py`, `docs/overnight-2026-11-24/lanes/entitlements.md`.

Decision status: PO-01 (free or paid), PO-05 (scope), PO-06 (checkout), PO-07 (offline lease length)
are all `BLOCKED_BY_OWNER`. Therefore: **no paywall is activated anywhere.** The catalogue and
lesson endpoints are not touched; every existing free lesson stays reachable whatever `billing`
contains or even if `billing` is unreachable. Flag `EDU_ENTITLEMENTS_ENABLED`, default off.

## Model (Platform-00 doc 04 §4.2 — read it)
- `plans` (data: code, duration, scope, prices as **integer minor units + currency code**; synthetic).
- `entitlements`: one row per grant — learner, `scope` (`all` | grade | course; modelled from day
  one even if only `all` is used), starts, ends, `source` ∈ purchase | gift | promo | school_licence
  | trial | staff_grant | migration, source reference, **idempotency key** (unique → a double grant
  is impossible), granted by. Extending = a new row; rows are never edited; revocation is a new
  record. Overlaps allowed; access = any active grant.
- `orders` and `provider_events` (raw payload, unique by provider + provider event id → applied
  exactly once, replay/duplicate/out-of-order safe, amount and plan verified on the server).
- `billing.is_entitled(p_scope …)` read-only function for the caller; `billing.erase_learner` hook.
- RLS: a learner reads only their own grants; **no client request can create or extend a grant**.

## API
- `GET /v1/entitlements` — own active grants, server time, `free_content_always_available: true`.
- Staff grant/revoke under `/v1/staff/billing` (role `admin`), audited — wire through
  `staff.require_role` / `ops.audit_write` once the staff lane's B1 is merged (the director will
  message you); until then build and test the SQL with a marked seam.
- **Mock provider only:** a pure in-process adapter and a function that applies a *simulated*
  provider event (signed with a local test secret generated at test time, never committed). No route
  for it is mounted outside `environment in ('local', 'test')`. No HTTP call to any provider, no
  provider SDK, no real currency movement.

## Offline lease — specification only
Write the signed offline lease design (statement, key handling and rotation, clock-rollback
considerations, what the phone does at expiry: paid locks, free never locks, downloaded content
stays) in the lane doc with the test list. **Do not implement signing or verification** — the
security design is not approved (master brief F4).

## Tests
Double grant with the same idempotency key; overlapping grants; expiry at the boundary; revocation;
scope matching; duplicated / replayed / out-of-order / forged simulated provider events change
nothing they should not; amount mismatch refused; learner cannot grant, cannot read others;
learning endpoints (`/v1/catalog`, `/v1/lessons`, `/v1/sync/*`) answer normally with the flag on,
with it off, and with the `billing` schema made unreachable to the API role inside a test
transaction; Data API cannot reach `billing`; erasure hook.
