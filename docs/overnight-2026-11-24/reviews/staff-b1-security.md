# Security review — staff B1 (commit 7c3d2fb)

Reviewer: QA-1 (independent). Date: 2026-11-24. Branch `overnight/staff-worker`.

QA-1 verdict on 7c3d2fb (staff B1): APPROVE WITH FIXES — one HIGH must land before other lanes ship definer write paths on these primitives.

All probes ran on the integration stack only, inside rolled-back transactions. Afterwards: 0 probe rows, 0 role/config changes, all three logins still work, worktree clean. I also ran the author's suites there (`make test-db` 354 pass; staff pytest 66 pass); those append their usual `staff.access` denial rows, my own probes added none.

## HIGH

**H1 — the staff and worker database logins can escalate to the owner of the `SECURITY DEFINER` functions (search-path / temporary-schema weakness).**
- Where: `supabase/migrations/20261124010000_platform_roles_ops_staff.sql` — the `SET search_path = ''` clause of every function (lines 81, 100, 175, 219, 238, 250, 270).
- Class of weakness: an empty `search_path` does not remove the session's temporary schema from name resolution, and every role can create temporary objects in this database through the default `PUBLIC` privilege. A caller able to run SQL of its own choice on the staff or worker connection can therefore influence how names inside a definer function resolve, and get its own code executed with the function owner's privileges. This is the hazard described under "Writing SECURITY DEFINER Functions Safely" in the PostgreSQL documentation. Exploit statements are deliberately not published here; the reproduction is in the private review log.
- Confirmed by reproduction (rolled back) as the real `edu_staff_login` and as `edu_worker_login`: code ran as the owner, could read tables that neither role may touch, and could give a learner account an active staff role.
- Impact: needs arbitrary SQL on the staff or worker connection (injection or a leaked credential); the API itself only uses bound parameters. But this is exactly the worst case `tests/integration/test_staff_boundary.py:381` claims to cover, and the claim "reaches no table" is false. Every lane function built on the same template inherits it.
- Pre-existing, same class, outside this commit: the learner API login is affected in the same way through the baseline definer function it may execute, with the baseline helper `app.current_actor_id()` as the carrier. Confirmed by reproduction (rolled back). The statement "edu_api gets nothing in `ops` or `staff`" therefore also depends on this fix.
- Fix: because the baseline is frozen and the baseline helper is affected too, changing only the new functions is not enough (tried in a rolled-back transaction: the weakness remained through the helper). The smallest fix that closed it:
  `DO $$ BEGIN EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database()); END $$;`
  With that applied (rolled back afterwards), the three API/worker logins can no longer create temporary objects, and `actor_roles`/`require_role` still work. `postgres` owns the database, so a lane migration can do it.
- Decision for the director: the revoke also removes TEMP from `anon`/`authenticated`/`service_role`/`authenticator`. Nothing in this repo uses temp tables through those roles, but it is a database-wide change. I recommend it, plus `pg_catalog, pg_temp` as the search_path template for all lanes, and a pgTAP assertion `NOT has_database_privilege('edu_*_login', current_database(), 'TEMP')`.

## MEDIUM

**M1 — any signed-in learner can append unlimited permanent audit rows.**
- Where: `services/api/src/edu_api/staff/deps.py:91-97`.
- What is wrong: each refused request commits one row (about 150–250 bytes) to an append-only table that even the owner cannot delete from. The API has no rate limit. The author admits this in the lane doc, line 139.
- Evidence: 300 in-process requests on a pool of 1 completed in 0.51 s, so one token can write hundreds of rows per second. I did not run the flood itself; the author's test already proves one row per refusal.
- Mitigating: signup and anonymous sign-in are off (`supabase/config.toml:53-54`), so it needs a provisioned account.
- Fix: do not write one row per refusal. Either a counter upsert in an `ops` table keyed (actor, route, hour) with one audit row on first occurrence, or a per-actor throttle in `require_staff`. Do this before any staff route is exposed publicly.

**M2 — the audit details validator does not stop learner personal data; it only stops whitespace.**
- Where: migration lines 126 and 139.
- Accepted (run, rolled back): `{"answer":"Paris"}`, `{"name":"Jean-Pierre.Dupont"}`, `{"phone":"+50937123456"}`, `{"dob":"2014-03-09"}`, `{"ip":"192.168.1.20"}`, `{"contact":"jean.dupont/gmail.com"}`, `{"note":"my_teacher_hits_me_at_school"}`, a 1.8 KB base64url blob in an array, and free text in a key name or in `p_action`/`p_target_kind`.
- Why it matters: the brief says details "must never contain free text from learners". Other lanes will read "validated" as "safe" and pass learner-derived strings; a one-word answer or a display name goes straight in, permanently.
- Fix: state in the function comment and plan §3 that callers must never pass learner-typed values, only ids/enums/numbers. Tighten cheaply: string values at most 64 chars, and move the 120-char allowance to keys named `route`.

## LOW

- **L1 — superuser sessions are labelled `staff`.** Migration lines 84-86: `pg_has_role` is true for superusers. `ops.actor_kind_for('supabase_admin')` returns `staff`; as `supabase_admin`, `ops.audit_write(...)` with no actor raises "A staff audit event needs a verified actor". Any maintenance or cron path running as a superuser cannot audit, or is mislabelled when an actor is set. Fix: return `system` first when the role is `rolsuper`.
- **L2 — a learner's refusal is stored with `actor_kind='staff'`,** and details do not distinguish a learner from staff with the wrong role (`deps.py:92-96`; the test at `test_staff_boundary.py:116` pins this as intended). A query for "staff actions" returns learners. Fix: add `"held_roles": [...]` (empty for a learner) to the denial details and document that `actor_kind` means channel.
- **L3 — a route template with a character outside `[A-Za-z0-9_.:/{}+-]` turns the 403 into a 500 and loses the denial.** `deps.py:70-73` plus the validator. Repro: route `/v1/staff/probe/odd~route` with a learner token gave `500 internal_error` and 0 audit rows. It fails closed. Fix: in `_route_template`, replace anything outside the allowed set, or fall back to `"unknown"`.
- **L4 — a wrong staff DB credential or a wrong login gives 500, not 503, and nothing detects it at startup.** Repro: staff URL with a bad password gave `500 internal_error` (no leak in the body) while `/ready` stayed 200; staff URL set to the learner login gave 500 on every request. Not run, by reasoning: staff URL set to the admin `postgres` URL would work silently, with `actor_kind='system'` and NULL-actor audit writes allowed. Fix: on first use, assert `session_user`'s kind is `staff` and refuse otherwise; map SQLSTATE class 28 to 503.
- **L5 — test blind spot in `supabase/tests/100_platform_structure.sql:57-66`.** `information_schema.role_table_grants` only shows grants involving the current user's enabled roles and never PUBLIC-derived access. My own `has_table_privilege` sweep over every non-catalog relation for both logins returned 0 rows, so the state is fine today; the test would not catch a regression. Fix: use `has_table_privilege` over `pg_class`.

## NOTE

- R-01 compliance: `main.py:95` uses `include_in_schema=staff_database is not None`, not the module-level `INCLUDE_IN_SCHEMA = False` constant (the commit predates the ruling). `scripts/export_openapi.py` passes `_env_file=None` but still reads process environment, so an exported `EDU_STAFF_DATABASE_URL` would put `/v1/staff/me` into `openapi.json`.
- `CONNECTION LIMIT 10` for `edu_staff_login` against a per-process pool maximum of 5 means a third API process gets `53300`, which surfaces as 503.
- A multi-dimensional role array raises `0A000` from `array_position` instead of `22023`; it still fails closed.
- `staff.require_role` leaves no trace when it refuses, by design. Lanes need a second transaction to record DB-level denials; nothing in B1 helps them.
- Both logins can `ALTER ROLE <self> PASSWORD` / `SET` (standard PostgreSQL; verified and rolled back). With arbitrary SQL that is a self-lockout of the API.
- Baseline, not this commit: `Database.transaction(None)` does not clear `edu.actor_id`, relying on nothing ever setting it at session level.

## Verified sound (tried to break, could not)

- **Role attributes and membership:** all three group roles are plain NOLOGIN; each login is a member of exactly its own group; `postgres` holds only ADMIN-only (inherit off, set off) membership.
- **Privileges:** `anon`, `authenticated`, `authenticator`, `service_role`, `edu_api` and PUBLIC have no USAGE or EXECUTE in `ops`/`staff`. Function ACLs are exactly `edu_staff` (4 functions) and `edu_worker` (1). Helpers are not executable by the logins. No CREATE on any schema; no table, sequence or definer function reachable outside the four intended.
- **`session_user` attribution:** `SET SESSION AUTHORIZATION` is denied for the staff login; `SET ROLE` does not change the kind; a worker setting `edu.actor_id` stays `worker`.
- **Role-check arguments:** NULL array, empty array, NULL element, unknown, misspelt or trailing-space role, and more than 8 entries all raise; duplicates are fine; with no actor, `require_role` raises 42501 and `actor_has_role` is false; a malformed actor value raises; inactive roles are refused. No dynamic SQL; error messages do not echo input.
- **Audit forgery:** no actor or kind parameter; direct INSERT/UPDATE/DELETE on `app.audit_events` is denied; details are capped at 2048 bytes (largest row I produced was 1968 bytes); newline, tab and nested values are refused.
- **API ordering:** 401 comes before 503 and 403, and before path validation (no token + bad uuid gave 401; right role + bad uuid gave 422). Legacy anon and service_role JWTs, the secret key and the publishable key all get 401 on `/v1/staff/me`.
- **No caching or identity leak:** roles are read per request, with no cache in the code; the author's pooled-connection and deactivation tests are not vacuous. 300 concurrent requests on a pool of 1 all returned 200.
- **Provisioning script:** the password goes through `format(%L)` as a bound parameter; identifiers are constants; it refuses non-local hosts; `.env` is written 0600 and git-ignored.
- **Mission rules:** nothing created or granted in `app`; baseline migrations, seed and 0xx tests untouched; no secrets in the diff.

## Missing tests

- Temporary-object creation by the three logins and the H1 weakness against each definer function; TEMP privilege of the three logins.
- Superuser session kind (L1).
- A refusal on a route whose template has an out-of-set character (L3).
- Wrong password, wrong login and admin login on the staff pool (L4).
- The personal-data-shaped values in M2, pinned as accepted or refused.
- Any bound on audit growth per actor (M1).
- `SET SESSION AUTHORIZATION` from the staff and worker logins.
- Vacuous today: "RLS on every table in ops/staff" and "no table privilege in ops or staff" at `100_platform_structure.sql:63-69` (there are no tables yet); they are forward guards only.

## Not examined

- The hosted/production role setup and Supavisor behaviour.
- `scripts/local_stack.py` was read, not executed.
- The lane doc beyond its "Known gaps" section.
- Anything after 7c3d2fb in the staff worktree.
- Load behaviour of the staff pool under real network latency.
- MFA/aal (design-only per the brief).
