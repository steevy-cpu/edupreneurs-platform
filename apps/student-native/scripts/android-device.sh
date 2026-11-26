# Sourced by the Android scripts. ADB is the path to the platform-tools executable.
select_android() {
  : "${ANDROID_SERIAL:?Set ANDROID_SERIAL to the exact serial from adb devices}"
  [[ "$("$ADB" -s "$ANDROID_SERIAL" get-serialno)" = "$ANDROID_SERIAL" ]] || return 1
}

device_adb() { "$ADB" -s "$ANDROID_SERIAL" "$@"; }

android_backend() {
  local port
  for port in "$FASTAPI_PORT" "$AUTH_PORT"; do
    if [[ "$1" = reachable ]]; then
      device_adb reverse "tcp:$port" "tcp:$port" || return 1
    else
      device_adb reverse --remove "tcp:$port" || return 1
    fi
  done
}
