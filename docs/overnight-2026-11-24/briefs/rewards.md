# Lane REWARDS — Gold ledger, streaks, achievements (F8, owner priority · M-10)

Worktree `/Volumes/EdupreneursDev/worktrees/overnight/rewards` · branch `overnight/rewards-gold` ·
stack API 56521 / DB 56522 · schema `rewards` · migrations `2026112405xxxx_*` · pgTAP `180–199_*`.

Owned paths: `supabase/migrations/2026112405*`, `supabase/tests/18*.sql`, `supabase/tests/19*.sql`,
`services/api/src/edu_api/rewards/**`, `services/api/src/edu_api/routers/rewards.py`,
`tests/**/test_rewards_*.py`, `tests/rewards_fixtures.py`, `docs/overnight-2026-11-24/lanes/rewards.md`.
One authorised touch of a verified module: a **single, flag-guarded hook** in the sync push path
(`services/api/src/edu_api/sync/service.py` or `routers/sync.py`) — see "Integration with sync".

## Principles (Platform-00 doc 04 §4.5, doc 05 M-10, PO-09)
The device never reports points. Gold exists only as rows in an **append-only ledger**, each tied to
an operation the server already accepted (`app.sync_receipts` / `app.practice_attempts` /
`app.lesson_progress`). Balances and streaks are derived and rebuildable. The exactly-once and
commit-ordered guarantees of `app.sync_apply_operation` must be untouched: do not modify it, and add
no trigger, grant or policy in schema `app`.

## Data model (schema `rewards`)
- `rules` (code, event kind, amount, caps, version, active) — **data, not code**. Tonight's values
  are synthetic placeholders using Platform-00's recommendation: Gold for the *first correct* answer
  to a question and for the *first* completion of a lesson; nothing for wrong answers, repeats,
  rejected operations, exams, or opening things. Mark amounts `BLOCKED_BY_OWNER` (PO-09).
- `ledger`: learner, amount (integer, non-zero; awards positive; a correction is a new `reversal`
  row, never an edit), rule code + version, source kind, source `op_id`, a **source key** with a
  unique constraint that makes double-awarding impossible — design it so that the same question
  answered correctly again (same or newer revision, other device, replayed op, new op id) earns
  nothing (think `(lesson_id, question_key)`), and a lesson earns once. Haiti calendar date of
  server acceptance. Append-only trigger. RLS: own rows, read-only for `edu_api`.
- `balances` (derived cache) with `rewards.rebuild_balance(...)`; a test proves
  `sum(ledger) = balance` after every scenario and after a rebuild from scratch.
- Bounded farming: per-lesson and per-day caps enforced in SQL and tested.
- `streak_state`: days (Haiti date of **server acceptance**) with at least one accepted learning
  event; current and longest. Non-punitive: no "you lost your streak" state is produced; offline
  work synced late counts on the day the server accepts it (back-dating is PO-09 — design a bounded
  optional rule in the doc, do not enable it). Test Haiti midnight and DST edges with explicit instants.
- `achievement_definitions` / `achievement_awards` (unique per learner+code; a few synthetic,
  age-appropriate examples such as first lesson completed; awarding is idempotent and ledger-linked).
- `rewards.erase_learner(uuid)` hook (see `00-PLAN.md` §3).

## Award path
- `rewards.award_for_operation(p_op_id uuid) RETURNS jsonb` — definer, EXECUTE to `edu_api`; actor
  from `app.current_actor_id()`; looks up the caller's **accepted** receipt for that op, derives the
  events from server-written rows only, inserts ledger rows with `ON CONFLICT DO NOTHING`, updates
  balance/streak/achievements in the same transaction. Unknown, rejected, or someone else's op → no
  award (and no information leak).
- `rewards.reconcile_learner(...)` (and a bounded batch variant for the worker/staff role later):
  awards any accepted operation that has no ledger entry. This is what makes the ledger rebuildable
  and self-healing if the hook was off or failed.

## Integration with sync (flag `EDU_REWARDS_ENABLED`, default **off**)
With the flag off, the push path is byte-for-byte the current behaviour. With it on, after an
operation is accepted the API calls `rewards.award_for_operation` **inside a savepoint in the same
transaction**; if the reward step raises, the savepoint is rolled back, the learning operation still
commits, a structured log line is written, and reconciliation heals it later. The push response
shape does not change (old apps keep working). Prove: all 144 baseline API tests pass with the flag
off **and** on.

## Learner API
`GET /v1/rewards/summary` (balance, streak, achievements, a small "recent" list) and
`GET /v1/rewards/ledger?cursor=&limit=` (opaque cursor, bounded limit). 404 in the standard error
shape when the flag is off. Document the **provisional** contract for the app: Gold shown for
unsynced offline work is labelled pending and is replaced by the server's ledger after sync; the
server never accepts an amount from the device.

## Tests (the leaderboard lane may not start until these pass and are reviewed)
Replay of the same op (same payload) → one award; op-id reuse with a different payload; the same
correct answer from two devices with different op ids; correct after wrong; wrong only; rejected
op; repeated completion; twenty concurrent pushes of the same batch; caps; ledger immutability;
negative/zero/forged amounts impossible; `edu_api` cannot insert into the ledger or call rebuild
for another learner; cross-account isolation; reconcile after the hook was off; rebuild equality;
reward failure does not fail the learning operation; streak boundaries; erasure hook.
