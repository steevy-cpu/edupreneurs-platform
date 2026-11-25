/**
 * Word of the Day: read-through cache and the honesty rule for its label.
 *
 * - The card is drawn from SQLite. Re-reading the cached word never needs the network.
 * - A word is called "today's" ONLY while the server's own deadline for it has
 *   not passed: `fetchedAt <= now < validUntil`, where `validUntil` is the
 *   instant of the next midnight in Haiti as sent by the server. This phone
 *   never works out the Haitian date itself.
 * - After that instant — or if this phone's clock has gone backwards since the
 *   download — the same word is shown as "last downloaded word · <its date>".
 *   Yesterday's word is never presented as today's.
 * - The network is used sparingly. While today's word is in the cache: one
 *   small conditional request (ETag, answered 304 with no body) at most every
 *   `REVALIDATE_AFTER_MS`, because the server may withdraw a word during the
 *   day. Otherwise: at most one attempt every `RETRY_AFTER_MS`.
 * - A word the server withdrew (404 while the cached one is still "today's")
 *   is removed from the cache: withdrawn content is not kept on screen.
 *
 * Known limit (documented in the lane notes): if the phone's clock is set
 * BEHIND the real time, "now < validUntil" stays true for longer than it
 * should. Any successful refresh corrects it.
 */
import { ApiError, isAborted } from '../api/errors';
import type { Locale } from '../api/types';
import type { AccountStore } from '../db/accountStore';
import type { StringKey } from '../i18n/strings';
import { ExperienceRemote, parseRemoteDailyWord, RemoteDailyWord } from './remote';
import type { DailyWordOutcome, DailyWordRow, StoredDailyWord } from './store';

/** Minimum wait between two download attempts that did not bring today's word. */
export const RETRY_AFTER_MS = 10 * 60 * 1000;
/** How long today's cached word is shown before the server is asked (cheaply) whether it still stands. */
export const REVALIDATE_AFTER_MS = 6 * 60 * 60 * 1000;

export type DailyWordFreshness = 'today' | 'last_downloaded';

export function freshnessOf(word: Pick<StoredDailyWord, 'fetchedAt' | 'validUntil'>, now: Date): DailyWordFreshness {
  const at = now.getTime();
  const fetched = Date.parse(word.fetchedAt);
  const until = Date.parse(word.validUntil);
  return Number.isFinite(fetched) && Number.isFinite(until) && fetched <= at && at < until ? 'today' : 'last_downloaded';
}

export interface DailyWordView {
  /** As of the `now` given to `dailyWordView`. Screens that stay open must use `freshnessOf(view.timing, now)` at render time. */
  freshness: DailyWordFreshness;
  /** What freshness is computed from, so a mounted screen can re-evaluate it as time passes. */
  timing: Pick<StoredDailyWord, 'fetchedAt' | 'validUntil'>;
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

/** What the card shows, or null when nothing has ever been downloaded (then there is no card). */
export function dailyWordView(row: DailyWordRow | null, now: Date): DailyWordView | null {
  if (!row?.word) return null;
  let parsed: RemoteDailyWord;
  try {
    // Validated again on the way out: a row written by another app version is never trusted blindly.
    parsed = parseRemoteDailyWord(row.word.body, row.locale);
  } catch {
    return null;
  }
  return {
    freshness: freshnessOf(row.word, now),
    timing: { fetchedAt: row.word.fetchedAt, validUntil: row.word.validUntil },
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
 * Bring today's word into the cache if it is not there yet. Never throws.
 * NETWORK: callers only invoke this when the `dailyWord` flag is on.
 */
export async function refreshDailyWord(
  account: AccountStore,
  remote: ExperienceRemote,
  locale: Locale,
  env: { now: () => Date; isActive?: () => boolean },
): Promise<DailyWordRefresh> {
  const store = account.experience;
  const now = env.now();
  const active = () => env.isActive?.() ?? true;
  try {
    const row = await store.getDailyWord(locale);
    const isToday = Boolean(row?.word && freshnessOf(row.word, now) === 'today');
    if (row?.lastAttemptAt) {
      const since = now.getTime() - Date.parse(row.lastAttemptAt);
      if (since >= 0 && since < (isToday ? REVALIDATE_AFTER_MS : RETRY_AFTER_MS)) return isToday ? 'cached_today' : 'throttled';
    }
    // A conditional request only makes sense while the cached word could still be today's
    // (revalidation during the day, or the clock went backwards). Past its deadline we ask
    // plainly, so that an answer always carries a new `valid_until`.
    const stillCurrent = Boolean(row?.word && now.getTime() < Date.parse(row.word.validUntil));
    const conditional = stillCurrent ? (row?.word?.etag ?? null) : null;
    let outcome: DailyWordOutcome;
    try {
      const result = await remote.getDailyWord(locale, conditional ?? null);
      if (!active()) return 'aborted';
      const at = env.now().toISOString();
      if (result.kind === 'not_modified') {
        await store.noteDailyWordAttempt(locale, at, 'not_modified', true);
        return 'not_modified';
      }
      await store.putDailyWord(locale, {
        haitiDate: result.word.haiti_date,
        validUntil: result.word.valid_until,
        etag: result.etag,
        body: result.word,
        fetchedAt: at,
      });
      return 'updated';
    } catch (error) {
      if (isAborted(error) || !active()) return 'aborted';
      if (error instanceof ApiError && error.kind === 'client') {
        outcome = error.code === 'daily_word_not_available' ? 'none_today' : 'unavailable';
        if (outcome === 'none_today' && stillCurrent) {
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
