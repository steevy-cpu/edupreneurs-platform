/**
 * First-run onboarding: the rules, with no screen and no network in them.
 *
 *   welcome → language → grade → downloads → ready
 *
 * - RESUMABLE. Every move is committed to this account's SQLite database before
 *   the screen changes, so a phone that is switched off mid-flow reopens on the
 *   same step with the same choices.
 * - PER ACCOUNT. The state lives in the account's own database file.
 * - NEVER REPEATED. Once the status is completed / skipped / returning it stays
 *   that way, whatever `ONBOARDING_FLOW_VERSION` a later app carries: a learner
 *   is not sent through the introduction again after an upgrade. (The product
 *   tour is the place for "what is new", and it is optional.)
 * - HARMLESS. Nothing here deletes or resets learning data. The only learning-
 *   adjacent values it writes are the two preferences the Apprendre screen
 *   already writes: the chosen grade and, when the grade changes, an empty subject.
 */
import type { Locale } from '../api/types';
import type { AccountStore } from '../db/accountStore';
import { PREF_GRADE, PREF_SUBJECT } from '../learning/overview';
import { ONBOARDING_STEPS } from './schema';
import type { OnboardingRecord, OnboardingStatus, OnboardingStep, ServerOnboardingState } from './store';

/** Bump when the flow's steps change. Stored for the record; it never forces a finished learner back in. */
export const ONBOARDING_FLOW_VERSION = 1;

export const SERVER_STATES: ServerOnboardingState[] = ['new', 'profile_selected', 'downloads_informed', 'ready'];

export function stepIndex(step: OnboardingStep): number {
  return ONBOARDING_STEPS.indexOf(step);
}

function furthest(a: OnboardingStep, b: OnboardingStep): OnboardingStep {
  return stepIndex(a) >= stepIndex(b) ? a : b;
}

export function isFinished(status: OnboardingStatus): boolean {
  return status !== 'in_progress';
}

/**
 * What the server should know. Forward-only by construction: it is derived
 * from the furthest step ever reached, never from the step currently shown.
 */
export function serverStateOf(record: Pick<OnboardingRecord, 'status' | 'furthestStep'>): ServerOnboardingState {
  if (isFinished(record.status)) return 'ready';
  if (record.furthestStep === 'ready') return 'downloads_informed';
  if (record.furthestStep === 'downloads') return 'profile_selected';
  return 'new';
}

export function serverRank(state: ServerOnboardingState | null): number {
  return state === null ? -1 : SERVER_STATES.indexOf(state);
}

/** The step a learner should see for a state learnt from the server (another phone got that far). */
function stepForServerState(state: ServerOnboardingState): OnboardingStep {
  if (state === 'profile_selected') return 'downloads';
  if (state === 'downloads_informed' || state === 'ready') return 'ready';
  return 'welcome';
}

export type OnboardingGate = 'required' | 'done';

/**
 * Should this account be shown the first-run flow?
 *
 * Reads SQLite only. An account with no onboarding row that has already chosen
 * a grade on this phone is a returning learner (it used the app while the flow
 * was switched off): it is recorded as such and not asked again.
 */
export async function onboardingGate(account: AccountStore, now: Date): Promise<OnboardingGate> {
  const existing = await account.experience.getOnboarding();
  if (existing) return isFinished(existing.status) ? 'done' : 'required';
  const grade = await account.getPreference(PREF_GRADE);
  if (!grade) return 'required';
  await account.experience.updateOnboarding((current) => current ?? returningRecord(now.toISOString(), grade));
  return 'done';
}

function returningRecord(at: string, gradeCode: string | null): OnboardingRecord {
  return {
    flowVersion: 0,
    status: 'returning',
    step: 'ready',
    furthestStep: 'ready',
    gradeCode,
    startedAt: at,
    updatedAt: at,
    completedAt: at,
    serverState: null,
    serverSyncedAt: null,
    needsPush: true,
    profileNeedsPush: false,
  };
}

/** Open the flow: the stored record if there is one (resume), otherwise a new one on the first step. */
export async function beginOrResumeOnboarding(account: AccountStore, now: Date): Promise<OnboardingRecord> {
  const at = now.toISOString();
  const grade = await account.getPreference(PREF_GRADE);
  const record = await account.experience.updateOnboarding((current) =>
    current
      ? null
      : {
          flowVersion: ONBOARDING_FLOW_VERSION,
          status: 'in_progress',
          step: 'welcome',
          furthestStep: 'welcome',
          gradeCode: grade,
          startedAt: at,
          updatedAt: at,
          completedAt: null,
          serverState: null,
          serverSyncedAt: null,
          needsPush: true,
          profileNeedsPush: false,
        },
  );
  return record as OnboardingRecord;
}

/** Show another step (forward or back). Finished flows are left alone. */
export async function goToOnboardingStep(account: AccountStore, step: OnboardingStep, now: Date): Promise<OnboardingRecord | null> {
  return account.experience.updateOnboarding((current) => {
    if (!current || isFinished(current.status) || current.step === step) return null;
    const reached = furthest(current.furthestStep, step);
    return {
      ...current,
      step,
      furthestStep: reached,
      updatedAt: now.toISOString(),
      needsPush: current.needsPush || reached !== current.furthestStep,
    };
  });
}

/** The learner tapped a language. (The preference itself is saved by the app's existing `setLocale`.) */
export async function noteOnboardingLocale(account: AccountStore, _locale: Locale, now: Date): Promise<OnboardingRecord | null> {
  return account.experience.updateOnboarding((current) =>
    current && !isFinished(current.status) ? { ...current, updatedAt: now.toISOString(), profileNeedsPush: true } : null,
  );
}

/** The learner tapped a grade chip: remembered at once, so a restart shows the same selection. */
export async function selectOnboardingGrade(account: AccountStore, gradeCode: string, now: Date): Promise<OnboardingRecord | null> {
  return account.experience.updateOnboarding((current) =>
    current && !isFinished(current.status) && current.gradeCode !== gradeCode
      ? { ...current, gradeCode, updatedAt: now.toISOString() }
      : null,
  );
}

/**
 * Leave the grade step with the selected grade: it becomes the account's grade
 * (the same preference Apprendre writes) and the flow moves on.
 * Safe to repeat: if the phone dies between the writes, doing it again gives the same result.
 */
export async function confirmOnboardingGrade(account: AccountStore, now: Date): Promise<OnboardingRecord | null> {
  const record = await account.experience.getOnboarding();
  if (!record || isFinished(record.status)) return record;
  if (record.gradeCode) {
    const previous = await account.getPreference(PREF_GRADE);
    if (previous !== record.gradeCode) {
      await account.setPreference(PREF_GRADE, record.gradeCode);
      // Same rule as Apprendre: a subject belongs to a grade, so a new grade starts with no subject chosen.
      await account.setPreference(PREF_SUBJECT, '');
    }
    await account.experience.updateOnboarding((current) => (current ? { ...current, profileNeedsPush: true } : null));
  }
  return goToOnboardingStep(account, 'downloads', now);
}

/** "I will choose later": no grade is stored, the flow moves on. */
export async function skipOnboardingGrade(account: AccountStore, now: Date): Promise<OnboardingRecord | null> {
  await account.experience.updateOnboarding((current) =>
    current && !isFinished(current.status) && current.gradeCode !== null
      ? { ...current, gradeCode: null, updatedAt: now.toISOString() }
      : null,
  );
  return goToOnboardingStep(account, 'downloads', now);
}

/** End of the flow (reached the last step, or skipped the introduction). Never undone. */
export async function finishOnboarding(account: AccountStore, how: 'completed' | 'skipped', now: Date): Promise<OnboardingRecord | null> {
  return account.experience.updateOnboarding((current) => {
    if (!current || isFinished(current.status)) return null;
    const at = now.toISOString();
    return { ...current, status: how, updatedAt: at, completedAt: at, needsPush: true };
  });
}

/**
 * Fold in what the server says (another phone, or an earlier install).
 * Forward-only: a server state behind the local one changes nothing; `ready`
 * ends the flow here too, so a learner who already finished elsewhere is not asked again.
 */
export function mergeServerOnboarding(
  current: OnboardingRecord | null,
  server: ServerOnboardingState,
  now: Date,
): OnboardingRecord | null {
  const at = now.toISOString();
  if (current === null) {
    if (server === 'new') return null;
    if (server === 'ready') return { ...returningRecord(at, null), serverState: server, serverSyncedAt: at, needsPush: false };
    const step = stepForServerState(server);
    return {
      flowVersion: ONBOARDING_FLOW_VERSION,
      status: 'in_progress',
      step,
      furthestStep: step,
      gradeCode: null,
      startedAt: at,
      updatedAt: at,
      completedAt: null,
      serverState: server,
      serverSyncedAt: at,
      needsPush: false,
      profileNeedsPush: false,
    };
  }
  const local = serverStateOf(current);
  if (serverRank(server) <= serverRank(local)) {
    // The server is level with or behind this phone: remember what it has, push if it is behind.
    const behind = serverRank(server) < serverRank(local);
    if (current.serverState === server && current.needsPush === behind) return null;
    return { ...current, serverState: server, serverSyncedAt: at, needsPush: behind };
  }
  if (server === 'ready') {
    return { ...current, status: 'returning', completedAt: at, updatedAt: at, serverState: server, serverSyncedAt: at, needsPush: false };
  }
  const step = stepForServerState(server);
  return {
    ...current,
    step: furthest(current.step, step),
    furthestStep: furthest(current.furthestStep, step),
    updatedAt: at,
    serverState: server,
    serverSyncedAt: at,
    needsPush: false,
  };
}
