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
export ANDROID_AVD_HOME="$RUNNER_TEMP/avd"
mkdir -p "$ANDROID_AVD_HOME"
sdkmanager "$image" 'platform-tools' 'emulator'
printf 'no\n' | avdmanager create avd --name qa24 --package "$image"
sudo chmod a+rw /dev/kvm
adb start-server
"$ANDROID_HOME/emulator/emulator" -list-avds | grep -Fx qa24
df -h "$ANDROID_AVD_HOME"
# API 24 has no use for Vulkan. Force headless software rendering.
"$ANDROID_HOME/emulator/emulator" -avd qa24 -port 5554 -memory 1024 -cores 2 \
  -no-window -no-audio -no-boot-anim -no-snapshot -no-metrics -feature -Vulkan \
  -gpu swiftshader_indirect > "$RUNNER_TEMP/emulator.log" 2>&1 &
emulator_pid=$!
api_pid=''
cleanup() {
  rc=$?
  if (( rc != 0 )); then
    tail -80 "$RUNNER_TEMP/emulator.log"
    adb devices -l
  fi
  kill "$emulator_pid" 2>/dev/null || true
  if [[ -n "$api_pid" ]]; then kill "$api_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT
export ANDROID_SERIAL=emulator-5554
for ((i=0; i<150; i++)); do
  kill -0 "$emulator_pid" || { echo 'Emulator exited during boot'; exit 1; }
  if [[ $(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r') == 1 ]]; then break; fi
  sleep 2
done
test "$(adb shell getprop sys.boot_completed | tr -d '\r')" = 1
test "$(adb shell getprop ro.build.version.sdk | tr -d '\r')" = 24
uv run uvicorn edu_api.main:create_app --factory --host 127.0.0.1 --port 41000 > "$RUNNER_TEMP/qa-api.log" 2>&1 &
api_pid=$!
(
  cd apps/student-native
  ./node_modules/.bin/expo prebuild --platform android --no-install
  cd android
  NODE_ENV=production ./gradlew :app:assembleRelease -PreactNativeArchitectures=x86_64 --max-workers=2
)
kill -0 "$api_pid"
curl -fsS "$EXPO_PUBLIC_API_URL/ready" >/dev/null
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
    flowdir="$RUNNER_TEMP/flows-$lang-$scale"
    mkdir -p "$flowdir"
    python3 "$QA/runner/flow.py" "$lang" "$flowdir"
    status=pass
    for screen in home learn reader quiz review; do
      if [[ "$actual" == "$scale" ]] && timeout 240 "$maestro" test -e PASS_A="$PASS_A" "$flowdir/$screen.yaml"; then
        timeout 15 adb exec-out screencap -p > "$cell/$lang-$scale-$screen.png"
        test -s "$cell/$lang-$scale-$screen.png"
        echo "Reached $lang $scale $screen"
      else
        echo "Stopped at $lang $scale $screen"
        timeout 15 adb exec-out screencap -p > "$cell/failure.png"
        status=fail
        failed=1
        break
      fi
    done
    echo "Device cell $lang at $actual: $status"
    printf '%s,%s,%s,%s\n' "$CANDIDATE" "$lang" "$actual" "$status" >> "$EVIDENCE/cells.csv"
  done
done
exit "$failed"
