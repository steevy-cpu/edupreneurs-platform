# How the native iOS and Android projects are generated

This app uses Expo's **Continuous Native Generation**: the `ios/` and `android/`
folders are **generated output**, not source. They are git-ignored. The source
of truth is `app.json` (plus the plugins listed in it and `package.json`).

```
app.json + package.json ──(npx expo prebuild)──▶ ios/  android/ ──(xcodebuild / gradle)──▶ installable app
        source                                    generated                                  build output
```

## What lives where

| Path | What it is | Size (approx.) | Regenerable? |
|---|---|---|---|
| `app.json` | App name, identifiers, icons, plugins | tiny | **No — this is the source** |
| `ios/Edupreneurs.xcodeproj`, `ios/Edupreneurs/`, `ios/Podfile` | Generated Xcode project | < 5 MB | Yes, by prebuild (seconds) |
| `ios/Pods/` | iOS native dependencies | 1.4 GB | Yes, `pod install` (4 min, downloads) |
| `ios/build/` | iOS build output, incl. the `.app` installed in the simulator | 2.4 GB | Yes, full rebuild (10 min) |
| `android/` (except below) | Generated Gradle project | < 5 MB | Yes, by prebuild (seconds) |
| `android/app/build/`, `android/build/`, `android/.gradle/` | Android build output, incl. the `.apk` | 1–2 GB | Yes, rebuild |
| `~/.gradle/` | Gradle itself and downloaded libraries (shared by all Android projects) | 2–3 GB | Yes, re-downloads |

An app already installed in a simulator or emulator keeps working even if these
folders are deleted — but it cannot be rebuilt or reinstalled until they are regenerated.

## What triggers regeneration — and what it destroys

| Command / change | Effect |
|---|---|
| `npx expo prebuild --platform ios` (or `android`) with **no** relevant change | Updates files in place. Build output is kept |
| Same command after changing **`name`** in `app.json` | **Regenerates the whole platform folder.** The project is named after the app, so the old folder is replaced: `ios/Pods` and `ios/build` are deleted |
| Same command after changing `ios.bundleIdentifier`, `android.package`, `scheme`, or adding/removing a plugin or native dependency | Native files change; a rebuild is required. Changing an identifier makes the OS treat it as a different app |
| `npx expo prebuild --clean` | **Deletes and recreates** the platform folder(s), always |
| `npx expo prebuild` with no `--platform` | Does **both** platforms |
| `npx expo run:ios` / `run:android` (`make mobile-ios` / `mobile-android`) | Runs prebuild first if the folder is missing, then builds |
| Editing only JavaScript/TypeScript (`src/`) | Nothing native changes; Metro reloads the app |

This happened once in this project: renaming the app to "Edupreneurs" and
re-running prebuild removed 3.8 GB of iOS build output without that being intended.

## Rules for this repository

1. **Never run `expo prebuild --clean`, and never run prebuild after changing
   `name`, an identifier, or the plugin list, without explicit approval** — say
   first what will be deleted and how long the rebuild takes.
2. Always pass `--platform ios` or `--platform android`; never regenerate both by accident.
3. Do not edit files inside `ios/` or `android/` by hand: the next prebuild
   overwrites them. Change `app.json` or write a config plugin instead.
4. Before deleting any build folder to save disk, ask; state the rebuild cost.
5. Check what a prebuild would change before running it:
   `git diff app.json package.json` (if `name`, identifiers or plugins differ
   from what was last built, expect regeneration).
6. To open an already-built app, do not rebuild:
   `scripts/ios-open.sh` (iOS) or `scripts/android-open.sh` (Android).

## Pending native changes (not yet applied to the iOS build)

- The iOS home-screen label still reads "Mon Edupreneur" in the installed
  simulator build; `app.json` already says "Edupreneurs". It will change at the
  next iOS rebuild, planned together with the icon and splash screen.
- Identifiers intentionally unchanged: bundle id / package
  `ht.edupreneur.student.dev`, scheme `monedupreneur`, slug `mon-edupreneur-student`.
