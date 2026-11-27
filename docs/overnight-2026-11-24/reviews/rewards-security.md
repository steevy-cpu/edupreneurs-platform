# Security review — rewards lane (Gold ledger, streaks, achievements)

Reviewer QA-1 (independent) · branch `overnight/rewards-gold` @ `53ec9aa` (3 commits on `dd2aa19`) ·
QA stack `qa1` (Postgres 127.0.0.1:57022, gateway 57021), disposable, synthetic accounts only.

**Verdict: APPROVE WITH FIXES.** The ledger's exactly-once design held against every double-award,
forgery, privilege and concurrency attack run. Two fixes are required before the leaderboard builds
on it: H1 (definer-function search-path template, R-03) and M1 (unbounded lock wait in the push hook).

## Suite counts observed (qa1, 53ec9aa)

| Command | Result |
|---|---|
| `make test-db` (twice, before and after pytest) | 482/482 PASS, 8 files (209 baseline + 273 rewards) |
| `uv run pytest -q` (flag off) | 236 passed |
| `EDU_REWARDS_ENABLED=true uv run pytest -q` | 236 passed |
| baseline only (`--ignore-glob='*test_rewards_*'`), flag off / flag on | 144 passed / 144 passed |
| `make lint`, `make typecheck`, `export_openapi.py --check` | clean |

After the flag-on baseline run the database held 255 `processed_operations` rows, so the hook really ran.
Baseline files (4 verified migrations, seed, `supabase/tests/0*`, conftest/helpers, contracts, Makefile):
no diff against `origin/main`. No secrets in the diff.

## Findings

### H1 — HIGH — R-03 template missing on all 15 functions; class reproduced against this schema
- Where: every `CREATE FUNCTION` in the two rewards migrations uses `SET search_path = ''`;
  `supabase/tests/180_rewards_structure.sql:111` pins that value.
- Class: temporary-schema type shadowing in `SECURITY DEFINER` functions (ruling R-03). On this branch
  the API login still holds TEMP.
- Impact (reproduced on the QA stack): a session with arbitrary SQL on the API login can execute
  statements as the function owner — a cached balance was set to an arbitrary value with an empty
  ledger; rules and other learners' rows are equally reachable.
- Precondition: SQL injection or a leaked API database credential.
- Smallest fix: `SET search_path = pg_catalog, pg_temp` on all 15 functions (including the four
  non-definer ones, which run inside definer calls), and change the assertion at 180:111.

### M1 — MEDIUM — the reward step can stall a push for N × 5 s while it holds the learner's sync lock
- Where: `services/api/src/edu_api/rewards/hook.py:29-43`, called per accepted op from `sync/service.py:142-143`;
  `rewards.lock_learner` waits with the connection-wide lock/statement timeout (5000 ms).
- Class: unbounded lock wait amplified per operation; no circuit breaker.
- Impact (reproduced): with the learner's rewards lock held by another session, a 3-op push took 15.0 s
  (still 200, all accepted, awards healed later) and a second device of the same learner received 503
  after 5.1 s. A full 50-op batch would take about 250 s. Legitimate lock holders are the batch
  reconcile, erasure and the summary reconcile; a session with SQL on the API login can cause it for
  any learner.
- Smallest fix: a short `SET LOCAL lock_timeout` (≈200 ms) inside the hook's savepoint, or a try-lock
  variant for the push path; skip the award for the rest of the batch after the first failure; have
  `reconcile_batch` commit per learner.

### M2 — MEDIUM (product integrity, owner PO-09) — Gold needs no evidence of learning
- Where: rule `lesson_first_completed` + achievement bonus; baseline `app.sync_apply_operation` accepts
  `lesson_completed` for any released revision with no answer required, and answer keys ship to the device.
- Evidence: a bare `completed_op` push was recorded `awarded, gold 30` (probe4 §2). A scripted client
  reaches the day caps (200 completion + 300 question Gold) every day without studying.
- Not a ledger defect (the brief specified these events), but a leaderboard ranked on this Gold ranks
  scripts. Fix belongs to the owner/leaderboard lane: e.g. require N server-scored answers in the lesson
  before the completion award, or rank on a measure that needs them.

### L1 — LOW — caps and "no active rule" are final per operation, so they only bind honest clients
- Where: `rewards.apply_operation` (processed_operations is written for `capped_day`, `capped_lesson`, `no_active_rule`).
- Evidence (probe4 §2, test rule with day cap 20): second lesson completion `capped_day, 0`; a repeat op
  during a window with no active rule version → `no_active_rule, 0`; a later repeat `lesson_completed`
  op for the same lesson → `awarded, 20`. An honest app never re-sends, so it loses the Gold; a modified
  client collects it the next day. Switching rule versions in two transactions also silently drops
  awards for operations examined in the gap.
- Fix: document the caps as rate limits, or let reconcile re-examine `capped_day` / `no_active_rule`
  outcomes; switch rule versions in one transaction.

### L2 — LOW — erasure is undone by the learner's next summary request while receipts remain
- Where: `rewards.erase_learner` + lazy reconcile in `rewards/service.py:84-105`.
- Evidence (probe4 §5): erase deleted 3 ledger / 2 processed rows; next `GET /v1/rewards/summary`
  → balance 35 again. The author documents the required order; nothing enforces it.
- Fix: the account orchestrator must remove receipts first (FK RESTRICT already forces this for a full
  account deletion); add an orchestrator test that asserts no rewards rows reappear.

### L3 — LOW — the ledger cursor exposes the global ledger sequence
- Where: `rewards/cursor.py:31-34`, `ledger.seq` is one identity across all learners.
- Evidence: a learner's `next_cursor` decodes to `{"a":"…","s":422,"v":1}`; differences over time
  reveal platform-wide award volume. No cross-account row access (see verified items).
- Fix: page on a per-learner ordinal, or seal the cursor (HMAC/encrypt).

### NOTES
- N1 Latency: 50-op accepted batch 33–42 ms flag off vs 99–139 ms flag on (savepoint + call + release
  per op, inside the sync lock). `sync_max_ops` allows up to 500; above 64 writing savepoints per
  transaction PostgreSQL's subtransaction cache overflows — keep the cap ≤ 64 or award once per batch.
- N2 `GET /summary` runs an anti-join over all the learner's accepted receipts on every call (author's known gap).
- N3 FK `ON DELETE RESTRICT` to `app.learner_profiles` from 6 tables adds 12 internal RI triggers on that
  `app` table (not counted by the structure test; R-02 respected — no FK to the five learning tables).
  Deleting a profile with rewards rows now fails (reproduced) until `erase_learner` has run.
- N4 A reversal is dated on the day it is made; period leaderboards must expect negative days.
- N5 The append-only guard's erase exception is a session setting anyone can set; it is safe only
  because no role but the owner holds DELETE (verified). TRUNCATE is not guarded for the owner.
- N6 `apply_operation` selects the active rule by code without checking `event_kind`; a mis-keyed
  operator row makes every award fail in the trigger (contained by the savepoint).

## Verified sound (attacked, not broken)
- **Privileges** (as real `edu_api_login`, actor set): INSERT/UPDATE/DELETE/TRUNCATE denied on all 8
  tables; SELECT denied on `rules`, `processed_operations`, `activity_days`; sequence denied; all of
  `apply_operation`, `reconcile_learner_internal`, `reconcile_batch`, `rebuild_balance`,
  `rebuild_streak`, `reverse_entry`, `erase_learner`, `lock_learner` → 42501. ACL dump: only `postgres`
  and `edu_api` (SELECT on 5 tables, EXECUTE on 3 functions); nothing for PUBLIC/anon/authenticated/
  authenticator/service_role; all objects owned by `postgres`; nothing new in schema `app`.
- **Crafted `award_for_operation`**: another learner's accepted op, their rejected op, a random uuid and
  NULL all return the identical `no_award`; no actor → 42501; own replay repeats the recorded decision.
- **Double award**: wrong-then-right, same op replayed, same question FR + HT, repeat correct answer,
  completion via FR/HT/repeat → one row each (35 Gold total); newer revision and the retired revision
  answered again → no change (45 → 45); rejected ops earn nothing.
- **Concurrency storm** (2 learners × 4 devices × 6 rounds with replays, flag-on and flag-off apps mixed,
  summaries, while the owner looped `reconcile_batch`, `rebuild_balance`, `rebuild_streak`): 108/108
  HTTP 200, 0 hook failures, 0 deadlocks, 723 samples of balance = sum(ledger) with 0 violations,
  0 duplicate keys, question Gold exactly at the 100 cap, 0 unexamined receipts afterwards.
  Lock order analysis: rewards functions never touch `account_sync_state`; FK checks take only KEY SHARE
  on `learner_profiles` — no cycle with the sync row lock.
- **Blast radius**: flag off — `on_accepted` is `None`, the only added code in the loop is one
  short-circuited `if` (`sync/service.py:142`); response identical. Flag on — a 5 s lock timeout inside
  the savepoint left all operations committed with the normal response (M1 is about the delay only).
  A dead connection fails the next statement → 5xx, nothing committed, client retries (by reasoning).
- **API**: A's cursor used by B → 422 `invalid_cursor`; self-forged max cursor returns only own rows;
  flag-off body equals an unknown path's body; POST/PUT/DELETE → 405.
- **Data API**: `Accept-Profile: rewards` with anon and service-role keys → 406 PGRST106 for table and RPC.
- **Erasure** removes rows from all six per-learner tables (counts returned and checked).

## Missing or weak tests
- No test for a **lock/statement timeout** in the hook (only an immediate permission error is used), so
  M1's delay and the per-op retry are untested.
- The structure test asserts the pre-R-03 search path (180:111) and there is no TEMP-object negative test.
- "A newer revision does not pay again" depends on fixtures reusing keys `q1…`; no test of a revision
  whose keys differ (bounded only by the per-lesson cap).
- No test that a capped / no-active-rule operation can or cannot be re-earned (L1), none for a rule
  version switch under load.
- Erasure is tested alone, not followed by a summary request (L2).
- Per-day cap is tested in pgTAP only, not through the API or across the Haiti-midnight boundary.

## Not examined
Mutation claim in the author's doc (lock replaced by no-op); streak DST tests beyond reading them;
load beyond ~100 concurrent requests on one laptop; true connection-drop mid-savepoint (reasoned only);
behaviour after merge with the staff/identity lanes (TEMP revoke, erasure orchestrator); the native app.
