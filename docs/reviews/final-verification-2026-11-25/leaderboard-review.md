# leaderboard-review — branch overnight/leaderboard @ 472f792 (stacked on rewards-gold ce5a64e)

Public version. Exploitable weaknesses are described as class, impact and fix only; the
reproductions are kept in the private report.

Scope: `git diff ce5a64e 472f792` (migration `20261124060100_leaderboard_schema.sql`,
`services/api/src/edu_api/leaderboard/`, `routers/leaderboard.py`, `supabase/tests/200_*`, `205_*`,
`tests/integration/test_leaderboard_api.py`, `tests/leaderboard_fixtures.py`), checked against the
lane brief and the rewards ledger contract. Reproduced on a disposable local stack with the real
`edu_api_login` role and an actor set, the HTTP API built with the flag on through settings
overrides, and owner SQL. Erasure was also checked on `overnight/integration-2026-11-24` (34a2e6d).

## Suites observed at 472f792
- pgTAP: 1133 tests in 17 files, PASS; leaderboard files 61 + 111 = 172.
- pytest: 489 passed; `test_leaderboard_api.py` 24.
These match the lane's figures.

## Verdict

**PR #13 is not ready to merge and stays a draft.** The permissions are clean: grants, search_path,
ownership, RLS, Data API exposure, the flag-off 404, no global ranking, no names or e-mail,
exactly-once scoring through the ledger, and erasure through the account orchestrator. Three
problems remain:

- In small cohorts the one learner read reveals other children's Gold and consent decisions (LB-1).
- The read cost grows with cohort size. At the brief's own 5 000-member scale it can tie up the
  whole API (LB-3).
- Opt-out can lose against a refresh that runs at the same time (LB-2).

472f792 is already part of the integration branch (PR #11). There it does nothing until someone
turns the flag on, and only the owner can enrol learners, through SQL.

Before PR #13 can be considered:
- LB-1: enforce a minimum cohort size in SQL, failing closed, and stop revealing cohort size changes live.
- LB-3: rewrite the read as one set-based query and add the 5 000-member timing test.
- LB-2: lock refresh against withdraw and erasure, and add a concurrency test.
- LB-4: put the cohort block behind the cohorts flag as well.
- LB-5: add tests for the Haiti week boundary and DST.

## Findings

| ID | Severity | Location | Class and impact | Fix |
|---|---|---|---|---|
| LB-1 | MEDIUM (becomes HIGH as soon as a real class can be enrolled) | `supabase/migrations/20261124060100_leaderboard_schema.sql:216-228, 418-436 @472f792` | **Small-cohort inference.** There is no minimum cohort size. Rank and cohort size are recomputed live at every read. In a cohort of two or three, a learner can work out how much Gold an identifiable classmate has, compared with their own and in some cases exactly, from how their own rank changes. Because size is recomputed live, a learner also sees right away when another member opts in, opts out, is erased or becomes staff. So one child's consent decision is visible to their classmates. | In `my_standing`, return no rank or size below a minimum K (for example 5, as a constant the owner can change). Take the population from the snapshot instead of recomputing it at read time; still hide the withdrawn learner's own row. Consider bands instead of exact positions for small cohorts. Add pgTAP tests for sizes 1–4 and for "another member's opt-out does not change my size before the next refresh". |
| LB-2 | LOW | `…leaderboard_schema.sql:296-311, 352-374 @472f792` | **Race between snapshot refresh and opt-out/erasure.** If a learner opts out while a refresh is running, the refresh can still store snapshot rows for that learner, including the final rows of a closed week. The opt-out is then incomplete: data is kept, and a closed-week row can come back if the learner opts in again. It can never be recomputed. If erasure runs during a refresh, it fails with a foreign-key error and has to be retried. It fails closed, so nothing is left half-erased. | Serialise these per cohort. Refresh locks the cohort row `FOR SHARE` (or the memberships it reads); withdraw and erase lock it `FOR UPDATE` first. Add a test with two sessions. |
| LB-3 | MEDIUM (availability) | `…leaderboard_schema.sql:181-228, 422-427 @472f792` | **Read cost grows with cohort size, and a learner can trigger it.** The read calls helper functions for every row, and their `SET search_path` clause stops PostgreSQL from inlining them. In a 5 000-member cohort one `/me` read took about 3 s; a set-based version of the same query took about 10 ms. With a 5 s statement timeout and a 10-connection pool, a few concurrent reads use up the API's database connections for every route, and larger cohorts time out. There is no per-learner request budget, and the brief's required 5 000-member timing test was not done. | Use one set-based statement (joins plus `NOT EXISTS` on staff roles, `count(*) FILTER (WHERE gold > mine)`), add an index on `snapshots (cohort_id, period_key, gold)`, add a per-learner request budget, and add the large-cohort timing test with an upper bound. |
| LB-4 | LOW | `services/api/src/edu_api/config.py:72-78`, `routers/leaderboard.py:28-31 @472f792` | **The cohorts flag does nothing.** Nothing reads `EDU_LEADERBOARD_COHORTS_ENABLED`, so `/me` returns pseudonym, cohort id, rank and size under `EDU_LEADERBOARD_ENABLED` alone. | Return `cohort: null` unless the cohorts flag is on too, and test both flag combinations. |
| LB-5 | LOW (tests) | `supabase/tests/205_*`, `tests/integration/test_leaderboard_api.py @472f792` | **Missing and clock-dependent tests.** Missing: the large-cohort timing, the Haiti Sunday/Monday boundary and DST weeks, concurrency between refresh and opt-out or erasure, the mock-data script, and exclusion of system/test-marker accounts (no such marker exists yet). The week assertions use the current Haiti date across separate transactions or requests, so a run that crosses Sunday→Monday midnight in Haiti can fail spuriously. | Add boundary tests on 2026-03-08/09 and 2026-11-01/02 with explicit `accepted_day`, and take the period from the response instead of recomputing it. |
| LB-6 | NOTE | `…leaderboard_schema.sql:200 @472f792` | Scoring excludes adjustments with a deny-list, while the rewards contract defines an allow-list. A source kind added later would count towards rank without anyone deciding it should. | `source_kind IN ('question_first_correct','lesson_first_completed','achievement','reversal')`. |
| LB-7 | NOTE | `…leaderboard_schema.sql:445 @472f792` | For a closed week, `gold` is the live sum while the closing snapshot is frozen, so the two can differ. The lane documents this. It concerns the learner's own data only. | Return the snapshot value for closed periods, or label the live figure as such. |
| LB-8 | NOTE | migration | Opt-ins and opt-outs are not audited, and nothing records who gave consent (BLOCKED_BY_OWNER). | When routes exist, audit them with ids and codes only. |

## Verification table

| ID | Property | Commit | Reproduction result | Fix assessment | Remaining path | Test coverage | Verdict |
|---|---|---|---|---|---|---|---|
| V1 | No public/global ranking | 472f792 | The only route is `/me`. `global` and cohort-less refreshes are refused. | n/a | none | pgTAP, pytest | PASS |
| V2 | No real name, display name or e-mail | 472f792 | Only a pseudonym from the 576-name allow-list appears. No profile column is read. | n/a | none | pgTAP, pytest | PASS |
| V3 | Only the caller's own data | 472f792 | Direct fields are the caller's own, and spoofed query parameters are ignored. Indirect leak through rank and size in small cohorts. | needed | LB-1 | none | FAIL |
| V4 | Unknown consent = not a member; flags off by default | 472f792 | Nothing is seeded, enrolment is owner-only, both flags default to off. | cohorts flag unused | LB-4 | pgTAP, pytest | PASS |
| V5 | Errors, timing and `period` reveal nothing about others | 472f792 | 15 period variants, including Unicode digits, return 200 or 422 with one message and no echo. No 500. | n/a | none | pytest | PASS |
| V6 | RLS and Data API | 472f792 | RLS on every table with no policy. PostgREST refuses the schema for both anon and learner tokens. | n/a | none | pgTAP | PASS |
| V7 | Ledger only; adjustments out, reversals in, negatives clamped | 472f792 | Confirmed by reading the code and by the pgTAP cases. | deny-list | LB-6 | pgTAP | PASS |
| V8 | Competition ranking, deterministic ties | 472f792 | Ties share a rank; the read's rank matches `rank()`. | n/a | none | pgTAP | PASS |
| V9 | Haiti week boundaries and DST | 472f792 | Correct at 4 boundaries (including DST start and end, 2026–2027). | n/a | none | none | PASS (untested) |
| V10 | Closed-week freeze | 472f792 | Freeze holds; a concurrent opt-out can still leave rows behind. | lock | LB-2 | pgTAP | PASS with LB-2 |
| V11 | Replayed sync operations never move a rank, end to end | 472f792 | Through `/v1/sync/push` with rewards on: replays and re-sent answers leave Gold, rank and snapshot unchanged. | n/a | none | pytest, pgTAP | PASS |
| V12 | Recomputation equality | 472f792 | Rows are rebuilt identically. | n/a | LB-2 | pgTAP | PASS |
| V13 | Refresh vs read vs opt-out concurrency | 472f792 | Reads are consistent. The opt-out and erasure races are confirmed. | needed | LB-2 | none | FAIL |
| V14 | Staff (active and inactive roles), opted-out and erased learners excluded at refresh and read | 472f792 | Confirmed. | n/a | read-time exclusion feeds LB-1 | pgTAP, pytest | PASS |
| V15 | Erasure hook complete and registered | 472f792 / 34a2e6d | Through `account.erase_learner` nothing is left. If the hook is unregistered, erasure is blocked (fails closed). The registration lives in the account lane's migration. | n/a | LB-2 (retry) | hook level only | PASS |
| V16 | search_path, owner, grants | 472f792 | All 10 functions use `pg_catalog, pg_temp` and are owned by postgres. `edu_api` can execute only `my_standing`. No grant for PUBLIC/anon/authenticated/authenticator/service_role. | n/a | none | pgTAP | PASS |
| V17 | Nothing in app/rewards/ops/staff; no FK to the learning tables; baseline files unchanged | 472f792 | Confirmed. | n/a | none | pgTAP | PASS |
| V18 | Hidden route, standard 404 with flag off | 472f792 | Response identical to an unknown path, with or without a token. | n/a | none | pytest | PASS |
| V19 | Audit details without free text | 472f792 | Nothing is audited. | n/a | LB-8 | n/a | PASS |
| V20 | Timings for a 5 000-member cohort | 472f792 | About 3 s per read. | needed | LB-3 | none | FAIL |
| V21 | Suite counts | 472f792 | 1133/172 pgTAP, 489/24 pytest | — | — | — | PASS |

## Not examined
- Cohort page, membership and staff routes, and the scheduled refresh: none of these exist yet.
- Account lifecycle states other than an auth soft-delete, for example whether a pending deletion request is still ranked.
- Native/mobile.
- Load through HTTP: pool exhaustion was inferred from the measured SQL time and the settings, not load-tested.
