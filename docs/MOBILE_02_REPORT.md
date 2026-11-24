# Mobile-02 — Design-00 integrated into the real app

Date: 2026-11-24. Branch `mobile-02` (based on `design-00`). Draft pull request into `main`; not merged.

Everything below was run on this branch. Where something was **not** tested it says so.
All results come from an **Android emulator and an iPhone simulator on a Mac**. None of
them is evidence about a physical phone.

## 1. What changed

The student app now uses the Design-00 design system on every screen, with real data.

| Destination | Route | What it shows (all read from SQLite on the phone) |
|---|---|---|
| **Accueil** | `/home` | "Continue" card for the lesson opened last, how many of its exercises are done, a row when work is waiting to sync, the downloaded lessons |
| **Apprendre** | `/learn` | Grade and subject chips, then the path: one node per lesson with "Terminé / Étape suivante / À faire / À télécharger" and a download button |
| **Réviser** | `/review` | Saved lessons that have exercises, with answered / correct counts, "Refaire les exercices" and, when there are wrong answers, "Revoir mes erreurs (n)" |
| **Profil** | `/profile` | Account e-mail, chosen grade and subject, progress, sync state, language, sign-out |
| Leçon | `/lesson/[id]` | New header, content blocks, worked example, pinned "Faire les exercices" |
| Exercices | `/quiz/[id]` | Answer cards, feedback panel, provisional result |
| Connexion | `/sign-in` | Restyled, same behaviour |

`/select`, `/lessons` and `/progress` are gone: their functions moved into Apprendre and Profil.
The fourth tab is **Profil** (French) / **Pwofil** (Haitian Creole).

### What was deliberately not shown

Design-00 previews contained things the app has no data for. They are hidden, not faked:
lesson objective, "key ideas", the Jude hint card, the four-step strip and per-step
completion, the weekly goal, "lesson 2 of 5 · 40 %". Dark mode stays off (the app is fixed
to the light palette). There is no "Connecté" pill: the app has no network sensor, so it only
shows **Hors ligne** after a sync attempt has actually failed to reach the server.

### What was not touched

`git diff main` is empty for: the local databases (`src/core/db`), the sync engine
(`src/core/sync`), sign-in and session (`src/core/auth`, `src/platform`), the API client
(`src/core/api`), `actions.ts` (`answerQuestion`, `completeLesson`, `saveLessonOffline`),
and everything outside the mobile app (API, database, contracts). The only root-level change is one lint exemption in `pyproject.toml` for the device-testing helper script. `app.json` is unchanged:
no native change, no new permission, same bundle identifiers.

One small addition to stored data: an account-scoped preference `last_lesson_id`,
written when a lesson is opened, so "Continue" can find it. It uses the existing
preferences table; no schema change.

## 2. Acceptance: the nine steps

Run with Maestro on **standalone release builds** (JavaScript inside the app, Metro not
running). Flows: `apps/student-native/e2e/`; runner: `scripts/e2e-run.sh`.

| # | Step | Android 7.0 release, **airplane mode** | iPhone 17 simulator release, backend stopped |
|---|---|---|---|
| 1 | Sign in | Pass | Pass |
| 2 | Choose grade and subject | Pass | Pass |
| 3 | Navigate the new learning path | Pass | Pass |
| 4 | Open a downloaded lesson | Pass | Pass |
| 5 | Complete an exercise offline | Pass (5 questions) | Pass (5 questions) |
| 6 | Force-quit and reopen with no internet | Pass | Pass |
| 7 | Find saved progress and pending work under Profil | Pass ("5 action(s) en attente", "En attente de synchronisation (5)", never "Tout est synchronisé") | Pass |
| 8 | Reconnect and synchronise exactly once | Pass | Pass |
| 9 | Switch accounts without exposing the other student's progress | Pass (student B sees 0 of 5, no pending work) | Pass |

Also passed on both: sign-out with unsynchronised work (warning shown, "keep my work"
keeps it, it uploads after signing back in), and the Haitian Creole interface with the
Creole lesson.

**Exactly once, checked on the server** after each full run (5 answers + 1 more in the
sign-out flow): `practice_attempts` = 6, `sync_receipts` = 6, distinct operation ids = 6,
all belonging to student A. Same result on Android and on iOS.

Honest limits of "offline":
- **Android:** real airplane mode on the emulator (`ping` to the Mac failed while the offline steps ran).
- **iOS:** the simulator cannot be put in airplane mode. The API process was stopped and the
  Auth gateway paused instead, so requests failed while the Mac's network stayed up.

## 3. Automated tests

| Suite | Before (this branch's starting point) | Now | Result |
|---|---|---|---|
| Database (pgTAP) | 209 | 209 | all pass |
| API (pytest) | 144 | 144 | all pass |
| Mobile (jest) | 128 | **157** | all pass |

New mobile tests (29):
- `tests/integration/redesigned_screens.test.ts` (4): the data behind the screens against
  real SQLite and the real local API — empty state, path states, offline answers surviving a
  force-quit, "synced" impossible while work is waiting, account switch.
- `tests/components/screens.test.tsx` (19): the **real screen components** rendered in Node
  over real SQLite. Among them: feedback and "Réponse enregistrée sur ce téléphone" appear
  only after the SQLite write has finished (the write is held open and the screen is checked
  before and after); a failed write confirms nothing; the sign-out warning; tab labels in
  both languages; no numbers on empty screens.
- `tests/unit/overview.test.ts` (6): Continue-card choice, sync display rule, tab labels.

What the component tests are not: `react-native`, `expo-router` and the safe-area library
are replaced by small stand-ins, so these tests check words, states and ordering — not
layout. Layout was checked on the emulators (next section).

## 4. Native checks

| Check | Android 7.0 (API 24, 1 GB, 480×800 = 320 dp) | iPhone 17 simulator (iOS 26.5) |
|---|---|---|
| Touch targets and screen-reader names on real screens | 66 controls, 0 failures, smallest 48 dp | 44 controls, 0 failures, smallest 48 pt |
| Large text | 150 % and 200 %: readable, scrollable, nothing cut off horizontally | 194 % ("accessibility large"): same |
| Reduced motion | Animations off: quiz behaves the same, feedback appears without animation | Reduce Motion on: same |
| French / Haitian Creole | Both | Both |
| Offline / online | Airplane mode / normal | Backend stopped / running |

Screenshots: `docs/mobile-02/android/` (release build, full journey),
`docs/mobile-02/android-large-text/`, `docs/mobile-02/ios/`. Audit output:
`docs/mobile-02/a11y-android.txt`, `a11y-ios.txt`.

Not done: nobody listened to TalkBack or VoiceOver; the audit only proves each control has a
name and is big enough. No physical phone. No usability session with students.

### Defects found on the emulators and fixed

1. **Last letter of "Profil" cut off on Android 7** after the content above the tab bar was
   scrolled ("Profi"). The label's box was the right size; Android 7 repainted part of the bar
   during scrolling. Fixed by giving the tab bar its own rendering layer; checked on 18
   captures after scrolling on all four tabs, plus the whole journey.
2. **Status pill ran off the screen at 200 % text** on the lesson header. Pills now wrap.
3. **A tap during a scroll fling was swallowed** in the UI test (sign-out button). This is
   normal scroll behaviour, not an app defect; the test now waits for the scroll to settle.

## 5. Size, speed and memory

Emulator / simulator numbers on an Apple-silicon Mac. **They do not predict a low-end phone.**

| Measure | Release-01 | Mobile-02 | Change |
|---|---|---|---|
| JavaScript bundle, Android (exported) | 2,723,229 bytes | 2,778,788 bytes | +55,559 (+2.0 %) |
| Same, gzip | 1,174,320 | 1,202,808 | +28,488 |
| JavaScript bundle, iOS (exported) | 2,735,165 bytes | 2,790,753 bytes | +55,588 (+2.0 %) |
| Android release APK (arm64) | 32,170,960 bytes | 32,217,296 bytes | +46,336 (+0.14 %) |
| iOS release app bundle (simulator build) | 80 MB | 81 MB | +1 MB |
| Android cold start → first frame (`am start -W`, 7 runs) | 184 ms median (159–192) | 147 ms median (125–170) | within run-to-run noise |
| Android warm start (7 runs) | 29 ms median | 31 ms median (25–40) | same |
| Android memory on Home (PSS) | 84 MB | 79 MB | same order |
| iOS memory (resident, simulator process) | 275 MB | 277 MB on Home after opening several screens; 179 MB idle after the full journey | same order; varies with state |

New in this milestone (measurement build with `EXPO_PUBLIC_PERF_LOG=1`, Android release, airplane mode):

| Measure | Result |
|---|---|
| Process start → Home drawn from SQLite (log timestamps, 7 cold starts) | **275 ms median** (267–287) |
| Tap "Continuer ma leçon" → lesson content committed (10 opens) | **11 ms median** (9–30) |

The second number is measured inside JavaScript: it excludes the time for the touch to reach
the app and for the frame to be painted. On iOS these two timings were **not measured**:
release builds on iOS do not write JavaScript log lines to the device log, and I did not add
another mechanism.

No new runtime dependency (`dependencies` in `package.json` is unchanged). Two development-only
packages were added for the component tests: `react-test-renderer` and its types.

## 6. Preview / production boundary

- `metro.config.js` blocks `src/app/design` (preview routes) and `src/design/preview`
  (fixtures and preview-only strings) from production bundles.
- Checked three ways: the exported production bundles, the JavaScript inside the release APK,
  and the iOS release `main.jsbundle` contain none of the preview identifiers
  (`previewBadge`, `usePreviewNav`, …); an export with `EXPO_PUBLIC_DESIGN_PREVIEW=1` does.
- In development (`expo start`) the previews are still available at `monedupreneur://design`.
- Real screens import nothing from `src/design/preview`.

## 7. Android / iOS differences observed

- Sign-out warning: Android shows a Material dialog with three text buttons; iOS shows the
  system alert with three stacked buttons. Same wording and order of meaning.
- iOS asks "Open in Edupreneurs?" the first time a `monedupreneur://` link is opened from
  outside the app. Normal iOS behaviour; it does not affect in-app navigation.
- iOS offers to save the password after sign-in (system prompt).
- Text wraps slightly differently: e.g. the e-mail address breaks mid-word at very large
  text on iOS.
- The Android-only tab-bar repaint defect above did not occur on iOS.

## 8. Limits of the data and the API

- **Lesson-level progress only.** The path shows one node per lesson. Step-level progress
  (Comprendre → Réviser) needs new stored data.
- **Completion is a separate action.** Answering every question does not mark a lesson
  finished; the student taps "J’ai terminé la leçon". The path follows that record.
- **"Continue" is per phone.** `last_lesson_id` is a local preference and is not synced.
- **Réviser is simple by design.** "My mistakes" = questions whose last recorded answer was
  wrong. No spaced repetition, no recommendation.
- **Lesson content.** Only heading, paragraph, example and callout blocks exist. Objective,
  key ideas and hints need content-schema work and reviewed content.
- **The catalog has one lesson.** The path was also seen with 25 lessons (test leftovers in
  the local database, before it was reset) and laid out correctly, but that was not a
  recorded test.
- **Local test note.** The API test suite leaves 24 synthetic lessons in the local database;
  `make db-reset` restores the one-lesson seed. The UI journey assumes the seed.

## 9. Outstanding risks

1. **No physical device.** Android 7 on a real 1 GB phone may be slower and may render differently.
2. **Screen readers not listened to.** Names and sizes pass; the spoken experience is unverified.
3. **Haitian Creole wording is a draft**, including about 40 new strings added here. Needs an educator's review.
4. **The tab-bar fix addresses a rendering quirk seen on the Android 7 emulator.** It should be re-checked on a real Android 7/8 phone.
5. **First lesson's download button is below the fold on a 320 dp screen** (grade and subject chips come first). One scroll reaches it. Worth a design decision.
6. **Component tests use the deprecated `react-test-renderer`.** It works with React 19 today; a native-runtime test setup would be the long-term replacement.
7. **Open design decisions from Design-00** are unchanged: final violet / amber values, logo, dark mode.
8. **Timing on iOS** (start → Home, lesson open) was not measured.

## 10. Reproduce

```bash
. scripts/dev-env.sh
make db-reset && make api                 # clean seed, API on 127.0.0.1:8000
make test && make mobile-test             # 209 + 144 + 157

# Android release, then the journey with airplane mode
cd apps/student-native/android
EXPO_PUBLIC_API_URL=http://10.0.2.2:8000 EXPO_PUBLIC_SUPABASE_URL=http://10.0.2.2:54321 \
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY="$(grep PUBLISHABLE ../.env.local | cut -d= -f2)" \
NODE_ENV=production ./gradlew assembleRelease -PreactNativeArchitectures=arm64-v8a
adb install -r app/build/outputs/apk/release/app-release.apk
E2E_OFFLINE=airplane ../scripts/e2e-run.sh android

# iOS release, then the journey
CONFIGURATION=Release apps/student-native/scripts/ios-build.sh
apps/student-native/scripts/e2e-run.sh ios
```
