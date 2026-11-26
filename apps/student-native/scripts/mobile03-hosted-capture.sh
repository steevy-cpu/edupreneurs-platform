#!/usr/bin/env bash
# Hosted CI only: captures real application routes using the existing Maestro journey.
# Partial coverage is reported honestly in the manifest; no design fixtures are opened.
set -euo pipefail
ROOT="${1:?source checkout required}"
OUT="${2:?evidence directory required}"
KIND="${3:?baseline or candidate required}"
mkdir -p "$OUT"
SHA=$(git -C "$ROOT" rev-parse HEAD)
export ANDROID_SERIAL=emulator-5554
export EDU_DEV_VOLUME="$RUNNER_TEMP/mobile03-dev"
mkdir -p "$EDU_DEV_VOLUME"
ln -s "$ANDROID_HOME" "$EDU_DEV_VOLUME/android-sdk"
mkdir -p "$EDU_DEV_VOLUME/android-avd" "$EDU_DEV_VOLUME/gradle" "$EDU_DEV_VOLUME/caches/uv" "$EDU_DEV_VOLUME/caches/npm"
export E2E_OUT="$OUT/runs"
adb -s "$ANDROID_SERIAL" wait-for-device
adb -s "$ANDROID_SERIAL" shell wm size 480x800
adb -s "$ANDROID_SERIAL" shell wm density 240
adb -s "$ANDROID_SERIAL" install -r "$ROOT/apps/student-native/android/app/build/outputs/apk/release/app-release.apk" || exit 1
adb -s "$ANDROID_SERIAL" shell getprop ro.build.version.sdk > "$OUT/api.txt"
test "$(tr -d '\r\n' < "$OUT/api.txt")" = 24
wc -c < "$ROOT/apps/student-native/android/app/build/outputs/apk/release/app-release.apk" > "$OUT/apk-bytes.txt"
adb -s "$ANDROID_SERIAL" shell wm size > "$OUT/size.txt"
adb -s "$ANDROID_SERIAL" shell wm density > "$OUT/density.txt"
grep -q "480x800" "$OUT/size.txt"
grep -q "240" "$OUT/density.txt"
printf '%s\n' "$SHA" > "$OUT/commit.txt"
printf '%s\n' "$KIND" > "$OUT/build.txt"
# Indicative only: cold launches to the signed-out screen, no student data.
for run in 1 2 3; do
  adb -s "$ANDROID_SERIAL" shell am force-stop ht.edupreneur.student.dev
  adb -s "$ANDROID_SERIAL" shell am start -W -n ht.edupreneur.student.dev/.MainActivity > "$OUT/cold-start-$run.txt"
done
adb -s "$ANDROID_SERIAL" shell dumpsys meminfo ht.edupreneur.student.dev > "$OUT/meminfo.txt"
# Independent signed-out capture: verify the real UI hierarchy before saving pixels.
# This can provide partial evidence even if the Maestro journey fails.
capture_signed_out() {
  local directory="$1" attempt
  mkdir -p "$directory/shots"
  adb -s "$ANDROID_SERIAL" shell pm clear ht.edupreneur.student.dev > /dev/null || return 1
  adb -s "$ANDROID_SERIAL" shell am start -n ht.edupreneur.student.dev/.MainActivity > /dev/null || return 1
  for attempt in $(seq 1 12); do
    sleep 5
    if adb -s "$ANDROID_SERIAL" shell uiautomator dump /sdcard/mobile03-window.xml > /dev/null 2>&1 && \
       adb -s "$ANDROID_SERIAL" shell cat /sdcard/mobile03-window.xml | grep -q 'sign-in-email'; then
      adb -s "$ANDROID_SERIAL" exec-out screencap -p > "$directory/shots/00-sign-in.png" || return 1
      return 0
    fi
  done
  return 1
}
failed=0
for scale in 1.0 1.3 2.0; do
  adb -s "$ANDROID_SERIAL" shell settings put system font_scale "$scale"
  actual_scale=$(adb -s "$ANDROID_SERIAL" shell settings get system font_scale | tr -d '\r\n')
  test "$actual_scale" = "$scale"
  export E2E_OUT="$OUT/runs/$scale"
  mkdir -p "$E2E_OUT"
  if capture_signed_out "$E2E_OUT/run.direct"; then
    printf 'passed\n' > "$E2E_OUT/run.direct/result.txt"
  else
    printf 'failed\n' > "$E2E_OUT/run.direct/result.txt"
    echo "Signed-out UI capture failed at font scale $scale"
    failed=1
  fi
  if (cd "$ROOT" && apps/student-native/scripts/e2e-run.sh android); then
    printf 'passed\n' > "$E2E_OUT/result.txt"
  else
    printf 'failed\n' > "$E2E_OUT/result.txt"
    # Report categories only: the original Maestro logs can include synthetic credentials.
    python3 - "$E2E_OUT" <<'PYDIAG'
from pathlib import Path
import re, sys
logs = list(Path(sys.argv[1]).glob('run.*/journey.log'))
checks = {
    'Maestro CLI option or usage error': r'unknown option|unknown argument|usage:',
    'Java or binary compatibility error': r'UnsupportedClassVersionError|Exec format error|NoClassDefFoundError',
    'Maestro executable missing or permission denied': r'No such file or directory|Permission denied',
    'UI element or assertion failure': r'Element not found|Assertion is false|Assertion failed|not visible',
    'Maestro driver or connection failure': r'Unable to connect|failed to connect|Unable to start|driver.*fail',
    'Application launch failure': r'Failed to launch|Unable to launch|app.*crash',
}
for log in logs:
    data = log.read_text(errors='replace')
    found = [label for label, pattern in checks.items() if re.search(pattern, data, re.I)]
    exceptions = sorted(set(re.findall(r'\b[A-Za-z][A-Za-z0-9_.]*(?:Exception|Error)\b', data)))
    print('Safe failure categories:', ', '.join(found) or 'unclassified')
    print('Exception type names:', ', '.join(exceptions) or 'none')
PYDIAG
    failed=1
  fi
done
# The known existing flow only covers some requested screen/locale combinations.
# Screenshots remain in each run directory with their original Maestro names.
export MOBILE03_ROOT="$OUT" MOBILE03_SHA="$SHA" MOBILE03_KIND="$KIND"
python3 - <<'PY'
import datetime, json, os
from pathlib import Path
root = Path(os.environ['MOBILE03_ROOT'])
captures = []
for path in sorted(root.glob('runs/*/run.*/shots/*.png')):
    scale = path.parts[-4]
    state = path.stem
    locale = 'ht' if state.startswith(('30-', '31-', '32-', '33-', '34-')) else 'fr'
    is_direct = path.parts[-3] == 'run.direct'
    result_file = root / 'runs' / scale / ('run.direct/result.txt' if is_direct else 'result.txt')
    result = result_file.read_text().strip()
    captures.append({'file': str(path.relative_to(root)), 'commit_sha': os.environ['MOBILE03_SHA'],
        'api_level': 24, 'device': 'GitHub-hosted emulator, x86_64, 1024 MB configured',
        'physical_size_px': '480x800', 'density_dpi': 240, 'logical_width_dp': 320,
        'locale': locale, 'font_scale': scale, 'screen_and_state': state,
        'feature_flags': 'all optional learner flags off; design preview off',
        'captured_at_utc': datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc).isoformat(),
        'journey_result': result, 'verification_method': 'UI hierarchy check' if is_direct else 'Maestro journey'})
if not captures:
    print('No screenshots captured; evidence remains incomplete.')
(root / 'capture-manifest.json').write_text(json.dumps({'build': os.environ['MOBILE03_KIND'],
    'captures': captures, 'limitations': 'Existing Maestro journeys only; not the complete requested matrix. Inspect failed journey logs; no claim of TalkBack or large-screen coverage.'}, indent=2)+'\n')
PY
compgen -G "$OUT/runs/*/run.*/shots/*.png" > /dev/null || failed=1
exit "$failed"
