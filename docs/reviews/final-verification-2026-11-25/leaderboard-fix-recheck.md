# leaderboard-fix-recheck — overnight/leaderboard @ 4706cf7 (fix of LB-1..LB-7 on 472f792)

Reviewer: independent security re-check, worktree final-verification/qa6 (stack edu-fv-qa6, PG 58322). Written as I go.
Scratch: /Volumes/EdupreneursDev/logs/final-verification-2026-11-25/tmp/leaderboard-fix-recheck/

## Suites observed at 4706cf7 (after `uv sync --frozen && make db-reset`)
- pgTAP `make test-db`: Files=18, Tests=1183, PASS (matches implementer).
- pytest `make test-api`: 497 passed (matches implementer). The 5 000-member test printed: my_standing median 0.2 ms, worst 1.2 ms; refresh_snapshot 966 ms.

## Hygiene (catalog) — PASS
- 10 functions in `leaderboard`, all owner postgres, all `search_path=pg_catalog, pg_temp`; SECURITY DEFINER: enroll, erase_learner, my_standing, refresh_snapshot, withdraw.
- EXECUTE among edu_api/edu_api_login/edu_staff(_login)/edu_worker(_login)/anon/authenticated/authenticator/service_role/public: only edu_api + edu_api_login on my_standing.
- 7 tables (new: config), RLS on, 0 policies, ACL postgres only; no role above holds any table privilege; no default ACLs; schema USAGE postgres + edu_api.
- The fix migration's DDL/DML targets only `leaderboard.*` (one REVOKE line on ALL TABLES IN SCHEMA leaderboard). Nothing in app/rewards/ops/staff. Only migration changed vs 472f792 is the new file; the original migration is untouched.
- Baseline files byte-identical to origin/main at 4706cf7.
- `leaderboard.visible_rows` is left in place, unused (dead code; harmless, owner-only).

## R1 — original LB-1 reproduction re-run over HTTP (scripts/recheck_http.py -> recheck_http.out)
The original small-cohort scenario (two synthetic learners, repeated refreshes, the reader only uses its own `/v1/leaderboard/me`), both flags on.
- **K=5 (default):** every refresh writes 0 rows (`members 0`); B always sees `rank=None size=None snapshot_gold=None`; withdrawal, refresh, re-opt-in, refresh: nothing changes for B. The original inference is closed. PASS.
- **K lowered to 1 by owner SQL (the CHECK allows it):** the original inference class (another member's exact Gold, and participation changes at refresh granularity) returns in a 2-member cohort. Snapshot-only reads still hide changes until the next refresh. The protection rests entirely on the value of K, and one owner-level UPDATE can switch it off. See NEW LB-R2. Impact: re-opens LB-1 for small cohorts. Fix: a hard lower bound on K.

## R2 — new inference paths, owner SQL with my_standing executed as edu_api (scripts in tmp/inference.sql -> inference.out; all rolled back)
14 synthetic learners, learner n has 10n Gold all-time (+n in closed week 2026-11-16). Cohort X = L1..L5 (exactly K=5), reader L3.
- S1 exactly K: `3/5`; L5 withdraws, no refresh: still `3/5` (PASS: not live); refresh -> 4 < K -> `null/null`, snapshot_gold null, the cohort block (cohort_id, pseudonym, computed_at) stays. L5 re-enrols: `null/null` until refresh, then `3/5`. The disappearance tells the reader "the number of participants fell below K at the last refresh" — the same information as a size drop K+1 -> K (S4: `5/6` -> `4/5`). Neither identifies who. Residual: the exact `size` publishes the net change in the number of participating classmates per refresh. ACCEPTABLE residual at K>=5 in my judgement, provided refreshes are batched on a schedule (not run after individual consent events), see LB-R3.
- S2 exactly one other member earns between two refreshes: the reader's rank drops by one with its own snapshot Gold unchanged. The reader learns that some classmate passed it — not who, not how much. This is the intended function of a rank and an ACCEPTABLE residual. Limit, stated plainly: over many refreshes a reader can learn the distribution of the other members' Gold without identities, and K-1 colluding members can bracket the remaining member's Gold (the usual k-anonymity limit).
- S3 own live gold vs snapshot_gold: `gold=34 snap=33` until refresh, then 34/34. Only own data. PASS.
- S5 closed week frozen at 5: L5 withdraws -> L5's row deleted (4 rows left) but run member_count stays 5, reader still `3/5 frozen` (no leak); re-enrolled L5 gets `null/null frozen` and refresh of that week -> `recomputed false`. PASS.
- S6 cohort switch X->Y (withdraw X, enrol Y): before refresh X readers unchanged `4/5`, Y readers unchanged `5/5`, switcher sees Y with `null/null`; after refresh X -> `null/null` (4 < K), Y -> `5/6`, switcher `6/6`. Nothing live. PASS.
- S7 K raised to 7: Y(6) -> `null/null` at read, no refresh needed (fail closed). K lowered to 2: X keeps `null/null` until refresh (no rows), then `3/4`. `DELETE FROM leaderboard.config` -> reads fall back to 5: X(4 rows) `null/null`, Y(6) `5/6`; refresh writes 0 rows for X. Fail-closed default PASS.
- S8 another member granted staff: unchanged until refresh (`5/6` -> `4/5` after); revoked: unchanged until refresh. Reader granted staff -> `cohort null` at once; revoked (no refresh) -> own old row back `5/6` (own data). PASS.
- S9 erasure of another member: unchanged `5/6` until refresh, then `4/5`. S10 auth soft-delete of another member: unchanged until refresh. PASS.
- S11 `my_standing` as edu_api returns the full cohort block: the cohorts flag is not known to SQL (see R4).

## R3 — concurrency, real separate asyncpg connections (scripts/race.py -> race.out, scripts/race_rr_frozen.py -> race_rr_frozen.out), K=1 so 2 students form a ranked cohort
- C1 original R6 (refresh `all` + closed week 2026-11-16 in one tx; withdraw A from a 2nd connection): withdraw **waited** for the refresh commit, returned true, A rows after = 0, B rows 2; A re-opts in and reads the closed week: `rank null, size null, frozen true` (no resurrection). PASS.
- C2 erase B during refresh: waited, then `{"snapshots": 1, "memberships": 1}`; B rows 0, membership 0 (no 23503 any more). PASS.
- C3 two refreshes of the same (cohort, period): second waits (advisory lock), both succeed, rows 2 = run member_count 2. PASS.
- C4 learner read during an uncommitted refresh: 4.3 ms, not blocked, sees the previous committed snapshot. PASS.
- C5 withdraw first (uncommitted), refresh starts afterwards, READ COMMITTED: refresh waits, then members=1, A rows 0. PASS.
- C8 enroll during refresh: waits; A gets no row until the next refresh. PASS.
- C7 two multi-period refresh transactions taking the periods in opposite order (`all` then week vs week then `all`): one gets `DeadlockDetectedError`, the other commits. Detected and rolled back, no hang, no partial state; only reachable by a caller that refreshes several periods in one transaction in different orders. NOTE.
- **C6 (NEW, LB-R1): race window at non-default isolation.** Class: TOCTOU between the cohort lock and the transaction snapshot. When the refresh runs inside a REPEATABLE READ or SERIALIZABLE transaction, its snapshot predates the lock wait, so a withdrawal that commits during the wait can be ignored and the withdrawn learner written into the snapshot — for a closed week permanently (it reappears on re-opt-in, the original LB-2 impact). SSI did not prevent it. Under READ COMMITTED (the default and the only isolation any caller uses today) the fix holds. Only owner SQL can call refresh today, so LOW. Fix: refuse non-READ-COMMITTED isolation in refresh_snapshot, or lock the scored membership rows so RR/SSI raise a serialization error; add an RR variant of the two-connection test.

## R4 — flags (LB-4), HTTP, ASGI apps built with build_settings (recheck_http.out)
B is an opted-in, ranked member (K=1). `/v1/leaderboard/me`:
- both off: 404 with and without token, body identical (minus request_id) to `/v1/does-not-exist`. PASS.
- `EDU_LEADERBOARD_COHORTS_ENABLED` alone: same standard 404 (with/without token). PASS.
- `EDU_LEADERBOARD_ENABLED` alone: 200 `{"period":…,"gold":15,"cohort":null}`; no token 401. PASS.
- both on: 200 with the cohort block (cohort_id, pseudonym, rank, size, …); no token 401. PASS.
- Below HTTP: the gate is `service.my_standing(include_cohort=…)` (`services/api/src/edu_api/leaderboard/service.py:33-34 @4706cf7`), applied after the SQL call. `leaderboard.my_standing` executed as edu_api returns the full cohort block regardless (R2 S11). Severity NOTE: edu_api_login is held only by the API process (and the API is the only caller that sets the verified actor); the block contains only the caller's own pseudonym/cohort id and K-gated rank/size, so a bypass would require API compromise, which already exposes more. Defence in depth if wanted: a `cohorts_enabled boolean DEFAULT false` column in leaderboard.config checked in my_standing.

## R5 — performance, 5 000 members (perf.sql/perf.out, perf2.sql/perf2.out; all rolled back)
5 000 synthetic learners via the real `enroll` path (5.3 s), 4 ledger rows each, actor n=2500.
| measurement | no fresh statistics (bulk load in the same tx, never ANALYZEd — the original review's condition) | after ANALYZE (the implementer's test condition) |
|---|---|---|
| NEW my_standing (4706cf7) week/all | 1.6-2.8 ms | (pytest: median 0.2 ms, worst 1.2 ms) |
| OLD my_standing (472f792 body re-installed in the same tx) week/all | **2 698-2 763 ms** | **67-69 ms** |
| NEW refresh_snapshot week / all | **9 717 ms / 6 139 ms** | 90 / 88 / 98 ms (pytest: 966 ms, ANALYZE of ledger+memberships only) |
- Both earlier numbers are right, under different conditions: the 3 s came from planning with no statistics on freshly loaded rows; with statistics the old read costs ~70 ms. The steady-state severity of the original LB-3 was therefore overstated (O(n) at ~70 ms/read at 5 000, not 3 s), but it was still linear and is now constant time (~1-3 ms, independent of statistics). LB-3 fix: PASS.
- The new refresh is plan-sensitive: 6-10 s right after a bulk enrolment before autovacuum/ANALYZE, ~90 ms after. Not on the request path (owner-only today); a future worker with a statement_timeout should ANALYZE after bulk enrolment or the refresh query should be made plan-robust. NOTE (LB-R5).

## R6 — tests changed by the implementer
- pgTAP 205: three assertions changed from "the others move up / cohort shrinks AT ONCE, without a refresh" (opt-out, staff grant, erasure) to "others keep rank/size of the snapshot until the next refresh". The old assertions encoded the LB-1 side channel itself; the new ones assert its absence. The privacy assertions around them are untouched: the withdrawn/staff/erased learner loses the own block at once, snapshot rows deleted from every period, consent instant recorded, "a refresh after erasure does not bring C back". K lowered to 1 mid-file inside the file's rolled-back transaction, after the pre-existing admin/opt-out cohort checks. Not weakened.
- pgTAP 200: table list 6 -> 7 (config). Not weakened.
- pytest test_leaderboard_api.py: two `(rank,size)` assertions changed from live `(1,1)` to snapshot `(2,2)` (same reasoning), plus the post-refresh exclusion check for staff (rows 0) kept; the week test now reads the period back from the response (LB-5 flake fix) and adds an explicit closed-week check. `low_floor` (K=1) applies to the pre-existing API tests only; their privacy checks (no other learner's data in the body, spoofed params ignored, 404/401 shapes, staff never ranked) do not depend on K. `clean_leaderboard` resets K to 5 on wipe. Not weakened.
- New tests: 210 (K floor 1..5, K boundary, opt-out/opt-in/staff invisible until refresh, K raised at read time, allow-list, Haiti DST boundaries with explicit instants, frozen Gold) and test_leaderboard_review_fixes.py (flag combination lb_only, floor through the API, withdrawal invisible until refresh, frozen Gold, two-connection withdraw/erase during refresh at READ COMMITTED, 5 000 timing). Gaps: no test for "cohorts flag on + leaderboard flag off -> 404" (verified manually, PASS); concurrency tested only at READ COMMITTED (LB-R1); no test that K cannot be set below a safe floor (LB-R2).

## Other checks
- LB-6: `period_gold` and the set-based refresh both use the allow-list `IN ('question_first_correct','lesson_first_completed','achievement','reversal')`; no `<> 'adjustment'` left in the live functions. PASS.
- LB-7: closed + frozen period returns the snapshot Gold (S5: `gold=3 snap=3 frozen=true`; 210 late-ledger-row case). PASS.
- LB-5: 210 covers Sunday 23:59:59 / Monday 00:00 in the DST-start and DST-end weeks with explicit instants; the pytest week test no longer recomputes the period from the clock. PASS.
- Refresh reads app.staff_roles and auth.users without locks: a staff grant or soft-delete committed during a refresh can be ranked until the next refresh (the person's own block is hidden live; others only see a count including them). Not a consent decision; NOTE only.
- Erasure through `account.erase_learner`: no `account` schema on this branch; not re-examined (original R8 on the integration branch).

---

# Verdict

**PR #13 + 4706cf7 is acceptable as a DRAFT carrying the leaderboard to the owner (flags off, not merged).** The original LB-1 inference is closed at the default K=5 (reproduced: no rank/size, no observable opt-out/opt-in); rank and size come only from the snapshot, so another member's opt-out, opt-in, staff grant, soft-delete or erasure is never visible before a refresh; frozen weeks no longer leak; the cohort block needs both flags; the read is constant-time; LB-2 is fixed under READ COMMITTED (the only isolation any caller uses today); hygiene, grants, baseline and suites (pgTAP 1183, pytest 497) check out; the implementer's test edits strengthen, not weaken, the privacy property.

Before the owner ever enables it (not blocking the draft): LB-R1 (refresh must refuse or be safe under REPEATABLE READ/SERIALIZABLE), LB-R2 (do not let K drop below a safe hard floor; K is BLOCKED_BY_OWNER), LB-R3 (owner decision on refresh cadence and exact vs banded size — the remaining residual).

# Findings (new)
| ID | Severity | Location | Evidence | Smallest fix |
|---|---|---|---|---|
| LB-R1 | LOW | `supabase/migrations/20261125000200_leaderboard_review_fixes.sql:121,149-166 @4706cf7` | Class: lock/snapshot ordering race. Impact: a refresh run at REPEATABLE READ/SERIALIZABLE concurrently with a withdrawal can keep the withdrawn learner in a snapshot, permanently for a closed week. Verified with two connections. Owner-only caller today. | Refuse non-READ-COMMITTED isolation in refresh_snapshot (or lock scored membership rows); RR variant of the concurrency test. |
| LB-R2 | LOW | `…review_fixes.sql:26 @4706cf7` | Class: privacy floor configurable down to 1. Impact: at K=1/2 the original LB-1 inference returns unchanged (verified). The test suite runs most ranking tests at K=1. | Hard lower bound in the CHECK (owner-decided, e.g. 5) and test cohorts of that size, or change K only through an audited owner function. |
| LB-R3 | NOTE (residual, owner policy) | design (`my_standing`, size field) | R2 S1/S4: exact `size` publishes the net change in the number of participating classmates at each refresh (K -> block disappears; K+1 -> K); S2: a rank change shows that some classmate passed the reader. Never who. K-1 colluders recover the remaining member's Gold bracket. | Refresh on a fixed batched schedule (never after individual consent events); consider banded size ("5-9", "10-19") or no size; keep K >= 5. |
| LB-R4 | NOTE | `services/api/src/edu_api/leaderboard/service.py:33-34 @4706cf7` | Cohorts flag enforced only in the service; SQL returns the block to edu_api (R2 S11). Only the API holds edu_api_login. | Optional: `cohorts_enabled` in leaderboard.config checked in my_standing. |
| LB-R5 | NOTE | refresh_snapshot @4706cf7 | 6-10 s at 5 000 members right after bulk enrolment without statistics; ~90 ms after ANALYZE. | ANALYZE after bulk enrolment in the future worker / statement_timeout budget; plan-robust query. |
| LB-R6 | NOTE | refresh_snapshot advisory lock | Two transactions each refreshing two periods in opposite order: one `deadlock detected` (rolled back cleanly). | Document "one refresh per transaction" or take period locks in a fixed order. |
| LB-R7 | NOTE | `20261124060100_leaderboard_schema.sql:216 @4706cf7` | `leaderboard.visible_rows` unused after the fix (owner-only). | Drop it in the next migration. |

# Verification table
| ID | Original defect | Affected commit | Reproduction (ran -> saw) | Fix assessment | Remaining exploit / regression path | Test coverage | Verdict |
|---|---|---|---|---|---|---|---|
| LB-1 | Small cohort: own rank + size revealed another child's Gold and consent decisions | 472f792 | Original scenario re-run over HTTP at default K=5: no rank/size ever returned, no other-member event visible; SQL scenarios S1-S10 (exact K, K+1, switch, K changes, staff, erasure, soft-delete): nothing visible before a refresh | Floor enforced at refresh and read, fail-closed; snapshot-only rank/size | K can be lowered to 1 (LB-R2); residual count/rank-change disclosure at refresh granularity (LB-R3) | pgTAP 210, pytest | PASS (with LB-R2, LB-R3) |
| LB-2 | Opt-out lost to a concurrent refresh; erase failed during refresh | 472f792 | Two-connection probes: original scenario now waits and deletes (no resurrection, closed week included); erase waits then succeeds; concurrent refreshes, enroll and reads correct. At REPEATABLE READ/SERIALIZABLE the original impact recurs (LB-R1) | Correct under READ COMMITTED | LB-R1; detected deadlock (LB-R6) | pytest two-connection tests, READ COMMITTED only | PASS for READ COMMITTED; FAIL under RR/SERIALIZABLE (LB-R1, LOW) |
| LB-3 | ~3 s read at 5 000 members | 472f792 | perf.sql: old body 2.7 s without stats / 67 ms with stats; new 1.6-2.8 ms without stats, 0.2-1.2 ms with | Constant-time read | refresh plan-sensitive (LB-R5), not on request path | pytest 5 000 test (bound 30 ms read, 5 s refresh) | PASS |
| LB-4 | Cohort data without the cohorts flag | 472f792 | recheck_http.py: off/off 404 (identical), cohorts-only 404, lb-only `cohort:null`, both on -> block | Gated in service layer | SQL still returns block to edu_api (LB-R4, NOTE) | pytest lb_only; no test for cohorts-only | PASS |
| LB-5 | No Haiti boundary/DST tests; clock flake | 472f792 | read 210 + pytest diff; suites pass | Explicit-instant tests for both DST weeks; period read back from response | none found | pgTAP 210, pytest | PASS |
| LB-6 | Deny-list scoring | 472f792 | catalog/function bodies: allow-list in period_gold and refresh | Fixed | none | pgTAP 210 regex on function defs | PASS |
| LB-7 | Live Gold for a closed week | 472f792 | S5 `gold=3 snap=3 frozen=true`; 210 late-row case 1 not 51 | Fixed | none | pgTAP 210, pytest | PASS |
| H | Hygiene: search_path, owner, grants, RLS, nothing in app/rewards/ops/staff, baseline | 4706cf7 | catalog queries; git diff vs origin/main | Clean (config: RLS, no policy, owner-only ACL) | visible_rows dead (LB-R7) | pgTAP 200/210 | PASS |
| T | Implementer's test edits do not weaken privacy | 4706cf7 | read diffs of 200/205/pytest/fixtures | Edits invert assertions that encoded the leak; surrounding checks kept; K=1 confined to rolled-back tx / fixture reset | none | — | PASS |
| S | Suite counts | 4706cf7 | make test-db: 18 files, 1183 PASS; make test-api: 497 passed | matches implementer | — | — | PASS |

# Not examined
- Erasure through `account.erase_learner` (no account schema on this branch); integration-branch merge of 4706cf7.
- Load through HTTP (pool exhaustion), PostgREST exposure of the new config table over HTTP (catalog checked: no grant, schema not exposed per original review).
- Mobile/native; future cohort/membership/staff routes and a scheduled refresh (not built).
- Account states other than staff grant, auth soft-delete and erasure (e.g. pending deletion request).
