# Development storage on the external SSD

Large development files live on an external volume so the Mac's internal disk
is not filled by SDKs, caches and build output.

## The volume

| | |
|---|---|
| Physical drive | Samsung T7, 1 TB, USB, formatted exFAT (unchanged; it also holds unrelated files) |
| Development volume | `EdupreneursDev` — an APFS **disk image** stored as one item on the T7: `/Volumes/T7/EdupreneursDev.sparsebundle` |
| Mounted at | `/Volumes/EdupreneursDev` |
| Capacity | up to 200 GB; the image only occupies what is actually stored |

Why a disk image: exFAT has no symbolic links, no Unix permissions and wastes
space on small files, all of which development tools depend on. The image gives
a normal Mac (APFS) volume without erasing or repartitioning the drive.

## Mounting after a restart or after plugging the drive in

The volume does **not** mount by itself.

```bash
open /Volumes/T7/EdupreneursDev.sparsebundle     # or double-click it in Finder
cd /Volumes/EdupreneursDev/Mon-edupreneur
make dev-volume                                  # same thing, from inside the repository
```

Before unplugging the T7: stop the API/Metro/emulator, then eject
**EdupreneursDev** first and **T7** second (Finder eject buttons, or
`hdiutil detach /Volumes/EdupreneursDev && diskutil eject /Volumes/T7`).
Pulling the cable while it is mounted can corrupt the image.

## What is where

| On the development volume | Path | Tool setting |
|---|---|---|
| Git repository (working copy) | `/Volumes/EdupreneursDev/Mon-edupreneur` | — |
| Android SDK, NDK, emulator, system images | `android-sdk/` | `ANDROID_HOME`, `ANDROID_SDK_ROOT` |
| Android virtual devices | `android-avd/` | `ANDROID_AVD_HOME` |
| Gradle distribution and caches | `gradle/` | `GRADLE_USER_HOME` |
| iOS build output | `xcode-derived-data/edupreneurs/` | `xcodebuild -derivedDataPath` (via `scripts/ios-build.sh`) |
| Python / npm / CocoaPods download caches | `caches/` | `UV_CACHE_DIR`, `npm_config_cache`, `CP_HOME_DIR` |
| JDK 17, Maestro | inside the repository: `.tools/` | `JAVA_HOME` |
| Android build output | inside the repository: `apps/student-native/android/` | — |

| Stays on the internal disk | Why |
|---|---|
| Xcode (`/Applications/Xcode-26.6.app`) | Must be internal |
| iOS simulator runtime and its caches (`/Library/Developer/CoreSimulator`, about 11 GB) | Apple provides no supported way to relocate them |
| iOS simulator devices (`~/Library/Developer/CoreSimulator/Devices`) | Same |
| Docker / OrbStack data (the local Postgres) | Deliberately not moved |
| macOS swap | System-managed |

## How the settings are applied

Nothing system-wide was changed. Two project-level mechanisms set the variables:

- **`make …`** — the Makefile exports them whenever the volume is mounted.
- **`. scripts/dev-env.sh`** — for a terminal where you run tools by hand
  (`adb`, `emulator`, `./gradlew`, `npx expo …`).

Xcode's global "Derived Data" preference was left alone on purpose: changing it
would affect every Xcode project on the Mac and break them whenever the SSD is
unplugged. `make mobile-ios` builds with an explicit `-derivedDataPath` instead.

**Android Studio** is a separate app and does not read these variables. If you
open the project in it, set *Settings → Languages & Frameworks → Android SDK →
Android SDK Location* to `/Volumes/EdupreneursDev/android-sdk`, and launch it
from a terminal that has sourced `scripts/dev-env.sh` so it finds the emulator devices.

## If the volume is not mounted

`make` targets that need the SDK fall back to the tools' defaults (which may no
longer exist on the internal disk) and fail with a clear "SDK not found"
message; `scripts/dev-env.sh` prints how to mount the volume. The backend
(`make start`, `make api`, tests) only needs the repository, which is on the volume too.
