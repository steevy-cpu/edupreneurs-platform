#!/bin/bash
# Open Edupreneurs in the iOS Simulator using the EXISTING development build.
# No rebuild, no simulator reset. Safe to run repeatedly.
#
#   apps/student-native/scripts/ios-open.sh            # iPhone 17
#   SIM_NAME="iPhone 17 Pro" apps/student-native/scripts/ios-open.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode-26.6.app/Contents/Developer}"
# Optional: SDK/caches on the external development volume (not needed just to open the app)
# shellcheck disable=SC1091
. "$APP_DIR/../../scripts/dev-env.sh" 2>/dev/null || true
SIM_NAME="${SIM_NAME:-iPhone 17}"
BUNDLE_ID="ht.edupreneur.student.dev"
SIMULATOR_APP="$DEVELOPER_DIR/Applications/Simulator.app"

if [ ! -d "$SIMULATOR_APP" ]; then
  echo "error: Simulator.app not found under $DEVELOPER_DIR" >&2
  exit 1
fi
BUILT_APP="$(ls -d "${EDU_IOS_DERIVED_DATA:-/nonexistent}"/Build/Products/Debug-iphonesimulator/*.app "$APP_DIR"/ios/build/Build/Products/Debug-iphonesimulator/*.app 2>/dev/null | head -1 || true)"

UDID="$(xcrun simctl list devices available | grep -E "^ +$SIM_NAME \(" | head -1 | sed -E 's/.*\(([0-9A-F-]{36})\).*/\1/')"
if [ -z "$UDID" ]; then
  echo "error: no available simulator named '$SIM_NAME'. See: xcrun simctl list devices available" >&2
  exit 1
fi

echo "1/5 booting $SIM_NAME ($UDID)"
xcrun simctl boot "$UDID" 2>/dev/null || true
xcrun simctl bootstatus "$UDID" >/dev/null

echo "2/5 opening the Simulator window"
# By full path: 'open -a Simulator' fails until macOS has seen this copy of Xcode once.
open "$SIMULATOR_APP" --args -CurrentDeviceUDID "$UDID"

echo "3/5 checking the app is installed"
if ! xcrun simctl get_app_container "$UDID" "$BUNDLE_ID" >/dev/null 2>&1; then
  if [ -z "$BUILT_APP" ]; then
    echo "error: no development build found. Build once with: make mobile-ios" >&2
    exit 1
  fi
  xcrun simctl install "$UDID" "$BUILT_APP"
  echo "    installed $(basename "$BUILT_APP")"
fi

echo "4/5 checking the Metro bundler (http://127.0.0.1:8081)"
if ! curl -s --max-time 2 http://127.0.0.1:8081/status | grep -q running; then
  # Fully detached, so this script can finish while Metro keeps running.
  (cd "$APP_DIR" && nohup npx expo start --port 8081 > "${TMPDIR:-/tmp}/edupreneurs-metro.log" 2>&1 < /dev/null &) > /dev/null 2>&1
  for _ in $(seq 1 60); do
    curl -s --max-time 2 http://127.0.0.1:8081/status | grep -q running && break
    sleep 1
  done
  echo "    started Metro (log: ${TMPDIR:-/tmp}/edupreneurs-metro.log)"
fi

echo "5/5 launching the app"
xcrun simctl terminate "$UDID" "$BUNDLE_ID" 2>/dev/null || true
xcrun simctl launch "$UDID" "$BUNDLE_ID" >/dev/null

if ! curl -s --max-time 2 http://127.0.0.1:8000/ready | grep -q ready; then
  echo "note: the API is not running. Start it in another terminal with: make api"
fi
echo "done. To stop Metro later: pkill -f 'expo start --port 8081'"
