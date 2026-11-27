# Lane REWARDS — Gold ledger, streaks, achievements

Branch `overnight/rewards-gold` · schema `rewards` · flag `EDU_REWARDS_ENABLED` (default **off**) ·
Platform-00 M-10 · owner decision **PO-09 is open**.

Everything below was built and tested on a disposable local stack with synthetic accounts.
Nothing is deployed and no real learner has Gold.

## What exists

| Piece | Where |
|---|---|
| Schema, tables, guards, RLS, placeholder rules | `supabase/migrations/20261124050100_rewards_schema.sql` |
| Award / reconcile / rebuild / reversal / erase functions | `supabase/migrations/20261124050200_rewards_functions.sql` |
| Worker grant, audited admin reversal and adjustment (needs staff B1) | `supabase/migrations/20261124050300_rewards_staff_worker.sql` |
| Push hook (savepoint) | `services/api/src/edu_api/rewards/hook.py`, called from `sync/service.py` |
| Read API | `services/api/src/edu_api/routers/rewards.py`, `rewards/service.py`, `rewards/schemas.py`, `rewards/cursor.py` |
| Database tests | `supabase/tests/180_rewards_structure.sql`, `185_rewards_ledger_integrity.sql`, `190_rewards_streaks.sql`, `195_rewards_staff_worker.sql` |
| API tests | `tests/integration/test_rewards_ledger.py`, `tests/integration/test_rewards_api.py`, `tests/integration/test_rewards_staff_worker.py`, `tests/unit/test_rewards_cursor.py`, fixtures in `tests/rewards_fixtures.py` |

Nothing was created in schema `app`, `ops` or `staff`; `app.sync_apply_operation`, the four
verified migrations, `seed.sql` and every existing test file are unchanged. The branch contains
staff B1 (merge of `7c3d2fb`) and applies director rulings R-01 to R-04.

## How Gold is earned

The device never reports points. The only input the rewards engine takes is *which operation to
look at*; everything else is read from rows the server wrote.

1. `POST /v1/sync/push` applies an operation with `app.sync_apply_operation` (unchanged).
2. If the flag is on and the operation is `accepted`, the API calls
   `rewards.award_for_operation(op_id)` **inside a savepoint of the same transaction**.
3. That function finds the caller's accepted receipt, works out what the operation stands for from
   `app.practice_attempts` (server score = 1) or `app.lesson_progress` (completed), and inserts
   ledger rows. Gold therefore commits atomically with the learning operation, or not at all.
4. If the reward step raises, only the savepoint is rolled back: the learning operation still
   commits, the push response is unchanged, one log line `rewards_award_failed …` is written, and
   reconciliation awards it later.
5. **Time budget (security review M1).** The push holds the learner's sync lock, so the award
   waits at most ~200 ms for the learner's rewards lock and then answers `deferred` (log line
   `rewards_award_deferred`). After the first deferral or failure the rest of that batch skips the
   reward step. A held rewards lock therefore costs a push about 0.2 s once, not 5 s per operation.

The push response has **no** rewards field, with the flag on or off (tested by comparing shapes).

### The exactly-once key

`rewards.ledger` has `UNIQUE (learner_id, source_key)`, and `source_key` is a **generated column**:

| What was rewarded | `source_key` |
|---|---|
| first correct answer to a question | `q:<lesson_id>:<question_key>` |
| first completion of a lesson | `l:<lesson_id>` |
| achievement bonus | `a:<achievement_code>` |
| the single reversal of a row | `r:<ledger_id>` |
| one audited staff adjustment | `adj:<adjustment_id>` |

The key names the *thing rewarded*, not the operation that carried it. A replayed op, a new op id,
a second device, the Creole revision of the same lesson, and a newer revision of the same question
all produce the same key and are refused by the constraint (`ON CONFLICT DO NOTHING`). Because the
column is generated, no writer — not even the table owner — can supply a look-alike key.

A second table, `rewards.processed_operations` (PK `learner_id, op_id`), records the decision taken
for every accepted operation (`awarded`, `duplicate`, `capped_lesson`, `capped_day`, `forfeited`,
`awaiting_evidence`, `not_eligible`, `no_active_rule`). It makes "has this operation been examined?" a primary-key
look-up, makes a cap decision final, and lets reconciliation find unexamined operations.

### Guards that hold for every writer

- `validate_ledger_entry` (BEFORE INSERT): the amount must equal the rule version's amount; the row
  must point at an **accepted** receipt of the same learner with the same acceptance instant; a
  question row needs a server-scored correct attempt for that lesson + question key; a lesson row
  needs a recorded completion; a reversal must exactly negate one award of the same learner; an
  adjustment must be attributed to an active admin who is not the learner.
- `CHECK`s: amount non-zero and within ±1000 (±100 for an adjustment); `accepted_day` = Haiti date
  of `accepted_at`; one allowed shape per `source_kind`; the reason of a reversal or adjustment is
  a code (`^[a-z][a-z0-9_]{2,39}$`), never free text.
- Append-only triggers on `ledger`, `achievement_awards`, `processed_operations` (no UPDATE ever;
  DELETE only inside `rewards.erase_learner`, and only for the learner being erased).
- Rule versions are immutable (only `is_active` / `decision_status` may change); at most one live
  version per rule code.
- `edu_api`: `SELECT` on five tables through "own rows" policies, `EXECUTE` on exactly
  `award_for_operation(uuid)`, `reconcile_learner(integer)` and `haiti_day(timestamptz)`. No
  function it can call takes a learner id or an amount.
- Every function pins `search_path = pg_catalog, pg_temp` (ruling R-03); the structure test asserts
  exactly that value for the whole schema.

### Balance

`rewards.balances` is a cache maintained by an AFTER INSERT trigger on the ledger, so it follows
every insert path. `rewards.rebuild_balance(learner)` recomputes it from the ledger alone. Tests
assert `sum(ledger) = balance` after every scenario and after a rebuild from a deleted and from a
corrupted cache.

### Concurrency

- Push path: serialised per learner by the sync row lock (held to commit), then the rewards lock.
- Reconcile, rebuild, reversal, erase: take only the rewards lock — a transaction-scoped advisory
  lock per learner (`rewards.lock_learner`, key namespace `54050`). Lock order is always
  "sync, then rewards", so there is no cycle.
- The lock makes cap checks and streak rebuilds race-free and each operation examined once. The
  double-award protection does not depend on it: that is the unique constraint.
- Verified by mutation: with `lock_learner` replaced by a no-op, the concurrent tests fail
  (duplicate `processed_operations` key, deadlock); with it restored they pass.

### Reconciliation (self-healing)

`rewards.reconcile_learner(limit)` (caller only) examines accepted operations that have no
`processed_operations` row, oldest first, bounded (default 200, max 500), then rebuilds streak and
balance. It heals operations synced while the flag was off or whose award step failed. Healed rows
carry the **original** acceptance instant and day.

`rewards.reconcile_batch(max_learners, max_ops_per_learner)` is the worker's entry point
(`EXECUTE` to `edu_worker` only; learners taken in id order, bounded). No job schedules it yet.

Until a worker job exists, healing is triggered lazily by `GET /v1/rewards/summary` (its own
short write transaction before the read; a failure there only yields `up_to_date: false`) and by
any retry of the same batch (the hook also runs for replays of accepted operations).

## Rules — SYNTHETIC PLACEHOLDERS · `BLOCKED_BY_OWNER` (PO-09)

Rows in `rewards.rules`, each marked `decision_status = 'BLOCKED_BY_OWNER:PO-09'`. They follow
Platform-00's recommended default and exist so the mechanism can be tested.

| Rule code | v | Gold | Per-lesson cap | Per-day cap |
|---|---|---|---|---|
| `question_first_correct` | 1 | 5 | 100 | 300 |
| `lesson_first_completed` | 1 | 20 | 20 | 200 |
| `achievement_first_lesson` | 1 | 10 | — | — |
| `achievement_ten_correct` | 1 | 15 | — | — |

Nothing is earned for wrong answers, repeats, rejected operations, or operation kinds that have no
rule (exams, notes and "opening things" have no branch at all).

**Caps are final per source key (security review L1).** Caps are Gold totals per learner, enforced
in SQL under the learner lock. A question or lesson refused by a cap is recorded in
`rewards.forfeited_sources` and can never be paid later through a new operation (`forfeited`), so a
cap binds a modified client exactly as it binds an honest app. Consequence to decide under PO-09:
an honest learner who passes a cap loses that Gold for good.

**A switched-off rule is not final (integration review L3).** With no live version the operation
is recorded `no_active_rule` and not forfeited. Always switch versions with
`rewards.set_active_rule_version(code, version)` (internal, one call = no gap); when it switches a
rule on it forgets the `no_active_rule` decisions and reconciliation pays those operations.

**A completion needs evidence of learning (security review M2) — `BLOCKED_BY_OWNER` PO-09.**
Rule parameter `requires_scored_answer` (seeded **true** for `lesson_first_completed`, the safer
synthetic default): a completion is paid only once the server has scored at least one answer of
that learner in that lesson, right or wrong. A bare completion is recorded `awaiting_evidence`
(`rewards.pending_completions`) and paid, under its own operation and acceptance day, when the first
scored answer is examined. A rule version with the parameter false restores "any completion pays".
Both settings are tested. Whether one answer is the right bar is the owner's call. Changing a value = insert a new version and flip `is_active`; history keeps the version that
paid each row.

Achievements (draft French / Haitian Creole titles, **pending native-speaker review**):
`first_correct_answer` (no Gold), `first_lesson_completed` (+10), `ten_correct_answers` (+15),
`three_day_streak` (no Gold — streaks deliberately carry no Gold pressure).

Open for the owner (PO-09): the amounts and caps; whether Gold may be spent at all (there is no
spending path); whether achievements should carry Gold; which achievements exist; the wording.

## Streaks

- A day = the `America/Port-au-Prince` calendar date of the instant the **server accepted** the
  operation (`rewards.haiti_day`). The phone's clock is never read.
- Any accepted operation (right or wrong answer, any completion) makes the day active
  (`rewards.activity_days`). Rejected operations do not.
- `rewards.streak_state` is rebuilt from the activity days (gaps-and-islands), so it is correct in
  any arrival order — reconciliation may examine old operations after newer ones.
- **Non-punitive:** the table has no lost / broken / frozen column, a gap never costs Gold, and the
  API reports `current_days: 0` plus the kept `longest_days` rather than a loss.
- Offline work synced late counts on the day the server accepted it.
- Streak days keep counting while a Gold rule is switched off.
- Tested with explicit instants either side of Haiti midnight in winter (UTC-5) and summer
  (UTC-4), across the DST start (2026-03-08, 23-hour day) and end (2026-11-01, 25-hour day).

### Back-dating — designed, NOT built, NOT enabled (PO-09)

If the owner wants offline days to count, the bounded rule would be: an accepted operation may mark
the Haiti date of `client_recorded_at` as active instead of the acceptance date only when that date
is 1…N days before the acceptance date (N ≤ 3 recommended), never in the future, at most one
back-dated day per operation, and **streak only** — Gold day caps and `ledger.accepted_day` keep
using the server date. The device clock is forgeable, so the worst case is a learner filling gaps
in the last N days; it can never extend a run past today. It would be one nullable column on a
rule row plus a branch in `rewards.apply_operation`.

## Learner API — PROVISIONAL CONTRACT

Both routes need `Authorization: Bearer <Supabase access token>`. Read-only: there is no request
body and no way to send an amount (`POST/PUT/PATCH/DELETE` → 405).

**App rule:** Gold shown for work that has not synced yet must be labelled *pending*; after the next
sync it is replaced by what these endpoints return. The server never accepts an amount from the
device, and the push response carries no Gold.

Errors use the standard shape `{"error": {"code", "message", "request_id", "details"?}}`.

| Situation | Status | `error.code` |
|---|---|---|
| Flag off (any caller, with or without a token) | 404 | `not_found` (same body as an unknown path) |
| Missing / invalid token (flag on) | 401 | `unauthenticated` |
| Bad `limit` (0, > 100, not a number) or `cursor` longer than 200 chars | 422 | `validation_error` |
| Cursor malformed, tampered, or from another account | 422 | `invalid_cursor` |
| Database unavailable | 503 | `dependency_unavailable` |

### `GET /v1/rewards/summary`

```json
{
  "balance": 35,
  "lifetime_earned": 35,
  "streak": {
    "current_days": 1,
    "longest_days": 1,
    "last_active_day": "2026-11-24",
    "active_today": true
  },
  "achievements": [
    {"code": "first_correct_answer", "titles": {"fr": "Première bonne réponse", "ht": "Premye bon repons"},
     "earned_at": "2026-11-25T03:51:13.662Z", "gold": 0},
    {"code": "first_lesson_completed", "titles": {"fr": "Première leçon terminée", "ht": "Premye leson fini"},
     "earned_at": "2026-11-25T03:51:13.662Z", "gold": 10}
  ],
  "recent": [ { "…one ledger entry, see below; newest first, at most 5…": "" } ],
  "today": "2026-11-24",
  "up_to_date": true,
  "rules_status": "provisional"
}
```

- `balance` = sum of the ledger; `lifetime_earned` = sum of awards before reversals.
- `streak.current_days` = length of the latest run if it reached today or yesterday, else `0`.
  `last_active_day` is `null` for a learner with no activity. There is no "lost" field.
- `today` = the server's Haiti date. `up_to_date: false` means accepted operations are still being
  examined (call again); `rules_status` stays `"provisional"` until PO-09 is decided.
- `achievements` lists earned ones only, oldest first.

### `GET /v1/rewards/ledger?cursor=&limit=`

`limit` 1…100 (default 20). Newest first. `cursor` is the opaque `next_cursor` of the previous page.

```json
{
  "entries": [
    {
      "id": "0b0f5c0e-2f0e-4c57-9a0e-3d5f3f6f2a11",
      "kind": "award",
      "amount": 5,
      "source": "question_first_correct",
      "lesson_id": "b0000000-0000-4000-8000-000000000005",
      "question_key": "addition",
      "achievement_code": null,
      "op_id": "5a3c1d8e-6c1b-4f0a-8e55-0f6c2d0e9b77",
      "day": "2026-11-24",
      "created_at": "2026-11-25T03:51:13.662Z"
    }
  ],
  "next_cursor": null,
  "has_more": false,
  "balance": 35
}
```

`kind`: `award` | `reversal` (amount negative) | `adjustment` (a staff correction, either sign).
`source`: `question_first_correct` | `lesson_first_completed` | `achievement` | `reversal` |
`adjustment`. `op_id` is the accepted sync operation that earned the row (`null` for a reversal or
an adjustment). The reason code and the staff member behind a correction are not exposed. `next_cursor` is `null` on the last page. A cursor is bound
to its account and to this endpoint (a sync pull cursor is rejected). It encodes only the position
of one of the caller's own entries (`created_at`, `id`) — no table-wide sequence (security review
L3).

### Why the routes are not in `openapi.json` yet

Director ruling R-01.
`tests/integration/test_isolation_and_operations.py::test_openapi_contract` pins the exact set of
documented paths, and lanes may not edit baseline tests. The routes are therefore registered with
`include_in_schema=False` (one constant, `INCLUDE_IN_SCHEMA`, in `routers/rewards.py`), so
`packages/contracts/openapi.json` and the generated `schema.d.ts` are byte-identical to `main`.
**Integration step (director):** set the constant to `True`, add the two paths to the pinned set,
run `make openapi` and `npm run gen:api`. A lane test already proves that with the routes in the
schema both operations carry the bearer scheme, take no request body and document only the
standard error shape.

## For the leaderboard lane

Read through your own `SECURITY DEFINER` functions (owner `postgres`, which owns the tables and is
not subject to their RLS). `edu_api` can only ever see the caller's own rows, so a direct query
from the API cannot aggregate across learners — by design. Grant nothing on `rewards` to anyone.
Do not write to any `rewards` table, add no trigger, take no lock; read committed data.

| Object | Use |
|---|---|
| `rewards.ledger (learner_id, amount, entry_kind, source_kind, accepted_at, accepted_day)` | The truth. Period totals: `sum(amount) … WHERE accepted_day BETWEEN …` — index `idx_ledger_day (accepted_day, learner_id) INCLUDE (amount)` answers it without touching the table. |
| `rewards.balances (learner_id, balance, lifetime_earned)` | All-time totals, O(1) per learner. |
| `rewards.streak_state`, `rewards.activity_days` | Streak data. |
| `rewards.haiti_day(timestamptz)` | The one definition of a product day. |

### Dating rule (integration review M3)

1. **A ledger row belongs to the period of its `accepted_day`.** For an award that is the Haiti
   date on which the server accepted the learning operation. An operation healed later by
   reconciliation keeps its **original** accepted day (tested), as does a completion released by
   later evidence.
2. **A reversal or staff adjustment is dated the day it is made**, not the day of the award it
   corrects. It never rewrites an earlier day.
3. **Therefore a past day's sum can still grow** (late healing of an old operation) **but is never
   reduced or rewritten by a correction.** A leaderboard must close a period by taking a
   **snapshot** of the sums; a closed period is that frozen snapshot, not a live query. Rows that
   arrive afterwards with an old `accepted_day` count in the balance and in all-time totals only.
4. **A live period's sum for one learner can be negative** (a reversal made today of Gold earned in
   an earlier period). Clamp with `GREATEST(sum, 0)`; never show a negative score.
5. **What counts is your decision, stated explicitly:** "Gold earned by learning" =
   `source_kind IN ('question_first_correct', 'lesson_first_completed', 'achievement')` plus
   `reversal` rows; `adjustment` rows are staff credits or debits, not learning.
6. **Excluding staff and test accounts is the leaderboard's job** (`app.staff_roles`); the ledger
   does not know who is staff.
7. Amounts and caps are placeholders (PO-09): rank on sums, never on a hard-coded amount. This lane
   contains no ranking of any kind.

There is no per-day rollup table; the covering index was judged sufficient for tonight.

### Source-key contract for the content and staff lanes (integration review L4)

Exactly-once rests on `question_key` being **stable and equal across locales and revisions** of a
lesson. Renaming a key in a new revision = a new source key = pays again (bounded by the
per-lesson cap). Reusing an old key for a different question = pays nothing. Both are tested as
current behaviour for added keys; content tooling must treat `question_key` as an identity.

## Worker and staff entry points (after staff B1)

| Function | Who | What |
|---|---|---|
| `rewards.reconcile_batch(max_learners, max_ops_per_learner)` | `edu_worker` | Bounded healing run. Returns `{"learners", "examined", "gold"}`. |
| `rewards.staff_reverse_entry(ledger_id, reason_code)` | `edu_staff`, active `admin` | Appends the single reversal of one award. Returns `{"ledger_id", "amount", "balance"}`. |
| `rewards.staff_adjust(learner_id, amount, reason_code, adjustment_id)` | `edu_staff`, active `admin` | Appends one adjustment. Returns `{"ledger_id", "amount", "balance", "replayed"}`. |

Rules of the two staff functions (all enforced in SQL and tested):

- `staff.require_role('admin')` first: any other caller gets `42501` and nothing is written.
- `reason_code` must be one of `duplicate_award`, `content_error`, `scoring_error`,
  `abuse_confirmed`, `support_goodwill`, `test_correction`; anything else, including a sentence,
  is `22023`.
- Adjustment bounds — **synthetic placeholders, `BLOCKED_BY_OWNER` (PO-09)**: 1…100 Gold either way
  per adjustment; at most 300 Gold credited to one learner per Haiti day; a balance can never go
  below zero; an admin cannot adjust their own account.
- `adjustment_id` is chosen once by the caller and reused on retry: same content → replay (no
  second row, no second audit event); different content or learner → `22023`.
- An award can be reversed once (`23505` on a second attempt); a reversal or an adjustment cannot
  be reversed — correct an adjustment with an opposite adjustment.
- Each accepted action writes exactly one audit event in the same transaction through
  `ops.audit_write`: `rewards_ledger.reverse` / `rewards_ledger.adjust`, target
  `rewards_ledger` + the new row's id, details = `learner_id`, `amount`, `reason_code` and
  `reversed_ledger_id` or `adjustment_id`. Only ids, numbers and enum codes (ruling R-03 item 3).
- `edu_staff` and `edu_worker` have `USAGE` on the schema and these functions only — no table
  privilege. `edu_api` got nothing new.

There is **no HTTP route** for either staff function yet; they were exercised through SQL and
through the real `edu_staff_login` / `edu_worker_login` connections.

Still granted to nobody: `rewards.rebuild_balance`, `rewards.rebuild_streak`,
`rewards.reverse_entry` (internal), `rewards.erase_learner` (for the `account` erasure
orchestrator), and the internal award / reconcile functions.

**Erasure contract for the orchestrator (security review L2), all in ONE transaction:** call
`rewards.erase_learner(id)` first — it keeps the learner's rewards lock until commit, so no award
or reconcile can run in between — then remove the learner's sync receipts and learning rows, then
delete `app.learner_profiles` (rewards foreign keys are `RESTRICT`), then commit. Tested with
summary requests racing the erasure: nothing is recreated. If receipts are left behind after the
commit, reconciliation re-derives the rewards from them (also tested, as documented behaviour).

## Decisions taken tonight (reversible)

1. **Own advisory lock instead of the sync row lock** for reconcile/rebuild, so healing never
   blocks a learner's sync for longer than one award.
2. **No foreign key to `app.sync_receipts` / attempts / progress.** The verified test-suite
   `TRUNCATE`s those tables without `CASCADE`, and receipt compaction is in Platform-00's backlog.
   The insert trigger validates the link instead. The only foreign key into `app` is to
   `app.learner_profiles` (it adds system RI triggers there, which the structure test does not
   count; no user trigger, grant, policy or function was added to `app`).
3. **Rules apply at examination time.** An operation healed later is paid by the rule version live
   when it is examined, on the day it was accepted (see open finding L2 below).
4. **Achievement counters** count rewarded ledger rows (lessons and correct answers), so an
   achievement needs the same evidence as the Gold it celebrates; streak from `longest_run_days`.
5. **Lazy reconcile inside a GET** (idempotent, bounded, failure-tolerant) because there is no
   worker yet.
6. **The hook also runs for replays** of accepted operations: it is a primary-key look-up when
   already examined and heals a failed award on the phone's next retry.
7. **Hook touches two baseline files** (`sync/service.py`: optional `on_accepted` parameter and two
   lines in the loop; `routers/sync.py`: passes the hook only when the flag is on). The brief named
   one or the other; the transaction lives in the service and the flag in the router's settings.

## Review findings — status

Fixed and tested: security H1 (search path), **M1** (hook time budget, skip rest of batch, batch
reconcile skips busy learners and is one-call-per-transaction), **M2** (evidence parameter, default
on), **L1** (caps final per source key), **L2** (erasure contract), **L3** (cursor); integration
**M3** (dating rule documented, covering index), **L3** (`no_active_rule` not final), **L4**
(documented).

**Open review findings** (not done tonight):

| Id | Finding | State |
|---|---|---|
| integration L2 | Select the rule version by the operation's `accepted_at` (`effective_from`) so erase + re-derive reproduces the same balance | Not built. Today the version live at examination time pays. |
| integration L5 | Per-learner reconcile watermark instead of the anti-join on every summary | Not built. The ledger page query does use an index led by `learner_id` (`idx_ledger_learner_recent`). |
| integration L6 | `Cache-Control: private, no-store` and an `as_of` instant on both endpoints | Not built. The app may show a "pending" label but **no pending amount** — amounts are not exposed before sync. |
| integration (other) | Summary must answer 503, not 500, when the rewards schema is unusable; TRUNCATE guard on the ledger | Not built. |
| missing tests | 50-operation batch with the flag on; reversal effect on day sums; reused `question_key`; paging during inserts; rule switch under concurrent load; day cap across Haiti midnight through the HTTP API (covered in SQL with pinned instants — the API has no clock seam) | Not written. |
| security N1 | Award once per batch instead of one savepoint per operation (`sync_max_ops` > 64) | Not built. |

## Known gaps

- Routes are not in the OpenAPI document (see above), so the native app has no generated types.
- No worker job schedules `reconcile_batch`; no HTTP route for the staff reversal / adjustment.
- Whether staff may credit Gold at all, and the bounds and reason list, need the owner (PO-09).
- A worker reconcile run writes no audit event (its ledger rows are the record).
- Back-dating, spending Gold, and any ranking are not built.
- `rewards.rules` has no editing endpoint; values change by migration or by an operator calling
  `rewards.set_active_rule_version`.
- The erasure hook was exercised alone; the orchestrator that calls it belongs to the identity lane.
- Nothing was load-tested beyond 20–25 concurrent requests on one laptop.

## How to run

```sh
export UV_CACHE_DIR=/Volumes/EdupreneursDev/caches/uv npm_config_cache=/Volumes/EdupreneursDev/caches/npm
make db-reset && make test-db                      # pgTAP: 209 baseline + staff B1 + rewards (180–195)
uv run pytest -q                                   # baseline with the flag OFF + rewards tests
EDU_REWARDS_ENABLED=true uv run pytest -q          # the same suite with the flag ON
uv run pytest -q --ignore-glob='*test_rewards_*'   # the 144 baseline tests alone (add the env var for "on")
```

The baseline `app` fixture builds its settings from the environment, so `EDU_REWARDS_ENABLED=true`
switches the hook on for all 144 baseline tests. The rewards tests build their own applications
with the flag set explicitly, so they mean the same thing in both runs.
