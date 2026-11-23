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

if ! "$ADB" devices | grep -q "emulator-.*device$"; then
  echo "1/5 starting emulator $AVD_NAME (first boot of an old Android image takes a few minutes)"
  nohup "$ANDROID_HOME/emulator/emulator" -avd "$AVD_NAME" -no-snapshot -no-boot-anim -no-audio \
    > "${TMPDIR:-/tmp}/edupreneurs-emulator.log" 2>&1 < /dev/null &
  "$ADB" wait-for-device
else
  echo "1/5 emulator already running"
fi
until [ "$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do sleep 2; done

echo "2/5 forwarding the emulator's localhost to this Mac (Metro 8081, API 8000, Auth 54321)"
for port in 8081 8000 54321; do "$ADB" reverse "tcp:$port" "tcp:$port" >/dev/null; done

echo "3/5 checking the app is installed"
if ! "$ADB" shell pm list packages | grep -q "$PACKAGE"; then
  if [ ! -f "$APK" ]; then
    echo "error: no debug build found. Build once with: make mobile-android" >&2
    exit 1
  fi
  "$ADB" install -r "$APK" >/dev/null
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
"$ADB" shell am force-stop "$PACKAGE"
"$ADB" shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1

if ! curl -s --max-time 2 http://127.0.0.1:8000/ready | grep -q ready; then
  echo "note: the API is not running. Start it in another terminal with: make api"
fi
echo "done. To stop: adb emu kill ; pkill -f 'expo start --port 8081'"
