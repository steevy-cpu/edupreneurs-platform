/**
 * SQL for the learner-experience tables of ONE account (see schema.ts).
 *
 * Reached as `session.account.experience`: it shares the account's database
 * connection, so it is opened, isolated and closed exactly like the learning
 * data. Nothing here reads or writes a learning table.
 */
import type { Locale } from '../api/types';
import type { SqlDatabase, SqlExecutor } from '../db/driver';
import type { ONBOARDING_STEPS } from './schema';

export type OnboardingStep = (typeof ONBOARDING_STEPS)[number];
/**
 *   in_progress  the first-run flow has started and is not finished: resume at `step`
 *   completed    the learner reached the end
 *   skipped      the learner chose to skip the introduction
 *   returning    never went through the flow and does not have to (used the app before
 *                onboarding existed, or the server already knows this learner as onboarded)
 */
export type OnboardingStatus = 'in_progress' | 'completed' | 'skipped' | 'returning';
/** The server's vocabulary (briefs/identity.md). It only ever moves forward. */
export type ServerOnboardingState = 'new' | 'profile_selected' | 'downloads_informed' | 'ready';

export interface OnboardingRecord {
  /** Version of the flow definition that wrote the row; 0 for a returning learner who never saw one. */
  flowVersion: number;
  status: OnboardingStatus;
  /** Where the flow resumes. */
  step: OnboardingStep;
  /** The furthest step ever reached (going back does not lower it). */
  furthestStep: OnboardingStep;
  /** The grade picked in the flow, or null when it was not chosen (yet). */
  gradeCode: string | null;
  startedAt: string;
  updatedAt: string;
  completedAt: string | null;
  /** Last state the server acknowledged, if any. */
  serverState: ServerOnboardingState | null;
  serverSyncedAt: string | null;
  /** Local progress the server has not acknowledged yet. */
  needsPush: boolean;
  /** Grade / language chosen here that the server profile has not received yet. */
  profileNeedsPush: boolean;
}

export interface TourRecord {
  /** Highest tour version this account finished or dismissed; 0 = never. */
  versionSeen: number;
  dismissed: boolean;
  /** A run was started and not finished: reopen at `step`. */
  inProgress: boolean;
  step: number;
  updatedAt: string;
  needsPush: boolean;
}

interface OnboardingRow {
  flow_version: number;
  status: OnboardingStatus;
  step: OnboardingStep;
  furthest_step: OnboardingStep;
  grade_code: string | null;
  started_at: string;
  updated_at: string;
  completed_at: string | null;
  server_state: ServerOnboardingState | null;
  server_synced_at: string | null;
  needs_push: number;
  profile_needs_push: number;
}

interface TourRow {
  version_seen: number;
  dismissed: number;
  in_progress: number;
  step: number;
  updated_at: string;
  needs_push: number;
}

function toOnboarding(row: OnboardingRow): OnboardingRecord {
  return {
    flowVersion: row.flow_version,
    status: row.status,
    step: row.step,
    furthestStep: row.furthest_step,
    gradeCode: row.grade_code,
    startedAt: row.started_at,
    updatedAt: row.updated_at,
    completedAt: row.completed_at,
    serverState: row.server_state,
    serverSyncedAt: row.server_synced_at,
    needsPush: row.needs_push !== 0,
    profileNeedsPush: row.profile_needs_push !== 0,
  };
}

function toTour(row: TourRow): TourRecord {
  return {
    versionSeen: row.version_seen,
    dismissed: row.dismissed !== 0,
    inProgress: row.in_progress !== 0,
    step: row.step,
    updatedAt: row.updated_at,
    needsPush: row.needs_push !== 0,
  };
}

/** What the last attempt to download today's word ended with. */
export type DailyWordOutcome = 'updated' | 'not_modified' | 'none_today' | 'unavailable' | 'unreachable';

export interface DailyWordRow {
  locale: Locale;
  /** Null when no word has ever been downloaded for this language. */
  word: StoredDailyWord | null;
  lastAttemptAt: string | null;
  lastOutcome: DailyWordOutcome | null;
}

export interface StoredDailyWord {
  /** The server's calendar day (America/Port-au-Prince) this word belongs to, `YYYY-MM-DD`. */
  haitiDate: string;
  /** The instant of the next Haiti midnight, from the server. After it, this is no longer "today's" word. */
  validUntil: string;
  etag: string | null;
  /** The validated response body, stored as received. */
  body: unknown;
  /** This phone's clock when the word was downloaded (or last confirmed by a 304). */
  fetchedAt: string;
}

export interface RewardsRow {
  /** The validated server summary as received, or null when none has ever been downloaded. */
  body: unknown | null;
  fetchedAt: string | null;
  lastAttemptAt: string | null;
  lastOutcome: 'updated' | 'unavailable' | 'unreachable' | null;
}

export const EMPTY_TOUR: TourRecord = { versionSeen: 0, dismissed: false, inProgress: false, step: 0, updatedAt: '', needsPush: false };

async function readOnboarding(db: SqlExecutor): Promise<OnboardingRecord | null> {
  const row = await db.first<OnboardingRow>('SELECT * FROM onboarding_state WHERE id = 1');
  return row ? toOnboarding(row) : null;
}

async function readTour(db: SqlExecutor): Promise<TourRecord> {
  const row = await db.first<TourRow>('SELECT * FROM tour_state WHERE id = 1');
  return row ? toTour(row) : EMPTY_TOUR;
}

export class ExperienceStore {
  constructor(private readonly db: SqlDatabase) {}

  // ------------------------------------------------------------------ onboarding
  getOnboarding(): Promise<OnboardingRecord | null> {
    return readOnboarding(this.db);
  }

  /**
   * Read-modify-write of the single onboarding row in ONE transaction.
   * `change` receives the current record (null when none exists) and returns the
   * record to store, or null to leave the database untouched.
   */
  async updateOnboarding(
    change: (current: OnboardingRecord | null) => OnboardingRecord | null,
  ): Promise<OnboardingRecord | null> {
    return this.db.transaction(async (tx) => {
      const current = await readOnboarding(tx);
      const next = change(current);
      if (next === null) return current;
      await tx.run(
        `INSERT INTO onboarding_state (id, flow_version, status, step, furthest_step, grade_code, started_at,
           updated_at, completed_at, server_state, server_synced_at, needs_push, profile_needs_push)
         VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT (id) DO UPDATE SET
           flow_version = excluded.flow_version, status = excluded.status, step = excluded.step,
           furthest_step = excluded.furthest_step, grade_code = excluded.grade_code,
           updated_at = excluded.updated_at, completed_at = excluded.completed_at,
           server_state = excluded.server_state, server_synced_at = excluded.server_synced_at,
           needs_push = excluded.needs_push, profile_needs_push = excluded.profile_needs_push`,
        [
          next.flowVersion,
          next.status,
          next.step,
          next.furthestStep,
          next.gradeCode,
          next.startedAt,
          next.updatedAt,
          next.completedAt,
          next.serverState,
          next.serverSyncedAt,
          next.needsPush ? 1 : 0,
          next.profileNeedsPush ? 1 : 0,
        ],
      );
      return next;
    });
  }

  // ------------------------------------------------------------------------ tour
  getTour(): Promise<TourRecord> {
    return readTour(this.db);
  }

  async updateTour(change: (current: TourRecord) => TourRecord | null): Promise<TourRecord> {
    return this.db.transaction(async (tx) => {
      const current = await readTour(tx);
      const next = change(current);
      if (next === null) return current;
      await tx.run(
        `INSERT INTO tour_state (id, version_seen, dismissed, in_progress, step, updated_at, needs_push)
         VALUES (1, ?, ?, ?, ?, ?, ?)
         ON CONFLICT (id) DO UPDATE SET
           version_seen = excluded.version_seen, dismissed = excluded.dismissed,
           in_progress = excluded.in_progress, step = excluded.step,
           updated_at = excluded.updated_at, needs_push = excluded.needs_push`,
        [next.versionSeen, next.dismissed ? 1 : 0, next.inProgress ? 1 : 0, next.step, next.updatedAt, next.needsPush ? 1 : 0],
      );
      return next;
    });
  }

  // --------------------------------------------------------------- word of the day
  async getDailyWord(locale: Locale): Promise<DailyWordRow | null> {
    const row = await this.db.first<{
      haiti_date: string | null;
      valid_until: string | null;
      etag: string | null;
      body_json: string | null;
      fetched_at: string | null;
      last_attempt_at: string | null;
      last_outcome: DailyWordOutcome | null;
    }>('SELECT * FROM daily_word_cache WHERE locale = ?', [locale]);
    if (!row) return null;
    let word: StoredDailyWord | null = null;
    if (row.body_json && row.haiti_date && row.valid_until && row.fetched_at) {
      try {
        word = {
          haitiDate: row.haiti_date,
          validUntil: row.valid_until,
          etag: row.etag,
          body: JSON.parse(row.body_json) as unknown,
          fetchedAt: row.fetched_at,
        };
      } catch {
        word = null; // an unreadable row is treated as "nothing cached", never shown
      }
    }
    return { locale, word, lastAttemptAt: row.last_attempt_at, lastOutcome: row.last_outcome };
  }

  /** Replace the cached word for a language (one statement: a reader sees the old word or the new one). */
  async putDailyWord(locale: Locale, word: StoredDailyWord): Promise<void> {
    await this.db.run(
      `INSERT INTO daily_word_cache (locale, haiti_date, valid_until, etag, body_json, fetched_at, last_attempt_at, last_outcome)
       VALUES (?, ?, ?, ?, ?, ?, ?, 'updated')
       ON CONFLICT (locale) DO UPDATE SET haiti_date = excluded.haiti_date, valid_until = excluded.valid_until,
         etag = excluded.etag, body_json = excluded.body_json, fetched_at = excluded.fetched_at,
         last_attempt_at = excluded.last_attempt_at, last_outcome = excluded.last_outcome`,
      [locale, word.haitiDate, word.validUntil, word.etag, JSON.stringify(word.body), word.fetchedAt, word.fetchedAt],
    );
  }

  /** The server withdrew the word that was cached as today's: stop showing it. The attempt is remembered. */
  async clearDailyWord(locale: Locale, at: string): Promise<void> {
    await this.db.run(
      `UPDATE daily_word_cache SET haiti_date = NULL, valid_until = NULL, etag = NULL, body_json = NULL, fetched_at = NULL,
         last_attempt_at = ?, last_outcome = 'none_today' WHERE locale = ?`,
      [at, locale],
    );
  }

  /** Remember an attempt that brought no new word. The cached word, if any, is left exactly as it was. */
  async noteDailyWordAttempt(locale: Locale, at: string, outcome: DailyWordOutcome, confirmed = false): Promise<void> {
    await this.db.run(
      `INSERT INTO daily_word_cache (locale, last_attempt_at, last_outcome) VALUES (?, ?, ?)
       ON CONFLICT (locale) DO UPDATE SET last_attempt_at = excluded.last_attempt_at, last_outcome = excluded.last_outcome,
         fetched_at = CASE WHEN ? = 1 AND body_json IS NOT NULL THEN excluded.last_attempt_at ELSE fetched_at END`,
      [locale, at, outcome, confirmed ? 1 : 0],
    );
  }

  // ------------------------------------------------------------------ gold / streak
  async getRewards(): Promise<RewardsRow | null> {
    const row = await this.db.first<{
      body_json: string | null;
      fetched_at: string | null;
      last_attempt_at: string | null;
      last_outcome: RewardsRow['lastOutcome'];
    }>('SELECT * FROM rewards_summary_cache WHERE id = 1');
    if (!row) return null;
    let body: unknown | null = null;
    if (row.body_json && row.fetched_at) {
      try {
        body = JSON.parse(row.body_json) as unknown;
      } catch {
        body = null;
      }
    }
    return { body, fetchedAt: body === null ? null : row.fetched_at, lastAttemptAt: row.last_attempt_at, lastOutcome: row.last_outcome };
  }

  async putRewards(body: unknown, at: string): Promise<void> {
    await this.db.run(
      `INSERT INTO rewards_summary_cache (id, body_json, fetched_at, last_attempt_at, last_outcome) VALUES (1, ?, ?, ?, 'updated')
       ON CONFLICT (id) DO UPDATE SET body_json = excluded.body_json, fetched_at = excluded.fetched_at,
         last_attempt_at = excluded.last_attempt_at, last_outcome = excluded.last_outcome`,
      [JSON.stringify(body), at, at],
    );
  }

  /** An attempt that brought nothing: the last confirmed summary stays exactly as it was. */
  async noteRewardsAttempt(at: string, outcome: 'unavailable' | 'unreachable'): Promise<void> {
    await this.db.run(
      `INSERT INTO rewards_summary_cache (id, last_attempt_at, last_outcome) VALUES (1, ?, ?)
       ON CONFLICT (id) DO UPDATE SET last_attempt_at = excluded.last_attempt_at, last_outcome = excluded.last_outcome`,
      [at, outcome],
    );
  }
}
