#!/bin/bash
# Run the Mobile-02 UI journey with Maestro against the app ALREADY installed
# on a running Android emulator or iOS simulator. Local stack only.
#
#   apps/student-native/scripts/e2e-run.sh android [flow ...]
#   apps/student-native/scripts/e2e-run.sh ios     [flow ...]
#
# With no flow names it runs the whole journey, switching the backend between
# reachable and unreachable where a flow needs it:
#   android  removes / restores the selected device's verified API and Auth forwards
#   android + E2E_OFFLINE=airplane   real airplane mode (for standalone release builds)
#   ios      stops / starts the local API process and pauses / unpauses the Auth gateway
# Passwords for the two synthetic students are generated here and never printed.
set -euo pipefail

PLATFORM="${1:?usage: e2e-run.sh android|ios [flow ...]}"; shift || true
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$APP_DIR/../.." && pwd)"
# shellcheck disable=SC1091
. "$ROOT/scripts/dev-env.sh" >/dev/null 2>&1

MAESTRO="$ROOT/.tools/maestro/bin/maestro"
ADB="$ANDROID_HOME/platform-tools/adb"
. "$APP_DIR/scripts/android-device.sh"
case "$PLATFORM" in
  android) select_android; DEVICE="$ANDROID_SERIAL" ;;
  ios) DEVICE="${IOS_UDID:?Set IOS_UDID to the intended booted simulator}" ;;
  *) echo "Expected android or ios" >&2; exit 1 ;;
esac
TARGET=$(node "$APP_DIR/scripts/e2e-target.js" "${E2E_OFFLINE:-reverse}")
read -r DB_CONTAINER KONG_CONTAINER FASTAPI_PORT AUTH_PORT <<< "$TARGET"
OUT="${E2E_OUT:-$EDU_DEV_VOLUME/shots/mobile-02/$PLATFORM}"
LOG="${E2E_LOG:-$EDU_DEV_VOLUME/logs/mobile02-e2e-$PLATFORM.log}"
mkdir -p "$OUT/shots"

# Own the FastAPI listener for the whole run. A pre-existing listener cannot pass the bind check.
API_LOG=$(mktemp)
API_PID=""
GATEWAY_PAUSED=""
stop_api() {
  if [[ -n "$API_PID" ]]; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
    API_PID=""
  fi
}
cleanup() {
  stop_api
  if [[ -n "$GATEWAY_PAUSED" ]]; then docker unpause "$KONG_CONTAINER" >/dev/null; fi
  rm -f "$API_LOG"
}
trap cleanup EXIT
start_api() {
  # Resolve uvicorn before starting so the tracked child is the actual server process.
  local python
  python=$(cd "$ROOT" && uv run python -c 'import sys; print(sys.executable)')
  (cd "$ROOT" && exec "$python" -m uvicorn edu_api.main:create_app --factory --host 127.0.0.1 --port "$FASTAPI_PORT") >"$API_LOG" 2>&1 &
  API_PID=$!
  for _ in $(seq 1 30); do
    kill -0 "$API_PID" 2>/dev/null || { echo "Checkout API failed to bind port $FASTAPI_PORT" >&2; return 1; }
    if grep -Fq "Uvicorn running on http://127.0.0.1:$FASTAPI_PORT " "$API_LOG" &&
       curl --noproxy '*' -fsS --max-time 2 "http://127.0.0.1:$FASTAPI_PORT/ready" >/dev/null; then return 0; fi
    sleep 1
  done
  return 1
}
start_api
password() { (cd "$ROOT" && make -s dev-login ACCOUNT="$1" 2>/dev/null | awk '/^password:/ {print $2}'); }
PASS_A="$(password student_a)"; PASS_B="$(password student_b)"
ENVS=(-e EMAIL=student.a@edupreneur.test -e "PASSWORD=$PASS_A" -e EMAIL_B=student.b@edupreneur.test -e "PASSWORD_B=$PASS_B")

backend() { # reachable | unreachable
  if [ "$PLATFORM" = android ] && [ "${E2E_OFFLINE:-}" = airplane ]; then
    # Release builds reach the Mac at 10.0.2.2, so "offline" is real airplane mode on the emulator.
    if [ "$1" = unreachable ]; then
      # (This emulator image has no Wi-Fi radio; mobile data is its only network.)
      device_adb shell svc data disable >/dev/null 2>&1 || true
      device_adb shell settings put global airplane_mode_on 1
      device_adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true >/dev/null 2>&1 || true
    else
      device_adb shell settings put global airplane_mode_on 0
      device_adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false >/dev/null 2>&1 || true
      device_adb shell svc data enable >/dev/null 2>&1 || true
      for _ in $(seq 1 30); do device_adb shell ping -c 1 -W 1 10.0.2.2 >/dev/null 2>&1 && break; sleep 1; done
    fi
    echo "    airplane mode: $(device_adb shell settings get global airplane_mode_on | tr -d '\r'); ping Mac: $(device_adb shell ping -c 1 -W 1 10.0.2.2 >/dev/null 2>&1 && echo ok || echo unreachable)" | tee -a "$LOG"
  elif [ "$PLATFORM" = android ]; then
    android_backend "$1"
  elif [ "$1" = unreachable ]; then
    stop_api
    docker pause "$KONG_CONTAINER" >/dev/null
    GATEWAY_PAUSED=1
  elif [[ -n "$GATEWAY_PAUSED" ]]; then
    docker unpause "$KONG_CONTAINER" >/dev/null
    GATEWAY_PAUSED=""
    start_api
  fi
  echo "    backend: $1" | tee -a "$LOG"
}

# This Maestro version writes screenshots under ~/.maestro/tests/<run>/<flow>/; copy them next to the log.
collect() {
  local latest
  latest="$(ls -dt "$HOME"/.maestro/tests/*/"$1"/takeScreenshot/shots 2>/dev/null | head -1)"
  [ -n "$latest" ] && cp "$latest"/*.png "$OUT/shots/" 2>/dev/null || true
}

run() { # flow-name
  echo "==> $1" | tee -a "$LOG"
  (cd "$OUT" && "$MAESTRO" --device "$DEVICE" test "${ENVS[@]}" "$APP_DIR/e2e/$1.yaml") >> "$LOG" 2>&1 \
    && { collect "$1"; echo "    PASS $1" | tee -a "$LOG"; } \
    || { echo "    FAIL $1 (see $LOG)" | tee -a "$LOG"; backend reachable; exit 1; }
}

: > "$LOG"
if [ "$#" -gt 0 ]; then
  backend reachable
  for flow in "$@"; do run "$flow"; done
  exit 0
fi

# Start from a clean server state for the two synthetic students (LOCAL database only).
node -e "require(process.argv[1]).resetLearningState()" "$APP_DIR/tests/support/localStack"

backend reachable;   run 01_sign_in_and_save
backend unreachable; run 02_offline_quiz; run 03_reopen_offline
backend reachable;   run 04_reconnect_sync; run 05_switch_accounts
backend unreachable; run 06_sign_out_with_unsynced_work
backend reachable;   run 07_sign_in_resumes_sync; run 09_kreyol

# Online reading (Content-Delivery): read without downloading, answer with no connection, restart, reconnect.
node -e "require(process.argv[1]).resetLearningState()" "$APP_DIR/tests/support/localStack"
backend reachable;   run 10_read_online
backend unreachable; run 11_online_answers_offline; run 12_online_restart_offline
backend reachable;   run 13_online_reconnect
echo "ALL FLOWS PASSED ($PLATFORM). Screenshots: $OUT/shots" | tee -a "$LOG"
