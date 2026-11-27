# Morning report — overnight mission 2026-11-24 → 25

Written by the director (Fable). **Final version, 09:00 EST on 2026-11-25.** Nothing was still running
when it was written; §9 is the closing state.

**Read this first.** Nothing was merged into `main`. Nothing was deployed, linked to a hosted
project, or run against real data. Every database was a disposable local stack with synthetic
accounts. **No feature below is production-ready, and none is claimed complete**: the highest status
reached by anything tonight is "tested locally and independently reviewed, with review fixes that
were not re-checked". The account's usage limit stopped every agent three times (23:15–23:37,
23:55–04:30 and 04:51–07:38), so roughly eight of the planned hours did not happen.

Companion files in this folder: [`00-PLAN.md`](00-PLAN.md) (rules, architecture ruling, director
rulings R-01…R-04), [`LEDGER.md`](LEDGER.md), [`INCIDENTS.md`](INCIDENTS.md),
[`CHECKPOINT.md`](CHECKPOINT.md), [`briefs/`](briefs/), [`reviews/`](reviews/), and each lane's own
notes in `lanes/<lane>.md` on its branch (and here for the merged lanes).

## 1. What exists this morning

Eight implementation lanes ran in isolated Git worktrees, each with its own branch and its own
disposable Supabase stack, plus independent reviewers on two further stacks.

| Lane | Branch · draft PR | What it contains | Status |
|---|---|---|---|
| Staff boundary, audit, editorial, roles, worker | `overnight/staff-worker` · #4 | Roles `edu_staff`/`edu_worker`, `ops.audit_write`, staff role checks; editorial workflow through the API (draft → review by a different person → pack → release/rollback); role administration; worker job leasing; security hardening | **REVIEWED** twice. The security fix that concerns `main` was re-checked and is **closed**. The second review's medium finding (an admin could publish content nobody else reviewed) is fixed in `33aa2e2`, not re-checked. MFA: design text only |
| Identity, onboarding state, lifecycle | `overnight/identity-onboarding` · #5 | `PATCH /v1/me`, forward-only onboarding state, deletion/export requests, erasure of one learner on synthetic users | **REVIEWED** (erasure in depth; conventions not examined); high and two medium findings fixed, fixes **not re-checked** |
| Word of the Day | `overnight/word-of-the-day` · #9 | Vocabulary with review workflow, immutable Haiti-date schedule with a 10-minute freeze, `GET /v1/daily-word` with ETag, 15 staff routes | **REVIEWED** (approve with fixes); all three findings fixed in `0d607ec`, not re-checked |
| Gold ledger, streaks, achievements | `overnight/rewards-gold` · #12 | Append-only ledger tied to accepted sync operations, rebuildable balances, flag-guarded hook in the push path, read API, admin reversal/adjustment | **REVIEWED** twice; fix round applied, **not re-checked** |
| Entitlements (no payments) | `overnight/entitlements` · #10 | Grant model, `GET /v1/entitlements`, admin grant/revoke/list, mock provider with exactly-once simulated events; offline lease as a written spec | **REVIEWED**; the medium finding fixed, four low open |
| Notifications + security basics | `overnight/notify-security` · #6 | Outbox with dummy adapter (nothing is sent), preferences, opt-in rate limiter, opt-in JSON logs, a performed dump/restore drill | **REVIEWED** (approve with fixes); one medium and four low findings **open** |
| Content format v2 | `overnight/content-format-v2` · #7 | v2 block and question contracts, 358 shared test vectors, plain-Python validators, deterministic pack manifests, `content` schema with rights gate | **REVIEWED** (approve with fixes, two high findings on contract-only code); highs and mediums fixed in `660a87b`…`d53d0a1`, not re-checked; preconditions for shipping any v2 content are listed in the lane doc |
| Native experience | `overnight/native-experience` (stacked on `mobile-02`) · #8 | Onboarding, tour, Word of the Day card, Gold (pending vs confirmed), leaderboard review screen; all six client flags default off | **REVIEWED** in source; high and medium findings fixed, not re-checked; 14 emulator screenshots at 320 dp with a list of visible layout defects (§2) |
| Leaderboard | `overnight/leaderboard` · #13 | Step 1 only: private rank from the Gold ledger, flag off | **TESTED-LOCAL**, **not reviewed**; cohort list, membership endpoints and staff routes not built |
| Integration | `overnight/integration-2026-11-24` · #11 | Plan, ledger, reviews, and the merge of all eight backend lanes | **TESTED-LOCAL**, see §5 |

Not attempted at all: learning extras (F5), exams, library, Jude, games, social.

## 2. The four features you prioritised

**Word of the Day — TESTED-LOCAL and REVIEWED (approve with fixes); app card reviewed in source only.**
Evidence that exists: an assignment table keyed by (`America/Port-au-Prince` date, locale) that
becomes immutable once the date is today or past and is locked 10 minutes before it opens;
`ensure_assignments` fills future dates from the approved pool (never "day modulo word count") and is
idempotent under concurrency; approved revisions are immutable, the reviewer cannot be the author, a
word without cleared rights cannot be approved or served. The independent reviewer could not change a
published day's word through the API, the staff functions or the worker, and confirmed the day
boundary one second either side of Haiti midnight in winter, summer, on DST change days and in a
no-DST year (simulated clock — **no run was observed across a real midnight**). Lane gate: 910
database assertions, 429 API tests; the reviewer reproduced both counts. The review's medium finding (a raw
database session on the staff login, not reachable over HTTP, could commit a reschedule after the day
had opened) is fixed with a per-day lock and tested with two sessions and a real commit; residual
risk: such a session can make that day answer "no word" until it ends — never a different word.
After the fix: 926 database assertions, 433 API tests (fix not re-checked by a reviewer). Audio is metadata only — no storage, no playback, no TTS. No
view tracking (needs consent). Demo words are synthetic and unreviewed. **Blocked on you:** who may
clear rights; what a learner sees if rights on today's word are withdrawn (today: no word until
restored, never a different word); audio limits; notification hour; Creole wording.

**Gold, rewards, achievements — TESTED-LOCAL and REVIEWED twice; fixes applied, not re-checked.**
Two independent reviewers could not make the ledger award twice (replay, new op id, second device,
other locale, newer revision, repeated completion), forge an award, or break `balance = sum(ledger)`
under a concurrency storm; push and pull responses are identical with the flag off and on; learning
still commits when the rewards schema is broken or slow. After the reviews the lane fixed: a push can
no longer stall on a held lock (waits ≈200 ms, then defers and heals later); the ledger cursor no
longer reveals platform-wide volume; erasure is not undone by a later request; a switched-off rule no
longer loses awards. Lane gate: 961 database assertions; 465 API tests with the flag off and 465 with
it on. On the integration branch the whole suite passes with the rewards flag on. **Decisions for you
(PO-09):** all amounts and caps are placeholders; a lesson completion now earns Gold only after one
server-scored answer in that lesson (placeholder default — without it a script could farm the daily
cap); an honest learner who passes a cap forfeits that Gold for good. `EDU_REWARDS_ENABLED` defaults off.

**Leaderboard — step 1 TESTED-LOCAL, not reviewed; the rest NOT BUILT.** What exists
(`overnight/leaderboard`, draft PR #13): schema `leaderboard` and `GET /v1/leaderboard/me?period=`
behind `EDU_LEADERBOARD_ENABLED` (default off) — the caller's own Gold for the week or all time and,
only if opted into a synthetic cohort, their own rank and the cohort size. It is computed only from
the Gold ledger (staff adjustments excluded, negative sums clamped, ties share a position, staff and
opted-out or erased accounts excluded at refresh and again at every read) and **never returns anyone
else's data; there is no public or global ranking in any code path**. 172 database assertions and 24
API tests. **Not built:** the cohort list (podium data), opt-in/opt-out endpoints, staff routes, any
scheduled refresh — enrolment and refresh are owner-run SQL only, so nothing can reach a real learner.
Known gap: no minimum cohort size, so in a cohort of two your rank reveals the other member's relative
Gold. In the app, the leaderboard screen's production route shows an empty state; the podium exists
only as a design preview with `-TEST` names. **Blocked on you:** who may consent for a minor, whether
real children are ever shown rankings, pseudonym policy.

**Onboarding and product tour — backend REVIEWED (erasure in depth, profile/onboarding sampled); app
REVIEWED in source, never seen on a screen.** Server: forward-only, replay-safe onboarding state and
profile edit, account isolation tested. App: resumable flow (welcome → language → grade → offline
explainer → ready), dismissible/replayable tour, per-account additive local tables, an upgrade test
from a frozen Mobile-02 database that keeps every saved row. 337 Jest tests pass (baseline 157). The
source review's high finding (yesterday's word could stay labelled "Mot du jour" on a mounted screen)
and its five medium findings are fixed with tests; four low ones are open in the lane doc; the fixes
were not re-checked. **Seen on an emulator once:** 14 screenshots at 320 dp (Android API 24) are in
`docs/overnight-2026-11-24/screenshots/native/` on the native branch — onboarding in French and
Creole, tour, Accueil, Profil (real signed-in flow), plus the podium preview and Word/Gold cards
filled from a hand-seeded local cache (labelled as such). Defects visible in them, **not fixed**:
the grade step opens with no class visible and a greyed "Continuer" (title, intro and a "no
connection yet" notice fill the space above two pinned buttons), and that notice appeared while the
API was up; the welcome step shows one of three points above the footer; the French title breaks as
"es-/tu ?"; Accueil greets the learner by the local part of their e-mail. Large text and other
widths were not captured. 103 new
Haitian Creole strings are drafts.

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
| **Integration** (all nine backend lanes incl. leaderboard, and every review-fix round) | **3025 of 3025, PASS** (run twice) | **1754 passed** flags off · **1754 passed** with `EDU_REWARDS_ENABLED=true` | director, `integration-final-4.log` |

Also on integration: lint, mypy strict and the OpenAPI freshness check are clean; the mobile contract
check (`npm run check:api`) and both mobile TypeScript checks pass against the regenerated API types.
**GitHub CI** (the repository's existing workflow) passed on draft PRs #4 to #12 before the last
fix commits were pushed; check the current status of each PR, including #13. Lane numbers that changed after this table was
first written: identity 1007 / 506 at `6913435`, entitlements 925 / 514 at `50a6b52`, staff 593 / 376
at `642ab5c`, vocab 910 / 429 at `a3c48a3`, rewards 961 / 465 at `ce5a64e`, notify 880 / 484 at
`c77f376`, native Jest 337 at `e559e6b`. Logs: `/Volumes/EdupreneursDev/logs/overnight-2026-11-24/`.
**Not run on integration:** the mobile Jest suite. Two director errors are recorded in §7.

## 6. Independent review results

| Review | Verdict | Most important findings | State of fixes |
|---|---|---|---|
| Staff B1 — security | Approve with fixes | **High:** privilege-escalation class (below). Medium: unbounded audit rows from refused requests; audit-details validator is not a privacy filter. Five low | All fixed in `16f4ee1` by the lane; **the fix was not re-checked by a reviewer** |
| Rewards — security | Approve with fixes | Ledger held against every attack. Medium: push can stall while the rewards lock is held elsewhere; product question on Gold without evidence of learning. Three low | High (search_path) fixed; rest in progress |
| Rewards — integration | Approve with fixes | No critical/high. Period-dating rule for the leaderboard; rule versions by acceptance time; app cannot show a pending *amount* | In progress |
| Native — source review | Approve with fixes (safe with flags off) | High: stale "word of the day" label on a mounted screen. Medium: device-clock handling, revalidation rhythm, onboarding sync retry loop, grade step skipped on a new phone, stale streak | Sent to the lane |
| Identity | Approve with fixes — containment of the trigger-disabling window held under every test; erasure may stay in a draft PR, **must not be enabled** | High: a request racing an in-flight erasure left the id behind. Medium: audit row re-stored the id; worker could erase any id; valid token re-creates the profile | High and first two mediums fixed in `d6560ce`, **not re-checked**; profile re-creation open (needs PO-04) |
| Entitlements | Approve with fixes, no critical/high | Medium: staff and purchase idempotency keys shared a namespace. Four low | Medium fixed; low findings open in the lane doc |
| Word of the Day | Approve with fixes | Medium: reschedule can land after the day opened via a raw staff database session. Low: owner TRUNCATE; midnight protection untested | All three fixed in `0d607ec`, **not re-checked** |
| Notify + limiter + logs | Approve with fixes, no critical/high; flags-off path confirmed unchanged | Medium: per-address limit can be dodged behind a proxy. Low: WebSocket handshake logs a query string; expired-token learners behind a shared carrier address get 429 | **Open** (lane stopped by the usage limit) — keep both opt-in flags off |
| Staff — second review (editorial, roles, worker) + re-check | Approve with fixes. **The high finding of the first review is closed**: the original attack was refused as each of the three real database logins | Medium: an admin could rewrite another editor's draft and approve it. Low: control character → 500; duplicate lesson in a pack; no takedown route; last-admin check | Medium and first two lows fixed in `33aa2e2`, **not re-checked**; last two open |
| Content format v2 | Approve with fixes | High: verifier accepted a format-1 pack with a format-2 question kind; release recording trusted a caller-supplied hash and unvalidated bodies. Medium: math accepted markup-shaped text; depth bypass; unchecked totals/duplicates; invisible characters. Not live: no v2 content or activation path exists | Highs and mediums fixed (`d53d0a1`), **not re-checked**; six preconditions before any v2 content ships are in the lane doc, three not done |
| Leaderboard | **not reviewed** | — | — |

**Security finding that also affects `main` (ruling R-03).** With `SET search_path = ''`, PostgreSQL
still resolves unqualified *type* names through a session's temporary schema first. A session able to
run arbitrary SQL on an API database login (SQL injection or a leaked credential) could make a
`SECURITY DEFINER` function run code as its owner. The reviewer reproduced it locally against the new
functions and against the verified baseline function on `main`. Nothing is hosted, so there is no
live exposure. Fix shipped in the staff lane: `REVOKE TEMPORARY ON DATABASE … FROM PUBLIC` plus tests,
and every new function uses `search_path = pg_catalog, pg_temp`. The reproduction steps are kept out
of this public repository (`/Volumes/EdupreneursDev/logs/overnight-2026-11-24/reviews/*-FULL.md`).
An independent reviewer re-ran the original attack against the fixed branch as each of the three real
database logins: refused in every case. **`main` itself is unchanged and still has the weakness until
the staff branch (PR #4) — or at least its TEMP revoke — is merged.** Before hosting: add a deploy-time
assertion that no API role holds TEMP.

## 7. Incidents

- **I-01:** the existing mobile Jest harness hard-codes the shared database container name, so one
  baseline run from the native lane truncated five learning tables on your shared local stack (port
  54322). Lessons, profiles, accounts and schema are intact; the rows were synthetic and are gone.
- **I-02:** all agents shared one scratchpad; one lane executed another lane's gate script by name
  collision. It stopped at a lint error; nothing changed.
- **Director's own errors:** "keep both sides" merge resolutions twice left routers registered more
  than once on the integration branch (found and fixed, gates re-run afterwards); and the director
  did not audit the mobile test harness for hard-coded container names before authorising a run (I-01).
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

## 9. Closing state (09:00 EST)

Nothing is running. Every branch is pushed and matches its local head: integration, staff `33aa2e2`,
identity `6913435`, Word of the Day `58ce157`, rewards `ce5a64e`, leaderboard `472f792`, entitlements
`50a6b52`, notify `c77f376`, content `d53d0a1`, native `9bdc15f`. Draft PRs #4–#13 are open; none is
merged; nothing is deployed. The disposable lane stacks (Docker projects `edu-on-*`) are still
running and can be stopped with `npx supabase stop` in each worktree; the shared stack was not
touched after incident I-01. No emulator, Metro or API process is running.

Not done: notify review fixes (one medium, four low — keep its two opt-in flags off); the R-01
contract flip; mobile Jest on integration; leaderboard steps 2–3 and its review; fixing the layout
defects seen in the screenshots; re-checks of the fix rounds (identity, rewards, native, vocab,
content, staff editorial).

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
5. The onboarding screenshots (native branch, `docs/overnight-2026-11-24/screenshots/native/`), starting with the grade step that looks blocked on a 320 dp screen.

## 12. Recommended next steps, in order

1. Re-check the fixes that no reviewer has seen again (staff security fix if §9 does not show it, identity erasure, rewards, native) and close the open notify findings.
2. Close the open review findings in rewards and native.
3. Merge rewards and Word of the Day into the integration branch; make the single R-01 commit (flip the constants, extend the pinned path set, regenerate `openapi.json` and `schema.d.ts`); run the mobile suite there through a harness that derives its container from `supabase/config.toml` (fixes I-01 permanently).
4. Fix the layout defects seen at 320 dp, then a fresh emulator pass including large text.
5. Review leaderboard step 1; build its cohort view only after the PO-09 and visibility decisions.
6. Worker process and schedules (job leasing, daily word assignment, reward reconcile, notification delivery) — today these are library functions exercised by tests only.
