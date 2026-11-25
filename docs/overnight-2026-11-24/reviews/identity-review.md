# Identity lane review — overnight/identity-onboarding @ 4699a8a

Reviewer: independent security/integration review, QA stack qa2 (database reset at 4699a8a, real `edu_*_login` connections over TCP, PostgREST on 57121). Time-boxed: Priority 1 (erasure) examined in depth, Priority 2 sampled, Priorities 3–4 mostly not examined (see the end). Commit 114ab62 (later, test-only) not reviewed.

**Verdict: APPROVE WITH FIXES** — the replica-mode window itself is contained and correctly scoped; the erasure is acceptable in a DRAFT PR with the flag off and synthetic users only, on the conditions in "Verdict on the erasure mechanism". It must not be enabled for real learners before H-1, M-1, M-2 and M-3 are fixed.

## Findings

### H-1 (HIGH) Erasure reports success while concurrent learner calls leave the id behind
Location: `account.advance_onboarding` and `account.export_own_data` (20261124020200 / 20261124020300) versus `account.erase_learner` step 6.
Problem: these two functions check the profile with an unlocked read (`EXISTS` / plain `SELECT`), and their tables reference `auth.users`, not the profile. A call made with a still-valid token while an erasure of the same learner is in flight commits rows after the erasure's postcondition has run. `request_deletion`, `cancel_deletion_request`, `update_own_profile` and the sync push lock the profile and are refused correctly.
Evidence: reproduced on the reviewer's private QA stack; exact steps are in the private report.
Smallest fix: in both functions replace the unlocked profile check with `PERFORM 1 FROM app.learner_profiles WHERE user_id = v_actor FOR KEY SHARE; IF NOT FOUND THEN raise 42501` (same pattern the other functions use), so they queue behind the erasure and are refused. Add a concurrency test.

### M-1 (MEDIUM) The audit record is written after the postcondition and can re-store the erased id
Location: `account.erase_learner` lines 561–597 of 20261124020300 (postcondition, then `audit_seam`); `ops.audit_write` takes the actor from the session.
Problem: if the executing session's verified actor equals the target (a worker that processes "on behalf of" the learner), the final audit row stores the erased id in append-only `app.audit_events.actor_id`, after the check that is supposed to prove it is gone.
Evidence: reproduced on the reviewer's private QA stack; exact steps are in the private report.
Smallest fix: refuse at the top when `app.current_actor_id() = p_user_id`; and run `find_learner_references` after the audit write (or again).

### M-2 (MEDIUM) The worker path can erase any learner without an open deletion request
Location: 20261124020400 line 69 (`GRANT EXECUTE ... TO edu_worker`), `erase_learner` has no precondition on `account.deletion_requests`.
Problem: one compromised or buggy worker credential can irreversibly destroy every learner's history, including the append-only tables, one call per id, with an audit row that by design carries no target. An unknown id also returns `erased: true` and writes an audit event.
Evidence: reproduced on the reviewer's private QA stack; exact steps are in the private report.
Smallest fix: keep `erase_learner` owner-only; grant the worker a wrapper `account.worker_process_deletion(p_request_id uuid)` that requires a row with `status = 'requested'` (and, once PO-04 decides it, older than the cooling-off period), derives the user id from that row, and raises when nothing exists. Staff path: require a reason code and return "not found" for an id with no data.

### M-3 (MEDIUM) Nothing stops a still-valid token from re-creating the account; the documented ordering cannot be followed
Location: comment at 20261124020300 lines 393–396; baseline FK `learner_profiles_user_id_fkey ... ON DELETE RESTRICT` and the three `account.*` FKs to `auth.users`.
Problem: "delete the Auth account FIRST" is impossible (the delete is refused while any profile/onboarding/request row exists), so the order is always erase -> delete Auth user, and in between an unexpired access token silently re-creates a profile and can file new requests.
Evidence: reproduced on the reviewer's private QA stack; exact steps are in the private report.
Smallest fix: document the only workable order (ban the Auth user and revoke sessions, erase, delete the Auth user) and make the executor do it; or keep a non-identifying, time-limited tombstone that refuses profile creation. Decide with PO-04.

### L-1 (LOW) Hook discovery can be blocked by a temporary function (denial of erasure)
Location: `erase_learner` lines 442–451: the "unregistered hook" scan matches any schema, including per-session temporary schemas.
Evidence: reproduced on the reviewer's private QA stack; exact steps are in the private report.
Smallest fix: add `AND n.nspname !~ '^pg_'` to that scan (and apply the already ordered TEMP revoke, R-03).

### L-2 (LOW) Hook contract gaps
- A hook in a registered schema with any other signature than `(uuid)` is treated as `absent` and silently skipped (ran: `rewards.erase_learner(text)` -> hooks all "absent", `erased: true`, lane rows containing the id in text/jsonb left behind). Fix: block when a registered schema has an `erase_learner` of another signature.
- The role setting is not re-checked after each hook. A hook that leaves `session_replication_role = replica` (other lanes with append-only tables will need their own window) makes steps 2–3 run without triggers; the function still returns with `origin` (ran). Fix: assert `origin` after every hook call.
- A registered schema that exists but ships no hook is indistinguishable from a lane that forgot one; only the uuid-column postcondition catches it.

### L-3 (LOW) The postcondition covers less than "the id is nowhere"
`find_learner_references` checks only `uuid` columns of permanent tables. Ran: the id stored in a text column, a jsonb column, a `uuid[]` column and an UNLOGGED table's uuid column of a lane schema -> `erased: true`, all four left behind. In the schemas present today (app, account, ops, staff) nothing is missed. Fix: include unlogged tables and `uuid[]`; state the text/jsonb limit in the hook contract (lanes must not store learner ids as text/jsonb, or must erase them in their hook), and add a text/jsonb sweep to the test suite for every lane schema.

### L-4 (LOW) Lock order is inverted with respect to `app.sync_apply_operation`
Erasure locks profile then sync state; a first sync operation of a transaction locks sync state then (through the attempt's FK check) the profile. Ran with the sync lock sequence emulated by hand (sync-state `FOR UPDATE`, then profile `FOR KEY SHARE`): PostgreSQL reported "deadlock detected" and aborted the erasure; nothing was erased and nothing corrupted. Also, a sync push that queues behind an erasure fails with a raw FK error 23503 rather than the clean 42501. Fix: in `erase_learner` take the sync-state lock before the profile lock (or only the profile lock), retry the erasure on 40P01, and map 23503 from sync for a missing profile.

### L-5 (LOW) Display name accepts invisible and direction-changing characters at both layers
Ran as `edu_api_login`: a name containing a right-to-left override and a name made only of zero-width spaces are stored (`status: ok`); the API validator (schemas.py lines 21–41) forbids the same categories as SQL (controls, line/paragraph separators) and not format characters. Private to its owner today; fix before the name is shown to anyone else (reject Unicode category Cf, require at least one visible character).

### NOTE
- N-1 The mechanism relies on local Supabase letting the non-superuser `postgres` set `session_replication_role` (`rolsuper = f`, no `pg_parameter_acl` row: the permission comes from the platform's extension). Unverified on hosted; if refused there the function fails closed at the first statement of the window.
- N-2 Under a REPEATABLE READ caller the pre-window FK check would use an old snapshot; callers must use READ COMMITTED (assert `transaction_isolation` in the function).
- N-3 The audit de-identifying UPDATE scans the whole of `app.audit_events` with a text search of `details` while triggers are off; correct today, but its duration grows with the table. Rows of other actors whose details mention the id lose their whole `details` (by design).

## Verified sound (tried to break, could not)
- Replica-mode containment, as `edu_worker_login` and as a staff admin: `session_replication_role` is `origin` after normal return, after two calls in one transaction, after `ROLLBACK TO SAVEPOINT`, after commit/rollback, at session level and after `RESET ALL`; and after a lock timeout, a statement timeout, and an external cancel, each delivered while the function was blocked inside the window (statement timeout and cancel are not caught by the handler; the subtransaction abort restores the setting). After a hook raised: rolled back, `origin`. Learner rows intact after every failure.
- Who can run it: `edu_api_login` (no actor / learner actor), `edu_staff_login` (no actor, editor, learner id on the staff channel), staff calling the orchestrator directly, worker calling the staff wrapper, anon and service-role keys through PostgREST: all refused. No login role can set the parameter itself. Admin cannot erase themselves or another staff account (refused: staff records). A learner has no parameter through which to name another learner; deletion requests take the actor only.
- Scoping: every DELETE/UPDATE in and after the window is filtered by the target id; dynamic SQL uses `%I` / `regclass` on catalog names and binds the id as a parameter; no caller-controlled text reaches it.
- Completeness and collateral (real committed erasure of A): afterwards the id appears only in the Auth schema; the submitted display name appears nowhere in the database; learner B's rows and change version byte-identical; no orphan in feed/attempts/receipts; all 16 `app` triggers enabled and still refusing deletes/updates; hash of all 15 `app` functions unchanged; audit record holds counts only, no target id.
- Fail-closed: unregistered hook schema, hook with wrong return type, hook that raises, a lane table with an FK into the append-only rows, a lane table with a uuid column holding the id — each aborts with nothing erased.
- Profile function (sampled as `edu_api_login`): unknown keys, non-string values, oversized input refused; SQL text in a value is stored as data; only the caller's row is visible/changed. Onboarding: cannot go backwards, version bound enforced. Export without actor refused.

## Verdict on the erasure mechanism
Acceptable to keep in a draft PR, flag off, synthetic users only, with these conditions before any real use: (1) fix H-1 and M-1 and add concurrency tests; (2) replace the worker's direct grant by a request-bound wrapper (M-2); (3) settle the Auth ordering/tombstone (M-3) with PO-04; (4) exclude temporary schemas from hook discovery, assert `origin` after each hook, and publish the hook contract (L-1…L-3) before any other lane ships a hook; (5) verify on a hosted-like project that the owner may set the parameter (N-1); (6) owner sign-off on the principle of suspending triggers inside a definer function.

## Missing tests
Erasure racing onboarding/export/sync (H-1, L-4); executor whose actor is the target (M-1); temporary-schema hook (L-1); wrong-signature hook and hook that leaks the setting (L-2); text/jsonb/uuid[]/unlogged leftovers (L-3); timeout/cancel inside the window (sound, but unproven by the author's suite as far as examined); profile re-creation after erasure (M-3).

## Not examined
Priority 3 (R-01 route convention and regenerated contract files, flag-off 404, R-02/R-03 templates beyond the `proconfig` listing — all 13 `account` functions do pin `search_path = pg_catalog, pg_temp` —, baseline byte-identity, error shapes, `GET /v1/me` shape); Priority 4 (doc-claim vs test audit, vacuous tests); the FastAPI layer (routers, service, schemas) except the display-name validator; export size bounds and cross-account probes beyond one sample; onboarding under concurrency; `make lint` / `make typecheck`; behaviour with the real schemas of other lanes (only simulated ones); commit 114ab62.

## Suites observed
After a fresh `make db-reset` at 4699a8a: `make test-db` PASS (Tests=720; author reports 720), `uv run pytest -q` 339 passed (author reports 339). `make lint` and `make typecheck` not run.
