/**
 * Opt-in timing marks for MEASUREMENT builds only.
 *
 * A build made with EXPO_PUBLIC_PERF_LOG=1 prints lines such as
 *   [perf] home_ready               Home has been drawn from SQLite (compare its log
 *                                   timestamp with the system's "Start proc" line)
 *   [perf] lesson_open_ms=11        tap handler → lesson content committed (JavaScript
 *                                   side only: excludes touch delivery and frame painting)
 * to the device log. In every other build `ENABLED` is the constant `false`
 * and these functions do nothing: no timing, no logging, no stored data.
 */
const ENABLED = process.env.EXPO_PUBLIC_PERF_LOG === '1';
let tappedAt = 0;
let homeReported = false;

/** Call when the student taps something whose result is timed. */
export function perfTap(): void {
  if (ENABLED) tappedAt = Date.now();
}

/** Time since the last perfTap(), logged once per tap. */
export function perfSinceTap(name: string): void {
  if (!ENABLED || tappedAt === 0) return;
  // eslint-disable-next-line no-console
  console.log(`[perf] ${name}=${Date.now() - tappedAt}`);
  tappedAt = 0;
}

/** Marks the moment Home is drawn, once per app start. */
export function perfHomeReady(): void {
  if (!ENABLED || homeReported) return;
  homeReported = true;
  // eslint-disable-next-line no-console
  console.log('[perf] home_ready');
}
