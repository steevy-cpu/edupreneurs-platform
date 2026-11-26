/** Client flags: everything new is OFF unless a build switches it on. */
const NAMES = ['ONBOARDING', 'TOUR', 'ONBOARDING_SYNC', 'DAILY_WORD', 'REWARDS', 'LEADERBOARD_REVIEW'];

function load(env: Record<string, string>) {
  const saved = { ...process.env };
  for (const name of NAMES) delete process.env[`EXPO_PUBLIC_FF_${name}`];
  Object.assign(process.env, env);
  let loaded!: typeof import('../../src/core/experience/flags');
  jest.isolateModules(() => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    loaded = require('../../src/core/experience/flags');
  });
  process.env = saved;
  return loaded;
}

test('with no configuration every flag is off', () => {
  const { FLAGS, anyNetworkFlag } = load({});
  expect(FLAGS).toEqual({ onboarding: false, tour: false, onboardingSync: false, dailyWord: false, rewards: false, leaderboardReview: false });
  expect(anyNetworkFlag()).toBe(false);
});

test('a flag is on only for "1" or "true"; each flag has its own variable', () => {
  const { FLAGS, anyNetworkFlag } = load({ EXPO_PUBLIC_FF_ONBOARDING: '1', EXPO_PUBLIC_FF_TOUR: 'yes', EXPO_PUBLIC_FF_REWARDS: '0', EXPO_PUBLIC_FF_DAILY_WORD: 'true' });
  expect(FLAGS).toEqual({ onboarding: true, tour: false, onboardingSync: false, dailyWord: true, rewards: false, leaderboardReview: false });
  expect(anyNetworkFlag()).toBe(true);
  // The local features alone never open a network path.
  expect(load({ EXPO_PUBLIC_FF_ONBOARDING: '1', EXPO_PUBLIC_FF_TOUR: '1', EXPO_PUBLIC_FF_LEADERBOARD_REVIEW: '1' }).anyNetworkFlag()).toBe(false);
});
