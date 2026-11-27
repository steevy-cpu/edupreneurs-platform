# Lane LEADERBOARD — private rank and opt-in synthetic cohort ranking (F14, owner priority; depends on F8)

Worktree `/Volumes/EdupreneursDev/worktrees/overnight/leaderboard` · branch `overnight/leaderboard`,
**stacked on `overnight/rewards-gold`** (started only after the Gold ledger's integrity tests passed
and were independently reviewed) · stack API 56921 / DB 56922 · schema `leaderboard` · migrations
`2026112406xxxx_*` · pgTAP `200–219_*`.

Owned paths: `supabase/migrations/2026112406*`, `supabase/tests/20*.sql`, `supabase/tests/21*.sql`,
`services/api/src/edu_api/leaderboard/**`, `services/api/src/edu_api/routers/leaderboard.py`,
`services/api/src/edu_api/routers/staff_leaderboard.py`, `tests/**/test_leaderboard_*.py`,
`tests/leaderboard_fixtures.py`, `docs/overnight-2026-11-24/lanes/leaderboard.md`.
The rewards lane's files are read-only for you; if you need something from `rewards`, ask for it in
your report rather than editing it.

## Privacy position (not negotiable tonight)
The learners are minors. **There is no public or global ranking in any code path**, no real names,
no display names from profiles, no ranking by anything social. What exists:
1. a **private** "my Gold this period / my rank inside my cohort" view visible only to the learner;
2. a **synthetic opt-in class cohort** leaderboard showing **approved pseudonyms only**, visible only
   to opted-in members of that cohort.
Both are behind flags that default **off** (`EDU_LEADERBOARD_ENABLED`, and a separate
`EDU_LEADERBOARD_COHORTS_ENABLED`). Who may consent for a minor, whether schools enrol classes, and
whether any ranking is shown to real children are `BLOCKED_BY_OWNER`. Membership requires an
explicit opt-in record; unknown consent = not a member.

## Model (schema `leaderboard`)
- `periods` (all-time and ISO-style weeks computed in `America/Port-au-Prince`; closed periods are frozen).
- `cohorts` (kind `class` | `school`, synthetic; created by staff), `memberships` (learner, cohort,
  opt-in timestamp, opt-out timestamp, **pseudonym chosen from a server-side allow-list** —
  generated neutral names, unique within the cohort, never user-typed text).
- Ranking is computed **only from `rewards.ledger`** (verified Gold; reversals included), never from
  a client number or a profile column. Exclusions enforced on the server: staff accounts
  (`app.staff_roles`), system/test-marker accounts, opted-out and erased learners.
- `snapshots` (period, cohort, learner, gold, rank, computed_at): bounded materialisation produced by
  `leaderboard.refresh_snapshot(cohort, period)`; reads are served from the snapshot (cached result,
  `computed_at` exposed so staleness is honest); recomputation is idempotent and rebuilds exactly.
- **Deterministic ties:** equal Gold → same displayed position (competition ranking 1,1,3), stable
  order inside a tie by a non-identifying deterministic key; document and test it.
- `leaderboard.erase_learner(uuid)` hook; opt-out and erasure take effect on reads immediately (not
  only at the next refresh).

## API
- `GET /v1/leaderboard/me?period=` — own Gold for the period, own rank and cohort size if opted in,
  else Gold only. Never returns anyone else.
- `GET /v1/leaderboard/cohorts/{cohort_id}?period=&cursor=&limit=` — cursor pagination, bounded
  limit, pseudonym + Gold + position rows, the caller's own row flagged; 404 (not 403) for
  non-members so cohort existence is not probeable; simple per-learner request budget.
- `POST/DELETE /v1/leaderboard/cohorts/{cohort_id}/membership` — opt in (pseudonym assigned by the
  server) / opt out; only callable when the cohorts flag is on.
- Staff (role `admin`) under `/v1/staff/leaderboard`: create synthetic cohort, trigger refresh —
  only if the staff lane's B1 is already present on your base; otherwise SQL + marked seam.

## Tests (master brief list)
Cross-cohort / cross-school isolation; a non-member cannot read; stale cache honesty; revocation
(opt-out) and erasure; tie positions; invalid negative awards and reversals; duplicated events do
not move a rank (exactly-once comes from the ledger — prove it end to end through `/v1/sync/push`);
staff/system exclusion; recomputation equality; closed period immutability; pagination stability
under concurrent refresh; a **large synthetic cohort** (e.g. 5 000 members) with measured refresh
and page-read timings recorded in the lane doc; flags off → 404 everywhere; Data API cannot reach
`leaderboard`. Provide a mock-data script for the native review screen (pseudonyms only).
