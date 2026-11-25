# Lane LEADERBOARD — step 1: private standing (F14)

Branch `overnight/leaderboard`, stacked on the Gold ledger (`ce5a64e`). Migration
`20261124060100_leaderboard_schema.sql`. Flag `EDU_LEADERBOARD_ENABLED`, default **off**.

**Status: step 1 only.** The schema, the snapshot refresh, the erasure hook and one read route
(`GET /v1/leaderboard/me`) exist and are tested. No cohort list, no membership route and no staff
route exists (see "Not done").

## Privacy position (the learners are minors)

- There is **no public or global ranking in any code path**. A rank exists only inside one cohort
  and only for a learner with an explicit opt-in row. Unknown consent = not a member. `global` is
  not a period and is refused.
- Schema `leaderboard` holds **no real name, no profile display name, no e-mail**: a pgTAP test
  asserts that no column carries such a name, and the API test asserts the response contains none
  of the caller's or anyone else's identity fields.
- The only label is a **pseudonym assigned by the server** from `leaderboard.pseudonym_pool`
  (576 generated neutral pairs such as "Colibri Sage"; unique inside a cohort; suffix `" n"` once a
  cohort outgrows the pool). No function accepts user-typed text for it.
- Every cohort is **synthetic** (`CHECK (is_synthetic)`); a non-synthetic cohort cannot be inserted.
- The one function `edu_api` may execute, `leaderboard.my_standing(text)`, takes **no learner id
  and no cohort id**: the actor is the verified transaction-scoped one. It returns the caller's own
  row and two integers (rank, cohort size).

## Design

Schema `leaderboard` (nothing created in `app`, `rewards`, `ops`, `staff`; no trigger and no lock
outside this schema; no foreign key to the tables forbidden by R-02 — the only outside key is
`app.learner_profiles(user_id) ON DELETE RESTRICT`, like `rewards`).

| Object | Role |
|---|---|
| `pseudonym_pool` | Allow-list of generated names. |
| `periods` | `all` (all-time) or a week keyed by its Monday `YYYY-MM-DD`, Monday..Sunday in `America/Port-au-Prince` (via `rewards.haiti_day`). A row appears at the first snapshot. |
| `cohorts` | `class` / `school`, machine `code`, synthetic only. |
| `memberships` | Consent record: `opted_in_at`, `opted_out_at`, pseudonym. Member = row with `opted_out_at IS NULL`. At most one active cohort per learner (partial unique index). |
| `snapshot_runs` | One row per (period, cohort): `computed_at`, `member_count`, `frozen_at`. |
| `snapshots` | (period, cohort, learner, gold, rank, tie_order, computed_at). |

RLS is enabled on all six tables with **no policy**; no table privilege for anyone. All functions
pin `search_path = pg_catalog, pg_temp` and are owned by `postgres`.

| Function | Executable by | Purpose |
|---|---|---|
| `my_standing(p_period text) RETURNS jsonb` | `edu_api` | The caller's own standing. |
| `refresh_snapshot(p_cohort_id uuid, p_period text) RETURNS jsonb` | owner only | Rebuilds one snapshot from `rewards.ledger`. |
| `enroll(cohort, learner)`, `withdraw(cohort, learner)` | owner only | Opt-in (assigns the pseudonym) / opt-out. Internal seam for step 2. |
| `erase_learner(p_user_id uuid) RETURNS jsonb` | owner only | Erasure hook for the account orchestrator. |
| `resolve_period`, `is_rankable`, `period_gold`, `display_pseudonym`, `visible_rows` | owner only | Helpers. |

Nothing is granted to `PUBLIC`, `anon`, `authenticated`, `authenticator`, `service_role`,
`edu_staff` or `edu_worker`. Until step 3 a refresh is run by the owner in SQL:
`SELECT leaderboard.refresh_snapshot('<cohort uuid>', 'week');`

## Rules chosen

1. **Score** = "Gold earned by learning": `sum(amount)` over `rewards.ledger` rows of the learner
   with `source_kind <> 'adjustment'` (awards and their reversals). Staff adjustments do not count.
   Nothing else is read: no client number, no profile column, not `rewards.balances`.
2. **Period membership** is by `accepted_day`. A reversal is dated the day it is made, so it lowers
   the period in which it is made, never an earlier one.
3. **Negative sums** (a reversal this week of Gold earned earlier) are clamped: `GREATEST(sum, 0)`.
   A score is never negative (also a `CHECK` on `snapshots.gold`).
4. **Ranking** is competition ranking: equal Gold = equal rank, the next rank is skipped (1, 1, 3).
5. **Order inside a tie** (`tie_order`, a gap-free 1..n) follows
   `sha256(cohort_id:period_key:learner_id)`: deterministic, recomputable, carries no identity and
   differs per period and cohort so nobody is always first among equals. It is stored for the
   step-2 cohort view and is not returned by `/me`.
6. **Exclusions** at refresh **and again at every read**: an account that has any row in
   `app.staff_roles` (active or not), an opted-out member, an account that no longer exists in
   `auth.users` or is soft-deleted. A staff account still sees its own Gold, never a cohort.
7. **Opt-out and erasure are immediate.** `withdraw` and `erase_learner` delete the learner's
   snapshot rows (frozen periods included); independently, the read re-ranks the caller over the
   rows that are still visible, so the others' rank and the cohort size change on their next read
   without a refresh.
8. **Recomputation** is idempotent: the same ledger and memberships give the same rows (tested
   row for row). Refreshes of one (cohort, period) are serialised by an advisory transaction lock.
9. **Closed weeks**: the first refresh made after a week has ended is the closing snapshot; it is
   then frozen and later refreshes return it unchanged (`recomputed: false`).
10. **Staleness is honest**: `gold` is the caller's live sum, `cohort.snapshot_gold` and
    `cohort.rank` are the snapshot's, and `cohort.computed_at` says when it was taken. A member who
    joined after the last refresh has `rank`, `size`, `snapshot_gold`, `computed_at` = `null`.

## Endpoint contract (provisional)

`GET /v1/leaderboard/me?period=` — bearer token required.

- `period`: `week` (default, current Haiti week), `all`, or the Monday `YYYY-MM-DD` of a past week
  (not before 2026-01-05, not in the future).
- `EDU_LEADERBOARD_ENABLED` off (default): standard `404 not_found`, checked before the token.
- `401` without a valid token; `422 validation_error` for an unknown period; other methods `405`.
- Registered but hidden from the OpenAPI document (R-01): the single constant
  `INCLUDE_IN_SCHEMA = False` in `services/api/src/edu_api/routers/leaderboard.py`. `openapi.json`
  is unchanged. A test builds the app with the constant on and asserts the operation carries the
  bearer security requirement and only the standard error shape.

```json
{
  "period": "2026-11-23",
  "kind": "week",
  "starts_on": "2026-11-23",
  "ends_on": "2026-11-29",
  "closed": false,
  "gold": 15,
  "cohort": {
    "cohort_id": "5b0c7d4e-2f1a-4c55-9a51-0d8f6f0f8a11",
    "pseudonym": "Colibri Sage",
    "rank": 1,
    "size": 2,
    "snapshot_gold": 15,
    "computed_at": "2026-11-25T09:12:44.120394+00:00",
    "frozen": false
  }
}
```

`cohort` is `null` unless the caller is an opted-in, rankable member. The response never contains
another learner's Gold, pseudonym or identifier.

## Tests

- pgTAP `200_leaderboard_structure.sql` (61): tables, RLS and no policy, no identity column,
  nothing added to other schemas, table and function privileges, `search_path` pin and owner,
  `erase_learner` signature, period resolution, `anon` / `authenticated` / `service_role` cannot
  reach the schema.
- pgTAP `205_leaderboard_ranking.sql` (111): Gold earned through the real award path, no cohort
  before opt-in, `edu_api` reaches only its own standing, server-assigned unique pseudonyms, ranks
  and ties, staff / opted-out / deleted exclusion, cross-cohort isolation, recomputation equality,
  duplicates do not move a rank, staleness, adjustments ignored, reversals and negative clamp,
  closed week frozen, opt-out / staff grant / erasure immediate, refresh input checks.
- pytest `tests/integration/test_leaderboard_api.py` (24) through the real API: flag off = 404,
  flags default off, not in the generated contract, constant-on contract test, token required,
  no write method, 422 shape, end to end `/v1/sync/push` → refresh → `/me` with exactly-once,
  no foreign data or identity in the answer, opt-out and erasure, staff never ranked, cohort
  isolation, `edu_api` cannot reach tables or other functions.

Whole branch at the gate: pgTAP 1133 in 17 files, pytest 489.

## Not done

- **Step 2:** `GET /v1/leaderboard/cohorts/{cohort_id}` (pseudonymous page, cursor, 404 for
  non-members, request budget) and `POST/DELETE /v1/leaderboard/cohorts/{cohort_id}/membership`.
  `EDU_LEADERBOARD_COHORTS_ENABLED` exists in the settings (default off) but nothing reads it yet.
- **Step 3:** staff routes under `/v1/staff/leaderboard` (create cohort, trigger refresh), any
  scheduled refresh (`edu_worker` has no grant).
- Large-cohort timings (5 000 members), pagination stability under concurrent refresh, the
  mock-data script for the native screen, any mobile work.
- `erase_learner` is not yet called by an account-deletion orchestrator (none exists on this
  base); because of the `ON DELETE RESTRICT` keys it must run before the profile is deleted.

## Known gaps

- No minimum cohort size: in a cohort of two, an own rank reveals whether the other member has
  more or less Gold. A floor (for example no rank below 5 members) is a policy decision.
- "System / test-marker accounts" from the brief are not excluded separately: no such marker
  exists on this base. Staff accounts are excluded.
- For a closed week `gold` is still the live ledger sum and can grow by late reconciliation,
  while the frozen snapshot does not; a closing snapshot taken long after the week ended includes
  such late rows.
- `member_count` in `snapshot_runs` is the count at computation time and is not decremented by a
  later opt-out or erasure; reads do not use it.
- A learner who opted out keeps the membership row (the consent history and the reserved
  pseudonym) until erasure.

## BLOCKED_BY_OWNER

- **Who may consent for a minor** (the learner, a parent or guardian, a school) and how that
  consent is recorded and revoked. Until decided, memberships can only be created by the owner in
  SQL on synthetic cohorts.
- **Whether real children are ever shown a ranking** at all, including their own rank. Both flags
  stay off.
- **Pseudonym policy**: the word list, the language (French / Kreyòl), whether a learner may ask
  for a new one, approval of the list.
- **Gold values (PO-09)**: every amount and cap is a placeholder; ranks are computed on sums and no
  amount is hard-coded here.
