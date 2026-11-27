# Lane NOTIFY — notification outbox with a dummy adapter; security and operations basics (F6, F3 · M-12)

Worktree `/Volumes/EdupreneursDev/worktrees/overnight/notify` · branch `overnight/notify-security` ·
stack API 56721 / DB 56722 · schema `notify` · migrations `2026112408xxxx_*` · pgTAP `240–259_*`.

Owned paths: `supabase/migrations/2026112408*`, `supabase/tests/24*.sql`, `supabase/tests/25*.sql`,
`services/api/src/edu_api/notify/**`, `services/api/src/edu_api/routers/notifications.py`,
`services/api/src/edu_api/ratelimit.py`, `services/api/src/edu_api/logging_config.py`,
`tests/**/test_notify_*.py`, `tests/**/test_ratelimit_*.py`, `tests/**/test_logging_*.py`,
`tests/notify_fixtures.py`, `docs/overnight-2026-11-24/lanes/notify.md`,
`docs/overnight-2026-11-24/lanes/operations-drill.md`.
Shared files you may extend additively: `main.py` (router + middleware registration), `config.py`,
`middleware.py` only if unavoidable (prefer new modules).

Decision status: notification policy and quiet hours are PO-10 (`BLOCKED_BY_OWNER`). **Nothing is
sent to anyone.** No push provider, no e-mail, no SMS, no device tokens from real devices.

## Part A — `notify` outbox (flag `EDU_NOTIFICATIONS_ENABLED`, default off)
- `outbox`: recipient, `kind` (allow-list, e.g. `daily_word_available`, `sync_reminder`,
  `entitlement_expiring`), **reference ids only — no free text**, channel policy, `deliver_after`,
  dedupe key (unique → the same event is never enqueued twice), state.
- `deliveries`: attempt log per channel with retry semantics (attempt count, next attempt, bounded
  backoff, terminal failure) — written only by server code.
- `preferences`: per learner categories and quiet hours evaluated in `America/Port-au-Prince`
  (synthetic default 21:00–06:00 from Platform-00's recommendation, marked PO-10).
- `notify.enqueue(...)`: the single producer entry point (definer; **not** executable by `edu_api`,
  so no client request can create a notification); `notify.claim_due(...)` / `notify.record_attempt`
  for a delivery worker (grant to `edu_worker` once the staff lane's roles are merged — the
  director will message you; until then test as owner behind a marked seam).
- **Dummy local adapter** in Python: "delivers" by writing a structured record to an in-memory/test
  sink; payload builder proves a push body for a minor carries **no content** (kind + opaque ids only).
- Learner API: `GET/PUT /v1/me/notification-preferences`, `GET /v1/notifications?cursor=` (own
  in-app list: kind + ids; the app renders the words in the learner's language). `notify.erase_learner`.
- Tests: client cannot enqueue; dedupe; quiet hours across Haiti midnight and DST; retry/backoff to
  terminal; preference opt-out respected; isolation; no free text can be stored (constraint);
  lessons and sync answer normally when `notify` is unreachable; Data API cannot reach `notify`.

## Part B — security and operations basics (F3)
- **Rate limiting** (`ratelimit.py`): a small in-process token-bucket middleware keyed by verified
  principal (falling back to client address for unauthenticated routes), per-route-class budgets from
  settings, `429` in the standard error shape with `Retry-After`, **disabled by default**
  (`EDU_RATE_LIMIT_ENABLED=false`) so existing tests are unaffected; tests for burst, refill,
  isolation between principals, bounded memory (eviction), and that sync retries of the same batch
  are not turned into data loss (document the client retry contract). State clearly in the doc that
  this is per-process and that a gateway/shared-store limiter is still required for a hosted
  multi-instance deployment (Platform-02).
- **Privacy-respecting structured logs** (`logging_config.py`): JSON lines with request id, route
  template, status, duration, actor id **hashed or omitted** (decide and justify), never tokens,
  bodies, answers, names or e-mail; a test that greps captured logs for a planted token/e-mail/answer.
  Opt-in via setting; default formatting unchanged.
- **Health/readiness rules**: document what `/ready` must and must not depend on (learning must stay
  up when notify/billing/rewards are down); add tests if a rule is not yet covered.
- **Backup/restore drill on your own disposable stack** (`operations-drill.md`): actually perform
  `pg_dump` of your lane database from inside the stack's Postgres container, restore it into a
  scratch database on the same disposable instance, verify row counts and that RLS/grants survived,
  time it, and write the exact commands and measurements. Local only; no cloud; remove the scratch
  database afterwards. If the container tooling makes this impossible, document exactly why.
