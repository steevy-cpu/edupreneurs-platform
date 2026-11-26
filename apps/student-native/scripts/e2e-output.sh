# Keep logs, screenshots and Maestro output together for one invocation.
prepare_e2e_output() {
  local parent="${E2E_OUT:-$EDU_DEV_VOLUME/shots/mobile-02/$PLATFORM}"
  mkdir -p "$parent"
  parent=$(cd "$parent" && pwd)
  OUT=$(mktemp -d "$parent/run.XXXXXXXX")
  LOG="${E2E_LOG:-$OUT/journey.log}"
  mkdir -p "$OUT/shots" "$(dirname "$LOG")"
  echo "Device $DEVICE, checkout $ROOT, evidence $OUT" | tee -a "$LOG"
}
