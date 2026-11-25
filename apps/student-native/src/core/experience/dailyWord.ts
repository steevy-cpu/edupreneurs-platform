/**
 * Word of the Day: read-through cache and the honesty rule for its label.
 *
 * - The card is drawn from SQLite. Re-reading the cached word never needs the network.
 * - A word is called "today's" ONLY for a measured stretch of time after its
 *   download: `0 <= now - fetchedAt < lifetimeMs`. The lifetime is what was
 *   left until the server's deadline (`valid_until`, the next Haiti midnight)
 *   on the SERVER's clock (the response `Date` header) when the word arrived,
 *   capped at `MAX_LIFETIME_MS`. Only ELAPSED time on this phone is used, so a
 *   phone whose date is wrong — behind, ahead, or reset to another year — still
 *   stops saying "Mot du jour" at the right moment; a clock that jumps backwards
 *   past the download ends it at once. The phone never works out the Haitian date.
 * - Afterwards the same word is shown as "last downloaded word · <its date>".
 *   Yesterday's word is never presented as today's.
 * - Revalidation (rule agreed with the vocab lane, whose answers are
 *   `Cache-Control: private, no-cache` because a word can be withdrawn during
 *   the day): one conditional request (ETag; a 304 has no body) per app start
 *   and per return to the foreground — the caller passes `force` — and never
 *   more often than `REVALIDATE_SPACING_MS`. Once the lifetime is over the app
 *   always asks (unconditionally), `RETRY_AFTER_MS` apart after a failure.
 * - A word the server withdrew (404 `daily_word_not_available` while the cached
 *   one is still today's) is removed from the cache. When the feature is off on
 *   the server (any other 404) the cache is kept but the card is hidden.
 *
 * Remaining limit: with no readable `Date` header the lifetime falls back to
 * `valid_until - phone clock` at download, which is only as good as that clock.
 */
import { ApiError, isAborted } from '../api/errors';
import type { Locale } from '../api/types';
import type { AccountStore } from '../db/accountStore';
import type { StringKey } from '../i18n/strings';
import { ExperienceRemote, parseRemoteDailyWord, RemoteDailyWord } from './remote';
import type { DailyWordOutcome, DailyWordRow, StoredDailyWord } from './store';

/** Minimum wait after an attempt that did not bring or confirm a word. */
export const RETRY_AFTER_MS = 10 * 60 * 1000;
/** Minimum wait between two checks of a word that is in the cache as today's. */
export const REVALIDATE_SPACING_MS = 5 * 60 * 1000;
/** No word is "today's" for longer than this after its download, whatever deadline was received. */
export const MAX_LIFETIME_MS = 25 * 60 * 60 * 1000;

export type DailyWordFreshness = 'today' | 'last_downloaded';
export type DailyWordTiming = Pick<StoredDailyWord, 'fetchedAt' | 'lifetimeMs'>;

/** Time left until the server's deadline, by the server's own clock when it is known. Clamped to [0, MAX_LIFETIME_MS]. */
export function lifetimeFrom(validUntil: string, serverDate: string | null, phoneNow: Date): number {
  const until = Date.parse(validUntil);
  const server = serverDate === null ? NaN : Date.parse(serverDate);
  const from = Number.isFinite(server) ? server : phoneNow.getTime();
  if (!Number.isFinite(until)) return 0;
  return Math.max(0, Math.min(MAX_LIFETIME_MS, until - from));
}

export function freshnessOf(word: DailyWordTiming, now: Date): DailyWordFreshness {
  const elapsed = now.getTime() - Date.parse(word.fetchedAt);
  return Number.isFinite(elapsed) && elapsed >= 0 && elapsed < word.lifetimeMs ? 'today' : 'last_downloaded';
}

export interface DailyWordView {
  /** As of the `now` given to `dailyWordView`. Screens that stay open must use `freshnessOf(view.timing, now)` at render time. */
  freshness: DailyWordFreshness;
  /** What freshness is computed from, so a mounted screen can re-evaluate it as time passes. */
  timing: DailyWordTiming;
  /** `YYYY-MM-DD`, the Haitian calendar day the word was assigned to (from the server). */
  haitiDate: string;
  word: RemoteDailyWord['word'];
  /** Language of the word's text. */
  servedLocale: Locale;
  isFallbackLocale: boolean;
  hasAudio: boolean;
  /** Why there is no newer word, when the last attempt did not bring one. */
  lastOutcome: DailyWordOutcome | null;
}

/**
 * What the card shows, or null when there is no card: nothing was ever
 * downloaded, or the server last said the feature is off (the cache is kept).
 */
export function dailyWordView(row: DailyWordRow | null, now: Date): DailyWordView | null {
  if (!row?.word || row.lastOutcome === 'unavailable') return null;
  let parsed: RemoteDailyWord;
  try {
    // Validated again on the way out: a row written by another app version is never trusted blindly.
    parsed = parseRemoteDailyWord(row.word.body, row.locale);
  } catch {
    return null;
  }
  return {
    freshness: freshnessOf(row.word, now),
    timing: { fetchedAt: row.word.fetchedAt, lifetimeMs: row.word.lifetimeMs },
    haitiDate: row.word.haitiDate,
    word: parsed.word,
    servedLocale: parsed.locale,
    isFallbackLocale: parsed.is_fallback_locale,
    hasAudio: parsed.audio !== null,
    lastOutcome: row.lastOutcome,
  };
}

export type DailyWordRefresh = 'cached_today' | 'throttled' | DailyWordOutcome | 'aborted';

/**
 * Bring today's word into the cache, or check that the cached one still stands.
 * Never throws. NETWORK: callers only invoke this when the `dailyWord` flag is on.
 * `force`: the first call after an app start or a return to the foreground.
 */
export async function refreshDailyWord(
  account: AccountStore,
  remote: ExperienceRemote,
  locale: Locale,
  env: { now: () => Date; isActive?: () => boolean; force?: boolean },
): Promise<DailyWordRefresh> {
  const store = account.experience;
  const now = env.now();
  const active = () => env.isActive?.() ?? true;
  try {
    const row = await store.getDailyWord(locale);
    const isToday = Boolean(row?.word && freshnessOf(row.word, now) === 'today');
    if (row?.lastAttemptAt) {
      const since = now.getTime() - Date.parse(row.lastAttemptAt);
      const settled = row.lastOutcome === 'updated' || row.lastOutcome === 'not_modified';
      if (since >= 0 && since < (isToday && settled ? REVALIDATE_SPACING_MS : RETRY_AFTER_MS)) return isToday ? 'cached_today' : 'throttled';
    }
    if (isToday && !env.force) return 'cached_today';
    // Conditional only while the cached word is still today's; past its lifetime we ask plainly,
    // so that an answer always carries a new deadline.
    const conditional = isToday ? (row?.word?.etag ?? null) : null;
    let outcome: DailyWordOutcome;
    try {
      const result = await remote.getDailyWord(locale, conditional);
      if (!active()) return 'aborted';
      const arrived = env.now();
      const at = arrived.toISOString();
      if (result.kind === 'not_modified') {
        if (row?.word && result.serverDate !== null) {
          await store.reconfirmDailyWord(locale, at, lifetimeFrom(row.word.validUntil, result.serverDate, arrived));
        } else {
          await store.noteDailyWordAttempt(locale, at, 'not_modified');
        }
        return 'not_modified';
      }
      await store.putDailyWord(locale, {
        haitiDate: result.word.haiti_date,
        validUntil: result.word.valid_until,
        etag: result.etag,
        body: result.word,
        fetchedAt: at,
        lifetimeMs: lifetimeFrom(result.word.valid_until, result.serverDate, arrived),
      });
      return 'updated';
    } catch (error) {
      if (isAborted(error) || !active()) return 'aborted';
      if (error instanceof ApiError && error.kind === 'client') {
        outcome = error.code === 'daily_word_not_available' ? 'none_today' : 'unavailable';
        if (outcome === 'none_today' && isToday) {
          // The server says there is no word today, yet this phone holds one for today: it was withdrawn.
          await store.clearDailyWord(locale, env.now().toISOString());
          return 'none_today';
        }
      } else {
        outcome = 'unreachable';
      }
    }
    await store.noteDailyWordAttempt(locale, env.now().toISOString(), outcome);
    return outcome;
  } catch {
    return 'unreachable'; // storage trouble: the card simply keeps what it had
  }
}

const PART_OF_SPEECH: Record<string, StringKey> = {
  noun: 'wordPosNoun',
  verb: 'wordPosVerb',
  adjective: 'wordPosAdjective',
  adverb: 'wordPosAdverb',
  pronoun: 'wordPosPronoun',
  preposition: 'wordPosPreposition',
  conjunction: 'wordPosConjunction',
  interjection: 'wordPosInterjection',
  determiner: 'wordPosDeterminer',
  expression: 'wordPosExpression',
};

/** The label to show for the server's part-of-speech code, or null for a code this app version does not know. */
export function partOfSpeechKey(code: string | null): StringKey | null {
  return code !== null && Object.prototype.hasOwnProperty.call(PART_OF_SPEECH, code) ? PART_OF_SPEECH[code] : null;
}

const MONTHS: Record<Locale, string[]> = {
  fr: ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'],
  ht: ['janvye', 'fevriye', 'mas', 'avril', 'me', 'jen', 'jiyè', 'out', 'septanm', 'oktòb', 'novanm', 'desanm'],
};

/**
 * "2026-11-24" → "24 novembre 2026" / "24 novanm 2026". Pure text work on the
 * server's date string: no time zone, no `Intl` (old Android engines lack Creole data).
 */
export function formatHaitiDate(haitiDate: string, locale: Locale): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(haitiDate);
  if (!match) return haitiDate;
  const month = MONTHS[locale][Number(match[2]) - 1];
  if (!month) return haitiDate;
  const day = Number(match[3]);
  return `${locale === 'fr' && day === 1 ? '1er' : day} ${month} ${match[1]}`;
}
