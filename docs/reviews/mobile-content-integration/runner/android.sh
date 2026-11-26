#!/usr/bin/env bash
set -euo pipefail
test "$RUNNER_ENVIRONMENT" = github-hosted
test "$(git rev-parse HEAD)" = "$CANDIDATE"
export JAVA_HOME="$JAVA_HOME_17_X64"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"
export EXPO_PUBLIC_API_URL=http://127.0.0.1:41000
export EXPO_PUBLIC_SUPABASE_URL=http://127.0.0.1:41001
export EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=$(sed -n 's/^LOCAL_SUPABASE_PUBLISHABLE_KEY=//p' .env)
test -n "$EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY"
PASS_A=$(uv run python scripts/dev_login.py student_a | sed -n 's/^password: //p')
test -n "$PASS_A"
echo "::add-mask::$PASS_A"
export PASS_A
image='system-images;android-24;default;x86_64'
sdkmanager "$image" 'platform-tools' 'emulator'
printf 'no\n' | avdmanager create avd --name qa24 --package "$image"
sudo chmod a+rw /dev/kvm
"$ANDROID_HOME/emulator/emulator" -avd qa24 -no-window -no-audio -no-boot-anim -no-snapshot -gpu swiftshader_indirect > "$RUNNER_TEMP/emulator.log" 2>&1 &
emulator_pid=$!
trap 'kill "$emulator_pid" 2>/dev/null || true' EXIT
uv run uvicorn edu_api.main:create_app --factory --host 127.0.0.1 --port 41000 > "$RUNNER_TEMP/qa-api.log" 2>&1 &
api_pid=$!
trap 'kill "$api_pid" "$emulator_pid" 2>/dev/null || true' EXIT
(
  cd apps/student-native
  ./node_modules/.bin/expo prebuild --platform android --no-install
  cd android
  NODE_ENV=production ./gradlew :app:assembleRelease -PreactNativeArchitectures=x86_64 --max-workers=2
)
kill -0 "$api_pid"
curl -fsS "$EXPO_PUBLIC_API_URL/ready" >/dev/null
timeout 240 adb wait-for-device
timeout 240 bash -c 'until adb shell getprop sys.boot_completed | grep -q 1; do sleep 2; done'
test "$(adb shell getprop ro.build.version.sdk | tr -d '\r')" = 24
adb shell wm size 640x1066
adb shell wm density 320
adb shell input keyevent 82
adb reverse tcp:41000 tcp:41000
adb reverse tcp:41001 tcp:41001
adb install apps/student-native/android/app/build/outputs/apk/release/app-release.apk
curl -fsSL --retry 3 https://github.com/mobile-dev-inc/Maestro/releases/download/cli-2.12.1/maestro.zip -o "$RUNNER_TEMP/maestro.zip"
unzip -q "$RUNNER_TEMP/maestro.zip" -d "$RUNNER_TEMP/qa-tools"
maestro="$RUNNER_TEMP/qa-tools/maestro/bin/maestro"
chmod +x "$maestro"
export MAESTRO_CLI_NO_ANALYTICS=1
adb shell wm size > "$EVIDENCE/display.txt"
adb shell wm density >> "$EVIDENCE/display.txt"
printf 'candidate,locale,font_scale,result\n' > "$EVIDENCE/cells.csv"
failed=0
for scale in 1.0 1.3 2.0; do
  adb shell settings put system font_scale "$scale"
  actual=$(adb shell settings get system font_scale | tr -d '\r')
  for lang in fr ht; do
    cell="$EVIDENCE/$lang-$scale"
    mkdir -p "$cell"
    python3 "$QA/runner/flow.py" "$lang" "$cell" > "$RUNNER_TEMP/cell.yaml"
    if [[ "$actual" == "$scale" ]] && "$maestro" test -e PASS_A="$PASS_A" "$RUNNER_TEMP/cell.yaml"; then
      status=pass
    else
      status=fail
      failed=1
    fi
    printf '%s,%s,%s,%s\n' "$CANDIDATE" "$lang" "$actual" "$status" >> "$EVIDENCE/cells.csv"
  done
done
exit "$failed"
