/**
 * Gold on the phone: a copy of what the server confirmed, and nothing else.
 * Real SQLite; the server is an in-memory stand-in with synthetic numbers
 * (the rewards lane's endpoint is not on this branch).
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { ApiError } from '../../src/core/api/errors';
import { AccountStore } from '../../src/core/db/accountStore';
import { ExperienceApi, parseRemoteRewardsSummary } from '../../src/core/experience/remote';
import { refreshRewards, REWARDS_RETRY_AFTER_MS, rewardsView, streakDisplay } from '../../src/core/experience/rewards';
import { FakeRemote, sampleRewards } from '../support/experienceHarness';
import { nodeDatabases } from '../support/nodeSqlite';

const A = 'a0000000-0000-4000-8000-00000000000a';
const B = 'a0000000-0000-4000-8000-00000000000b';

let dir: string;
let account: AccountStore;
let remote: FakeRemote;
let clock: number;
const env = { now: () => new Date(clock) };

beforeEach(async () => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'edu-gold-'));
  account = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
  remote = new FakeRemote();
  remote.rewards = sampleRewards(120);
  clock = Date.parse('2026-11-24T15:00:00.000Z');
});
afterEach(async () => {
  await account.close().catch(() => undefined);
  fs.rmSync(dir, { recursive: true, force: true });
});

const view = async (pending = 0) => rewardsView(await account.experience.getRewards(), pending);

describe('confirmed versus pending', () => {
  test('before any summary there is no number at all, only the count of waiting actions', async () => {
    expect(await view(3)).toEqual({ confirmed: null, pendingActions: 3 });
  });

  test('the confirmed balance is exactly the server’s, whatever is waiting on the phone', async () => {
    expect(await refreshRewards(account, remote, env)).toBe('updated');
    for (const pending of [0, 1, 25]) {
      const shown = await view(pending);
      expect(shown.confirmed).toMatchObject({ balance: 120, streak: { current: 3, longest: 7 }, achievements: 2 });
      expect(shown.pendingActions).toBe(pending);
    }
    // The view has no field in which a locally computed Gold amount could travel.
    expect(Object.keys(await view(5)).sort()).toEqual(['confirmed', 'pendingActions']);
  });

  test('offline: the last confirmed balance stays, with the time it was confirmed', async () => {
    await refreshRewards(account, remote, env);
    const confirmedAt = (await view()).confirmed!.fetchedAt;
    remote.mode = 'offline';
    remote.rewards = sampleRewards(999, { streak: null, achievements: 0 });
    clock += REWARDS_RETRY_AFTER_MS;
    expect(await refreshRewards(account, remote, env)).toBe('unreachable');
    expect((await view()).confirmed).toMatchObject({ balance: 120, fetchedAt: confirmedAt });
  });

  test('feature off on the server (404): nothing is shown and nothing is invented', async () => {
    remote.rewards = null;
    expect(await refreshRewards(account, remote, env)).toBe('unavailable');
    expect((await view(2)).confirmed).toBeNull();
  });
});

describe('review M5: a streak is only "in progress" while the copy is recent', () => {
  const copy = (fetchedAt: string, over = {}) => ({ ...sampleRewards(120, over), fetchedAt });
  test('less than a day old: current; older: as of the server’s date; older with no date: omitted; zero: never', () => {
    const at = new Date('2026-11-12T15:00:00.000Z');
    expect(streakDisplay(copy('2026-11-12T10:00:00.000Z'), at)).toEqual({ kind: 'current', days: 3 });
    expect(streakDisplay(copy('2026-11-01T10:00:00.000Z', { today: '2026-11-01' }), at)).toEqual({ kind: 'as_of', days: 3, date: '2026-11-01' });
    expect(streakDisplay(copy('2026-11-01T10:00:00.000Z', { today: null }), at)).toEqual({ kind: 'none' });
    expect(streakDisplay(copy('2026-11-12T10:00:00.000Z', { streak: { current: 0, longest: 9 } }), at)).toEqual({ kind: 'none' });
    // a phone clock that went backwards is not evidence that the copy is recent
    expect(streakDisplay(copy('2026-11-20T10:00:00.000Z', { today: '2026-11-20' }), at)).toEqual({ kind: 'as_of', days: 3, date: '2026-11-20' });
  });
});

describe('when the summary is downloaded', () => {
  test('not again within ten minutes — unless work was synchronised in between', async () => {
    await refreshRewards(account, remote, env);
    remote.calls.length = 0;
    clock += REWARDS_RETRY_AFTER_MS - 1;
    expect(await refreshRewards(account, remote, env)).toBe('throttled');
    expect(remote.calls).toEqual([]);

    // A sync run confirmed work: the ledger may have changed, so one download is due at once.
    remote.rewards = sampleRewards(140, { streak: { current: 4, longest: 7 } });
    await account.markSynced(new Date(clock).toISOString());
    clock += 1000;
    expect(await refreshRewards(account, remote, env)).toBe('updated');
    expect((await view()).confirmed?.balance).toBe(140);

    clock += REWARDS_RETRY_AFTER_MS;
    expect(await refreshRewards(account, remote, env)).toBe('updated');
  });

  test('a session that ended during the request stores nothing', async () => {
    expect(await refreshRewards(account, remote, { ...env, isActive: () => false })).toBe('aborted');
    expect(await account.experience.getRewards()).toBeNull();
  });

  test('the copy is per account and survives a restart', async () => {
    await refreshRewards(account, remote, env);
    await account.close();
    const other = await AccountStore.open(await nodeDatabases(dir)(`account-${B}`), B);
    expect(await other.experience.getRewards()).toBeNull();
    await other.close();
    account = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
    expect((await view()).confirmed?.balance).toBe(120);
  });
});

describe('response validation (assumed contract, briefs/rewards.md)', () => {
  test('accepts the documented shape; achievements are counted, extra fields are ignored', () => {
    expect(
      parseRemoteRewardsSummary({
        balance: 120,
        streak: { current: 3, longest: 7 },
        achievements: [{ code: 'first_lesson_completed', awarded_at: '2026-11-20T10:00:00Z' }, { code: 'x' }, 'junk'],
        recent: [{ amount: 10, rule_code: 'first_correct_answer' }],
        pending: 500, // a server would not send this; if anything did, it is not read
      }),
    ).toEqual({ balance: 120, streak: { current: 3, longest: 7 }, achievements: 2, today: null, up_to_date: true, rules_status: null });
  });

  test('accepts the summary as the rewards lane currently sends it', () => {
    const parsed = parseRemoteRewardsSummary({
      balance: 35,
      lifetime_earned: 40,
      streak: { current_days: 2, longest_days: 6, last_active_day: '2026-11-24', active_today: true },
      achievements: [{ code: 'first_lesson_completed', titles: { fr: 'x', ht: 'y' }, earned_at: '2026-11-20T10:00:00Z', gold: 5 }],
      recent: [{ id: 'e1', kind: 'award', amount: 5, source: 'question_first_correct' }],
      today: '2026-11-24',
      up_to_date: false,
      rules_status: 'provisional',
    });
    expect(parsed).toEqual({ balance: 35, streak: { current: 2, longest: 6 }, achievements: 1, today: '2026-11-24', up_to_date: false, rules_status: 'provisional' });
    // what the phone stores is what it reads back
    expect(parseRemoteRewardsSummary(JSON.parse(JSON.stringify(parsed)))).toEqual(parsed);
  });

  test('accepts the flat streak spelling, and a missing streak', () => {
    expect(parseRemoteRewardsSummary({ balance: 0, current_streak: 2, longest_streak: 5 })).toMatchObject({ balance: 0, streak: { current: 2, longest: 5 }, achievements: 0 });
    expect(parseRemoteRewardsSummary({ balance: 5 })).toMatchObject({ balance: 5, streak: null, achievements: 0 });
    // "longest" can never be shown smaller than "current"
    expect(parseRemoteRewardsSummary({ balance: 5, streak: { current: 4, longest: 1 } }).streak).toEqual({ current: 4, longest: 4 });
  });

  test.each([
    ['a missing balance', {}],
    ['a text balance', { balance: '120' }],
    ['a fractional balance', { balance: 12.5 }],
    ['a negative balance', { balance: -10 }],
    ['an absurd balance', { balance: 1e300 }],
    ['not an object', [120]],
  ])('refuses %s', (_name, body) => {
    expect(() => parseRemoteRewardsSummary(body)).toThrow(ApiError);
  });

  test('the adapter only ever sends a GET with the token: no amount, no identity', async () => {
    const seen: { url: string; method: string; body: unknown }[] = [];
    const client = new ExperienceApi({
      baseUrl: 'http://127.0.0.1:9',
      timeoutMs: 1000,
      getAccessToken: async () => 'token',
      fetchImpl: async (url, init) => {
        seen.push({ url, method: init?.method ?? 'GET', body: init?.body ?? null });
        return new Response(JSON.stringify({ balance: 120, streak: { current: 3, longest: 7 }, achievements: [] }), { status: 200 });
      },
    });
    expect(await client.getRewardsSummary()).toMatchObject({ balance: 120, streak: { current: 3, longest: 7 }, achievements: 0 });
    expect(seen).toEqual([{ url: 'http://127.0.0.1:9/v1/rewards/summary', method: 'GET', body: null }]);
  });
});
