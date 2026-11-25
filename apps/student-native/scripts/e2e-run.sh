#!/bin/bash
# Run the Mobile-02 UI journey with Maestro against the app ALREADY installed
# on a running Android emulator or iOS simulator. Local stack only.
#
#   apps/student-native/scripts/e2e-run.sh android [flow ...]
#   apps/student-native/scripts/e2e-run.sh ios     [flow ...]
#
# With no flow names it runs the whole journey, switching the backend between
# reachable and unreachable where a flow needs it:
#   android  removes / restores the emulator's port forwards (API 8000, Auth 54321)
#   android + E2E_OFFLINE=airplane   real airplane mode (for standalone release builds)
#   ios      stops / starts the local API process and pauses / unpauses the Auth gateway
# Passwords for the two synthetic students are generated here and never printed.
set -euo pipefail

PLATFORM="${1:?usage: e2e-run.sh android|ios [flow ...]}"; shift || true
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$APP_DIR/../.." && pwd)"
# shellcheck disable=SC1091
. "$ROOT/scripts/dev-env.sh" >/dev/null 2>&1

# Derive the database containers from THIS checkout (never a hard-coded shared stack name).
PROJECT_ID="$(awk -F'"' '/^project_id[[:space:]]*=/ {print $2; exit}' "$ROOT/supabase/config.toml")"
DB_PORT="$(awk '/^\[/{s=$0} s=="[db]" && /^port[[:space:]]*=/ {gsub(/[^0-9]/,"",$3); print $3; exit}' "$ROOT/supabase/config.toml")"
ENV_DB_PORT="$(sed -n 's/^LOCAL_ADMIN_DATABASE_URL=.*@[^:]*:\([0-9]*\)\/.*/\1/p' "$ROOT/.env" | head -1)"
[ -n "$PROJECT_ID" ] || { echo "refusing: no project_id in supabase/config.toml" >&2; exit 1; }
if [ "$PROJECT_ID" = mon-edupreneur ] && [ "${EDU_TEST_ALLOW_SHARED_STACK:-}" != 1 ]; then
  echo "refusing: project_id is the shared stack mon-edupreneur (set EDU_TEST_ALLOW_SHARED_STACK=1 to override)" >&2; exit 1
fi
[ -n "$DB_PORT" ] && [ "$DB_PORT" = "$ENV_DB_PORT" ] || { echo "refusing: root .env database port ($ENV_DB_PORT) != supabase/config.toml [db] port ($DB_PORT)" >&2; exit 1; }
DB_CONTAINER="supabase_db_$PROJECT_ID"; KONG_CONTAINER="supabase_kong_$PROJECT_ID"
docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER" || { echo "refusing: container $DB_CONTAINER is not running (make start)" >&2; exit 1; }
echo "e2e target stack: $PROJECT_ID ($DB_CONTAINER, db port $DB_PORT)" >&2
MAESTRO="$ROOT/.tools/maestro/bin/maestro"
ADB="$ANDROID_HOME/platform-tools/adb"
OUT="${E2E_OUT:-$EDU_DEV_VOLUME/shots/mobile-02/$PLATFORM}"
LOG="${E2E_LOG:-$EDU_DEV_VOLUME/logs/mobile02-e2e-$PLATFORM.log}"
mkdir -p "$OUT/shots"

password() { (cd "$ROOT" && make -s dev-login ACCOUNT="$1" 2>/dev/null | awk '/^password:/ {print $2}'); }
PASS_A="$(password student_a)"; PASS_B="$(password student_b)"
ENVS=(-e EMAIL=student.a@edupreneur.test -e "PASSWORD=$PASS_A" -e EMAIL_B=student.b@edupreneur.test -e "PASSWORD_B=$PASS_B")

api_up() { curl -s --max-time 2 http://127.0.0.1:8000/ready | grep -q ready; }
backend() { # reachable | unreachable
  if [ "$PLATFORM" = android ] && [ "${E2E_OFFLINE:-}" = airplane ]; then
    # Release builds reach the Mac at 10.0.2.2, so "offline" is real airplane mode on the emulator.
    if [ "$1" = unreachable ]; then
      # (This emulator image has no Wi-Fi radio; mobile data is its only network.)
      "$ADB" shell svc data disable >/dev/null 2>&1 || true
      "$ADB" shell settings put global airplane_mode_on 1
      "$ADB" shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true >/dev/null 2>&1 || true
    else
      "$ADB" shell settings put global airplane_mode_on 0
      "$ADB" shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false >/dev/null 2>&1 || true
      "$ADB" shell svc data enable >/dev/null 2>&1 || true
      for _ in $(seq 1 30); do "$ADB" shell ping -c 1 -W 1 10.0.2.2 >/dev/null 2>&1 && break; sleep 1; done
    fi
    echo "    airplane mode: $("$ADB" shell settings get global airplane_mode_on | tr -d '\r'); ping Mac: $("$ADB" shell ping -c 1 -W 1 10.0.2.2 >/dev/null 2>&1 && echo ok || echo unreachable)" | tee -a "$LOG"
  elif [ "$PLATFORM" = android ]; then
    if [ "$1" = unreachable ]; then
      "$ADB" reverse --remove tcp:8000 >/dev/null 2>&1 || true
      "$ADB" reverse --remove tcp:54321 >/dev/null 2>&1 || true
    else
      "$ADB" reverse tcp:8000 tcp:8000 >/dev/null; "$ADB" reverse tcp:54321 tcp:54321 >/dev/null
    fi
  else
    if [ "$1" = unreachable ]; then
      pkill -f 'uvicorn edu_api.main' >/dev/null 2>&1 || true
      docker pause "$KONG_CONTAINER" >/dev/null 2>&1 || true
    else
      docker unpause "$KONG_CONTAINER" >/dev/null 2>&1 || true
      if ! api_up; then
        (cd "$ROOT" && nohup make api > "$EDU_DEV_VOLUME/logs/mobile02-api.log" 2>&1 < /dev/null &)
        for _ in $(seq 1 30); do api_up && break; sleep 1; done
      fi
    fi
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
  (cd "$OUT" && "$MAESTRO" test "${ENVS[@]}" "$APP_DIR/e2e/$1.yaml") >> "$LOG" 2>&1 \
    && { collect "$1"; echo "    PASS $1" | tee -a "$LOG"; } \
    || { echo "    FAIL $1 (see $LOG)" | tee -a "$LOG"; backend reachable; exit 1; }
}

: > "$LOG"
if [ "$#" -gt 0 ]; then
  for flow in "$@"; do run "$flow"; done
  exit 0
fi

# Start from a clean server state for the two synthetic students (LOCAL database only).
docker exec "$DB_CONTAINER" psql -U postgres -q -c \
  'TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed, app.lesson_progress, app.account_sync_state' >/dev/null

backend reachable;   run 01_sign_in_and_save
backend unreachable; run 02_offline_quiz; run 03_reopen_offline
backend reachable;   run 04_reconnect_sync; run 05_switch_accounts
backend unreachable; run 06_sign_out_with_unsynced_work
backend reachable;   run 07_sign_in_resumes_sync; run 09_kreyol
echo "ALL FLOWS PASSED ($PLATFORM). Screenshots: $OUT/shots" | tee -a "$LOG"
