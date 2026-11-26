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
