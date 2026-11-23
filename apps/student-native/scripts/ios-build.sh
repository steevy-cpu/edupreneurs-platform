#!/bin/bash
# Build the iOS development (Debug) app for the simulator.
# Build output goes to $EDU_IOS_DERIVED_DATA (on the development volume), not into
# the repository and not into ~/Library/Developer/Xcode/DerivedData.
#
# This does NOT regenerate the native project if ios/ already exists.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
. "$APP_DIR/../../scripts/dev-env.sh"
SIM_NAME="${SIM_NAME:-iPhone 17}"

cd "$APP_DIR"
if [ ! -d ios ]; then
  echo "ios/ does not exist: generating it from app.json (see docs/NATIVE_PROJECTS.md)"
  CI=1 npx expo prebuild --platform ios --no-install
fi
cd ios
WORKSPACE="$(ls -d ./*.xcworkspace 2>/dev/null | head -1 || true)"
if [ ! -d Pods ] || [ -z "$WORKSPACE" ]; then
  echo "installing iOS dependencies (CocoaPods; a few minutes)"
  pod install
  WORKSPACE="$(ls -d ./*.xcworkspace | head -1)"
fi
SCHEME="$(basename "$WORKSPACE" .xcworkspace)"
UDID="$(xcrun simctl list devices available | grep -E "^ +$SIM_NAME \(" | head -1 | sed -E 's/.*\(([0-9A-F-]{36})\).*/\1/')"
[ -n "$UDID" ] || { echo "error: no simulator named '$SIM_NAME'" >&2; exit 1; }

mkdir -p "$EDU_IOS_DERIVED_DATA"
echo "building $SCHEME (Debug) -> $EDU_IOS_DERIVED_DATA"
xcodebuild -workspace "$WORKSPACE" -scheme "$SCHEME" -configuration Debug -sdk iphonesimulator \
  -destination "id=$UDID" -derivedDataPath "$EDU_IOS_DERIVED_DATA" build \
  > "$EDU_IOS_DERIVED_DATA/build.log" 2>&1 || { tail -30 "$EDU_IOS_DERIVED_DATA/build.log"; exit 1; }
grep -E "BUILD SUCCEEDED" "$EDU_IOS_DERIVED_DATA/build.log"

xcrun simctl boot "$UDID" 2>/dev/null || true
xcrun simctl bootstatus "$UDID" >/dev/null
xcrun simctl install "$UDID" "$(ls -d "$EDU_IOS_DERIVED_DATA"/Build/Products/Debug-iphonesimulator/*.app | head -1)"
echo "installed on $SIM_NAME"
