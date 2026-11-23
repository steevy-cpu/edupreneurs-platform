# Release-01 — standalone offline validation

Date: 2026-11-22. Repository: `/Volumes/EdupreneursDev/Mon-edupreneur`, branch `mobile-01`.

**Result: the definition of success is met on the Android emulator and on the
iOS Simulator.** Release builds of Edupreneurs launch with no Metro server,
open a previously saved lesson, keep offline answers through a full app restart,
and synchronise each answer exactly once when the backend is reachable again.

Two qualifications, stated up front:

- On **Android** "no network" was genuine: airplane mode, no connected network,
  the backend deliberately left running and receiving zero requests.
- On **iOS** the Simulator shares the Mac's network and cannot be put offline on
  its own, so "offline" there means **the backend was unreachable** (API process
  stopped, Auth gateway paused, Metro not running). No real airplane mode was tested on iOS.

Nothing here was run on a physical phone.

## 1. Preflight

| Check | Result |
|---|---|
| Development volume mounted | `/Volumes/EdupreneursDev` (APFS image on the T7) |
| Tool paths | `ANDROID_HOME`, `GRADLE_USER_HOME`, AVD home on the volume; JDK 17.0.21 in `.tools/`; Xcode 26.6 via `DEVELOPER_DIR` |
| Storage before | internal 15.7 GB free, volume 179.7 GB free |
| Automated tests before | 209 + 144 + 52 = 405 passed |
| Release embeds JavaScript | Android: Gradle task `createBundleReleaseJsAndAssets` (`bundleCommand = "export:embed"`). iOS: Xcode "Bundle React Native code and images" phase in Release |
| Signing | Android release is signed with the template's `debug.keystore` (certificate `CN=Android Debug`): local test signing only. iOS simulator builds are not signed for distribution. No production key was created |
| Values bundled | Only `EXPO_PUBLIC_API_URL`, `EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (all public by design; the code reads no other environment variable) |
| UX direction document | `~/Mon-edupreneur/Edupreneurs_UX_Direction_v0.1.md` copied byte-for-byte to `docs/design/EDUPRENEURS_UX_DIRECTION_v0.1.md`; no previous copy existed; nothing from it implemented; the old repository was not otherwise touched |

**Local-testing configuration.** No new build variant was needed:

- Android: the release bundle was built with the API and Auth URLs set to
  `http://10.0.2.2:…` (the emulator's address for the Mac) through environment
  variables at build time. No `adb reverse` forwarding is involved, so turning
  the device network off really cuts the app off.
- Plain HTTP works in this release build **only because the device is
  Android 7**. From Android 9 the same build would be refused cleartext HTTP
  (the manifest allows it only in debug). That is correct for production, which
  must use HTTPS; testing a release build against a local HTTP backend on a
  newer Android would need an explicit local-testing variant.
- iOS: unchanged `.env.local` (`127.0.0.1`); `NSAllowsLocalNetworking` permits local HTTP.

## 2. Builds

| | Android | iOS |
|---|---|---|
| Command | `./gradlew assembleRelease -PreactNativeArchitectures=arm64-v8a` (with the three `EXPO_PUBLIC_*` variables and `NODE_ENV=production`) | `CONFIGURATION=Release INSTALL=0 apps/student-native/scripts/ios-build.sh` (runs `pod install` if needed, then `xcodebuild -configuration Release -sdk iphonesimulator -derivedDataPath <volume>`) |
| First build | `BUILD SUCCESSFUL` in 5 min 23 s | `BUILD SUCCEEDED`, 11 min 9 s including `pod install`; 0 compiler errors |
| Rebuild after a JavaScript fix | 33 s | 29 s |
| Embedded JavaScript | `assets/index.android.bundle`, 2.2 MB, Hermes bytecode | `main.jsbundle`, 2.7 MB, Hermes bytecode |
| Output | `app-release.apk`, 30.7 MB, arm64, not debuggable | `Edupreneurs.app`, 80 MB (simulator build), minimum iOS 16.4 |
| Secret scan (bundle + manifest) | 0 hits for secret key, service role, database credentials, private keys | 0 hits |
| Disk used on the volume | 2.1 GB | 6.6 GB (Pods + build) |
| Lowest internal free space during build | 14.0 GB | 13.4 GB |

Artifacts kept on the volume: `artifacts/edupreneurs-release-arm64.apk`,
`artifacts/edupreneurs-debug-arm64.apk`, and a backup of the previously
installed iOS debug app (`artifacts/ios-debug-app/`). Summary of the Android
build: `apps/student-native/docs/native-validation/android-release-build-summary.txt`.

Side effect to know about: installing the iOS Release build **replaced the debug
build** on the iPhone 17 simulator (same bundle id). Its home-screen label now
reads "Edupreneurs". The icon and splash are still the template placeholders.

## 3. Android release — acceptance (Android 7.0 / API 24, 480×800, 1 GB RAM)

Metro: not running (port 8081 closed). `adb reverse`: none.

| # | Requirement | Result |
|---|---|---|
| 1 | Launches with Metro stopped | Passed |
| 2 | Authentication with synthetic local accounts | Passed (real sign-in against local Supabase Auth) |
| 3 | Lesson download | Passed; the API logged one lesson request |
| 4 | Network completely disabled | Wi-Fi off, mobile data off, airplane mode on; 0 connected networks; ping to the Mac failed. **The backend was left running on purpose** |
| 5 | Saved lesson still accessible | Passed |
| 6 | Five questions offline | Passed (4 right, 1 wrong) |
| 7 | Force-quit and reopen while offline | Passed: opened on the home screen showing "5 action(s) en attente" |
| 8 | SQLite retains lesson, answers, progress, pending operations | Read from the device as root: 5 attempts, 5 pending operations, 0 marked synced, 5 progress rows (4 correct); saved lesson revision 1 with 5 questions |
| 9 | No false sync success | The in-app sync attempt showed "Serveur injoignable"; pending count unchanged. **The API received 0 requests during the whole offline phase** |
| 10 | Exactly-once sync after reconnecting | Server: 5 attempts, 5 distinct `op_id`s identical to the device's, 5 accepted receipts, versions 1–5; **one** push request; device outbox empty |
| 11 | Account switching | Passed: student B saw 0 answers; student A's 5 returned |
| — | Haitian Creole | Passed (home, lessons, reader, quiz) |

Crashes / ANRs in the device log: 0.

## 4. iOS release — acceptance (iPhone 17 simulator, iOS 26.5)

Metro: not running.

| Requirement | Result |
|---|---|
| App launch and session restoration | Passed; no "bundling" step, straight to the app |
| Complete offline restart | Passed twice: force-quit and reopen, and a **full simulator shutdown and boot**, both with the backend unreachable; home showed 5 pending |
| Local answer persistence | App sandbox SQLite: 5 attempts, 5 pending, 0 synced, 5 progress rows |
| Sync after reconnection | Server: 5 attempts, 5 distinct `op_id`s identical to the device's, 5 accepted receipts, versions 1–5; one push request |
| Sign-out and account isolation | Passed; two files on the device: A = 5 attempts, B = 0 |
| Layout and safe areas | Content clears the translucent navigation bar and the home indicator on every captured screen (after the fix in section 6) |
| French and Haitian Creole | Passed; accents render correctly |

Fault-level log lines for the app: 0. Crash reports: 0.

## 5. Performance: Debug vs Release

All numbers are from an emulator / simulator running on an Apple-silicon Mac.
**They are not phone measurements** and do not establish the 3 s / 1 s targets
for a low-memory device.

| Measure | Android Debug | Android Release | iOS Debug | iOS Release |
|---|---|---|---|---|
| Cold start → first frame | 175–239 ms (5 runs) | **184 ms median** (159–192, 7 runs) | not measured | not measured |
| Cold start → session restored and first request sent | 1.23–1.25 s (3 runs) | **0.48 s median** (0.45–0.52, 7 runs) | 1.36–1.44 s (3 runs) | **0.80 s median** (0.76–0.93, 7 runs) |
| Warm start (Home, then reopen) | not measured | **29 ms median** (27–36, 7 runs) | not measured | not measured |
| App memory | 243 MB PSS | **84 MB PSS** | 452 MB resident | **275 MB resident** |
| Installed size | 76.6 MB APK | **30.7 MB APK; 38.7 MB installed** | 128 MB app bundle | 80 MB app bundle |
| App data after the test | 372 KB | 392 KB SQLite (512 KB total) | 356 KB | 384 KB |

Methods:

- *First frame*: Android `am start -W` `TotalTime`, after `am force-stop`.
- *Session restored*: wall-clock time from the launch command until the app's
  first request appears in the API log. The app sends it only after opening
  SQLite, reading the session from secure storage and rendering. It therefore
  includes one local HTTP round trip.
- *Warm start*: `KEYCODE_HOME`, then `am start -W`.
- *Memory*: Android `dumpsys meminfo` (PSS) with the app on the home screen;
  iOS `ps` resident size of the simulator process. The two are **not comparable
  with each other**: a simulator process is a Mac process with different
  overheads.
- *Sizes*: file sizes of the APK / `.app`; Android installed size from `du` on
  the device. The iOS figure is a simulator build, not an App Store size.

Not measured: cached-lesson opening time (it completed inside the UI test's
polling interval; no precise timer was added), iOS first-frame and warm-start
times.

## 6. Defects found and fixed during Release-01

| # | Defect | How it was found | Fix |
|---|---|---|---|
| 1 | The quiz auto-scroll added for small Android screens also fired on a tall iPhone, where the content already fits, and pushed the question text under the navigation bar | Reviewing the iOS Release screenshots | `Screen` now scrolls to new bottom content only when the content does not fit (`revealEndKey`, `src/ui/components.tsx`); confirmed by screenshot on iOS and re-run on Android |

Both release apps were rebuilt after this fix. On the **final** builds the core
flows were re-run on both platforms: sign-in and lesson download, five questions
offline, force-quit and reopen offline, reconnect and sync (server: 5 attempts,
5 distinct, one push request, on each platform). Account switching, the Creole
flow, the full simulator restart and the measurements above were taken on the
first release builds, which differ from the final ones only by that fix.

## 7. Automated tests after the code change

| Suite | Result |
|---|---|
| Database (pgTAP) | 209 passed |
| Backend (pytest, real local database and Auth) | 144 passed |
| Mobile core (jest) | 52 passed |
| **Total** | **405 passed, 0 failed** |
| TypeScript (app + tests), `expo-doctor`, ruff | clean, 20/20, clean |

## 8. Storage

| | Before | After |
|---|---|---|
| Internal disk free | 15.7 GB | 13.5 GB |
| Development volume free | 179.7 GB | 170.8 GB |

The internal drop is the iOS simulator's own data and macOS swap, which cannot
be relocated. It never approached the 7 GB floor. Build output on the volume:
Xcode derived data 4.8 GB, Gradle cache 4.5 GB, Android build folder 1.8 GB.

## 9. Evidence

- Screenshots: `apps/student-native/docs/native-validation/android-release/` and
  `…/ios-release/` (25 each).
- UI flows: `apps/student-native/e2e/01`–`09`.
- Logs (on the volume, not in Git): `/Volumes/EdupreneursDev/logs/`
  (`android-build-release.log`, `api-release.log`, `api-ios-release.log`),
  and `xcode-derived-data/edupreneurs/build-Release.log`.

## 10. Remaining limitations

- **No physical device.** Real flash storage, real radios, vendor battery
  managers and low-end processors are untested.
- **iOS offline is "backend unreachable"**, not airplane mode.
- **Android: one version (7.0), one screen (480×800), arm64 only.** No 32-bit
  ARM build. Android 9+ would block this build's HTTP calls to a local backend.
- **iOS: one simulator model, one OS version (26.5).** The supported floor,
  iOS 16.4, was not run.
- **Not production builds.** Test signing only; no code shrinking was enabled;
  the app icon and splash are template placeholders; store packaging
  (Android App Bundle, iOS archive) was not produced.
- **Android backup flag.** The release manifest has `allowBackup` enabled (the
  template default), so the unencrypted learning database could be included in
  device backups. To decide before any distribution.
- Open items from `apps/student-native/docs/MOBILE_01_REPORT.md` §9 still apply
  (no integrity check on downloaded lessons, unencrypted local databases, no
  UI component tests, CI workflow never run).

## 11. Reproduce

```bash
open /Volumes/T7/EdupreneursDev.sparsebundle && cd /Volumes/EdupreneursDev/Mon-edupreneur
. scripts/dev-env.sh

# Android release (emulator reaches the Mac at 10.0.2.2)
cd apps/student-native/android
EXPO_PUBLIC_API_URL=http://10.0.2.2:8000 EXPO_PUBLIC_SUPABASE_URL=http://10.0.2.2:54321 \
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY="$(grep PUBLISHABLE ../.env.local | cut -d= -f2)" \
NODE_ENV=production ./gradlew assembleRelease -PreactNativeArchitectures=arm64-v8a
emulator -avd edu_api24 -no-snapshot &      # then, once booted:
adb install -r app/build/outputs/apk/release/app-release.apk

# iOS release
cd .. && CONFIGURATION=Release ./scripts/ios-build.sh   # builds and installs on iPhone 17

# backend, and credentials for a synthetic student
make api
make dev-login ACCOUNT=student_a
```

Do not start Metro. To go offline on Android, turn on airplane mode in the
emulator; on iOS, stop `make api`.
