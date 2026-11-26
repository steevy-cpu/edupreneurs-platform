#!/usr/bin/env bash
# Exercise the candidate's Android adapter using a recorder in place of ADB.
set -euo pipefail
app=$(cd "${1:?Pass the candidate checkout}/apps/student-native" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export QA_ADB_RECORD="$tmp/commands"
export ANDROID_SERIAL=qa-emulator-recording
ADB="$tmp/record-adb"
cat > "$ADB" <<'RECORDER'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$QA_ADB_RECORD"
if [[ "$3" = get-serialno ]]; then printf '%s\n' qa-emulator-recording; fi
RECORDER
chmod +x "$ADB"

ports=$(cd "$app" && node <<'NODE'
const assert = require('node:assert/strict');
const { deriveTarget } = require('./tests/support/localStack');
const { deviceTarget } = require('./scripts/e2e-target');
const configText = 'project_id = "qa-recorder"\n[api]\nport = 41401\n[db]\nport = 41402';
const env = {
  LOCAL_ADMIN_DATABASE_URL: 'postgresql://qa@localhost:41402/postgres',
  EDU_DATABASE_URL: 'postgresql+asyncpg://qa@localhost:41402/postgres',
  LOCAL_SUPABASE_URL: 'http://localhost:41401',
  EDU_AUTH_ISSUER: 'http://localhost:41401/auth/v1',
  EDU_AUTH_JWKS_URL: 'http://localhost:41401/auth/v1/.well-known/jwks.json',
};
const input = { configText, env, processEnv: { EDU_MOBILE_TEST_API_PORT: '41400' },
  getPorts: (_, internal) => [internal === 5432 ? 41402 : 41401] };
const target = deriveTarget(input);
assert.throws(() => deriveTarget({ ...input, env: { ...env,
  EDU_DATABASE_URL: 'postgresql+asyncpg://qa@localhost:41502/postgres' } }), /EDU_DATABASE_URL/);
const mobile = { EXPO_PUBLIC_API_URL: 'http://localhost:41400',
  EXPO_PUBLIC_SUPABASE_URL: 'http://localhost:41401' };
assert.throws(() => deviceTarget(target, mobile,
  { EXPO_PUBLIC_SUPABASE_URL: 'http://localhost:41501' }, ['localhost']), /override/);
const checked = deviceTarget(target, mobile, {}, ['localhost']);
console.log(checked.fastApiPort, checked.apiPort);
NODE
)
read -r FASTAPI_PORT AUTH_PORT <<< "$ports"
. "$app/scripts/android-device.sh"
select_android
android_backend reachable
android_backend unreachable
if (ANDROID_SERIAL=qa-wrong-serial; select_android); then exit 1; fi

cat > "$tmp/expected" <<'EXPECTED'
-s qa-emulator-recording get-serialno
-s qa-emulator-recording reverse tcp:41400 tcp:41400
-s qa-emulator-recording reverse tcp:41401 tcp:41401
-s qa-emulator-recording reverse --remove tcp:41400
-s qa-emulator-recording reverse --remove tcp:41401
-s qa-wrong-serial get-serialno
EXPECTED
diff -u "$tmp/expected" "$QA_ADB_RECORD"
cat "$QA_ADB_RECORD"

# Run the production evidence helper and flow collection against a recording Maestro.
# The two simulated checkouts share a temporary volume and invoke the same flow name.
unset E2E_OUT E2E_LOG
EDU_DEV_VOLUME="$tmp/volume"
PLATFORM=android
APP_DIR="$app"
ENVS=(-e QA_RECORDING=1)
MAESTRO="$tmp/record-maestro"
cat > "$MAESTRO" <<'MAESTRO'
#!/usr/bin/env bash
set -eu
test "$1" = --device
test "$3" = test
test "$4" = --test-output-dir
mkdir -p "$5/takeScreenshot/shots"
printf '%s\n' "$2" > "$5/takeScreenshot/shots/review.png"
MAESTRO
chmod +x "$MAESTRO"
. "$app/scripts/e2e-output.sh"
sed -n '/^run() {/,/^}/p' "$app/scripts/e2e-run.sh" > "$tmp/run-function.sh"
. "$tmp/run-function.sh"

DEVICE=qa-device-one
ROOT="$tmp/checkout-one"
prepare_e2e_output
first_out=$OUT
first_log=$LOG
run shared-flow
printf '%s\n' sentinel >> "$first_log"
DEVICE=qa-device-two
ROOT="$tmp/checkout-two"
prepare_e2e_output
test "$OUT" != "$first_out"
test "$LOG" != "$first_log"
run shared-flow
grep -Fxq sentinel "$first_log"
test "$(cat "$first_out/shots/review.png")" = qa-device-one
test "$(cat "$OUT/shots/review.png")" = qa-device-two
# Explicit log overrides append, including when multiple invocations share a log.
E2E_LOG="$tmp/explicit.log"
printf '%s\n' sentinel > "$E2E_LOG"
prepare_e2e_output
grep -Fxq sentinel "$E2E_LOG"
echo 'Distinct default logs and captures verified. Explicit log sentinel preserved.'
