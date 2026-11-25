# Morning report — overnight mission 2026-11-24 → 25

Written by the director (Fable) at ≈04:50 EST and updated until the session ended; the last section
says exactly where things stood at the final update.

**Read this first.** Nothing was merged into `main`. Nothing was deployed, linked to a hosted
project, or run against real data. Every database was a disposable local stack with synthetic
accounts. **No feature below is production-ready, and none is claimed complete**: the highest status
reached by anything tonight is "tested locally and independently reviewed, with review fixes still
open". The session was stopped twice by the account's usage limit (23:15–23:37 and 23:55–04:30), so
about five of the planned hours did not happen.

Companion files in this folder: [`00-PLAN.md`](00-PLAN.md) (rules, architecture ruling, director
rulings R-01…R-04), [`LEDGER.md`](LEDGER.md), [`INCIDENTS.md`](INCIDENTS.md),
[`CHECKPOINT.md`](CHECKPOINT.md), [`briefs/`](briefs/), [`reviews/`](reviews/), and each lane's own
notes in `lanes/<lane>.md` on its branch (and here for the merged lanes).

## 1. What exists this morning

Eight implementation lanes ran in isolated Git worktrees, each with its own branch and its own
disposable Supabase stack, plus independent reviewers on two further stacks.

| Lane | Branch | What it contains | Status |
|---|---|---|---|
| Staff boundary, audit, editorial, roles | `overnight/staff-worker` | Roles `edu_staff`/`edu_worker`, `ops.audit_write`, staff role checks, `/v1/staff/me`; editorial workflow through the API (draft → review by a different person → pack → release/rollback); role administration; security-review fixes | B1: **REVIEWED** (security; fixes applied, fix not re-checked). Editorial slice and role admin: **TESTED-LOCAL**, not reviewed. Worker job leasing: see §9 |
| Identity, onboarding state, lifecycle | `overnight/identity-onboarding` | `PATCH /v1/me`, forward-only onboarding state, deletion/export requests, erasure of one learner on synthetic users | **TESTED-LOCAL**; review interrupted (see §6) |
| Word of the Day | `overnight/word-of-the-day` | Vocabulary with review workflow, immutable Haiti-date schedule, `GET /v1/daily-word` with ETag, staff routes | **TESTED-LOCAL**, not reviewed; see §9 for merge state |
| Gold ledger, streaks, achievements | `overnight/rewards-gold` | Append-only ledger tied to accepted sync operations, rebuildable balances, flag-guarded hook in the push path, read API, admin reversal/adjustment | **REVIEWED** twice (approve with fixes); fix round partly done, see §6 |
| Entitlements (no payments) | `overnight/entitlements` | Grant model, `GET /v1/entitlements`, admin grant/revoke/list, mock provider with exactly-once simulated events; offline lease as a written spec | **TESTED-LOCAL**; review interrupted |
| Notifications + security basics | `overnight/notify-security` | Outbox with dummy adapter (nothing is sent), preferences, opt-in rate limiter, opt-in JSON logs, a performed dump/restore drill | **TESTED-LOCAL**, not reviewed |
| Content format v2 | `overnight/content-format-v2` | v2 block and question contracts, 358 shared test vectors, plain-Python validators, deterministic pack manifests, `content` schema with rights gate | **TESTED-LOCAL**, not reviewed |
| Native experience | `overnight/native-experience` (stacked on `mobile-02`) | Onboarding, tour, Word of the Day card, Gold (pending vs confirmed), leaderboard review screen; all six client flags default off | **REVIEWED** (approve with fixes; safe with flags off); **never run on an emulator or phone** |
| Leaderboard | — | — | **NOT STARTED** |
| Integration | `overnight/integration-2026-11-24` | Plan, ledger, reviews, and the merge of staff + identity + entitlements + notify + content | see §5 |

Not attempted at all: learning extras (F5), exams, library, Jude, games, social.

## 2. The four features you prioritised

**Word of the Day — backend TESTED-LOCAL, not independently reviewed; app card reviewed in source only.**
Evidence that exists: an assignment table keyed by (`America/Port-au-Prince` date, locale) that
becomes immutable once the date is today or past; `ensure_assignments` fills future dates from the
approved pool (never "day modulo word count") and is idempotent under concurrency (8 connections);
approved revisions are immutable, the reviewer cannot be the author, a word without cleared rights
cannot be approved or served; tests for Haiti midnight, DST transitions (2017, 2015) and a no-DST
year, missing translation (French fallback flagged), a word edited after assignment, rejected / draft
/ future words invisible, response size (worst case 1,338 bytes), audio size cap. Lane gate after its
second turn: 732 database assertions, 283 API tests (lane's own report). Audio is metadata only — no
storage, no playback, no TTS. No view tracking (needs consent). All demo words are synthetic and
unreviewed. **Blocked on you:** who may clear rights, audio limits, notification hour, Creole wording.

**Gold, rewards, achievements — TESTED-LOCAL and REVIEWED twice; fix round open.**
Two independent reviewers could not make the ledger award twice (replay, new op id, second device,
other locale, newer revision, repeated completion), forge an award, or break `balance = sum(ledger)`
under a concurrency storm; the 144 baseline API tests pass with the rewards flag off and on; push and
pull responses are identical with the flag off and on; learning still commits when the rewards schema
is broken or slow. Open at the time of writing: a stuck reward step can stall a push (medium, fix in
progress), the period-dating rule the leaderboard needs, and a **product decision**: a bare "lesson
completed" earns Gold with no answer required, so a script could reach the daily cap every day.
All amounts are synthetic placeholders (**PO-09**). The flag `EDU_REWARDS_ENABLED` defaults off.

**Leaderboard — NOT STARTED.** It was deliberately gated behind the Gold ledger's reviews, and the
usage-limit stops consumed the time. What exists: the specification (`briefs/leaderboard.md`: private
"my rank", opt-in synthetic class cohort with server-assigned pseudonyms, no public or global ranking
in any code path) and, in the app, a review screen behind a default-off flag whose production route
shows an empty state. **Blocked on you in any case:** visibility and consent rules for minors.

**Onboarding and product tour — backend TESTED-LOCAL (review interrupted); app REVIEWED in source,
never seen on a screen.** Server: forward-only, replay-safe onboarding state and profile edit, account
isolation tested. App: resumable flow (welcome → language → grade → offline explainer → ready),
dismissible/replayable tour, per-account additive local tables, an upgrade test from a frozen
Mobile-02 database that keeps every saved row. 319 Jest tests pass (baseline 157). Reviewer findings
to fix before the matching flags are switched on are listed in `reviews/native-review.md` (one high:
yesterday's word can stay labelled "Mot du jour" while the home screen stays mounted). **No screenshot
exists**: layout at 320 dp and large text is unverified. 102 new Haitian Creole strings are drafts.

## 3. Architecture decisions made tonight (please confirm or overrule)

1. **Nothing new inside schema `app`.** The verified structure test pins exact counts in `app`, so
   every new domain lives in its own private schema (`ops`, `staff`, `account`, `content`, `vocab`,
   `rewards`, `billing`, `notify`) and writes existing `app` tables only through `SECURITY DEFINER`
   functions. The 209 baseline database tests are byte-identical and green everywhere. This deviates
   from Platform-00, which sketched some tables as `app.*`; it is reversible.
2. **R-01 — new routes are hidden from the generated contract.** A baseline test pins the exact set
   of seven OpenAPI paths. Each lane keeps its new paths out of the schema behind one
   `INCLUDE_IN_SCHEMA = False` constant; `PATCH /v1/me` (new method on an existing path) is published.
   **Not done:** the planned single commit that flips the constants and extends the pinned set — the
   lanes' own tests assert the routes are hidden, so it needs a careful pass. It is follow-up #1.
3. **R-02 — no foreign key to the five learning tables** (baseline suites truncate them without CASCADE).
4. **R-03 — see §6, security finding.** 5. **R-04 — private scratch folder per lane** (incident I-02).

## 4. Migrations and APIs added

All additive, all in new schemas, run only on disposable local databases.

| Lane | Migrations (`supabase/migrations/`) |
|---|---|
| staff | `20261124010000_platform_roles_ops_staff`, `…010100_access_denial_window`, `…0102xx/0103xx` editorial and role admin, `…010400_revoke_temp_and_search_path` |
| identity | `20261124020100_account_profile`, `…020200_account_onboarding`, `…020300_account_lifecycle`, `…020400_account_b1_wiring` |
| content | `20261124030100_content_assets_and_pack_manifests` |
| vocab | `20261124040100_vocab_schema`, `…040200_vocab_functions` (+ staff wiring in its second turn) |
| rewards | `20261124050100_rewards_schema`, `…050200_rewards_functions`, `…050300_rewards_staff_worker` |
| billing | `20261124070100_billing_schema`, `…070200_billing_functions` |
| notify | `20261124080100_notify_outbox`, `…080200_notify_worker_grants` |

New endpoints (every learner-visible one is behind a server flag that defaults **off** and then
answers the standard 404): `PATCH /v1/me`; `GET/PUT /v1/me/onboarding`; `GET /v1/me/account-requests`,
`POST/DELETE /v1/me/deletion-request`, `POST /v1/me/export`; `GET /v1/daily-word`;
`GET /v1/rewards/summary`, `GET /v1/rewards/ledger`; `GET /v1/entitlements`;
`GET/PUT /v1/me/notification-preferences`, `GET /v1/notifications`; staff: `/v1/staff/me`, editorial
and role routes, `/v1/staff/billing/*`, `/v1/staff/vocab/*`. Exact JSON contracts are in each lane doc.

## 5. Test results and exact commands

Every lane ran this gate on its own stack; the director ran it on the integration stack:

```sh
export UV_CACHE_DIR=/Volumes/EdupreneursDev/caches/uv
make lint && make typecheck && uv run python scripts/export_openapi.py --check
make db-reset && make test-db && uv run pytest -q && make test-db
```

| Where | Database tests (pgTAP) | API tests (pytest) | Source of the number |
|---|---|---|---|
| Baseline `main`, isolated stack | PASS (209) ×2 | 144 passed | director, `baseline-integration-*.log` |
| staff @ 16f4ee1 | 532 | 356 | lane report |
| identity @ 114ab62 | 728 | 339 | lane report |
| content @ d1f5bf7 | 600 | 788 | lane report |
| vocab (second turn) | 732 | 283 | lane report |
| rewards @ 598fb1a | 721 | 310 (also 310 with the flag on) | lane report; reviewers reproduced 482 / 236 at 53ec9aa |
| entitlements @ 43ca9b9 | 745 | 367 | lane report |
| notify @ d960cd3 | 641 | 318 | lane report |
| native @ 779657f | — | Jest 319 passed (baseline 157) | lane report |
| **Integration** (staff + identity + entitlements + notify + content) | **1830 of 1830, PASS** | **1327 of 1328** | director, `integration-6lanes-b.log`, `integration-6lanes-pytest.log` |

The one failing integration test is `test_billing_staff_api.py::test_learners_and_non_admin_staff_
are_refused_and_the_refusal_is_audited`: it counts refused-request audit rows, which the staff
security fixes now bound per actor per minute. The fix was requested from the entitlements lane.
Logs are in `/Volumes/EdupreneursDev/logs/overnight-2026-11-24/`. **Not run on integration:** the
mobile Jest suite, the mobile TypeScript check against the regenerated `schema.d.ts`, GitHub CI.

## 6. Independent review results

| Review | Verdict | Most important findings | State of fixes |
|---|---|---|---|
| Staff B1 — security | Approve with fixes | **High:** privilege-escalation class (below). Medium: unbounded audit rows from refused requests; audit-details validator is not a privacy filter. Five low | All fixed in `16f4ee1` by the lane; **the fix was not re-checked by a reviewer** |
| Rewards — security | Approve with fixes | Ledger held against every attack. Medium: push can stall while the rewards lock is held elsewhere; product question on Gold without evidence of learning. Three low | High (search_path) fixed; rest in progress |
| Rewards — integration | Approve with fixes | No critical/high. Period-dating rule for the leaderboard; rule versions by acceptance time; app cannot show a pending *amount* | In progress |
| Native — source review | Approve with fixes (safe with flags off) | High: stale "word of the day" label on a mounted screen. Medium: device-clock handling, revalidation rhythm, onboarding sync retry loop, grade step skipped on a new phone, stale streak | Sent to the lane |
| Identity | interrupted by the usage limit | partial notes in the private logs folder | — |
| Entitlements | interrupted by the usage limit | interim public report committed | — |
| Notify, content, vocab, staff editorial/roles | **not reviewed** | — | — |

**Security finding that also affects `main` (ruling R-03).** With `SET search_path = ''`, PostgreSQL
still resolves unqualified *type* names through a session's temporary schema first. A session able to
run arbitrary SQL on an API database login (SQL injection or a leaked credential) could make a
`SECURITY DEFINER` function run code as its owner. The reviewer reproduced it locally against the new
functions and against the verified baseline function on `main`. Nothing is hosted, so there is no
live exposure. Fix shipped in the staff lane: `REVOKE TEMPORARY ON DATABASE … FROM PUBLIC` plus tests,
and every new function uses `search_path = pg_catalog, pg_temp`. The reproduction steps are kept out
of this public repository (`/Volumes/EdupreneursDev/logs/overnight-2026-11-24/reviews/*-FULL.md`).
**`main` itself is unchanged and still has the weakness until the staff branch is merged.**

## 7. Incidents

- **I-01:** the existing mobile Jest harness hard-codes the shared database container name, so one
  baseline run from the native lane truncated five learning tables on your shared local stack (port
  54322). Lessons, profiles, accounts and schema are intact; the rows were synthetic and are gone.
- **I-02:** all agents shared one scratchpad; one lane executed another lane's gate script by name
  collision. It stopped at a lint error; nothing changed.
- **Director's own error:** a "keep both sides" merge resolution left the staff router registered
  twice on the integration branch; found and fixed (`fix(integration): drop the superseded…`).
Details and containment: [`INCIDENTS.md`](INCIDENTS.md).

## 8. Performance and resources

- Rewards hook on push: 50 operations 26 ms → 57 ms typical (reviewer, medians of 15 runs).
- Daily word response: ≈520 bytes typical, 1,338 bytes worst case accepted by the database.
- Pack sizes (tiny synthetic lessons): seed pack 4,338 bytes uncompressed, ≈1.4 KB gzip estimate.
- Restore drill on the notify lane's disposable database: dump ≈0.2 s, restore ≈1.5 s, 57 tables /
  284 rows and policies/grants identical. Same instance, tiny data — not a disaster-recovery test.
- Native production JS bundle with flags off: 2,885,744 bytes (Mobile-02 report: 2,778,788).
- Machine: internal disk 13 GiB free at start, 12 GiB at 04:30 (floor 7); dev volume 169 GiB free;
  load 2.5–4.8 on 8 cores; no emulator or native build was started.

## 9. State at the final update

See the last section of [`CHECKPOINT.md`](CHECKPOINT.md) for branch heads, what was pushed, which
pull requests exist, and what each lane had in flight when the session ended.

## 10. Decisions only you can make (`BLOCKED_BY_OWNER`)

| Id | Decision | Why it matters now |
|---|---|---|
| PO-04 + legal | Personal data, consent, age band, who consents for a minor; retention of deletion requests and audit history | Erasure and export exist only as mechanics on synthetic users; consent is treated as unknown = not granted everywhere |
| — | Is the erasure mechanism acceptable? It disables triggers for one session inside one function, relying on a local Supabase permission that is **unverified on a hosted project** | The portable alternative is a reviewed change to the verified append-only trigger function |
| PO-09 | Gold amounts, caps, streak day, back-dating; **must a lesson completion show evidence of learning to earn Gold?** | All values are placeholders; the last question decides whether the leaderboard can be farmed |
| — | Leaderboard visibility, pseudonyms, cohort consent for minors | Nothing is built; nothing may be shown to real children without this |
| PO-01/05/06/07 | Free or paid, entitlement scope, checkout, offline lease length | Grant model only; no paywall exists; lease is a spec |
| PO-08 | What lesson format v2 contains and how mathematics is drawn | Contracts and vectors use the recommended minimum |
| PO-10 | Notification policy and quiet hours | Outbox only; 21:00–06:00 is a placeholder |
| — | Haitian Creole wording (102 app strings, demo vocabulary, vectors) | Needs a native speaker / educator |
| — | Staff second factor | Designed, **not implemented** |
| — | Confirm the "own schema per domain" ruling and the R-01 contract approach | Both shape every later migration |

## 11. Top five for human review today

1. The security finding in §6 and its fix in `overnight/staff-worker` (`…010400_revoke_temp_and_search_path.sql`) — it concerns `main`.
2. `account.erase_learner` in `overnight/identity-onboarding` (`…020300_account_lifecycle.sql`) — the most powerful function written tonight, with its review interrupted.
3. The rewards ledger's uniqueness design and the push hook (`overnight/rewards-gold`), with both review reports.
4. The Word of the Day schedule immutability and freeze rule (`overnight/word-of-the-day`), not yet reviewed by anyone.
5. The native onboarding flow on a real small Android phone — nobody has seen it rendered.

## 12. Recommended next steps, in order

1. Finish the interrupted reviews (identity, entitlements) and run the missing ones (notify, content, vocab, staff editorial/roles); re-check the staff security fix.
2. Close the open review findings in rewards and native.
3. Merge rewards and Word of the Day into the integration branch; make the single R-01 commit (flip the constants, extend the pinned path set, regenerate `openapi.json` and `schema.d.ts`); run the mobile suite there through a harness that derives its container from `supabase/config.toml` (fixes I-01 permanently).
4. Emulator pass on the seven screens the native lane listed, one build at a time, with screenshots.
5. Only then start the leaderboard lane from `briefs/leaderboard.md`, after the PO-09 and visibility decisions.
6. Worker process and schedules (job leasing, daily word assignment, reward reconcile, notification delivery) — today these are library functions exercised by tests only.
