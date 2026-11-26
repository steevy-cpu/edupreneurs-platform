#!/bin/sh
# Capture the Design-00 preview screenshots on a running device.
#   scripts/design-shots.sh android|ios OUT_DIR
# Needs: Metro running, the DEBUG app installed, previews reachable by deep link.
# Captures only; changes no app data. Font scale / dark appearance are restored at the end.
set -eu
PLATFORM="$1"; OUT="$2"; APP=ht.edupreneur.student.dev
mkdir -p "$OUT"
pause() { perl -e "select(undef,undef,undef,$1)"; }
open_url() {
  if [ "$PLATFORM" = android ]; then
    adb shell am start -a android.intent.action.VIEW -d "'monedupreneur://design/$1'" "$APP" >/dev/null 2>&1
  else
    xcrun simctl openurl booted "monedupreneur://design/$1"
  fi
  pause 3.5
}
snap() {
  if [ "$PLATFORM" = android ]; then adb exec-out screencap -p > "$OUT/$1.png"; else xcrun simctl io booted screenshot "$OUT/$1.png" >/dev/null 2>&1; fi
}
scroll_down() {
  if [ "$PLATFORM" = android ]; then adb shell input swipe 240 600 240 150 400; pause 1.2; fi
}
shot() { open_url "$1"; snap "$2"; }
# shot2: top of the screen, then (Android only) one swipe further down.
shot2() { open_url "$1"; snap "$2"; if [ "$PLATFORM" = android ]; then scroll_down; snap "$2-scrolled"; fi; }

for L in fr ht; do
  shot2 "home?locale=$L" "$L-home"
  shot2 "path?locale=$L" "$L-path"
  shot2 "lesson?locale=$L" "$L-lesson"
  shot  "quiz?locale=$L&state=selected" "$L-quiz-selected"
  shot  "quiz?locale=$L&state=correct" "$L-quiz-correct"
  shot  "quiz?locale=$L&state=incorrect" "$L-quiz-incorrect"
  shot2 "progress?locale=$L" "$L-progress"
done
# states (French)
for S in offline pending loading empty error; do shot "home?locale=fr&state=$S" "state-home-$S"; done
shot2 "path?locale=fr&state=offline" "state-path-offline"
shot "quiz?locale=fr" "state-quiz-idle"
shot "quiz?locale=ht&state=long" "state-quiz-long-ht"
shot "quiz?locale=fr&state=long-correct" "state-quiz-long-correct"
for S in pending failed attention empty; do shot2 "progress?locale=fr&state=$S" "state-progress-$S"; done
# dark theme
for P in home path lesson progress; do shot "$P?locale=fr&theme=dark" "dark-$P"; done
shot "quiz?locale=fr&theme=dark&state=incorrect" "dark-quiz-incorrect"
shot "quiz?locale=ht&theme=dark&state=correct" "dark-quiz-correct-ht"
# narrow widths (only meaningful on a device wider than the requested width)
if [ "$PLATFORM" = ios ]; then
  for W in 320 360; do
    for P in home path lesson progress; do shot "$P?locale=ht&width=$W" "w$W-$P-ht"; done
    shot "quiz?locale=ht&width=$W&state=incorrect" "w$W-quiz-incorrect-ht"
  done
fi
# larger text
set_scale() {
  if [ "$PLATFORM" = android ]; then adb shell settings put system font_scale "$1"; else xcrun simctl ui booted content_size "$2"; fi
  # Restart the app so it starts cleanly at the new text size.
  if [ "$PLATFORM" = android ]; then adb shell am force-stop "$APP"; else xcrun simctl terminate booted "$APP" >/dev/null 2>&1 || true; fi
  pause 2; open_url "home"; pause 8
}
# Android: font_scale is the multiplier itself. iOS: named sizes; React Native maps
# extra-extra-extra-large to 1.35x, accessibility-large to 1.94x, and the largest
# setting to 3.57x, which the design system caps at 2x ("max").
if [ "$PLATFORM" = android ]; then SIZES="1.5:x:150 2.0:x:200"; else SIZES="x:extra-extra-extra-large:135 x:accessibility-large:194 x:accessibility-extra-extra-extra-large:max"; fi
for SC in $SIZES; do
  SC=$(echo "$SC" | tr ':' ' ')
  set -- $SC
  set_scale "$1" "$2"; N="$3"
  shot2 "home?locale=ht" "text$N-home-ht"
  shot2 "path?locale=fr" "text$N-path"
  shot2 "lesson?locale=fr" "text$N-lesson"
  shot  "quiz?locale=ht&state=selected" "text$N-quiz-selected-ht"
  shot2 "quiz?locale=fr&state=incorrect" "text$N-quiz-incorrect"
  shot2 "progress?locale=ht&state=pending" "text$N-progress-ht"
done
set_scale 1.0 large
echo "done: $(ls "$OUT" | wc -l | tr -d ' ') screenshots in $OUT"
