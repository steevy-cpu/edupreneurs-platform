/**
 * Word of the Day: read-through cache, the "today / last downloaded" rule and
 * the HTTP adapter. Real SQLite; the server is an in-memory stand-in with
 * synthetic words (the vocab lane's endpoint is not on this branch).
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { ApiError } from '../../src/core/api/errors';
import { AccountStore } from '../../src/core/db/accountStore';
import {
  dailyWordView,
  formatHaitiDate,
  freshnessOf,
  lifetimeFrom,
  MAX_LIFETIME_MS,
  partOfSpeechKey,
  refreshDailyWord,
  RETRY_AFTER_MS,
  REVALIDATE_SPACING_MS,
} from '../../src/core/experience/dailyWord';
import { ExperienceApi, parseRemoteDailyWord } from '../../src/core/experience/remote';
import { FakeRemote, sampleWord } from '../support/experienceHarness';
import { nodeDatabases } from '../support/nodeSqlite';

const A = 'a0000000-0000-4000-8000-00000000000a';
const B = 'a0000000-0000-4000-8000-00000000000b';
/** Haiti midnight between 24 and 25 November 2026, as a UTC instant (standard time, UTC-5). */
const MIDNIGHT = Date.parse('2026-11-25T05:00:00.000Z');

let dir: string;
let account: AccountStore;
let remote: FakeRemote;
let clock: number;
const env = { now: () => new Date(clock) };

beforeEach(async () => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'edu-word-'));
  account = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
  remote = new FakeRemote();
  remote.dailyWords.fr = sampleWord('2026-11-24', 'fr');
  clock = Date.parse('2026-11-24T15:00:00.000Z'); // 10:00 in Haiti
});
afterEach(async () => {
  await account.close().catch(() => undefined);
  fs.rmSync(dir, { recursive: true, force: true });
});

const view = async (locale: 'fr' | 'ht' = 'fr') => dailyWordView(await account.experience.getDailyWord(locale), env.now());

describe('"today" ends exactly at the server’s deadline (Haiti midnight), measured as elapsed time', () => {
  const fetchedAt = '2026-11-24T15:00:00.000Z';
  const word = { fetchedAt, lifetimeMs: lifetimeFrom('2026-11-25T05:00:00Z', 'Tue, 24 Nov 2026 15:00:00 GMT', new Date(fetchedAt)) };
  test('23:59:59.999 in Haiti is still today; 00:00:00.000 is not', () => {
    expect(word.lifetimeMs).toBe(14 * 60 * 60 * 1000);
    expect(freshnessOf(word, new Date(MIDNIGHT - 1))).toBe('today');
    expect(freshnessOf(word, new Date(MIDNIGHT))).toBe('last_downloaded');
    expect(freshnessOf(word, new Date(MIDNIGHT + 1))).toBe('last_downloaded');
  });
  test('the deadline is the server’s instant, whatever the offset it is written with', () => {
    expect(lifetimeFrom('2026-11-25T00:00:00-05:00', 'Tue, 24 Nov 2026 15:00:00 GMT', new Date(0))).toBe(14 * 60 * 60 * 1000);
  });
  test('a phone clock that went backwards past the download ends "today" at once', () => {
    expect(freshnessOf(word, new Date('2026-11-24T14:59:59.000Z'))).toBe('last_downloaded');
    expect(freshnessOf(word, new Date('2019-01-01T00:00:00.000Z'))).toBe('last_downloaded');
  });
  test('the lifetime comes from the SERVER clock: a phone 5 hours slow still stops at the real midnight (review M1)', () => {
    // Real time 15:00Z; the phone believes it is 10:00Z.
    const slow = { fetchedAt: '2026-11-24T10:00:00.000Z', lifetimeMs: lifetimeFrom('2026-11-25T05:00:00Z', 'Tue, 24 Nov 2026 15:00:00 GMT', new Date('2026-11-24T10:00:00.000Z')) };
    // Real midnight = phone 00:00Z on the 25th, although the phone's clock is still 5 h before `valid_until`.
    expect(freshnessOf(slow, new Date('2026-11-24T23:59:59.999Z'))).toBe('today');
    expect(freshnessOf(slow, new Date('2026-11-25T00:00:00.000Z'))).toBe('last_downloaded');
    // A phone 5 hours FAST: still today for the 14 real hours that remain (review L1).
    const fast = { fetchedAt: '2026-11-24T20:00:00.000Z', lifetimeMs: slow.lifetimeMs };
    expect(freshnessOf(fast, new Date('2026-11-25T09:59:59.999Z'))).toBe('today');
    expect(freshnessOf(fast, new Date('2026-11-25T10:00:00.000Z'))).toBe('last_downloaded');
  });
  test('no word is today’s for more than about a day, whatever deadline arrives; a past deadline gives no lifetime', () => {
    expect(lifetimeFrom('2031-01-01T00:00:00Z', 'Tue, 24 Nov 2026 15:00:00 GMT', new Date(0))).toBe(MAX_LIFETIME_MS);
    expect(lifetimeFrom('2026-11-24T05:00:00Z', 'Tue, 24 Nov 2026 15:00:00 GMT', new Date(0))).toBe(0);
    expect(lifetimeFrom('soon', null, new Date(0))).toBe(0);
    // no readable Date header: the phone's clock at download is the only reference left
    expect(lifetimeFrom('2026-11-25T05:00:00Z', null, new Date('2026-11-24T15:00:00.000Z'))).toBe(14 * 60 * 60 * 1000);
  });
  test('unreadable timestamps never count as today', () => {
    expect(freshnessOf({ fetchedAt: 'yesterday', lifetimeMs: 1e9 }, new Date(MIDNIGHT - 1))).toBe('last_downloaded');
  });
});

describe('read-through cache', () => {
  test('first download stores the word; re-reading it needs no network at all', async () => {
    expect(await view()).toBeNull();
    expect(await refreshDailyWord(account, remote, 'fr', env)).toBe('updated');
    expect(await view()).toMatchObject({ freshness: 'today', haitiDate: '2026-11-24', word: { term: 'persévérance' }, hasAudio: false });

    remote.calls.length = 0;
    remote.mode = 'offline';
    clock += 6 * 60 * 60 * 1000; // later the same Haitian day, same app session
    expect(await refreshDailyWord(account, remote, 'fr', env)).toBe('cached_today');
    expect(remote.calls).toEqual([]);
    expect((await view())?.freshness).toBe('today');
  });

  test('once per app start / return to foreground the server is asked, cheaply, whether the word still stands (review M2)', async () => {
    await refreshDailyWord(account, remote, 'fr', env);
    remote.calls.length = 0;
    // too soon after the download: even a forced check waits
    clock += REVALIDATE_SPACING_MS - 1;
    expect(await refreshDailyWord(account, remote, 'fr', { ...env, force: true })).toBe('cached_today');
    expect(remote.calls).toEqual([]);
    clock += 1;
    expect(await refreshDailyWord(account, remote, 'fr', { ...env, force: true })).toBe('not_modified');
    expect(remote.calls).toEqual([`GET /v1/daily-word?locale=fr If-None-Match="2026-11-24:fr:rev-2026-11-24-fr"`]);
    expect((await view())?.freshness).toBe('today');
    // later visits in the same foreground session are not forced: no request
    clock += 60 * 60 * 1000;
    expect(await refreshDailyWord(account, remote, 'fr', env)).toBe('cached_today');
    expect(remote.calls).toHaveLength(1);
  });

  test('a check with no network changes nothing: the word is still today’s until its deadline', async () => {
    await refreshDailyWord(account, remote, 'fr', env);
    remote.mode = 'offline';
    clock += REVALIDATE_SPACING_MS;
    expect(await refreshDailyWord(account, remote, 'fr', { ...env, force: true })).toBe('unreachable');
    expect(await view()).toMatchObject({ freshness: 'today', word: { term: 'persévérance' } });
  });

  test('a word the server withdrew during the day is removed from the phone at the next check', async () => {
    await refreshDailyWord(account, remote, 'fr', env);
    delete remote.dailyWords.fr; // staff withdrew it: the endpoint now answers 404 daily_word_not_available
    clock += REVALIDATE_SPACING_MS;
    expect(await refreshDailyWord(account, remote, 'fr', { ...env, force: true })).toBe('none_today');
    expect(await view()).toBeNull();
    expect((await account.experience.getDailyWord('fr'))?.lastOutcome).toBe('none_today');
  });

  test('a word the server replaced during the day replaces the cached one', async () => {
    await refreshDailyWord(account, remote, 'fr', env);
    remote.dailyWords.fr = { ...sampleWord('2026-11-25', 'fr'), haiti_date: '2026-11-24', valid_until: '2026-11-25T05:00:00Z' };
    clock += REVALIDATE_SPACING_MS;
    expect(await refreshDailyWord(account, remote, 'fr', { ...env, force: true })).toBe('updated');
    expect(await view()).toMatchObject({ freshness: 'today', haitiDate: '2026-11-24', word: { term: 'hypothèse' } });
  });

  test('feature switched off on the server: the card is hidden, the cache is kept, and it comes back with the feature', async () => {
    await refreshDailyWord(account, remote, 'fr', env);
    remote.dailyWordDisabledCode = 'not_found';
    clock += REVALIDATE_SPACING_MS;
    expect(await refreshDailyWord(account, remote, 'fr', { ...env, force: true })).toBe('unavailable');
    expect(await view()).toBeNull(); // hidden…
    expect((await account.experience.getDailyWord('fr'))?.word).not.toBeNull(); // …not erased
    remote.dailyWordDisabledCode = null;
    clock += RETRY_AFTER_MS;
    expect(await refreshDailyWord(account, remote, 'fr', { ...env, force: true })).toBe('not_modified');
    expect((await view())?.word.term).toBe('persévérance');
  });

  test('phone clock 5 hours slow, ONLINE: after the real midnight the word is no longer today’s and the new one is fetched (review M1)', async () => {
    const SLOW = 5 * 60 * 60 * 1000;
    remote.serverNow = () => new Date(clock + SLOW); // the server knows the real time
    await refreshDailyWord(account, remote, 'fr', env);
    clock = MIDNIGHT - SLOW + 1000; // real time: one second past Haiti midnight; the phone thinks it is 19:00
    expect((await view())?.freshness).toBe('last_downloaded');
    remote.dailyWords.fr = sampleWord('2026-11-25', 'fr');
    expect(await refreshDailyWord(account, remote, 'fr', env)).toBe('updated'); // not forced: it asks because the lifetime is over
    expect(await view()).toMatchObject({ freshness: 'today', haitiDate: '2026-11-25' });
  });

  test('phone clock reset to another year, offline: never today’s', async () => {
    await refreshDailyWord(account, remote, 'fr', env);
    remote.mode = 'offline';
    clock = Date.parse('2020-01-01T00:00:00.000Z');
    expect((await view())?.freshness).toBe('last_downloaded');
  });

  test('phone clock 5 hours fast: one download serves the rest of the real day (review L1)', async () => {
    const FAST = 5 * 60 * 60 * 1000;
    clock = Date.parse('2026-11-25T00:00:00.000Z') + FAST; // real 19:00 Haiti on the 24th; the phone is already past valid_until
    remote.serverNow = () => new Date(clock - FAST);
    expect(await refreshDailyWord(account, remote, 'fr', env)).toBe('updated');
    expect((await view())?.freshness).toBe('today');
    remote.calls.length = 0;
    for (let i = 0; i < 6; i += 1) {
      clock += 20 * 60 * 1000;
      await refreshDailyWord(account, remote, 'fr', env);
    }
    expect(remote.calls).toEqual([]);
  });

  test('past midnight with no network: the same word is "last downloaded", never "today"', async () => {
    await refreshDailyWord(account, remote, 'fr', env);
    remote.mode = 'offline';
    clock = MIDNIGHT + 60_000;
    expect(await refreshDailyWord(account, remote, 'fr', env)).toBe('unreachable');
    expect(await view()).toMatchObject({ freshness: 'last_downloaded', haitiDate: '2026-11-24', word: { term: 'persévérance' }, lastOutcome: 'unreachable' });
  });

  test('failed attempts are spaced out; the next successful one brings the new day’s word', async () => {
    await refreshDailyWord(account, remote, 'fr', env);
    remote.mode = 'offline';
    clock = MIDNIGHT + 60_000;
    await refreshDailyWord(account, remote, 'fr', env);
    remote.calls.length = 0;

    clock += RETRY_AFTER_MS - 1;
    expect(await refreshDailyWord(account, remote, 'fr', env)).toBe('throttled');
    expect(remote.calls).toEqual([]);

    remote.mode = 'online';
    remote.dailyWords.fr = sampleWord('2026-11-25', 'fr');
    clock += 1;
    expect(await refreshDailyWord(account, remote, 'fr', env)).toBe('updated');
    // Past its deadline the request is unconditional, so the answer always carries a new deadline.
    expect(remote.calls).toEqual(['GET /v1/daily-word?locale=fr']);
    expect(await view()).toMatchObject({ freshness: 'today', haitiDate: '2026-11-25', word: { term: 'hypothèse' } });
  });

  test('no word assigned today (404): the old word stays, labelled as old, with the reason', async () => {
    await refreshDailyWord(account, remote, 'fr', env);
    clock = MIDNIGHT + 60_000;
    delete remote.dailyWords.fr;
    expect(await refreshDailyWord(account, remote, 'fr', env)).toBe('none_today');
    expect(await view()).toMatchObject({ freshness: 'last_downloaded', word: { term: 'persévérance' }, lastOutcome: 'none_today' });
  });

  test('nothing cached and nothing available: there is no word to show, and no retry storm', async () => {
    remote.dailyWordDisabledCode = 'not_found'; // e.g. EDU_DAILY_WORD_ENABLED is off on the server
    expect(await refreshDailyWord(account, remote, 'fr', env)).toBe('unavailable');
    expect(await view()).toBeNull();
    expect(await refreshDailyWord(account, remote, 'fr', env)).toBe('throttled');
    expect(remote.calls).toHaveLength(1);
  });

  test('Creole requested but only French exists: stored for Creole, flagged as a fallback; the French cache is separate', async () => {
    remote.dailyWords.ht = { ...sampleWord('2026-11-24', 'fr'), requested_locale: 'ht', is_fallback_locale: true };
    expect(await refreshDailyWord(account, remote, 'ht', env)).toBe('updated');
    expect(await view('ht')).toMatchObject({ isFallbackLocale: true, servedLocale: 'fr', word: { term: 'persévérance' } });
    expect(await view('fr')).toBeNull();
    remote.dailyWords.ht = sampleWord('2026-11-24', 'ht');
    await refreshDailyWord(account, remote, 'fr', env);
    expect(await view('fr')).toMatchObject({ isFallbackLocale: false, servedLocale: 'fr' });
  });

  test('a session that ended during the request stores nothing', async () => {
    expect(await refreshDailyWord(account, remote, 'fr', { ...env, isActive: () => false })).toBe('aborted');
    expect(await account.experience.getDailyWord('fr')).toBeNull();
  });

  test('the cache is per account and survives a restart', async () => {
    await refreshDailyWord(account, remote, 'fr', env);
    await account.close();
    const other = await AccountStore.open(await nodeDatabases(dir)(`account-${B}`), B);
    expect(await other.experience.getDailyWord('fr')).toBeNull();
    await other.close();
    account = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
    expect((await view())?.word.term).toBe('persévérance');
  });

  test('a cached row that no longer passes validation is not shown', async () => {
    await account.experience.putDailyWord('fr', {
      haitiDate: '2026-11-24',
      validUntil: '2026-11-25T05:00:00Z',
      etag: null,
      body: { haiti_date: '2026-11-24', locale: 'fr', valid_until: '2026-11-25T05:00:00Z', word: { term: '' } },
      fetchedAt: env.now().toISOString(),
      lifetimeMs: 60 * 60 * 1000,
    });
    expect(await view()).toBeNull();
  });
});

describe('response validation (assumed contract, briefs/vocab.md)', () => {
  const good = () => JSON.parse(JSON.stringify(sampleWord('2026-11-24', 'fr'))) as Record<string, any>;

  test('accepts the documented shape, and the same fields sent flat', () => {
    expect(parseRemoteDailyWord(good(), 'fr').word.term).toBe('persévérance');
    const flat = good();
    Object.assign(flat, flat.word);
    delete flat.word;
    expect(parseRemoteDailyWord(flat, 'fr').word).toMatchObject({ term: 'persévérance', gloss: 'pèseverans' });
  });

  test('optional parts may be missing; audio is metadata or null', () => {
    const body = good();
    delete body.word.gloss;
    delete body.word.pronunciation;
    // the vocab lane's field names
    body.audio = { asset_id: 'a1', mime_type: 'audio/mpeg', byte_size: 20480, duration_ms: 1800, sha256: 'ignored' };
    const parsed = parseRemoteDailyWord(body, 'fr');
    expect(parsed.word).toMatchObject({ gloss: null, pronunciation: null });
    expect(parsed.audio).toEqual({ mime: 'audio/mpeg', bytes: 20480, duration_ms: 1800 });
    // what the phone stores is what it reads back
    expect(parseRemoteDailyWord(JSON.parse(JSON.stringify(parsed)), 'fr')).toEqual(parsed);
  });

  test.each([
    ['no term', (b: any) => delete b.word.term],
    ['empty definition', (b: any) => (b.word.definition = '   ')],
    ['a date that is not a calendar date string', (b: any) => (b.haiti_date = '24/11/2026')],
    ['no deadline', (b: any) => delete b.valid_until],
    ['a deadline that is not a time', (b: any) => (b.valid_until = 'midnight')],
    ['another language without the fallback flag', (b: any) => (b.locale = 'ht')],
    ['an oversized body', (b: any) => (b.word.note = 'x'.repeat(9000))],
  ])('refuses %s', (_name, mutate) => {
    const body = good();
    mutate(body);
    expect(() => parseRemoteDailyWord(body, 'fr')).toThrow(ApiError);
  });

  test('the fallback flag is derived from the languages, not trusted blindly', () => {
    const body = good();
    body.is_fallback_locale = true; // claims fallback although French was asked and French was served
    expect(parseRemoteDailyWord(body, 'fr').is_fallback_locale).toBe(false);
  });
});

describe('the HTTP adapter', () => {
  function api(handler: (init: RequestInit) => Response) {
    const seen: { url: string; headers: Record<string, string> }[] = [];
    const client = new ExperienceApi({
      baseUrl: 'http://127.0.0.1:9',
      timeoutMs: 1000,
      getAccessToken: async () => 'token',
      fetchImpl: async (url, init) => {
        seen.push({ url, headers: init?.headers as Record<string, string> });
        return handler(init ?? {});
      },
    });
    return { client, seen };
  }

  test('asks for the interface language, keeps the ETag, and sends it back as If-None-Match', async () => {
    const word = sampleWord('2026-11-24', 'ht');
    const { client, seen } = api((init) =>
      (init.headers as Record<string, string>)['If-None-Match'] === '"abc"'
        ? new Response(null, { status: 304 })
        : new Response(JSON.stringify(word), { status: 200, headers: { ETag: '"abc"', 'Cache-Control': 'private, no-cache', Date: 'Tue, 24 Nov 2026 15:00:00 GMT' } }),
    );
    const first = await client.getDailyWord('ht', null);
    expect(first).toMatchObject({ kind: 'word', etag: '"abc"', serverDate: 'Tue, 24 Nov 2026 15:00:00 GMT', word: { word: { term: 'pèseverans' } } });
    expect(seen[0].url).toBe('http://127.0.0.1:9/v1/daily-word?locale=ht');
    expect(seen[0].headers['If-None-Match']).toBeUndefined();
    expect(await client.getDailyWord('ht', '"abc"')).toEqual({ kind: 'not_modified', serverDate: null });
    expect(seen[1].headers['If-None-Match']).toBe('"abc"');
  });

  test('404 carries the server’s reason code', async () => {
    const { client } = api(() => new Response(JSON.stringify({ error: { code: 'daily_word_not_available', message: 'x' } }), { status: 404 }));
    await expect(client.getDailyWord('fr', null)).rejects.toMatchObject({ kind: 'client', code: 'daily_word_not_available', status: 404 });
  });
});

test('part-of-speech codes get the app’s own label; an unknown code is hidden, never shown raw', () => {
  expect(partOfSpeechKey('noun')).toBe('wordPosNoun');
  expect(partOfSpeechKey('expression')).toBe('wordPosExpression');
  expect(partOfSpeechKey('gerund')).toBeNull();
  expect(partOfSpeechKey('constructor')).toBeNull();
  expect(partOfSpeechKey(null)).toBeNull();
});

test('dates are written out in French and in Creole without relying on the phone’s locale data', () => {
  expect(formatHaitiDate('2026-11-24', 'fr')).toBe('24 novembre 2026');
  expect(formatHaitiDate('2026-11-24', 'ht')).toBe('24 novanm 2026');
  expect(formatHaitiDate('2027-01-01', 'fr')).toBe('1er janvier 2027');
  expect(formatHaitiDate('2027-01-01', 'ht')).toBe('1 janvye 2027');
  expect(formatHaitiDate('2026-08-09', 'ht')).toBe('9 out 2026');
  expect(formatHaitiDate('not a date', 'fr')).toBe('not a date');
});
