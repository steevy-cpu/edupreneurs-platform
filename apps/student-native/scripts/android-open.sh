#!/bin/bash
# Open Edupreneurs on the Android emulator using the EXISTING debug build.
# No rebuild, no emulator wipe. Safe to run repeatedly.
#
#   apps/student-native/scripts/android-open.sh
#   AVD_NAME=edu_api24 apps/student-native/scripts/android-open.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
. "$APP_DIR/../../scripts/dev-env.sh"
AVD_NAME="${AVD_NAME:-edu_api24}"
PACKAGE="ht.edupreneur.student.dev"
ADB="$ANDROID_HOME/platform-tools/adb"
APK="$APP_DIR/android/app/build/outputs/apk/debug/app-debug.apk"

. "$APP_DIR/scripts/android-device.sh"
: "${ANDROID_SERIAL:?Set ANDROID_SERIAL to the intended device or emulator serial}"
# Development normally uses make api (8000). Tests select their own checkout port.
export EDU_MOBILE_TEST_API_PORT="${EDU_MOBILE_TEST_API_PORT:-8000}"
TARGET=$(node "$APP_DIR/scripts/e2e-target.js" dev)
read -r _ _ FASTAPI_PORT AUTH_PORT <<< "$TARGET"

if ! select_android 2>/dev/null; then
  [[ "$ANDROID_SERIAL" =~ ^emulator-([0-9]+)$ ]] || { echo "Selected device is unavailable" >&2; exit 1; }
  port="${BASH_REMATCH[1]}"
  nohup "$ANDROID_HOME/emulator/emulator" -avd "$AVD_NAME" -port "$port" -no-snapshot -no-boot-anim -no-audio \
    > "${TMPDIR:-/tmp}/edupreneurs-emulator-$port.log" 2>&1 < /dev/null &
  device_adb wait-for-device
  select_android
fi
until [ "$(device_adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do sleep 2; done

echo "2/5 forwarding Metro and the verified backend ports"
device_adb reverse tcp:8081 tcp:8081 >/dev/null
android_backend reachable

echo "3/5 checking the app is installed"
if ! device_adb shell pm list packages | grep -q "$PACKAGE"; then
  if [ ! -f "$APK" ]; then
    echo "error: no debug build found. Build once with: make mobile-android" >&2
    exit 1
  fi
  device_adb install -r "$APK" >/dev/null
  echo "    installed app-debug.apk"
fi

echo "4/5 checking the Metro bundler (http://127.0.0.1:8081)"
if ! curl -s --max-time 2 http://127.0.0.1:8081/status | grep -q running; then
  (cd "$APP_DIR" && nohup npx expo start --port 8081 > "${TMPDIR:-/tmp}/edupreneurs-metro.log" 2>&1 < /dev/null &) > /dev/null 2>&1
  for _ in $(seq 1 60); do
    curl -s --max-time 2 http://127.0.0.1:8081/status | grep -q running && break
    sleep 1
  done
  echo "    started Metro (log: ${TMPDIR:-/tmp}/edupreneurs-metro.log)"
fi

echo "5/5 launching the app"
device_adb shell am force-stop "$PACKAGE"
device_adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
