# 8. Database proposal

**Status: implementation-ready specification, not a migration.**
[`sql/tutor_schema.sql`](sql/tutor_schema.sql) is not under `supabase/migrations`
and is applied nowhere except to throwaway databases created by `tests/tutor_pg`.
An integration test asserts the application database has no `tutor` schema.

Why not a migration now: the staff/worker roles that should own the privileged
functions are in unmerged work (#4), the erasure orchestrator that must call
`tutor.erase_learner` is in #5, and the limits are owner decisions. Adding
tables to `main` ahead of those would create schema nobody can operate.

## Objects

| Object | Purpose |
|---|---|
| `tutor.policy` | One row: `paused` and every limit. **Starts paused with all limits 0.** |
| `tutor.price_versions` | Append-only prices (trigger refuses update/delete) |
| `tutor.usage_requests` | The ledger: one row per request that reached the budget. Unique `(learner_id, request_key)`. |
| `tutor.budget_counters` | `reserved`, `spent`, `request_count` per scope (global / learner) and period (day / month) |
| `tutor.usage_attempts` | One row per provider call that may have been billed: model, price version, tokens, cost, metered or not |
| `tutor.admin_audit` | Privileged operations, and system records of overages, dispatch mismatches and orphan settlements (to merge into `app.audit_events` with #4) |

`usage_requests` columns: ids, status, day, month, `reserved_micro`,
`spent_micro`, token counts, attempts, `outcome`, `provider`, `model`,
`price_version`, `prompt_version`, `lesson_revision_id`, `dispatches`,
`unmetered_attempts`, `bound_violations`, `overage_micro`, timestamps. One row
per **admission**: a key has at most one row that is not `released` (partial
unique index), and the row id is the reservation id. **No column
can hold conversation text**; the text columns are `CHECK`-constrained to code shapes.

`learner_id` has no foreign key, like `app.audit_events.actor_id`: account
deletion must not be blocked by, or cascade blindly into, an accounting table.
Erasure is explicit (`tutor.erase_learner`).

## Functions

| Function | Caller | Behaviour |
|---|---|---|
| `tutor.is_paused()` | API role | Kill-switch state |
| `tutor.reserve(request_key, estimate_micro)` | API role | Atomic check-and-hold; returns `reserved` or the refusing limit |
| `tutor.authorize_dispatch(reservation_id)` | API role | Before every provider call: `authorized` (and counted) / `paused` / `not_active` |
| `tutor.settle(reservation_id, …)` | API role | Records real cost once, uncapped; `settled` / `late_overage` / `already_finished` / `not_found`; pauses on an amount above the hold or a bound violation |
| `tutor.release(reservation_id, outcome, refused_attempts)` | API role | Returns a hold no billable call was made on; `dispatch_mismatch` if a dispatch is unaccounted for |
| `tutor.my_usage()` | API role | The caller's own counters; takes no learner parameter |
| `tutor.expire_stale(limit)` | worker | Charges reservations nobody settled |
| `tutor.set_paused(paused, actor)` | staff | Kill switch, audited |
| `tutor.erase_learner(learner, actor)` | erasure orchestrator | Deletes the learner's rows and counters; keeps global totals; audited without naming the learner |
| `tutor.purge_older_than(cutoff, actor)` | retention job | Deletes finished rows older than the cutoff; audited |

## Security model

- The API role (`edu_api`) gets `USAGE` on the schema and `EXECUTE` on the six
  functions above — **no privilege on any table**. Tested: direct `SELECT`,
  `UPDATE`, `INSERT`, `DELETE` and calls to privileged or internal functions all
  fail with "permission denied".
- The functions are `SECURITY DEFINER` with `search_path = ''` and identify the
  learner through `app.current_actor_id()`. There is no learner parameter to
  forge; a call without an actor is refused; a reservation id belonging to
  another learner is simply not found (tested with a forged reservation).
- Row-level security is enabled on every table with no policy, so even a
  mistaken future table grant reveals nothing.
- This follows the repository's existing pattern (sync functions in
  `…000400_sync_functions.sql`). The standing hardening note in
  `docs/NEXT_STEPS.md` — a dedicated owner role for `SECURITY DEFINER`
  functions — applies here too.

## Concurrency model

Every `reserve` / `settle` / `release`:

1. takes row locks, in one fixed order: **policy row → global month → learner
   month → learner day → request row** (creating a counter row if needed).
   `reserve` and `authorize_dispatch` take the policy row `FOR SHARE`;
   `set_paused` updates it, so a pause is strictly before or after each of them;
2. then reads the ledger and counters, decides, and writes;
3. commits, releasing the locks.

Fixed order means no lock cycle between these functions. They assert
`READ COMMITTED` isolation and raise otherwise, because step 2 depends on
seeing what the previous lock holder committed. Concurrency limits are counted
under the same locks, so they are exact.

Trade-off: the single global counter row serialises reservations. Measured
behaviour at scale is unverified; see [06](06-cost-and-budget.md).

## From proposal to migration (Jude-02 checklist)

1. Owner approves limits, retention period and who may flip the kill switch.
2. Rebase onto the staff/worker roles; grant `expire_stale`, `set_paused`,
   `erase_learner`, `purge_older_than` to them; move audit writes to `app.audit_events`.
3. Register `tutor.erase_learner` with the erasure orchestrator and
   `expire_stale` / `purge_older_than` with the worker.
4. Copy the file into `supabase/migrations` with a new timestamp; add pgTAP
   tests mirroring `tests/tutor_pg` (structure, privileges, RLS); extend
   `supabase/tests/010_structure.sql`.
5. Point `tests/tutor_pg` at the migrated schema instead of applying the file.
6. Decide whether `tutor.policy` is edited through the admin console (AD-9) or
   by migration only.
