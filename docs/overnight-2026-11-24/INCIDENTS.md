# Incidents — overnight 2026-11-24

## I-01 · Shared local stack: five learning tables truncated by the mobile test harness (≈23:0x)

**What happened.** The native lane ran the existing mobile Jest suite once from its own worktree to
record a baseline. The suite's support file `apps/student-native/tests/support/device.ts` (line 75)
hard-codes the container name `supabase_db_mon-edupreneur` in `resetServerLearningState()`, which
runs `TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
app.lesson_progress, app.account_sync_state` before each integration test. So although the lane's
API and database were its own isolated stack, the truncate went to the **shared** stack on port
54322 — the one the plan said would never be touched.

**Effect (verified by one read-only count at 23:1x).** On the shared stack those five tables are
empty. Lessons (8), learner profiles (3), accounts, schema and seed content are intact. The rows
were local synthetic test data; the same truncate happens every time the mobile suite is run from
the main checkout. Nothing can be restored and nothing else was changed.

**Cause.** Director's isolation model covered ports and `.env`, but did not audit the mobile test
harness for hard-coded Docker container names before authorising a Jest run. The agent also did not
read the harness before running it.

**Containment.** The mobile Jest suite is restricted to the native lane, which now runs it only
through a PATH shim that rewrites that one container name to its own lane container. No other
hard-coded reference to the shared stack exists in `tests/`, `scripts/` or the mobile support files
(searched). The shared stack has not been touched since, apart from the read-only count.

**Recommended permanent fix (not applied — it edits an existing verified test support file on
`mobile-02`/`main`):** derive the container name from `supabase/config.toml` `project_id`.

## I-02 · Shared scratchpad: one lane ran another lane's gate script by mistake (≈23:02)

All agents of this session share one scratchpad directory. The native lane and the staff lane both
wrote a file named `gate.sh` there; the native lane then executed the staff lane's version. It ran
`make lint` in the staff worktree, failed on an in-progress lint error and stopped. **No file
changed and no database was reset**, but had lint been green the script would have reset the staff
lane's database mid-work. The native lane also committed its slice 3 on the strength of that wrong
exit code; it then re-ran the real mobile gate on the committed tree (267 passed, 0 failed) and
corrected the count in the unpushed commit message.

**Cause.** The isolation model gave every lane its own worktree, branch, ports and database but not
its own scratch directory. **Containment (ruling R-04).** Every lane now keeps helper scripts and
temporary files only under `/Volumes/EdupreneursDev/logs/overnight-2026-11-24/tmp/<lane>/`, and every
helper script starts by changing into its own absolute worktree path and refusing to run elsewhere.
