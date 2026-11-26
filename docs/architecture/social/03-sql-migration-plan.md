# 3. SQL migration plan

**The files in `migrations/` are proposals. None was executed.** They are stored
under `docs/` deliberately: the Supabase CLI applies only what is in
`supabase/migrations/`, so `make db-reset`, CI and every developer machine
behave exactly as before this branch.

## Files

| Order | File | Contains |
|---|---|---|
| 1 | [`proposed/0001_social_schema_and_roles.sql`](migrations/proposed/0001_social_schema_and_roles.sql) | Schema `social`; group roles `edu_social`, `edu_social_mod`, `edu_social_worker`; `social.current_actor_id()` |
| 2 | [`proposed/0002_social_tables.sql`](migrations/proposed/0002_social_tables.sql) | 23 tables, their constraints and indexes; the single `config` and `visibility_clock` rows |
| 3 | [`proposed/0003_social_helpers_and_guards.sql`](migrations/proposed/0003_social_helpers_and_guards.sql) | Read helpers used by policies; internal helpers; 8 triggers (content lifecycle, independent approval, reply depth, membership rules, append-only logs) |
| 4 | [`proposed/0004_social_member_functions.sql`](migrations/proposed/0004_social_member_functions.sql) | The member write boundary: submit, react, report, block, join, delete, profile, settings, notifications; `visibility_changes()` |
| 5 | [`proposed/0005_social_moderation_functions.sql`](migrations/proposed/0005_social_moderation_functions.sql) | Queue claim, decide, escalate, sanction, lift; account erasure; retention job |
| 6 | [`proposed/0006_social_rls_and_grants.sql`](migrations/proposed/0006_social_rls_and_grants.sql) | Row-level security on every table, column grants, 31 policies, `EXECUTE` grants |
| — | [`future/F001_direct_messaging.sql`](migrations/future/F001_direct_messaging.sql) | **Not approved.** Draft tables for messaging |
| — | [`future/F002_media.sql`](migrations/future/F002_media.sql) | **Not approved.** Draft tables for images |

Grants come last so that every function exists before it is granted, and the
blanket `REVOKE … FROM PUBLIC` runs after every function was created
(PostgreSQL lets everyone execute a new function by default; see change C10 in
`docs/SCHEMA_CHANGELOG.md`).

## What does not change

- No statement in these files names the `app` schema (checked: 0 occurrences).
- No existing migration, seed, test, role, grant or policy is modified.
- `supabase/tests/010_structure.sql` counts tables, keys and policies **in
  schema `app` only**, so its assertions (22 tables, 28 foreign keys, 17
  policies) stay true after the social schema exists.
- `supabase/config.toml` keeps `schemas = ["public", "graphql_public"]`:
  `social` is never exposed through the Supabase Data API. Realtime and Storage stay disabled.
- The role `edu_api` receives nothing. The only statement that mentions it is a
  `REVOKE ALL ON SCHEMA social FROM edu_api` (a no-op that records the intent).

## How to adopt them (milestone Social-01 — not now)

1. Branch `social-01` from `main`.
2. Copy the six `proposed/` files to `supabase/migrations/` with timestamps
   **later than** `20261121000400`, keeping their order, e.g.
   `20270115000100_social_schema_and_roles.sql` … `20270115000600_social_rls_and_grants.sql`.
   Remove the "PROPOSED — NOT APPLIED" banner from the copies.
3. `make db-reset` on a **local disposable** database. Expect to fix things:
   these files were parsed, never run (see below).
4. Write the pgTAP files listed in [08-test-specification.md](08-test-specification.md)
   (`supabase/tests/100_social_*.sql` …) and make them pass.
5. Extend `scripts/local_stack.py provision` to create the three login roles
   with random passwords in the git-ignored `.env` — the same way
   `edu_api_login` is created today. No password in any migration.
6. Run the **existing** suite unchanged (`make check`). Any change in its
   results means the boundary leaked and is a release blocker.

Rollback while nothing depends on it (local or staging only):
`DROP SCHEMA social CASCADE; DROP ROLE edu_social, edu_social_mod, edu_social_worker;`
— `app` is unaffected because nothing in it references `social`.

## Function catalogue

"Drafted" = full body in the proposed files. "Specified" = signature and rules
agreed here; body to be written in the milestone shown. Every function has
`SET search_path = ''` and uses schema-qualified names only.

### Callable by `edu_social` (member endpoints)

| Function | Status | What it does |
|---|---|---|
| `current_actor_id()` | drafted | The verified caller of this transaction |
| `actor_access(community?)` | drafted | `ok` / `not_enrolled` / `not_active` / `suspended` / `not_member` |
| `can_read_community(community)`, `blocked_with(user)`, `shares_community_with(user)`, `actor_grade_band()` | drafted | Helpers used inside policies |
| `write_denial(community, capability)` | drafted | The error code that would stop a write, or NULL |
| `submit_post(…)`, `submit_comment(…)` | drafted | Safe retry → permission → limits → store as `pending_review` → queue for review |
| `set_reaction(post, comment, kind)` | drafted | Set / change / remove; keeps the total exact |
| `file_report(post, comment, profile, category, note)` | drafted | Record with snapshot → open or raise queue item → auto-hide if severe or threshold reached |
| `set_block(user, blocked)` | drafted | Block / unblock; refuses teachers and staff |
| `join_with_invite(code_digest)` | drafted | Counted attempt → request `pending_approval` |
| `decide_join_request(community, user, approve)` | drafted | For the group's teacher or staff; never for oneself |
| `leave_community(community)` | drafted | |
| `delete_own_content(post, comment)` | drafted | Hide at once; erase text unless a report/hold is open |
| `update_profile(name, avatar)` | drafted | Name goes to review |
| `accept_guidelines(version)`, `update_own_settings(…)`, `mark_notifications_read(up_to)` | drafted | |
| `visibility_changes(since, limit)` | drafted | Ids + visible flag for the phone's cache |
| `my_private_profile()`, `community_members(community)` | drafted | Narrow reads the column grants do not allow |
| `adult_update_settings(learner, …)`, `adult_withdraw_consent(learner)`, `adult_list_learners()` | **specified — Social-04** | Only for a `verified` row in `adult_links`; sets `locked_by = 'adult'`; withdrawal sets enrolment `paused` |

### Callable by `edu_social_mod` (moderation and admin endpoints)

| Function | Status | What it does |
|---|---|---|
| `mod_claim_next(lease_minutes)` | drafted | Most urgent, oldest item; never one's own content; `SKIP LOCKED` so two moderators never get the same item |
| `mod_decide(item, decision, reason, note)` | drafted | approve / reject / dismiss / remove; writes the action row first, then changes visibility; notifies |
| `mod_escalate(item, level, summary)` | drafted | Opens an escalation, places evidence holds |
| `mod_impose_sanction(…)`, `mod_lift_sanction(…)` | drafted | Role-limited (moderator vs safety lead) |
| `erase_user(user)` | drafted | Social half of account deletion |
| `admin_enroll(user, account_kind, grade_band, age_band, consent_method)` | **specified — Social-02** | `social_admin`/`safety_lead`; creates profile + enrolment + default settings; refuses self-enrolment; consent rules by age band per D-02 |
| `admin_set_enrollment_status(user, status)` | **specified — Social-02** | pause / close / reactivate |
| `admin_create_community(…)`, `admin_set_community_status(community, status)` | **specified — Social-02** | Legal transitions only (`draft→open⇄frozen→archived`) |
| `admin_create_invite(community, code_digest, max_uses, expires_at)`, `admin_revoke_invite(invite)` | **specified — Social-02** | The API generates the code and passes only its digest |
| `admin_assign_member(community, user, role)`, `admin_remove_member(community, user)` | **specified — Social-02** | `verification_method = 'staff_assignment'` |
| `admin_link_adult(adult, learner, relationship)`, `admin_verify_adult_link(link)` | **specified — Social-04** | Verifier ≠ adult |
| `admin_update_config(…)` | **specified — Social-02** | `safety_lead` only; audited |
| `mod_close_escalation(escalation, outcome, reference)`, `mod_release_hold(hold)` | **specified — Social-02** | `safety_lead` only |
| `mod_reveal_reporter(report)` | **specified — Social-02** | `safety_lead` only; returns the reporter's id; always writes an audit event. Moderators have no column grant on `reports.reporter_id` |

Granting a staff role itself (`social.staff_roles`) is done by the database
owner out of band, on purpose: no API path can create a moderator.

### Callable by `edu_social_worker`

| Function | Status | What it does |
|---|---|---|
| `run_retention()` | drafted | Erases expired text, deletes expired rows, skips anything on hold |

### Not callable by any API role (internal)

`lock_actor`, `next_visibility_seq`, `bump_rate`, `seconds_to_window_end`,
`write_audit`, `notify`, `require_staff`, `actor_staff_label`, and the five
trigger functions.

## Design notes a reviewer of the SQL should know

- **Lock order** (documented in the header of file 4): caller's enrolment →
  comment → post → moderation item → visibility clock. PostgreSQL detects a
  deadlock anyway and aborts one side; the API should retry once on SQLSTATE `40P01`.
- **Refused attempts are committed.** The functions return a result code rather
  than raise, so the API must *not* roll back on a refusal. This differs from
  the usual "error → rollback" reflex and needs a test (API-R03).
- **Fixed-window rate limits** allow up to twice the limit across a window
  boundary (e.g. 5 posts at 23:59 and 5 at 00:01 UTC). Acceptable here; the
  "waiting for review" cap bounds the real load.
- **The publication trigger reads `moderation_actions`.** Approval and
  publication happen in one transaction, in that order. A test must show that
  publishing without the action row, with a different digest, or with the
  author as approver, all fail (DB-C03…C05).
- **Counters are maintained by the functions**, not by triggers
  (`comment_count`, `reaction_count`). A consistency check query is part of the tests (DB-C12).
- **Ownership.** As in `app`, tables and functions are owned by the migration
  role, which bypasses row-level security. Hardening option, shared with
  `docs/SECURITY.md` item 4: a dedicated `NOLOGIN` owner with narrow grants.

## What "parsed, never run" means in practice

Likely places to find errors on first application, listed so nobody is surprised:

1. `GRANT SELECT (columns)` combined with policies that call helper functions —
   correct in principle, but column-level grants make `SELECT *` fail for the
   role, so every query in the API must name its columns.
2. Policies call `STABLE SECURITY DEFINER` helpers per row. Correct, but the
   query planner cannot see through them; feed pages are small (≤ 20 rows) so
   this should be fine. Measure in PERF-01 before trusting it.
3. `ALTER ROLE` / role creation on a hosted Supabase project behaves
   differently from local (`postgres` is not a true superuser there). Untested, like the existing pooler note.
4. Trigger functions that are shared between two tables rely on both tables
   having identically named columns. One mismatch is a runtime error on first write.
