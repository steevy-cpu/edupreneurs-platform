# Staff + identity fix verification (public version)

Reviewer: qa4 (independent). Date: 2026-11-25. Disposable local stack only.
Tree under test: `overnight/integration-2026-11-24` @ 34a2e6d (contains `overnight/staff-worker` @ 33aa2e2 and
`overnight/identity-onboarding` @ 6913435), after a fresh `make db-reset`; real service logins over TCP.
`main` @ dd2aa19 checked briefly for Part A. This public version describes weaknesses as class, impact and fix;
reproduction steps are kept in the private report.

**Verdict:** the original B1 HIGH (temporary-schema type shadowing in SECURITY DEFINER functions) is closed on the
integration tree, by the database-level TEMP revoke alone, but is still OPEN on `main`. A NEW HIGH (NF-1: every
service login can make the database run extension DDL as the platform superuser, through Supabase `supautils`) is
open on both. Staff fixes M-B2-1 and L-B2-2 PASS; L-B2-1 partial (one field still returns 500); L-B2-3 and L-B2-4
still open as documented. Identity fixes M-1, M-2, L-1, L-2, L-4 PASS; H-1 passes at the database level, but end to end
the learner id survives through M-3 (BLOCKED, owner decision). Containment of `session_replication_role` PASS.
Erasure across all lanes left no id behind in my runs; every schema holding learner rows is registered.

## Part A — database privilege escalation (B1 H1)

- **All three logins** (`edu_api_login`, `edu_staff_login`, `edu_worker_login`): TEMP privilege false; every way of
  creating a temporary object (table, function, domain, type, view, sequence, SELECT INTO, CTAS, DO block) is refused;
  no CREATE on any of the 24 schemas (including `public` and `extensions`); SET ROLE / SET SESSION AUTHORIZATION to
  privileged roles refused; `session_replication_role` cannot be set; the definer functions they can execute run
  normally with no injected code.
- **Control:** with TEMP re-granted inside a rolled-back transaction, the original class fires again as `postgres`,
  through the baseline `app.current_actor_id()`, including from NEW functions that pin
  `search_path = pg_catalog, pg_temp` (`leaderboard.my_standing`, `billing.is_entitled`), because they call that
  baseline function. The new search_path template does not protect them by itself; the single TEMP revoke does.
- **Inventory:** 130 SECURITY DEFINER functions in app-owned schemas, all owned by `postgres`, all with a pinned
  search_path (`app` 15 functions `""` — frozen baseline; 175 functions in the nine other app schemas
  `pg_catalog, pg_temp`). Executable by `edu_api_login` 14, `edu_staff_login` 54, `edu_worker_login` 16; none by
  `anon`, `authenticated`, `service_role`, `authenticator`, `supabase_auth_admin`, `dashboard_user`. `public` holds no
  object; no operator outside `pg_catalog`; no role-level setting for the edu roles; only platform event triggers.
- **Supabase functionality with the revoke:** `make db-reset` works; Auth health 200, admin password set + password
  sign-in issue a token, `/auth/v1/user` 200; Auth migrations in the image use no temporary tables; PostgREST
  `/rest/v1/` 200 through the gateway; `pg_dump` inside the stack's own DB container works as `postgres` and
  `supabase_admin`. `postgres`, `supabase_admin`, `dashboard_user` keep TEMP. Storage, Realtime, Studio, Edge
  Runtime and Analytics are disabled in `supabase/config.toml`, so whether Storage/Realtime need TEMP is
  NOT_VERIFIED; hosted behaviour NOT_VERIFIED.
- **`main`:** PUBLIC still holds TEMP; the original class is reproducible there as `edu_api_login` through the
  baseline sync function (code runs as `postgres`). It stays open until migration
  `20261124010400_revoke_temp_and_search_path.sql` part (a), or the equivalent one-statement revoke, reaches `main`.
- Baseline files are byte-identical between `main` and the integration tree.

## Part B — staff second deliverable

- **M-B2-1 PASS.** Admins and other editors can no longer edit, attach/detach sources on, or submit another
  author's draft (403); an admin's own revision cannot be self-reviewed (409). Residual of the same class in the
  content lane: NF-2.
- **L-B2-1 FAIL (partial).** Control characters in lesson text, title, choices, prompts, source title, rights notes
  and review notes now give 422. The source URI field still returns 500 for U+0000 (NF-3).
- **Carriage return:** CRLF and lone CR are refused with 422 while the published content contract allows them, so a
  client sending Windows line endings is refused. Right rule: normalise CRLF and CR to LF before validation and
  storage, refuse all other Cc except TAB and LF, and put the same rule in the contract.
- Format characters (RLO U+202E, zero-width-only text, U+2028, BOM) are accepted in lesson text — owner decision
  before content reaches minors.
- **L-B2-2 PASS.** Two revisions of one lesson in a pack are refused in either order.
- **L-B2-3 OPEN (confirmed).** Blocking the source of live content does not remove it; the first release of a pack
  cannot be withdrawn; no takedown route.
- **L-B2-4 OPEN (confirmed).** The last usable admin can revoke themselves when the only other admin account is
  banned; the check counts role rows, not usable accounts.

## Part C — identity erasure

- **H-1 BLOCKED (DB fix PASS).** Directly in the database, onboarding and export calls racing an erasure now wait and
  are refused. Through the API, the baseline "create the profile on every authenticated request" step waits for the
  erasure and then re-creates the learner, so onboarding, export and sync succeed and the id is back in eight tables
  while the erasure reported success. This is M-3 under concurrency; it is resolved only by the M-3 decision.
- **M-1 PASS.** An erasure whose session actor is the target is refused; the postcondition now follows the audit write.
- **M-2 PASS.** The worker can only process an open deletion request by its id; direct erasure is not executable;
  unknown ids are refused for worker and staff paths.
- **L-1 PASS**, **L-2 PASS** (wrong-signature-only hook and a hook leaking replica mode both block), **L-4 PASS**
  (no deadlock against the sync lock order, with or without an existing sync row).
- **L-3 still open (NOTE):** ids stored in text/jsonb columns are not covered by the postcondition.
- **M-3 BLOCKED.** After a real erasure, a still-valid token re-creates the profile and can file requests and sync;
  the Auth account remains. Needs the owner's decision (ban and revoke sessions → erase → delete the Auth user, or a
  non-identifying time-limited tombstone; PO-04).
- **Replica-mode containment PASS:** `origin` after normal return, savepoint rollback, the next transaction, a failing
  hook, a hook leaking replica, a failed postcondition, and lock timeout, statement timeout and cancel delivered inside
  the window. No login can set the parameter.
- **Cross-lane erasure PASS (L-3 aside):** a synthetic learner with real rows in app, account, rewards, billing,
  notify and leaderboard: after the worker erasure no table in any application schema contains the id (text sweep of
  every row). `account.erasure_hooks` registers notify, leaderboard, rewards, vocab, billing, content, staff, ops;
  every schema holding learner rows is registered. Notify refuses learner ids in its free references.
- **Hosted portability (N-1): BLOCKED / NOT_VERIFIED.** Locally the non-superuser owner may set
  `session_replication_role` only because Supabase's `supautils` allows it for its privileged role. Whether a hosted
  project allows it is not verified; if not, the erasure fails closed.

### Lifecycle behaviour that decides a legal question — BLOCKED_BY_OWNER (not judged)
De-identified audit rows and a permanent erasure record are kept; the Auth account (email) survives the database
erasure with no deadline; no cooling-off period and no staff reason code; billing orders and provider events are kept
in anonymised form; rewards and leaderboard history are deleted outright; export retention.

## New findings

### NF-1 (HIGH) Service logins can run "privileged extension" DDL executed as the platform superuser
- Location: platform configuration (Supabase `supautils` 4.0.0, `supautils.privileged_extensions`), exposed by the
  repository's password logins for services (`scripts/local_stack.py provision`; roles from
  `20261124010000_platform_roles_ops_staff.sql@33aa2e2`; `edu_api_login` already on `main` dd2aa19).
- Class: privilege boundary bypass. A session with arbitrary SQL on any of the three service logins can create, alter
  and drop listed extensions; the command runs as the superuser, can target any schema (including `app`, `account`
  and `pg_catalog`), and can drop existing extensions with CASCADE (including Vault). Some extensions then give the
  login outbound HTTP from the database host and scheduled jobs.
- Impact: same precondition as B1 H1 (arbitrary SQL on a service login). Persistent objects in protected schemas
  (breaks the pinned-structure invariant and can change operator resolution for every definer), superuser-executed
  destruction, an SSRF/exfiltration channel, persistence. I found no path to code execution as `postgres`; not
  exhausted. The TEMP revoke does not cover this.
- An event trigger owned by `postgres` does not stop it (tried locally; it does not fire for these commands).
- Smallest fix (owner/platform): verify on the hosted project whether the same holds; if so raise it with Supabase
  and keep service logins without any free-SQL surface; add a readiness check and a test that the extension list
  equals an allowlist and that no extension lives in application schemas or `pg_catalog` beyond the defaults; add a
  known-gap test asserting extension creation is refused for each login, so the gap stays visible.

### NF-2 (LOW) Content-asset attach/detach are not author-bound
- Location: `supabase/migrations/20261124030100_content_assets_and_pack_manifests.sql:414-470@34a2e6d`.
- Class: same as M-B2-1 in the content lane — the functions check the role (editor/admin), not authorship, so
  someone other than the author can change a draft's asset list and (if admin/reviewer) then approve it. No API route
  uses them yet.
- Fix: apply the author check (`staff.require_author`) in both; add a regression test.

### NF-3 (LOW) Source URI with U+0000 gives 500
- Location: `services/api/src/edu_api/routers/staff_editorial.py:164@34a2e6d` (the URI pattern's `\S` matches U+0000;
  the field lacks `NoControlCharacters`). Fails closed.
- Fix: add `NoControlCharacters` to the field; unit test.

## Verification table

| ID | Original defect | Commit | Result | Fix assessment | Remaining path | Tests | Verdict |
|---|---|---|---|---|---|---|---|
| B1-H1 | Temp-schema type shadowing → owner code execution | 7c3d2fb + baseline | Every temp/CREATE route refused for 3 logins; control with TEMP re-granted fires as `postgres` | Closed by TEMP revoke only | Any re-grant of TEMP reopens it for all definers; NF-1 separate | pgTAP TEMP assertions | PASS |
| main | Same on `main` | dd2aa19 | Reproduced as `edu_api_login` | Not fixed on main | Until 010400 (a) merges | — | FAIL (main) |
| M-B2-1 | Admin edits another's draft then approves | 642ab5c | 403 on edit/attach/detach/submit; 409 self-review | Correct | NF-2 | Author + probe | PASS |
| L-B2-1 | Control characters → 500 | 642ab5c | 422 except source URI (500) | Partial | NF-3; CR refusal vs contract | Unit tests | FAIL (partial) |
| L-B2-2 | Two revisions of one lesson in a pack | 642ab5c | 422 both orders | Correct | — | Author | PASS |
| L-B2-3 | No takedown | 642ab5c | Still no way to withdraw | Not fixed | Documented | — | OPEN |
| L-B2-4 | Last admin counts rows | 642ab5c | Revoke succeeded with only a banned co-admin | Not fixed | Documented | — | OPEN |
| H-1 | Race leaves id after erasure | 4699a8a | DB refused; API re-creates learner | DB fix correct | Via M-3 | DB-level only | BLOCKED |
| M-1 | Audit row re-stores id | 4699a8a | Refused 55000 | Correct | — | Author | PASS |
| M-2 | Worker erases any id | 4699a8a | Request-bound only | Correct | Cooling-off/reason code (owner) | Author | PASS |
| L-1 | Temp function blocks erasure | 4699a8a | Erasure completes | Correct | — | Author | PASS |
| L-2 | Hook contract | 4699a8a | Blocks wrong signature, leaked replica | Correct | — | Author | PASS |
| L-4 | Lock order | 4699a8a | No deadlock | Correct | — | Author | PASS |
| M-3 | Token re-creates profile | 4699a8a | Reproduced | Not fixed | Owner decision | — | BLOCKED |
| Containment | — | 6913435 | `origin` on every path tried | Sound | Hosted unknown | Partly | PASS |
| Cross-lane erasure | — | 34a2e6d | No id left; all schemas registered | Sound (uuid) | L-3 text/jsonb | Per lane only | PASS |
| N-1 hosted | — | — | Local only | — | — | — | BLOCKED / NOT_VERIFIED |
| NF-1 | New | dd2aa19, 34a2e6d | — | — | — | none | HIGH open |
| NF-2 | New | 34a2e6d | — | — | — | none | LOW open |
| NF-3 | New | 33aa2e2 | — | — | — | none | LOW open |

## Suites observed
Integration @ 34a2e6d after a fresh `make db-reset`: `make test-db` Files=42, Tests=3025, PASS; `uv run pytest -q`
1754 passed. `make lint` / `make typecheck` not run.

## Not examined
Hosted Supabase (privileged extensions, TEMP defaults, `session_replication_role`); Storage/Realtime (disabled);
vocab, billing, rewards, notify staff routes for control characters; NF-1 escalation beyond what is listed; the
`_supabase` database; mobile app; performance; `make lint` / `make typecheck`.
