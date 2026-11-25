# Overnight mission 2026-11-24 — plan, ownership and rules

Director / integrator / schema coordinator: Fable (Claude Code session on the MacBook Air).
Sources read in full before this plan: the three v2 briefs in `/Volumes/EdupreneursDev/overnight-briefs/`
(master prompt, priority addendum, Mac runbook) and Platform-00 docs README, 04, 05, 06, 07.

**Nothing in this mission is merged into `main`, deployed, linked to a hosted project, or run against
real data.** Every database is a disposable local stack with synthetic accounts.

Incidents are recorded in [`INCIDENTS.md`](INCIDENTS.md) (one so far: I-01, shared-stack learning tables truncated by the mobile test harness).

Live status is in [`LEDGER.md`](LEDGER.md). Per-lane specifications are in [`briefs/`](briefs/).

## 1. Preflight (22:25–22:50 local)

| Check | Result |
|---|---|
| Briefs | 3 v2 files found in `/Volumes/EdupreneursDev/overnight-briefs/`, byte-identical to the copies in `~/Downloads` |
| Other Claude sessions | none running (one `claude` process: this one) |
| Existing worktrees | `Mon-edupreneur` on `mobile-02` (clean), `worktrees/platform-00` (clean), separate clone `social-00-work` (clean). **None is touched.** |
| Shared local stack | `supabase_*_mon-edupreneur` on ports 54321/54322 — left completely alone (never reset, never used) |
| Disk | internal 13 GiB free (floor 7 GiB) · dev volume 169 GiB free · T7 768 GiB free |
| Memory | 16 GB RAM, 57 % free at start; Docker VM 7.8 GiB; one lane stack ≈ 230 MiB |
| Power | AC, `caffeinate` assertion active |
| Baseline on the isolated integration stack | pgTAP `Result: PASS`, pytest `144 passed`, pgTAP again PASS (logs in `/Volumes/EdupreneursDev/logs/overnight-2026-11-24/baseline-integration-*.log`) |

## 2. Isolation model

Each lane = one Git worktree + one feature branch + **its own disposable Supabase stack** (own Docker
project id `edu-on-<lane>` and port block), created serially by
`/Volumes/EdupreneursDev/worktrees/overnight/_tools/new-lane.sh`. `supabase/config.toml` carries the
lane's ports as a local-only change (`git update-index --skip-worktree`), so it can never be committed.

| Lane | Worktree (`/Volumes/EdupreneursDev/worktrees/overnight/…`) | Branch | Base | API / DB port |
|---|---|---|---|---|
| integration (director) | `integration` | `overnight/integration-2026-11-24` | `main` dd2aa19 | 56021 / 56022 |
| staff | `staff` | `overnight/staff-worker` | `main` | 56121 / 56122 |
| identity | `identity` | `overnight/identity-onboarding` | `main` | 56221 / 56222 |
| content | `content` | `overnight/content-format-v2` | `main` | 56321 / 56322 |
| vocab | `vocab` | `overnight/word-of-the-day` | `main` | 56421 / 56422 |
| rewards | `rewards` | `overnight/rewards-gold` | `main` | 56521 / 56522 |
| entitlements | `entitlements` | `overnight/entitlements` | `main` | 56621 / 56622 |
| notify | `notify` | `overnight/notify-security` | `main` | 56721 / 56722 |
| native | `native` | `overnight/native-experience` | `mobile-02` 54fec1c | 56821 / 56822 |
| leaderboard | `leaderboard` | `overnight/leaderboard` | `overnight/rewards-gold` (after review) | 56921 / 56922 |

Concurrency: 5 implementers at start (staff, identity, vocab, rewards, native), scaling to 8 when
telemetry allows; 2 independent reviewers (security, integration) per deliverable; one mobile Jest run
and at most one native build at a time (the mobile test harness uses a fixed API port).

## 3. Architecture decision that every lane follows — "nothing new inside `app`"

The verified structure test (`supabase/tests/010_structure.sql`) pins exact counts of tables, policies,
grants, functions and triggers **in schema `app`**. To keep the 209 baseline database tests
byte-identical and green, **no lane creates, alters, grants on, or drops anything in schema `app`, and
no lane edits the four verified migrations, `seed.sql`, or the existing test files.**

- Each domain gets its **own private schema** with its own RLS, grants and tests.
- Where a new feature must write an existing `app` table (profile edit, editorial workflow, job
  leasing, audit), it does so through a **`SECURITY DEFINER` function in the new schema**, owned by
  `postgres`, with `SET search_path = ''`, schema-qualified SQL, bounded inputs, the actor taken from
  `app.current_actor_id()` (never a parameter), and `REVOKE ALL … FROM PUBLIC, anon, authenticated`
  followed by an explicit `GRANT EXECUTE` to exactly the role that needs it. Existing integrity
  triggers in `app` still fire and are relied upon.
- This deviates from Platform-00 doc 04/05, which sketched some tables as `app.*`. It is recorded for
  the owners as a reversible naming choice: objects can be consolidated later in a reviewed migration.

| Schema | Owner lane | Migration block (`supabase/migrations/…`) | pgTAP block (`supabase/tests/…`) |
|---|---|---|---|
| `ops`, `staff` | staff | `2026112401xxxx_*` | `100–119_*` |
| `account` | identity | `2026112402xxxx_*` | `120–139_*` |
| `content` | content | `2026112403xxxx_*` | `140–159_*` |
| `vocab` | vocab | `2026112404xxxx_*` | `160–179_*` |
| `rewards` | rewards | `2026112405xxxx_*` | `180–199_*` |
| `leaderboard` | leaderboard | `2026112406xxxx_*` | `200–219_*` |
| `billing` | entitlements | `2026112407xxxx_*` | `220–239_*` |
| `notify` | notify | `2026112408xxxx_*` | `240–259_*` |

Migration numbers are assigned only by the director (this table). A lane needing a second migration
uses the next number inside its own block.

### Shared platform interface (delivered first by the staff lane, "B1")

```
roles     edu_staff  (NOLOGIN group; login role edu_staff_login,  env EDU_STAFF_DATABASE_URL)
          edu_worker (NOLOGIN group; login role edu_worker_login, env EDU_WORKER_DATABASE_URL)
          edu_api keeps exactly its current privileges; edu_api_login stays a member of edu_api only.
ops.audit_write(p_action text, p_target_kind text, p_target_id uuid,
                p_outcome text, p_details jsonb DEFAULT '{}') RETURNS uuid
          SECURITY DEFINER; actor = app.current_actor_id(); actor_kind derived from session_user's
          role membership (edu_staff → 'staff', edu_worker → 'worker', edu_api → 'user', else 'system').
          EXECUTE: edu_staff, edu_worker. Other schemas' definer functions call it as owner.
staff.actor_has_role(VARIADIC p_roles text[]) RETURNS boolean   -- active row in app.staff_roles
staff.require_role(VARIADIC p_roles text[]) RETURNS uuid        -- raises 42501 unless the actor has one
API       edu_api.staff.deps: require_staff(*roles) dependency, StaffDb (app.state.staff_db),
          all staff routes under /v1/staff/…; a learner token gets 403 on every staff route.
```

Cross-domain conventions:
- **Erasure hook:** every schema that stores per-learner rows ships
  `<schema>.erase_learner(p_user_id uuid) RETURNS jsonb` (definer, EXECUTE granted to nobody); the
  `account` orchestrator calls the hooks that exist.
- **Product day:** "today" is the `America/Port-au-Prince` calendar date, computed in SQL from the
  server clock (`(now() AT TIME ZONE 'America/Port-au-Prince')::date`), never from the device.
- **Feature flags:** every learner-visible new capability has an `EDU_<FEATURE>_ENABLED` setting that
  defaults to **off**; with all flags off the API behaves exactly as `main`.
- **Data API:** every new schema has a test proving it is not reachable through PostgREST and that
  `PUBLIC`, `anon`, `authenticated`, `authenticator` hold nothing in it.

## 4. Dependency graph and phases

```
B1 staff boundary + audit ──┬─► B2 editorial slice + worker leasing
                            ├─► vocab staff workflow          (vocab learner API starts immediately)
                            ├─► entitlements staff grants     (model + read API start without it)
                            └─► content assets (staff writes) (validators/vectors start without it)
identity (profile, onboarding, lifecycle) ── independent; audit hook after B1
rewards (ledger) ── needs only sync ──► leaderboard (only after ledger integrity tests pass + review)
notify + security basics ── independent; delivery worker after B2
native (on mobile-02 base) ── codes against the lane contracts; flags off by default
```

Phase 1 (start): staff·B1, identity, vocab, rewards, native.
Phase 2 (as slots and dependencies clear): staff·B2, content, entitlements, notify, leaderboard.
Phase 3 (only if everything above is reviewed): learning extras (F5), exams/Jude/library contracts.
Each deliverable: implement → self-test on own stack → two independent reviews → fixes → re-test →
director merges into `overnight/integration-2026-11-24` → full suite → push + draft PR.

## 5. Common rules for every implementation agent

1. Work **only** inside your own worktree and only on your own branch. Never `cd` into, edit, check
   out, reset or run commands against `/Volumes/EdupreneursDev/Mon-edupreneur`,
   `worktrees/platform-00`, `social-00-work` or another lane's worktree (reading another lane's files
   for reference is fine). Never use the shared stack on ports 54321/54322.
2. Never: `supabase link`, `supabase db push`, `--linked`, `--db-url`, any hosted service, any real
   e-mail/push/payment/AI call, any real person's data, `git push`, `git rebase`, `--amend` on pushed
   work, `--force`, branch deletion, `rm -rf` outside your worktree, new third-party dependencies
   (Python or JS) without it being named in your brief. The director pushes after review.
3. Owned paths are listed in your brief. Shared files you may touch **only as stated**:
   - `services/api/src/edu_api/main.py`: add your router import and one `include_router` line.
   - `services/api/src/edu_api/config.py`: append your settings in one clearly commented block.
   - `packages/contracts/openapi.json` and `apps/student-native/src/core/api/schema.d.ts`: generated —
     run `make openapi` then `(cd apps/student-native && npm run gen:api)` after any route change
     (CI checks both for freshness). Never hand-edit them.
   - Everything else that exists on `main` (`tests/conftest.py`, `tests/helpers.py`, `seed.sql`, the
     four migrations, `supabase/tests/0*.sql`, `docs/*.md`, `Makefile`, `pyproject.toml`,
     `supabase/config.toml`, CI) is **read-only** unless your brief names it. Put new fixtures in new
     files (`tests/<lane>_fixtures.py`), lane docs in `docs/overnight-2026-11-24/lanes/<lane>.md`.
4. Section 3 is binding: no object in schema `app`; own schema; definer-function pattern; flags off.
5. Tests are part of the work, not an afterthought: pgTAP for structure, grants, RLS, cross-account
   isolation and negative permission cases; pytest integration tests through the real API with real
   local Auth tokens; unit tests for pure logic. Follow the existing style (read `tests/conftest.py`,
   `supabase/tests/020_rls_isolation.sql`). All routes use `error_responses(...)` so the single error
   shape test keeps passing. Never weaken, skip, delete or edit an existing test.
6. Gate before you report (run in your worktree, on your own stack):
   ```sh
   export UV_CACHE_DIR=/Volumes/EdupreneursDev/caches/uv npm_config_cache=/Volumes/EdupreneursDev/caches/npm
   make lint && make typecheck && uv run python scripts/export_openapi.py --check
   make db-reset && make test-db && uv run pytest -q && make test-db
   ```
   Report the real counts. If something is red after two diagnosed fix attempts, stop, leave the
   evidence, and report it as failing — never greenwash.
7. Commit small, descriptive commits on your branch (`git add <explicit paths>`; never `.env`,
   `supabase/signing_keys.json`, logs, binaries, model files). No secrets, tokens, real names or
   copied prototype code/UUIDs anywhere.
8. Product/legal questions are not yours to decide (consent, age, pricing, reward values, ranking
   visibility, retention, rights). Use the synthetic default named in your brief, mark it
   `BLOCKED_BY_OWNER` in your lane doc with the PO-id, and keep the behaviour behind its flag.
9. Do not spawn further agents. Do not start Android/iOS builds or emulators.
10. Final message to the director, plain and honest: status (`TESTED_LOCAL` / `FAILED` / `BLOCKED`),
    commit hashes, files added, migrations, endpoints, exact test commands with pass/fail counts,
    deviations from the brief, known gaps, `BLOCKED_BY_OWNER` items. A compiled stub is not a feature.

## 6. Budgets and stop conditions

- Disk: stop starting builds/stacks below 7 GiB internal free; never delete anything to make room.
- Compute: ≤ 8 implementers + 2 reviewers; reduce if swap grows, tests slow down or errors rise.
- Model usage: parallel agents on the owner's plan; no external paid AI service is called by any code.
- A task that fails twice after diagnosed fixes is recorded `FAILED` with reproduction and parked.
- Stop the lane (not bypass) on: production host detected, secret disclosure, overlapping worktree,
  failing baseline learning tests, anything requiring owner authorisation.

## 7. Decisions that block implementation (`BLOCKED_BY_OWNER`)

| Id | Decision | What is built tonight instead |
|---|---|---|
| PO-04 | Personal data, consent, age band, who consents for minors | No consent tables or rules. Consent is treated as **unknown = not granted** everywhere; lifecycle request/erasure mechanics proven on synthetic users only |
| PO-09 | Reward rules: what earns Gold, amounts, streak day, back-dating | Rule **table** with synthetic placeholder values, flag off; Platform-00's recommended defaults used for tests |
| — | Leaderboard visibility, pseudonyms, cohort consent for minors | Private "my rank" + synthetic opt-in cohort behind flags that default off; no public/global ranking exists in code paths |
| PO-01/05/06/07 | Free vs paid, entitlement scope, checkout, offline lease length | Grant model + staff grants + mock provider only; no paywall; offline lease is a written spec |
| PO-08 | Lesson format v2 contents, mathematics rendering | Validators and test vectors for the recommended minimum + audio reference; no renderer shipped |
| PO-10 | Notification policy, quiet hours | Outbox + dummy local adapter; nothing is sent |
| PO-11, PO-16 | Jude, AI in the content pipeline | Not built tonight beyond contracts, if at all |
| PO-17/18 | Exam and book rights | No exam or book content |
| — | Haitian Creole wording | Draft strings pending native-speaker/educator review |
| — | Staff second factor (MFA) | Designed and documented; **not implemented, not claimed** |

## 8. Director rulings issued during the night

**R-01 (23:35) — new routes and the pinned OpenAPI path set.** The baseline test
`tests/integration/test_isolation_and_operations.py::test_openapi_contract` asserts that the served
OpenAPI document has *exactly* the seven `main` paths. Ruling (supersedes §5.3 on generated files):
- A lane that adds a **new path** registers its router always (404 in the standard error shape when
  its flag is off) but declares it with `include_in_schema=False` behind **one module-level constant**
  (`INCLUDE_IN_SCHEMA = False`) in the router file. `packages/contracts/openapi.json` and
  `apps/student-native/src/core/api/schema.d.ts` therefore stay byte-identical to `main` on lane
  branches, and no baseline test is edited by a lane.
- The lane documents the full contract (JSON examples, error codes) in its lane doc and adds its own
  test proving that, with the constant on, its operations carry the bearer security scheme and only
  the standard error shape.
- A lane that only adds a **method to an existing path** (identity: `PATCH /v1/me`) keeps it in the
  schema and regenerates both generated files.
- At integration the director flips the constants and extends the pinned path set **once**, in a
  single clearly labelled commit — the only edit to a baseline test file tonight, an extension of
  the allowed set and not a weakening — and regenerates both generated files there.

**R-02 (23:35) — no foreign key to the five learning tables.** The baseline suites
`TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed, app.lesson_progress,
app.account_sync_state` without `CASCADE`. A foreign key from any lane table to one of those five
tables makes that TRUNCATE fail and every baseline integration test error. Reference
`app.learner_profiles`, `app.lessons`, `app.lesson_revisions` etc. by FK if needed, but validate
links to the five learning tables in a function or trigger instead.
