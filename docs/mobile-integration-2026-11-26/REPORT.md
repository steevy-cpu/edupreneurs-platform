# Mobile integration and learning experience — 2026-11-26

Branch `integration/mobile-learning-2026-11-26`, started from `main` at `6ad3fdb` (after PR #20, #2, #23).
**Draft. Nothing merged into `main`, nothing deployed, no paid feature, no flag changed.**

## 1. Branch hierarchy

```
main 6ad3fdb  (hardened: #20, #2, #23)
 └─ integration/mobile-learning-2026-11-26
     ├─ merge origin/mobile-02                      (PR #3, 54fec1c)        clean
     ├─ merge origin/content-delivery-00            (PR #22, e30c816)       clean
     ├─ merge origin/review/fix-native-harness-and-onboarding (PR #15 stack, 202c12f; contains #8 overnight/native-experience)
     │     3 conflicts, resolved (see §2)
     ├─ Online-only continuity and withdrawn/updated content handling
     ├─ Integration tests against the real API
     └─ Mission D fixes, e2e flows, docs                                    (this PR)
```

The original branches and their draft PRs (#3, #22, #15, #8) were **not modified or force-pushed**. Codex's worktrees: none exist locally;
none were touched.

PR #15 is stacked on #8 (onboarding, tour, Word of the Day, Gold, leaderboard *preview*). The Mission-D onboarding items cannot be
verified without that code, so the whole stack was merged. **Every overnight client flag stays off** (`EXPO_PUBLIC_FF_*`, build-time,
default off); the leaderboard and rewards screens are unreachable in the production build. #19/#12 backend lanes are **not** included.

## 2. Reconciling PR #20 (hardened harness) with PR #15 (older harness fixes)

| File | Conflict | Resolution | Why |
|---|---|---|---|
| `tests/support/localStack.js` | content | **kept main (#20)** | #20 is a strict superset: per-checkout API port, `awaitOwnApi` (a foreign server answering `/ready` is never accepted), `assertPortFree`. #15 had a fixed port 8011 |
| `tests/support/globalSetup.js` | content | **kept main (#20)** | same reason |
| `apps/student-native/README.md` | content | kept #20's text (#15's side was empty there) | — |
| `scripts/e2e-run.sh` | auto-merged | kept both: #15's derive-from-`config.toml` + shared-stack refusal + PID-only kill, on top of #20 | complementary, no overlap |

Audit after the merge: no duplicate `include_router`; one route file per screen and unique `Stack.Screen` names; `tsc` (app and tests),
`check:api`, `ruff`, `export_openapi --check` all clean; **no reference to the old fixed port 8011 remains except inside #20's own test that asserts it is not used.**

## 3. Safe test environment

* The shared `mon-edupreneur` stack (4 containers) was **running the whole time and was never touched** (still up at the end).
* A disposable stack was created from this worktree: `project_id = edu-integration-1126`, ports 55420–55423 (kept out of git with
  `update-index --assume-unchanged supabase/config.toml`; **do not commit it**). Its own `.venv`, `node_modules`, `.env`.
* `make db-reset` ran only after `supabase status` was checked to point at port 55422. The hardened harness printed
  `stack edu-integration-1126, db container supabase_db_edu-integration-1126` before every run; it refuses `mon-edupreneur`.
* The API for the emulator ran on `127.0.0.1:8000` against that stack only (`.env` DB port 55422).

## 4. What was built (Missions B, C, D)

### B — online/offline lessons and continuity
* Both modes preserved: **Lire maintenant** (memory only) and **Télécharger** (transactional). Same reader and quiz screens.
* **Minimal persisted reference**: account schema v5 adds `lesson_refs(lesson_id, locale, title, revision_id, revision, last_opened_at)` —
  public metadata only, **no content, answers or questions** — written **in the same transaction** as an answer or completion, and when a lesson is opened.
  Investigation result: the existing models could not show online activity (Home/Review/Profile iterate saved lessons); this table is the smallest change that can.
* Home: "Continuer en ligne" with the online badge and "Cette leçon se lit en ligne…" for online-only lessons; "Continuer ma leçon" unchanged for downloaded ones.
  A separate "Leçons étudiées en ligne" list. Réviser lists online lessons with honest counts (no invented question total) and keeps
  "Revoir mes erreurs" working online. Profil counts them. No connection → a plain message and **Réessayer**, in the reader and the exercises.
* `removeDownloaded(..., {account})` keeps a reference first, so a removed lesson stays on Home/Review. **No remove button exists yet** (CD-2).
* Account isolation: references live in the per-account database (tested, including on the real stack).

### C — updated and withdrawn content (policy-neutral; see `docs/architecture/content-delivery-00/09-withdrawn-and-updated-content.md`)
States `unverified / current / update_available / not_listed / withdrawn_confirmed`, always with the date of the last check.
**A missing catalog entry is never "current"** (the previous code returned "up to date" — fixed). A network failure is never a withdrawal.
Copies and progress are always kept. Offline phones show their last-check date and say they cannot see newer changes — no claim of
immediate revocation. **Owner decisions W-1…W-5 are open; hard takedown is not distinguishable by the API today (needs W-2).**

### D — device usability (found and fixed on the emulator)
| Item | Result |
|---|---|
| Two actions per row at 320 dp, fr and ht, fonts 1.0 / 1.3 | OK, wraps at word boundaries |
| **Font 2.0: button labels broke mid-word** ("mai/ntenant", "Téléchar/ger") | **Fixed**: actions move below the row at full width when text is very large (`roomy` rule); verified fr + ht |
| **D2 onboarding step opened still scrolled** | **Fixed** (`ScreenFrame resetScrollKey`); verified on device at 2.0 and by a component test |
| **D1 wrapped class labels touched the pill border** | **Fixed** (rounded rectangle when the label wraps); verified at 2.0 |
| **7AF guidance**: after onboarding the path said "Choisis d'abord ta classe et ta matière" | **Fixed**: seed catalog has no 7AF course, so the saved class was ignored. Now "Pas encore de cours pour 7AF…"; class-only → "Choisis ta matière…"; Profil shows the class |
| Réviser intro said "everything works without internet" | Corrected (it now lists online lessons) |
| Connectivity/sync messaging, download and online/offline badges | Verified across flows 02–04, 12–13 (pill "Hors ligne", "Serveur injoignable", "Tout est synchronisé" only when nothing is pending) |

## 5. Test evidence

All commands run in the integration worktree. **Final state, same commit as this PR.**

| Check | Result |
|---|---|
| `tsc --noEmit` (app, tests), `check:api`, `ruff`, `export_openapi --check` | all clean |
| Mobile jest through the hardened harness on the disposable stack | **30 suites, 441 tests, all pass** — components 141, integration 45, experience 94, unit 130, delivery 30, perf 1 |
| of which new in this milestone | **41** = 16 (freshness, continuity, schema upgrades) + 18 (screens) + 6 (real API) + 1 (onboarding scroll reset); a further 23 arrived with PR #22 |
| Backend pgTAP (`supabase test db`) | **215 assertions, PASS** |
| Backend pytest | **148 passed** |
| Android emulator, **API 24**, 480×800 @240 dpi = **320 dp**, 1 GB RAM, release build, real airplane mode, Maestro | **12 / 12 flows pass**: 01–07, 09 (existing), 10–13 (new online journey) |
| Large text on the emulator | 1.0, 1.3, 2.0 × fr, ht: path, reader, review, onboarding |
| Force-quit / restart | flows 03, 08, 12 (`stopApp` + relaunch, offline) |

Required scenarios (mission E):

| Scenario | Evidence |
|---|---|
| Online reading creates no download | integration `online_reading` + screen tests; emulator flow 10 |
| Explicit download works | existing integration + flow 01 |
| Previously downloaded lessons open offline (after restart) | integration `online_reading` ("download, restart offline, remove"), flow 03 |
| Online answers survive connection failure and restart; server scores them | integration (5 answers offline → kill → reboot → sync → **server verdict 4/5**, feed has exactly 6 ops); flows 11–13 |
| Removal preserves progress | integration + unit (service level; **no UI yet**) |
| Two accounts never see each other's data | integration (real Auth), screens, flows 05/19-21 |
| Corrupt / interrupted downloads preserve valid copies | existing `downloads_and_storage` (11 cases) + new fault-injection tests |
| Withdrawal against the real server | integration: course archived → catalog "not_listed", lesson 404 → "withdrawn_confirmed"; copy and pending work kept; work still syncs; republish clears (course restored afterwards) |
| Native navigation fr + ht | flows 09 + scaled/onboarding matrices |

Screenshots: `docs/mobile-integration-2026-11-26/screenshots/` (19 images, from the emulator).

## 6. Known limitations — be explicit

1. **No physical device.** Everything is an API 24 emulator (arm64, software GPU). Real low-RAM phones, real mobile networks and real keyboards are untested.
2. **Onboarding was verified only on a test build with `EXPO_PUBLIC_FF_ONBOARDING=1`** (never committed). The production build has it off. The onboarding sign-in at font 2.0 with the keyboard open hides the password field (existing sign-in behaviour, not changed here).
3. **No "remove download" button, storage screen, or background update checks** (roadmap CD-2). Removal exists as a tested service operation.
4. **API has no withdrawal reason and no integrity hash/ETag** → a routine retirement and a rights takedown look the same; downloads are validated structurally only.
5. Creole strings added here (≈ 30) are **drafts** and need educator review; the ≈ 106 earlier draft strings are still unreviewed.
6. Leaderboard, rewards, Word of the Day, tour code is merged **but unreachable (flags off)**; its overnight native code "was never re-reviewed" (correction plan 3-6) and is still not independently reviewed.
7. **Build hazard found:** Gradle does not treat `EXPO_PUBLIC_*` as task inputs, so a "flags-off" build made right after a flags-on build silently kept the flags-on JS bundle (caught because flow 01 landed on onboarding). Delete `android/app/build/generated/assets` when switching flags. Release builds for the owner must be made from a clean tree.
8. Online-only answers sync normally, but Réviser/Profil cannot show a question total for lessons that are not downloaded (by design).
9. After a lesson **update**, new questions start with no answers (pre-existing; question ids are per revision).
10. The emulator airplane-mode journey proves the app's behaviour; it does not measure battery, data use, or performance on weak hardware.

## 7. Recommendation — when can #3 and #22 merge?

* **This PR supersedes the need to merge #3, #22 and #15 separately.** Merging it brings all of them with the hardened harness already reconciled. If the owner prefers the original order: #3 → #22 → #15 stack, resolving the same three files as §2 (take main's helpers).
* **Safe to merge into `main` now, flags off:** #3 (Mobile-02) and #22 (Content-Delivery-00) — both are covered by the 30-suite run and the 12-flow device journey, and add no backend change. Condition: owner review of the Creole drafts is **not** required to merge (they ship behind the existing language switch), but **is** required before telling Creole-speaking students about the new buttons.
* **Not yet:** the overnight native stack (#8/#15) should wait for the independent source review (3-6) and a physical-device pass (3-8) before any flag is enabled; merging it with flags off is acceptable only if the owner accepts unreviewed dormant code in the bundle. A safer alternative is to merge #3 + #22 first and keep #8/#15 for a later PR.
* Before any release build: physical low-RAM Android pass; decide W-1…W-5; keep every flag off.

## 8. Changed files (summary vs `main`)

* App: `core/learning/{contentAccess,overview,actions}.ts`, `core/db/{accountStore,contentStore}.ts`, `core/i18n/strings.ts`, screens `app/{home,learn,review,profile,onboarding}.tsx`, `app/lesson/[id].tsx`, `app/quiz/[id].tsx`, design `Chrome, Forms, Learning`, `platform/services.ts`, `ui/AppContext.tsx`.
* Tests: `tests/delivery/*` (2 files), `tests/components/{onlineReading,continuity}.test.tsx`, `tests/integration/online_reading.test.ts`, harness stand-ins; `jest.delivery.config.js` (stack-free subset).
* Device: `e2e/10–13`, `e2e/helpers/*`, `scripts/e2e-run.sh` (new flows).
* Docs: `docs/architecture/content-delivery-00/*` (incl. new `09`), this report.
