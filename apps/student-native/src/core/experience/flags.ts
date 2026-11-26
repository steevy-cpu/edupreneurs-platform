/**
 * Client feature flags for the learner-experience additions (overnight 2026-11-24).
 *
 * EVERY flag defaults to OFF. With all of them off the app behaves exactly as
 * Mobile-02: no new screen is reachable, no new request is made, and the
 * existing screens draw what they drew before.
 *
 * A flag is switched on at BUILD time with `EXPO_PUBLIC_FF_<NAME>=1` (the same
 * mechanism as the other EXPO_PUBLIC_* settings). The references below are
 * written out one by one because Expo only inlines `process.env.EXPO_PUBLIC_X`
 * when it appears literally in the source.
 *
 *   onboarding          local first-run flow (no network needed)
 *   tour                local product tour (no network needed)
 *   onboardingSync      NETWORK: PATCH /v1/me, GET/PUT /v1/me/onboarding
 *   dailyWord           NETWORK: GET /v1/daily-word (the cached word stays readable offline)
 *   rewards             NETWORK: GET /v1/rewards/summary
 *   leaderboardReview   the leaderboard REVIEW screen (not wired to real learners)
 */
export interface Flags {
  onboarding: boolean;
  tour: boolean;
  onboardingSync: boolean;
  dailyWord: boolean;
  rewards: boolean;
  leaderboardReview: boolean;
}

function on(value: string | undefined): boolean {
  return value === '1' || value === 'true';
}

export const FLAGS: Readonly<Flags> = {
  onboarding: on(process.env.EXPO_PUBLIC_FF_ONBOARDING),
  tour: on(process.env.EXPO_PUBLIC_FF_TOUR),
  onboardingSync: on(process.env.EXPO_PUBLIC_FF_ONBOARDING_SYNC),
  dailyWord: on(process.env.EXPO_PUBLIC_FF_DAILY_WORD),
  rewards: on(process.env.EXPO_PUBLIC_FF_REWARDS),
  leaderboardReview: on(process.env.EXPO_PUBLIC_FF_LEADERBOARD_REVIEW),
};

/** True when at least one flag that talks to the server is on. */
export function anyNetworkFlag(flags: Flags = FLAGS): boolean {
  return flags.onboardingSync || flags.dailyWord || flags.rewards;
}
