# Review: VOCAB lane ("Word of the Day") — security and integration

- Reviewed: branch `overnight/word-of-the-day` at `a3c48a3` (vocab files only: `supabase/migrations/2026112404*`, `supabase/tests/16*.sql`, `services/api/src/edu_api/vocab/`, `routers/daily_word.py`, `routers/staff_vocab.py`, `tests/**/test_vocab_*`, `scripts/seed_vocab_demo.py`).
- Environment: QA worktree `qa1`, disposable stack `supabase_db_edu-on-qa1` (PostgreSQL 17.12), real logins `edu_api_login`, `edu_staff_login`, `edu_worker_login`, and the table owner where stated.
- Date of review: 2026-11-25 (Haiti date 2026-11-25, started 09:39 UTC).

## Verdict: APPROVE WITH FIXES

The owner's requirement holds on every path the application can reach: no HTTP route, staff function or worker call could change, delete or re-point the word of a day that has opened, and "today" is the America/Port-au-Prince date of the server clock. One real gap remains below the API (F1), plus one owner-only gap (F2) and a test gap around the midnight race (F3).

## Suite counts observed

| Suite | Result |
|---|---|
| `make test-db` (pgTAP) | 15 files, 910 tests, PASS (author reported 910) |
| `uv run pytest -q` | 429 passed (author reported 429) |
| `make lint` | pass (89 files formatted) |
| `make typecheck` | pass (42 source files) |

## How time was simulated

The write path has no clock seam (the guards call `clock_timestamp()` directly), so in the QA database only I re-created the six vocab functions that read the clock (`guard_daily_assignment`, `check_daily_assignment_day`, `ensure_assignments`, `retire_word`, `calendar`, `validate_review`) from `pg_get_functiondef` with the single textual change `clock_timestamp()` -> `qa.clock()`, where `qa.clock()` returns the real clock plus an offset stored in a table. The offset is changed from a second connection, so a transaction that is already open sees time move. Learner reads used `vocab.daily_word_at(locale, qa.clock())` as the owner. The database was reset (`make db-reset`) afterwards. Everything not marked "simulated clock" ran on the unmodified code with the real clock.

## Findings

### F1 — MEDIUM — The commit-time check of a schedule change can be made to run early, so a change can land after the day has opened

Location: `supabase/migrations/20261124040100_vocab_schema.sql:592-616` (`check_daily_assignment_day`, a deferred constraint trigger).

Class: a check that is meant to run at COMMIT is implemented as a deferrable constraint, and the timing of deferrable constraints is under the control of the session.

Impact: a holder of a direct database session with schedule rights (the staff database login with a publisher or admin actor, or the owner) can make a schedule change that was legal when written become visible after the day has opened, replacing a word learners already received. Not reachable through the HTTP API: each route runs fixed statements in one short transaction, and the ordinary long-transaction case was reproduced as correctly refused. Reproduced on the QA stack with a simulated clock and two connections; the exact steps are in the private report.

Smallest fix (either, or both):
1. Cap transaction lifetime below the freeze for the logins that can write the schedule, e.g. `ALTER ROLE edu_staff_login SET transaction_timeout = '2min'; ALTER ROLE edu_staff_login SET idle_in_transaction_session_timeout = '30s';` (same for `edu_worker_login`). With a 10-minute freeze, a transaction that passed the statement-time guard can then no longer reach midnight by accident. A session can still override its own setting, so this closes the accidental case only.
2. To hold against a deliberate session: make the day a lock, not a late check. Writers that update or delete rows of date D take `pg_advisory_xact_lock(key(D))` in `guard_daily_assignment`; `vocab.daily_word_at` takes `pg_advisory_xact_lock_shared(key(today))` with a short `lock_timeout` (503 on timeout). A pending pre-midnight change then cannot become visible after any learner has read the day. Transaction-level advisory locks cannot be released early.
If neither is wanted, record the residual risk explicitly and correct the "every writer / SQL console" claim in the migration header and lane doc.

### F2 — LOW — `TRUNCATE` by the table owner removes opened days; the next fill then publishes a different word

Location: `20261124040100_vocab_schema.sql:581-583` (row-level triggers only; no statement-level `TRUNCATE` trigger). The header comment says rows of a locked date "can never be updated or deleted, by anyone".

Evidence (real clock, owner connection, then worker login):
```
OWNER TRUNCATE daily_assignments: OK []      rows after truncate: 0
ensure after truncate (worker): today now: [('2026-11-25','fr','deux-fr'), ('2026-11-25','ht','deux-ht')]   (was un-fr / un-ht)
```
Owner only: `edu_api`, `edu_staff`, `edu_worker` hold no table privilege (TRUNCATE refused 42501 for all three logins). The lane's own test fixture relies on this TRUNCATE.

Smallest fix: `CREATE TRIGGER ... BEFORE TRUNCATE ON vocab.daily_assignments FOR EACH STATEMENT EXECUTE FUNCTION vocab.prevent_append_only_change()` (also on `word_revisions` and `reviews`); the test fixture then disables that trigger explicitly inside its own cleanup.

### F3 — LOW (test adequacy) — The midnight race protection is never tested as a commit-time check

Location: `supabase/tests/162_vocab_schedule.sql:20`, `163_vocab_learner_read.sql:17`, `164_vocab_haiti_time.sql:18` all run `SET CONSTRAINTS ALL IMMEDIATE`; no test anywhere contains the refusal 'The day opened before this schedule change was committed' (grep over `supabase/tests/16*.sql` and `tests/`). The freeze is tested only through the pure function `vocab.is_day_locked`; the trigger's use of it at a real boundary is covered by a source-text assertion (164, test 63), not by behaviour.

Evidence that the code itself works on the plain path: the plain long-transaction case was refused at commit (simulated clock) and, at simulated 23:50:01, `schedule_word`, `unschedule_date`, owner UPDATE and owner DELETE of tomorrow all refused with 'The schedule of a day is frozen shortly before it opens'; at 23:49:30 they were allowed.

Smallest fix: give the two guard functions a test-only clock seam (for example an owner-only function `vocab._clock()` that the guards call, replaced inside the rolled-back pgTAP transaction), and add: (a) change at 23:49, commit after 00:00 -> refused; (b) the F1 case; (c) freeze boundary through the trigger.

### NOTE N1 — Withdrawing rights changes what learners see on an opened day (by design; the owner should know)

Reproduced (real clock, `set_source_rights` as publisher over `edu_staff_login`): with today's source set to `blocked`, the learner read returns no row (HTTP 404 `daily_word_not_available`); the assignment rows are untouched; `ensure_assignments` and `schedule_word` cannot give today another word, so today stays without a word; setting rights back to `cleared` brings the SAME word back. If only the Creole revision's source is withdrawn the learner gets the French revision of the same word; if only the recording's source is withdrawn the recording disappears. A different word is never served. This is the rights gate taking precedence over "the day never changes"; it is an owner decision, not a defect.

### NOTE N2 — A day that opened with no word can receive one later that day

`ensure_assignments` / `schedule_word` fill an opened day only when it has no row at all (reproduced). Learners who saw 404 in the morning see a word later. Nothing already seen is replaced. The 404 carries `Cache-Control: private, no-store`, so a client does not keep it.

### NOTE N3 — Residual instant between the deferred check and commit visibility

Even on the plain path the check runs just before the commit completes; a change checked at 23:59:59.99 becomes visible a moment after midnight. The 10-minute freeze makes this require a transaction held open for ten minutes. Fix 2 under F1 removes it.

## Verified sound (tried to break, could not)

Priority 1 — schedule integrity
- Today's assignment, real clock, as owner: UPDATE of `word_id` alone, of `word_id` + `word_revision_id`, of `word_revision_id` to a newer approved revision, of `locale`, of `haiti_date`, of `assigned_at`; DELETE of one locale and of the day; INSERT of a past day; `INSERT ... ON CONFLICT DO UPDATE`; DELETE after `SET CONSTRAINTS ALL IMMEDIATE` — all refused. As `edu_staff_login` / `edu_api_login` / `edu_worker_login`: SELECT, UPDATE, DELETE, TRUNCATE, INSERT on every vocab table refused 42501.
- Staff functions against today and yesterday as publisher and as admin: `schedule_word` (another word, and the same word), `unschedule_date`, `staff_ensure_assignments` (also a window starting 30 days in the past: no past row created), `retire_word` of today's word (0 locked rows removed, learner still gets the word) — today unchanged every time.
- Past day (simulated clock moved to the next day): staff unschedule / schedule, owner UPDATE / DELETE, retire, fill — all refused or no-ops; rows unchanged.
- Editing: approved revision cannot be updated or deleted (owner and editor); word and source cannot be deleted; a new approved revision of today's word leaves today's row and the learner's response on revision 1.
- Denormalised `word_id`: pinned by the composite foreign key `(word_revision_id, word_id, locale)`; a Creole-only day is refused at the constraint check.
- Translation approved after the day opened: not added by the fill, by `schedule_word`, by owner INSERT or by `_assign_word`; learner keeps the French fallback.
- Freeze (simulated clock): allowed at 23:49:30, refused from 23:50:01 for staff functions and owner DML; a word that lost rights is not swapped out of a frozen day; `calendar.is_locked` agrees.
- `ensure_assignments`: empty pool -> 0 rows and no learner row; pool containing only in-review / rejected / uncleared words -> 0 rows; pool of one -> the same word every day; second run -> 0 rows, identical schedule; adding a word to the library and re-running the same window -> existing rows byte-identical (not "day modulo count"), only new days appended; sequential refill vs two rounds of 8 concurrent worker connections -> identical schedule, one connection creates all rows and seven create none, every day has exactly one word and a French row; arguments 63 days / NULL refused 22023, `infinity`, `-infinity` and a start 400 days ahead create nothing; a future day whose word lost rights is freed and re-chosen while today is untouched.
- Day with no assignment: learner read returns no row -> 404 in `routers/daily_word.py:84-90`; never yesterday's word (the query filters on exactly one date).
- Time: `haiti_date` and `valid_until` checked at instants one second either side of local midnight in winter 2026 (05:00 UTC), summer 2026 (04:00 UTC), both 2026 DST change days (23- and 25-hour days) and July 2016 (no DST: 05:00 UTC). Session `TimeZone` set to Asia/Tokyo, Pacific/Kiritimati and UTC on the `edu_api_login` connection does not move the date. `vocab.daily_word(text)` takes no time argument and `daily_word_at` is not executable by any login role. The author's HTTP test sends `date`, `haiti_date`, `now`, `offset` parameters and `Date`, `X-Client-Time`, `X-Timezone` headers and still gets today (read and run: passes).

Priority 2 — visibility and permissions
- Privilege matrix read from the catalog: `edu_api` executes `vocab.daily_word(text)` only; `edu_worker` executes `ensure_assignments` only; `edu_staff` executes the 15 staff functions; `anon`, `authenticated`, PUBLIC execute nothing; table ACLs are owner-only with row-level security enabled on all six tables.
- `daily_word` without a verified actor -> 42501; locale `en` or NULL -> 22023.
- SQL role matrix over `edu_staff_login` for no actor / learner / editor / reviewer / publisher / admin / deactivated publisher on ten functions: exactly the documented roles pass; deactivated and learner actors get 42501 everywhere.
- Author approving own word: refused for an editor+reviewer and for an admin, for approve and reject, and also when the owner forces the status or inserts the review row directly. A reviewer cannot review an unsubmitted draft; another editor cannot edit or submit someone else's draft; approval with an unverified source refused.
- Data API (PostgREST on 57021) with the anon and the service-role key: `Accept-Profile: vocab` -> 406 "Only the following schemas are exposed: public, graphql_public"; tables and `rpc/daily_word` not found.
- ETag / 304 (code reading of `vocab/service.py:35-52` plus the author's tests, which I read and ran): the tag covers date, requested locale, served locale, revision id and recording id; those determine the whole body because approved revisions and their recordings are immutable. A withdrawn word returns no row, so the route answers 404 before any tag comparison — a 304 cannot keep a withdrawn word alive; a withdrawn recording or a fallback to French changes the tag. `Cache-Control: private, no-cache` on 200 and 304, `private, no-store` on 404.

Priority 3 — hygiene
- R-03: all 38 vocab functions carry `search_path=pg_catalog, pg_temp`; all are owned by `postgres`; no dynamic SQL in the three migrations.
- Bounded input: overlong term, control characters, 1001-character review note, 241-character source title, multi-byte payload over the 800-byte budget and a 102 401-byte recording are all refused by table constraints (102 400 accepted).
- Audit: 19 distinct vocab audit shapes inspected; details hold ids, dates, counts and closed-list values only; 0 audit rows contain any test term, definition or source title.
- Nothing created in schema `app` (0 relations, 0 functions matching vocab). No pre-existing migration modified (`git diff --name-status origin/main a3c48a3`: only `.env.example`, `scripts/local_stack.py`, `config.py`, `main.py` are modified, all others added). No secret values in the vocab diff.
- R-01: both routers always registered (`main.py:96-97`), `INCLUDE_IN_SCHEMA = False` on every route, flag off -> the same 404 as an unknown path before authentication (author's test read and run).

Priority 4 — tests
- The owner's named tests are real: midnight boundary and DST (pgTAP 164, fixed instants incl. 23- and 25-hour days and a no-DST year), missing translation, edited-after-assignment, idempotent and concurrent publication, rejected / draft / in-review / future content invisible, size budget (exact 800-byte worst case, plus one byte over refused), audio cap, rights gate.
- Spurious failure near midnight: pgTAP waits when midnight is under 5 seconds away and recomputes "today" per statement; pytest waits when under 20 seconds away. I re-ran pgTAP and the three vocab pytest modules with the simulated clock at 23:55 Haiti time (inside the freeze): 2 pgTAP failures and 1 pytest failure, all three caused by my shim (a QA object visible to the platform structure test, a source-text assertion on the guard, and the shimmed `assigned_at` compared with the real `transaction_timestamp()`), none by the lane. No freeze-window flake found.

## Missing tests

1. Commit after midnight of a change made before the freeze (plain path) — the refusal exists and works, but nothing tests it.
2. The F1 case.
3. Freeze boundary through the trigger (not only through `is_day_locked`).
4. `TRUNCATE` on the schedule (once F2 is fixed).
5. Rights withdrawn on a FUTURE scheduled day -> freed and re-chosen is tested in pgTAP; the "today stays empty and returns when rights are restored" behaviour (N1) is tested only as "hidden", not "returns unchanged".

## Not examined

- HTTP routes were not probed by hand: for flag-off, parameter / header probing, the HTTP role matrix, ETag and error mapping I relied on the author's tests after reading them and running them (all pass). SQL-level equivalents were probed directly.
- A real midnight (only simulated, as described above); real object storage or audio delivery (none exists); mobile client; `scripts/seed_vocab_demo.py` was read for target safety only, not run; accuracy of the lane doc; internals of `staff.require_role` and `ops.audit_write` (staff lane); load and query-plan behaviour; R-02.
