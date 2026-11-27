# Schema changelog: v0.2 draft → Foundation-01

The original drafts are preserved byte-for-byte in `docs/reference/schema-v0.2/`.
The live schema is `supabase/migrations/` (the only source of truth).

## What v0.2 claimed, and what running it showed

v0.2 was authored and statically checked only (22 tables, 27 policies, 14 trigger
guards); it had never been executed. When applied to a real local PostgreSQL 17 /
Supabase stack, **both draft files executed without a syntax error**. The
problems were not syntax: they were security and integrity gaps found by review.

Each of C01–C05 and C10 below was then **demonstrated against the unmodified
drafts** on a throw-away local database (`docs/reference/v02_defect_probe.sql`;
observed output in `docs/TEST_REPORT.md`), and each is now prevented by a test
that fails if the fix is removed.

## Counts

| | v0.2 draft | Foundation-01 | Why |
|---|---:|---:|---|
| Application tables | 22 | **22** | unchanged |
| RLS policies | 27 | **17** | 10 write policies removed (C01), 1 staff policy removed (C09), policies tightened (C14) |
| Triggers | 14 | **16** | 2 insert guards added (C02, C03) |
| Migration files | 2 | **4** | split by concern: tables · guards · roles+policies · sync function |
| Functions callable by the API role | 2 | **2** | `current_actor_id`, and `sync_apply_operation` replaces `next_change_version` |
| Foreign keys | 28 | 28 | unchanged |

## Changes

Severity: **Critical** = lets someone bypass a core guarantee · **High** = integrity
hole under realistic use · **Medium** = defence in depth / correctness · **Low** = hygiene.

### C01 — Critical — The student API role could write its own scores, receipts and change history
**Draft:** `edu_api` had `INSERT` on `practice_attempts` (including `score`),
`sync_receipts`, `account_change_feed`, `audit_events`; `INSERT/UPDATE` on
`lesson_progress`, `account_sync_state`, `learner_profiles`; and could call
`next_change_version()`. Policies only required "the row is mine".
**Problem:** RLS answers *whose row* but not *is the content true*. Any bug or
injection in the API layer could insert a perfect score, mark lessons complete,
forge a receipt, or rewind `current_version` to 0 (making phones re-download or skip changes).
**Now:** the API role has `SELECT` on those tables and nothing else. The single
write path is `app.sync_apply_operation()` (SECURITY DEFINER), which locks,
de-duplicates, **scores from the stored answer key**, allocates the version and
writes the feed row and receipt together. It takes no learner and no score
parameter. `next_change_version()` was removed (its logic is inside the function).
On `learner_profiles` the role keeps only `INSERT (user_id)` — it can create its
own profile row with defaults; there is no UPDATE right because no endpoint needs one yet.
**Tests:** `020_rls_isolation.sql`, `050_sync_function.sql`, `test_even_arbitrary_sql_on_the_api_connection_cannot_forge_state`.

### C02 — Critical — A lesson revision could be inserted already "approved"
**Draft:** the approval checks ran `BEFORE UPDATE OR DELETE` only.
**Problem:** `INSERT ... status='approved', approved_by=<anyone>` skipped the
review, independence and rights checks entirely.
**Now:** `guard_lesson_revision_insert` — new rows must be `draft` with no approver.

### C03 — Critical — A pack release could be inserted already "active"
Same shape as C02: lifecycle checks (non-empty, rights cleared, valid transition)
ran on UPDATE only. **Now:** `guard_pack_release_insert` — new releases must be `building`.

### C04 — High — Items could be moved out of a finalized pack
**Draft:** `validate_pack_item` on UPDATE checked only the *new* release.
**Problem:** `UPDATE pack_items SET pack_release_id = <a building pack>` silently
removed an item from a released, supposedly immutable pack.
**Now:** changing `pack_release_id` or `lesson_revision_id` of an item is refused.

### C05 — High — The "reviewer is not the author" rule could be dodged
**Draft:** `created_by` was nullable and editable; independence was skipped when it was NULL.
**Problem:** set `created_by` to NULL (or to someone else) and then review your own lesson.
**Now:** `created_by` is `NOT NULL` and cannot change after insert (nor can `id`, `created_at`).

### C06 — High — Approval could fail or pass on the wrong role row
**Draft:** the approval query `LEFT JOIN`ed `staff_roles` and took `LIMIT 1`.
**Problem:** a reviewer holding two roles (say `reviewer` active + `admin`
inactive) produced two rows; which one `LIMIT 1` picked was arbitrary.
**Now:** the latest review is selected alone; the role is a separate `EXISTS`.
**Test:** "a reviewer with an active reviewer role AND an inactive admin role can approve".

### C07 — High — Caller-supplied timestamps decided which review was "latest"
**Draft:** `reviewed_at`, `approved_at`, `released_at` were whatever the writer sent.
**Problem:** approval looks at the *latest* review; a future-dated old approval would outrank a later rejection.
**Now:** `reviewed_at := clock_timestamp()`, `approved_at := now()`, first `released_at := now()` are set by triggers.

### C08 — Medium — Check-then-write races between editors, reviewers and publishers
**Draft:** guards checked "no review exists" / "release is active" without locking.
**Problem:** two concurrent transactions could each pass their check and both
commit (e.g. a question added at the instant a review is recorded; the current
pointer moved onto a release that is being revoked).
**Now:** question and source-link guards take `FOR SHARE` on the parent revision
(reviews and approval take stronger locks on the same row); `validate_pack_current`
locks the release `FOR SHARE`.
**Not test-covered:** these are timing races; they are reasoned about, not reproduced. See `SECURITY.md`.

### C09 — Medium — Unneeded grants to the student role
Removed `SELECT` on `staff_roles` (and its policy) and `INSERT` on `audit_events`.
The student API needs neither, and "a student-facing connection can write audit
events" makes the audit log untrustworthy.

### C10 — Medium — `ALTER DEFAULT PRIVILEGES IN SCHEMA app REVOKE EXECUTE ... FROM PUBLIC` does nothing
PostgreSQL's default "PUBLIC may execute new functions" is a *global* default and
cannot be revoked per schema, so future functions in `app` would have been
publicly executable (limited only by schema USAGE). **Now:** each migration that
creates functions ends with an explicit `REVOKE`, and `010_structure.sql` fails
if any `app` function is executable by PUBLIC, `anon` or `authenticated`.

### C11 — Low — Receipts did not record how their digest was produced
Added `sync_receipts.op_kind` and `sync_receipts.canon_version`, so a future
change of the canonicalisation rule can be handled deliberately.

### C12 — Low — Seven foreign keys had no index
Added indexes on `staff_roles.granted_by`, `lesson_revisions.created_by` /
`approved_by`, `editorial_reviews.reviewer_id`, `pack_releases.created_by`,
`lesson_progress.lesson_id` / `last_revision_id`. Without them, deleting a
referenced row scans the whole child table.

### C13 — Low — Label maps could omit French
`labels` / `titles` JSON must contain `fr`, because the API falls back to French
when a Creole label is missing.

### C14 — Medium — Read policies were slightly too wide
- `revisions_read` now also requires the lesson to be visible (active lesson of
  a published course). Before, a revision in a current pack stayed readable after
  its course was archived.
- `pack_releases_read` re-checks `status = 'active'`.
- `units_read` / `lessons_read` / `pack_items_read` compose on the parent's policy instead of repeating its condition.

### C15 — Low — Mechanical changes
- Removed `BEGIN; … COMMIT;` wrappers (the Supabase CLI runs each migration in its own transaction).
- `CREATE OR REPLACE FUNCTION` → `CREATE FUNCTION` (a fresh schema should fail loudly on a name clash).
- Column references inside policies are table-qualified.
- `protect_pack_item_delete` uses `IS DISTINCT FROM` (NULL-safe); `validate_editorial_review` rejects a non-existent revision explicitly.
- Trigger functions that read no other table (`prevent_append_only_change`, the two insert guards) are no longer SECURITY DEFINER.

## Reviewed and deliberately kept

| Topic | Decision |
|---|---|
| `auth.users` foreign keys are `ON DELETE RESTRICT` | Kept. Deleting an account with learning data fails (tested). A proper deletion procedure is future work. |
| `edu_api` is `NOLOGIN`; a separate login role inherits it | Kept. The login role is created outside migrations so no password is ever in SQL. Verified working against local Postgres. |
| `SET LOCAL`-style actor context | Kept, implemented as `set_config(..., true)` with a bound parameter. Verified on a one-connection pool. |
| No `FORCE ROW LEVEL SECURITY` | Kept. Tables are owned by `postgres`, which has BYPASSRLS on Supabase anyway; the definer functions rely on reading all rows. The API never connects as the owner (tested). |
| Several `active` releases may exist per pack/locale | Kept. `pack_current` is the truth; it allows roll-forward/roll-back without a window with no current release. |
| A review of any verdict freezes the revision | Kept (matches the design note: fixes need a new revision). |
| `answer_key` is readable by students for published questions | Kept by design: offline practice needs it. Not suitable for exams. |

## Not changed, but worth a decision before v1

- `lesson_progress.last_revision_id` means "the revision that was completed". If
  reading-position tracking is added, it should get its own column.
- `practice_attempts.score` is nullable for future manually-graded kinds; today it is always set.
- There is no retention policy for receipts, feed rows or attempts (they grow forever).

## ExamHub-01 (2026-11-27, behind `EDU_EXAMS_ENABLED`, default off)

Migration `20261127000100_examhub.sql` adds, and alters nothing existing:

* tables `app.exams`, `app.exam_questions`, `app.exam_attempts`, `app.exam_answers` (26 application tables in total);
* functions `exam_start_attempt`, `exam_submit_answer`, `exam_finish_attempt`, `exam_attempt_review` (callable by `edu_api`) and the internal `exam_close_attempt`;
* triggers guarding publication (second-person approval, cleared rights, valid keys) and the immutability of published questions.

The API role has column-level `SELECT` on questions that excludes `answer_key` and `explanation`, and no write privilege on any exam table. See `docs/examhub-01/README.md`.
