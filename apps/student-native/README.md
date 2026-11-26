# Edupreneurs — student app (Mobile-01)

> **Naming.** The product and the app are called **Edupreneurs**. "Mon Edupreneur"
> is only the domain (mon-edupreneur.com) and this repository's folder name.
> Technical identifiers were deliberately left unchanged: bundle id / Android
> package `ht.edupreneur.student.dev`, deep-link scheme `monedupreneur://`, and
> Expo slug `mon-edupreneur-student`.

React Native (Expo SDK 58, React Native 0.88) app for the first offline learning
slice: sign in → choose class and subject → save a lesson → read it and answer
its questions with no network → sync when the connection returns.

> **Status:** the storage and sync logic is tested against the real local
> backend (52 automated tests), and the app has been built and run on the
> **iOS Simulator**, where the full offline workflow passed
> (`docs/NATIVE_VALIDATION_REPORT.md`). It has also been built and run on an
> **Android 7.0 emulator** with the same result. Standalone release builds (no Metro) also pass, in
> real airplane mode on Android (`../../docs/RELEASE_01_REPORT.md`). **No physical phone has been tested.**

Supported OS range of this Expo SDK: **Android 7.0+ (API 24)**, **iOS 16.4+**. Building for iOS requires **Xcode 26.4 or newer**.

## Layout

```
src/core/       platform-free TypeScript — everything that matters for correctness
  api/          generated OpenAPI types (schema.d.ts), fetch client, error model, snapshot validation
  auth/         Supabase Auth REST client, SessionManager (refresh, sign-out, account switching)
  db/           SqlDatabase interface, ContentStore (public lessons), AccountStore (private, per account)
  learning/     answerQuestion, completeLesson, saveLessonOffline, refreshCatalog
  sync/         SyncEngine (push, pull, backoff, single flight)
  i18n/         French + Haitian Creole strings
src/platform/   adapters: expo-sqlite, expo-secure-store, expo-crypto, env config
src/ui/         app context (session, locale, sync status), plain components
src/app/        Expo Router screens: sign-in, home, select, lessons, lesson/[id], quiz/[id], progress
tests/          jest: core logic on a real SQLite engine against the live local API + Auth
docs/           MOBILE_01_PLAN.md, MOBILE_01_REPORT.md
```

Runtime dependencies beyond Expo/React Native: `expo-router`, `expo-sqlite`,
`expo-secure-store`, `expo-crypto`. No Supabase SDK, no state / i18n / UI library.

## Run the automated checks (no phone needed)

From the repository root, with the backend stack up (`make start`):

```bash
make mobile-install   # once
make mobile-check     # generated API types are fresh + TypeScript (app and tests)
make mobile-test      # 52 tests: real SQLite files, real local API and Auth
```

`make mobile-test` starts its own copy of the API and resets the
local learning tables between tests. It only ever talks to `127.0.0.1`.
The target database is derived from this checkout's `supabase/config.toml`; the harness refuses to run
against the default shared `mon-edupreneur` stack unless `EDU_TEST_ALLOW_SHARED_STACK=1` is set deliberately
(CI sets it on its disposable stack). Run the tests from a separate worktree with its own `project_id`.

The test API port is derived per checkout (a stable value in 20000-29999 computed from the checkout path), so two
worktrees never share one; set `EDU_MOBILE_TEST_API_PORT` to override it. If the port is already taken the harness
refuses to start (it never talks to whatever is listening there), and it only treats the API as ready once its own
server has logged that it bound the port.

## Run the app on a simulator / emulator / phone

The app uses native modules (SQLite, SecureStore), so it needs a **development
build** — Expo Go is not enough. A first native build needs roughly 10 GB of
free disk space.

```bash
# terminal 1 — backend
make start && make api                    # API on http://127.0.0.1:8000

# terminal 2 — credentials for a synthetic student (prints e-mail + password)
make dev-login ACCOUNT=student_a

# terminal 3 — the app
make mobile-env TARGET=ios-sim            # or android-emu, or lan (real phone)
make mobile-ios                           # or: make mobile-android
```

| Target | `make mobile-env TARGET=` | Notes |
|---|---|---|
| iOS Simulator | `ios-sim` | Needs Xcode. If `xcodebuild` complains about command line tools, the make target already sets `DEVELOPER_DIR`; or run `sudo xcode-select -s /Applications/Xcode.app` once |
| Android emulator | `android-emu` | Needs the Android SDK (`~/Library/Android/sdk`), a virtual device, and JDK 17. `10.0.2.2` is the emulator's name for your Mac |
| Real phone, same Wi-Fi | `lan` | Start the API with `make api-lan` instead of `make api`. Development only: it serves plain HTTP on your local network |

After changing `.env.local`, restart the bundler (`npx expo start -c`).
Running the backend test-suites or `make token` gives the seed accounts new
random passwords — run `make dev-login` again afterwards.

### Opening the app again without rebuilding (iOS)

```bash
make api                                   # terminal 1 (backend)
apps/student-native/scripts/ios-open.sh    # terminal 2: boots the simulator, opens its window,
                                           # starts Metro if needed, launches the installed app
```

If Expo ever says "Simulator app did not open fast enough", run that script (or
`open /Applications/Xcode-26.6.app/Contents/Developer/Applications/Simulator.app`)
once and try again.

### Opening the app again without rebuilding (Android)

```bash
make api                                       # terminal 1
apps/student-native/scripts/android-open.sh    # terminal 2: starts the API 24 emulator, forwards ports,
                                               # installs the saved APK if needed, starts Metro, launches the app
```

The emulator reaches the Mac's API, Auth and Metro through `adb reverse`, so the
same `.env.local` (127.0.0.1) works for iOS and Android. Port forwarding is lost
when the emulator restarts; the script sets it again.

### The manual acceptance test

1. Sign in as student A. Choose **9AF → Mathématiques**. Tap **Enregistrer pour étudier hors ligne**.
2. Turn on **airplane mode**. Open the lesson, then **Faire les exercices**: answer all five questions.
3. **Force-quit** the app. Reopen it (still in airplane mode): home shows *5 action(s) en attente*; Progrès shows the five answers.
4. Turn airplane mode **off**, tap **Synchroniser maintenant**: *Tout est synchronisé*.
5. Check the server: `TOKEN=$(make -s token ACCOUNT=student_a)` then
   `curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/v1/sync/pull` → exactly five `practice_attempt` changes.
   (This resets the account's password; run `make dev-login` again to keep using the app.)

## Regenerating the API types

`src/core/api/schema.d.ts` is generated from `packages/contracts/openapi.json`:

```bash
npm run gen:api      # after the backend contract changes
npm run check:api    # CI: fails if the committed file is stale
```
