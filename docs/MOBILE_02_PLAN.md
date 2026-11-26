# Mobile-02 — integration plan and data dependencies

Written before any code change (branch `mobile-02`, based on `design-00`).
Baseline on this branch before changes: 209 database tests, 144 API tests,
128 mobile tests, all passing.

## Rule for this milestone

The design layer changes **how things look and where they are**. It does not
change **what is stored, sent or scored**. These files are not edited:

| Area | Files left untouched |
|---|---|
| Local databases | `src/core/db/accountStore.ts`, `contentStore.ts`, `driver.ts`, `src/platform/expoSqlite.ts` |
| Sync engine | `src/core/sync/engine.ts` |
| Sign-in and session | `src/core/auth/*`, `src/platform/secureTokenStore.ts` |
| API client | `src/core/api/*` |
| Answer / download logic | `src/core/learning/actions.ts` (`answerQuestion`, `completeLesson`, `saveLessonOffline`, `refreshCatalog`) |
| Backend | everything outside `apps/student-native` |

## Navigation

| Before (Release-01) | After (Mobile-02) |
|---|---|
| `/home` — list of buttons | `/home` — **Accueil** tab |
| `/select` + `/lessons` | `/learn` — **Apprendre** tab (grade, subject and learning path on one screen) |
| — | `/review` — **Réviser** tab |
| `/progress` | `/profile` — **Profil** tab (progress, sync, language, account) |
| `/lesson/[id]`, `/quiz/[id]` | same routes, redesigned, full-screen with a back button |
| `/sign-in` | same route, restyled |

The four tabs are the Design-00 `TabBar`. The navigator stays the existing
Expo Router stack (no new navigation dependency).

## Where each screen's data comes from

Every value shown is read from SQLite on the phone. Nothing is invented.

| Screen | Shows | Source |
|---|---|---|
| Accueil | Continue card | Preference `last_lesson_id` (new, account-scoped, written when a lesson is opened) → otherwise the first saved lesson not yet finished |
| | Progress bar on the card | Questions answered / questions in the saved lesson (`question_progress`) |
| | Pending-work row | `outbox` count (`syncSummary`) |
| | Downloaded lessons | `ContentStore.listSavedLessons` |
| Apprendre | Grades, subjects, units, lessons | Cached catalog (`ContentStore.getCatalog`), refreshed from the API when reachable |
| | Finished / to do | `lesson_progress` (lesson level only — step-level completion is not stored) |
| | Downloaded / to download | `ContentStore.listSavedLessons` |
| Leçon | Title, version, blocks | Saved lesson snapshot. Only the block types the schema has today: heading, paragraph, example, callout |
| | Subject, unit | Looked up in the cached catalog; hidden if the catalog does not list the lesson |
| Exercices | Questions, choices, explanation | Saved lesson snapshot |
| | Feedback, "saved on this phone" | Shown only after `answerQuestion()` resolves (SQLite commit) |
| Réviser | Lessons with exercises, answered / correct / to retry | `question_progress` for saved lessons |
| Profil | Lessons finished, correct answers, per-lesson detail | `lesson_progress`, `question_progress` |
| | Sync state | `syncSummary` + the last sync report held in memory |
| | Language, sign-out | Existing `setLocale`, existing sign-out warning |

## What Design-00 showed that the app cannot supply — and what happens to it

| Preview element | Decision |
|---|---|
| Lesson objective, "key ideas", hint card (Jude) | Hidden. Not in the lesson schema |
| Four-step strip (Comprendre → Réviser) and per-step completion | Hidden. The path shows one node per **lesson** |
| Weekly goal | Removed. No goal is stored |
| "Lesson 2 of 5 · 40 %" on the Continue card | Replaced by real "questions answered" for that lesson |
| "3 questions to review" | Real count of questions whose last answer was wrong; hidden when zero |
| "Connecté / Hors ligne" pill | Only "Hors ligne" is shown, and only after a sync attempt could not reach the server. The app has no network sensor and I am not adding one |
| Dark mode | Stays off: the app is fixed to the light palette |

## Strings

One catalog (`src/core/i18n/strings.ts`) for the whole app. Every existing key
is kept. Design-00 keys used by real screens are merged in; where both had the
same key with different wording, the existing app wording wins (the UI test
flows and reports quote it). Keys used only by the fixture previews move to
`src/design/preview/`.

## Stages (one commit each)

1. This plan.
2. Shared foundation: unified strings, light theme at the root, small component extensions.
3. Read-only data helpers for the screens (`src/core/learning/overview.ts`) with tests.
4. Screens and navigation.
5. Preview boundary: fixtures excluded from production bundles.
6. Tests and UI flows; native validation; measurements; report.
