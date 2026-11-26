# 8. Testing — evidence and limitations

## What was run (2026-11-26, branch `content-delivery-00`)

```
cd apps/student-native
npx tsc --noEmit                         # app           → 0 errors
npx tsc --noEmit -p tests/tsconfig.json  # tests         → 0 errors
npx jest -c jest.delivery.config.js      # 6 suites, 141 tests, all passing
```

`jest.delivery.config.js` = the repo's jest config **without** `globalSetup/globalTeardown`. It runs:

| Suite | Tests | Needs |
|---|---|---|
| `tests/delivery/contentAccess.test.ts` (new) | 14 | real SQLite (Node built-in), fake API |
| `tests/components/onlineReading.test.tsx` (new) | 9 | real screens + real SQLite, fake API |
| `tests/components/screens.test.tsx` (existing; one assertion updated, see below) | 19 | real screens + real SQLite |
| `tests/unit/*` (existing: design tokens 76, core 17, overview 6) | 99 | nothing |

Total 141 = 23 new + 118 existing. The existing component suite passed with **one deliberate change**: the Apprendre test used to assert that a
not-downloaded lesson has *no* open control; that rule is exactly what this feature replaces, so it now asserts "Lire maintenant" /
"Télécharger" and that pressing the row opens `/lesson/<id>?mode=online`.

## Why the stack-based suites were not run

`tests/integration/*` use `tests/support/globalSetup.js` and the local API + Supabase. On `mobile-02` that harness is the one the audit
found unsafe (S4: hard-coded shared container, truncates learning tables, pauses the shared gateway, pattern-kills APIs). The owner's shared
`mon-edupreneur` stack was running during this session, so **those suites were not run, deliberately.** To run them, first bring PR #20's
harness (or `review/fix-native-harness-and-onboarding`) into the base, on an isolated stack.

## Requirement → evidence

| Requirement (brief §13) | Evidence | Status |
|---|---|---|
| Online lesson loads without being permanently downloaded | service test (nothing in `saved_lessons`), screen test (no saved row, no "continue" preference) | ✅ tested |
| Offline-only lesson fails gracefully with no saved copy | service + screen tests (message, Retry, no invented content) | ✅ tested |
| Saved copy offered when the network fails | service + screen tests (`Ouvrir la version enregistrée`) | ✅ tested |
| Downloaded lessons work after force-quit and restart | service test closes every DB handle and reopens the files, no network | ⚠️ simulated (connections closed/reopened; **not** a real process kill or phone) |
| Network loss during download leaves the previous content intact | truncated/offline + injected `SQLITE_FULL` on write; old revision and its questions intact; later update succeeds | ✅ tested |
| Corrupted/truncated content rejected | 5 corruptions + HTML body; nothing cached or saved | ✅ tested (structural validation; **no hash check — API provides none yet**) |
| Answers remain durable when connectivity disappears | answer after reading online with API switched off → attempt + pending op, survives reopen | ✅ tested |
| Account switching never reveals private records | second account sees no pending ops, progress, completion, or preferences | ✅ tested |
| Download deletion does not remove progress | remove → attempts, pending ops, completion intact | ✅ tested (service level) |
| French and Haitian Creole layouts at 320 dp | — | ❌ **not tested** (no emulator run). Creole labels only checked to render. |
| Large text usable | — | ❌ **not tested**. The new catalog row stacks two buttons; at font scale 2.0 this needs an emulator check (known prior defects D1/D2). |
| All existing learning/sync tests pass | component + unit suites pass; **integration suites not run** (see above) | ⚠️ partial |

## Known limitations of this slice

* No emulator or physical-device run; no screenshots.
* Creole strings are drafts.
* Connectivity is not predicted: "Internet required" appears after an attempt, not before.
* `removeDownloaded` and `checkForUpdates` have no UI yet.
* Review/Home ignore online-only lessons (ADR-3).
* Pre-existing React `act()` warnings from `screens.test.tsx` (sign-out test) appear in output; not introduced here.
* The server contract is unchanged, so there is no integrity hash and no ETag; those are CD-3.
