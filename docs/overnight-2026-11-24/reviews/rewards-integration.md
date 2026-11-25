# Integration review — lane REWARDS (Gold ledger, streaks, achievements)

Reviewer QA-2 (integration) · branch `overnight/rewards-gold` at `53ec9aa` (3 commits on `main` dd2aa19) · QA stack `qa2`
(Postgres 17.12, 127.0.0.1:57122) · 2026-11-24. All numbers below were observed on that stack; the code was read
from the reviewed sha only. Evidence scripts: `/Volumes/EdupreneursDev/logs/overnight-2026-11-24/tmp/qa/qa-2/`
(`p1_compat_latency.py`, `p2_failures.py`, `p3_model.py`, `p3b_model.py`, `p4_api_scale.py`, `scale_load.sql`,
`explain.sql`, `explain2.sql`, `qa_shuffle.py`).

## Verdict: APPROVE WITH FIXES

The Platform-08 gate holds in every run I made: the same accepted answer never earned twice, totals rebuild from
the ledger, and the provisional contract is documented. Existing apps see no difference in push/pull with the flag
off or on. Nothing CRITICAL or HIGH. Two MEDIUM items should be fixed before the flag is switched on anywhere
(M1 hook has no time budget; M2 ruling R-03 not applied) and one before the leaderboard lane builds on the schema
(M3 late-examined and reversal rows vs. closed periods).

## Suite counts observed

| Check | Result |
|---|---|
| `make lint` / `make typecheck` (mypy strict, 33 files) / `export_openapi.py --check` | clean / clean / up to date |
| `make test-db` (4 runs, before and after pytest) | 8 files, **482** tests PASS (209 baseline + 273 rewards) |
| `uv run pytest -q`, flag off / `EDU_REWARDS_ENABLED=true` | **236 passed** / **236 passed** |
| Baseline alone (`--ignore-glob='*test_rewards_*'`) | **144 passed** |
| Rewards suites alone, 3 consecutive runs | 92 / 92 / 92 passed |
| Full pytest in shuffled order (seeds 7 and 42, flag off and on) | 236 passed ×4 |
| Baseline files | only `config.py`, `main.py`, `routers/sync.py`, `sync/service.py` differ from main (36+/3−); `openapi.json` and `schema.d.ts` byte-identical; no baseline test, migration or seed touched |

## Findings

### M1 (MEDIUM) — the push hook has no time budget or circuit breaker
`services/api/src/edu_api/rewards/hook.py:29-43`, `sync/service.py:142-143`. The hook is awaited once per accepted
operation and inherits the connection's 5 s `statement_timeout` / `lock_timeout`. Learning still commits (verified),
but a slow or blocked rewards step multiplies: measured 10 ops × 0.3 s sleep = 3121 ms push; 4 ops with a hanging
function and the timeout lowered to 1 s = 4077 ms (one timeout per op, 4 log lines). With defaults that is 5 s × up
to 50 ops ≈ 250 s (computed, not run) during which the learner's sync row lock and one of ten pooled connections
are held; a second device of the same learner hits `lock_timeout`, and a handful of such pushes exhaust the pool for
everyone. A rewards problem therefore becomes a learning-sync outage, which is what the savepoint was meant to prevent.
Smallest fix: inside the savepoint `SET LOCAL statement_timeout`/`lock_timeout` to a small budget (e.g. 250–500 ms),
and after the first failure in a batch skip the hook for the remaining ops (reconcile already heals them). Add a test.

### M2 (MEDIUM) — ruling R-03 template not applied
All 15 `SET search_path` clauses in `20261124050100_rewards_schema.sql` (5) and `20261124050200_rewards_functions.sql`
(10) are `''`; none is `pg_catalog, pg_temp`. `supabase/tests/180_rewards_structure.sql:111-112` asserts the empty
path, so the test must change with it. Fix in place in the lane's unmerged migrations and assert the new value.

### M3 (MEDIUM, for the leaderboard lane) — rows can appear in, or subtract from, the wrong period
(a) A healed operation is written now but with `accepted_day` = the original acceptance day (by design, doc
"Reconciliation"), so reconcile inserts rows into days that a leaderboard may already have closed and frozen.
(b) A reversal is dated the day it is made: measured per-day sums `2026-11-14: +5`, `2026-11-24: −5` for one
learner — a negative total in a period with no awards. (c) There is no index on `created_at`/`seq` across learners
to find "rows added since the last snapshot". Smallest fix: document the rule the leaderboard must use (period by
`accepted_day`, freeze by `seq` watermark, floor at 0 or attribute reversals to the original row's day via
`reverses_ledger_id`), and say so in "For the leaderboard lane". `ledger_seq_key` already gives the watermark scan.
Also missing for that lane: nothing excludes staff (seed editor has a learner profile and earns Gold; the
leaderboard must join `app.staff_roles` itself — stated in its brief, not in the rewards doc).

### L1 (LOW) — R-01 test missing
R-01 requires a lane test proving that, with `INCLUDE_IN_SCHEMA` on, the operations carry the bearer scheme and only
the standard error shape. `tests/integration/test_rewards_api.py:93` only proves the routes are absent from the
document. Add the test (build the app with the constant patched to True and inspect `/openapi.json`).

### L2 (LOW) — rules apply at examination time, so history is not re-derivable across a rule change
`20261124050200…:apply_operation` picks the active rule when the op is examined. Measured: after adding
`question_first_correct` v2 (7 Gold), erase + re-derive changed the same learner's balance 47 → 51; two learners
doing the same work on the same day are paid differently if one was healed after the change. Documented as decision
3, but it weakens "rebuildable". Fix: `effective_from` on rules and choose the version in force at `accepted_at`.

### L3 (LOW) — `no_active_rule` is recorded as final
Measured: with the question rule switched off, two correct answers were processed as `no_active_rule`; after
re-activation `up_to_date: true` and they never earn (balance stayed 30). Switching a rule off behaves unlike
switching the flag off. Fix: do not write a `processed_operations` row for `no_active_rule`, or document it loudly.

### L4 (LOW) — source key depends on editorial discipline that nothing enforces
Key `q:<lesson_id>:<question_key>` is right for same question across revisions, locales, devices and replays
(verified; seed FR/HT share keys). Measured weak spots: a question whose key was renamed in revision 2 paid a second
time; a brand-new question that reused an old key paid nothing (`duplicate`). A question moved to another lesson pays
again (by construction). Lesson `is_active=false` is still accepted by sync and still pays (baseline behaviour).
Fix belongs to the content lane: make `question_key` immutable per question and same across locales; note it in the doc.

### L5 (LOW) — read path at volume
With 999,100 ledger rows (100,000 for one learner; loaded with the validate/balance triggers deliberately disabled)
and 200,000 receipts for that learner: `GET /summary` median 195 ms, `GET /ledger` first page 141 ms, later pages 4 ms.
Causes: the reconcile fast-path anti-join scans all of the learner's receipts on every summary (50 ms, seq scans +
14 MB hash; doc lists this as a known gap), and the newest-first query chose `ledger_seq_key` backward with a filter
(899,100 rows removed, 713 ms cold) instead of `idx_ledger_learner_seq`. The second is amplified by my skew (one
learner = 10 % of the table, oldest rows) but the redundant `UNIQUE (seq)` index is what offers the bad plan.
Fix: a per-learner watermark for reconcile; write the page query as `ORDER BY learner_id, seq DESC` or drop the
standalone unique on `seq`. Cap sums, duplicate check, weekly aggregate (index-only, 9.8 ms) and push at this volume
(10 ops: 18.5 ms on vs 9.5 ms off) were fine. `rebuild_balance` over 100k rows: 269 ms.

### L6 (LOW) — provisional contract is thin for the native lane (slice 4)
Implementable only as a label: the server exposes no rule amounts (`rewards.rules` is not readable and not in the
summary) and the native brief forbids invented Gold values, so the app can show "pending" but not a pending amount.
Also no `Cache-Control`/`ETag` on either route (only `content-type` observed), no server instant (only `today`),
and no "newer than" query, so the offline cache must re-read page 1. Push carries no Gold, so one extra GET per sync.
Smallest fix: state in the doc that pending is shown without an amount (or add active amounts to the summary), add
`Cache-Control: private, no-store` and an `as_of` timestamp.

### Notes
- N1 Storage: ledger ≈ 638 bytes/row including 7 indexes (237 MB heap + 371 MB indexes per 1M rows; `ledger_exactly_once`
  alone 119 MB); `processed_operations` ≈ 154 bytes per accepted op, kept forever, including wrong answers. A learner
  doing 30 answers/day ≈ 11k processed rows + at most a few thousand ledger rows per year ≈ 2–4 MB/learner/year.
  `idx_ledger_rule` and `ledger_seq_key` are candidates to drop.
- N2 A corrupted balance cache is served as-is (summary showed 1 while the ledger sum was 40, `up_to_date: true`);
  only an operator call to `rebuild_balance` corrects it when nothing is pending. `activity_days` and
  `achievement_awards` are not rebuildable except by erase + reconcile while receipts exist.
- N3 `TRUNCATE rewards.ledger` is not blocked by the append-only guard (owner only). A reversed award cannot be
  re-granted and its achievement row stays.
- N4 With the schema unusable, `/summary` answers 500 `internal_error`, not the documented 503.
- N5 `sync_max_ops` may be configured up to 500; above 64 writing savepoints per transaction PostgreSQL's
  sub-transaction cache overflows. Default 50 is safe.
- N6 Hook touches two baseline files instead of one (doc decision 7): sound, 36 added lines, flag-off path passes `None`.
- N7 Acceptance instant is the transaction start (`now()`): a push begun just before Haiti midnight counts for the
  earlier day. Acceptable; say so in the doc.

## Brief compliance

| Brief item | Status |
|---|---|
| Schema `rewards`, nothing in `app`, no FK to the five learning tables (R-02) | Done; baseline 209 pgTAP green |
| `rules` as data, placeholders marked `BLOCKED_BY_OWNER:PO-09` | Done (column default + doc table) |
| Append-only ledger, generated source key, unique constraint, Haiti day, RLS own rows | Done and tested |
| `balances` + `rebuild_balance`, `sum(ledger) = balance` | Done; my delete-and-rebuild matched (40/40) |
| Per-lesson and per-day caps in SQL | Done; both tested in pgTAP 185, per-lesson also in pytest |
| `streak_state`, non-punitive, DST/midnight with explicit instants | Done; test 190 uses explicit UTC instants both DST edges |
| Back-dating designed, not enabled | Done, clearly marked not built |
| Achievements idempotent, ledger-linked | Done |
| `erase_learner` hook | Done, EXECUTE to nobody |
| `award_for_operation`, `reconcile_learner` + batch variant | Done (batch seam ungranted) |
| Flag-guarded savepoint hook, response unchanged, 144 baseline green off and on | Done; verified |
| `GET /summary`, `GET /ledger`, 404 standard shape when off | Done |
| R-01 | Followed for routing/constant; **test missing (L1)** |
| R-03 template | **Not followed (M2)** |
| Deviations | hook in two files (sound); lazy reconcile inside a GET (sound for now, see L5); rules at examination time (L2) |

Every item of the brief's test list maps to at least one test (replay, op-id reuse, two devices, correct after wrong,
wrong only, rejected, repeated completion, 20 concurrent pushes, caps, immutability, forged amounts, API role cannot
write or rebuild for others, isolation, reconcile after hook off, rebuild equality, reward failure, streak boundaries,
erasure). Missing tests: slow/timed-out hook; rule version change; renamed or reused `question_key`; batch at the
50-op limit with the flag on; reversal's effect on day sums; R-01 schema test; ledger paging while inserts happen.
No flaky or order-dependent test found.

## Verified sound (tried to break, could not)

- Push, replay, op-id conflict, pull, validation error and 51-op batch error: JSON identical flag off vs on after
  masking ids/timestamps, same header set.
- Learning commits with EXECUTE revoked, USAGE revoked, function raising, function slow, statement timeout, ledger
  table missing: push 200, all ops `accepted`, receipts/attempts/progress present, one log line per op, and the next
  summary healed everything (balance 40 or 45, `up_to_date: true`).
- Erase + reconcile from receipts reproduces the ledger row for row (same rules); `rebuild_streak` equality.
- Second reversal of the same row refused; re-answer after a reversal earns nothing.
- Paging: page 2 fetched with an old cursor was identical before and after six new inserts, no overlap with page 1;
  `limit` 0/101/abc → 422 `validation_error`; empty/garbage cursor → 422 `invalid_cursor`.
- Added latency, medians of 15 runs, loopback database (each accepted op adds three round trips):

| Batch | 1 op off → on | 10 ops off → on | 50 ops off → on |
|---|---|---|---|
| Typical (5 seed questions, right/wrong mix) | 5.0 → 7.9 ms | 10.0 → 22.6 ms | 26.3 → 57.4 ms |
| All new correct answers (awards until the cap) | 4.7 → 8.9 ms | 20.9 → 49.6 ms | 47.1 → 88.6 ms |
| Replay of 50 accepted ops | | | 21.6 → 52.5 ms |

  The learner row lock is held for the whole request, so it is held roughly twice as long with the flag on.

## Docs

The lane doc matches the code in everything I checked. PO-09 amounts, caps, achievements, spending and back-dating
are marked open and not presented as decided. Corrections needed: error table says 503 where a broken schema gives
500 (N4); "For the leaderboard lane" should carry M3; state L3 and L6 explicitly.

## Not examined

Permissions and abuse (security reviewer's scope); `reconcile_batch` under concurrency; behaviour behind a
transaction-mode pooler; a remote (non-loopback) database; the mobile app; lock contention between two real devices
during a slow hook (reasoned from timeouts, not run); 250 s worst case in M1 is extrapolated from the measured runs.
