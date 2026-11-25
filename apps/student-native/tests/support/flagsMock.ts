/**
 * Stand-in for src/core/experience/flags in tests that need a flag ON.
 * (The real module reads build-time environment variables once, at load.)
 *
 *   jest.mock('../../src/core/experience/flags', () => require('../support/flagsMock').flagsModule);
 *
 * Every flag is off unless a test switches it on; `resetFlags()` in beforeEach.
 * This file imports nothing, so it can be required from a hoisted jest.mock factory.
 */
export const testFlags = {
  onboarding: false,
  tour: false,
  onboardingSync: false,
  dailyWord: false,
  rewards: false,
  leaderboardReview: false,
};

export type TestFlag = keyof typeof testFlags;

export function resetFlags(...on: TestFlag[]): void {
  for (const key of Object.keys(testFlags) as TestFlag[]) testFlags[key] = on.includes(key);
}

export const flagsModule = {
  FLAGS: testFlags,
  anyNetworkFlag: (flags = testFlags) => flags.onboardingSync || flags.dailyWord || flags.rewards,
};
