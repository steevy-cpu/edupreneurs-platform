/**
 * SQL for the learner-experience tables of ONE account (see schema.ts).
 *
 * Reached as `session.account.experience`: it shares the account's database
 * connection, so it is opened, isolated and closed exactly like the learning
 * data. Nothing here reads or writes a learning table.
 */
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
}
