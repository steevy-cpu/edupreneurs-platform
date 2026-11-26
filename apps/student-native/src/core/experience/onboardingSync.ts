/**
 * Keeps the server's copy of the onboarding state and of the chosen grade /
 * language in step with this phone. NETWORK: only runs when the
 * `onboardingSync` flag is on.
 *
 * It is a background nicety, never a gate: the flow is complete without it, a
 * failure is swallowed and retried the next time, and nothing here touches
 * learning data.
 *
 * Order: read the server first (it may already know this learner as onboarded
 * from another phone), merge forward-only, then push whatever this phone is
 * ahead on. Repeating the whole thing is harmless: the server ignores a state
 * that does not move it forward, and the tour flags only ever grow.
 */
import { ApiError, isAborted } from '../api/errors';
import type { Locale } from '../api/types';
import type { AccountStore } from '../db/accountStore';
import { PREF_GRADE } from '../learning/overview';
import { mergeServerOnboarding, ONBOARDING_FLOW_VERSION, serverRank, serverStateOf } from './onboarding';
import type { ExperienceRemote, ProfilePatch } from './remote';

export type OnboardingSyncOutcome = 'synced' | 'nothing_to_do' | 'failed' | 'spaced';

/** Minimum wait between two runs for one account, unless the caller has a new milestone to report (`force`). */
export const ONBOARDING_SYNC_SPACING_MS = 10 * 60 * 1000;

interface SyncEnv {
  now: () => Date;
  isActive?: () => boolean;
  /** A milestone was just reached (the flow was finished): do not wait for the spacing. */
  force?: boolean;
}

// Per signed-in account store, in memory: one run at a time, and when the last one started.
const inFlight = new WeakMap<AccountStore, Promise<OnboardingSyncOutcome>>();
const lastStarted = new WeakMap<AccountStore, number>();

/**
 * Single flight and spacing around `runOnboardingSync`: screens may call this on
 * every focus without multiplying requests. Never throws.
 */
export async function syncOnboarding(account: AccountStore, remote: ExperienceRemote, env: SyncEnv): Promise<OnboardingSyncOutcome> {
  const running = inFlight.get(account);
  if (running) {
    const outcome = await running;
    if (!env.force) return outcome; // the run that was in flight covers this call
  }
  const started = lastStarted.get(account);
  const since = started === undefined ? Infinity : env.now().getTime() - started;
  if (!env.force && since >= 0 && since < ONBOARDING_SYNC_SPACING_MS) return 'spaced';
  lastStarted.set(account, env.now().getTime());
  const run = runOnboardingSync(account, remote, env).finally(() => {
    if (inFlight.get(account) === run) inFlight.delete(account);
  });
  inFlight.set(account, run);
  return run;
}

async function runOnboardingSync(account: AccountStore, remote: ExperienceRemote, env: SyncEnv): Promise<OnboardingSyncOutcome> {
  const active = () => env.isActive?.() ?? true;
  try {
    const server = await remote.getOnboarding();
    if (!active()) return 'failed';

    // 0. A phone with no grade for this account: ask the server profile once, so a learner the
    //    server already knows is not left with "class: to be chosen" (and Apprendre with no courses).
    let localGrade = await account.getPreference(PREF_GRADE);
    let serverGrade: string | null = null;
    if (!localGrade && server.state !== 'new') {
      try {
        serverGrade = (await remote.getProfile()).grade_code;
      } catch (error) {
        if (isAborted(error)) return 'failed';
        serverGrade = null; // not essential: the learner can still choose
      }
      if (!active()) return 'failed';
      if (serverGrade && server.state === 'ready') {
        // Finished elsewhere: there will be no grade step here, so the known grade becomes the phone's grade.
        await account.setPreference(PREF_GRADE, serverGrade);
        localGrade = serverGrade;
      }
    }

    // 1. forward-only merge of what the server has
    await account.experience.updateOnboarding((current) => {
      const merged = mergeServerOnboarding(current, server.state, env.now(), Boolean(localGrade));
      const base = merged ?? current;
      // Prefill the grade step's selection with the server's grade; the learner still confirms it there.
      if (base && serverGrade && !base.gradeCode) return { ...base, gradeCode: serverGrade };
      return merged;
    });
    await account.experience.updateTour((current) => {
      const versionSeen = Math.max(current.versionSeen, server.tour_version_seen);
      const dismissed = current.dismissed || server.tour_dismissed;
      const ahead = current.versionSeen > server.tour_version_seen || (current.dismissed && !server.tour_dismissed);
      if (versionSeen === current.versionSeen && dismissed === current.dismissed && current.needsPush === ahead) return null;
      return { ...current, versionSeen, dismissed, needsPush: ahead, updatedAt: current.updatedAt || env.now().toISOString() };
    });

    // 2. push what this phone is ahead on
    let pushed = false;
    const record = await account.experience.getOnboarding();
    const tour = await account.experience.getTour();
    const localState = record ? serverStateOf(record) : 'new';
    const stateAhead = serverRank(localState) > serverRank(server.state);
    if (stateAhead || tour.needsPush) {
      const acknowledged = await remote.putOnboarding({
        // Only what moves the server forward; the server ignores anything behind what it has.
        ...(stateAhead ? { state: localState } : {}),
        onboarding_version: ONBOARDING_FLOW_VERSION,
        tour_version_seen: tour.versionSeen,
        tour_dismissed: tour.dismissed,
      });
      if (!active()) return 'failed';
      const at = env.now().toISOString();
      await account.experience.updateOnboarding((current) =>
        current
          ? {
              ...current,
              serverState: acknowledged.state,
              serverSyncedAt: at,
              // Still ahead of what the server acknowledged (it should not happen): keep trying.
              needsPush: serverRank(serverStateOf(current)) > serverRank(acknowledged.state),
            }
          : null,
      );
      await account.experience.updateTour((current) => ({
        ...current,
        needsPush: current.versionSeen > acknowledged.tour_version_seen || (current.dismissed && !acknowledged.tour_dismissed),
      }));
      pushed = true;
    }

    // 3. the grade and language chosen on this phone
    const after = await account.experience.getOnboarding();
    if (after?.profileNeedsPush) {
      const patch: ProfilePatch = {};
      const grade = await account.getPreference(PREF_GRADE);
      const locale = await account.getPreference('locale');
      if (grade) patch.grade_code = grade;
      if (locale === 'fr' || locale === 'ht') patch.preferred_locale = locale as Locale;
      if (Object.keys(patch).length > 0) {
        try {
          await remote.patchProfile(patch);
          pushed = true;
        } catch (error) {
          // A refusal of the request itself (profile editing off on the server: 404; a grade the server
          // does not offer: 422; …) will not change by asking again: it is FINAL. Anything else is retried later.
          if (!(error instanceof ApiError && error.kind === 'client')) throw error;
        }
        if (!active()) return 'failed';
      }
      // Cleared only if nothing was chosen while the request was in flight (a newer choice keeps the flag).
      await account.experience.updateOnboarding((current) =>
        current && current.updatedAt === after.updatedAt ? { ...current, profileNeedsPush: false } : null,
      );
    }
    return pushed ? 'synced' : 'nothing_to_do';
  } catch (error) {
    if (isAborted(error)) return 'failed';
    // Offline, server down, endpoint not deployed: keep the local flags and try again later (spaced).
    return 'failed';
  }
}

/** Is there anything this phone still owes the server? Read from SQLite; lets callers avoid a pointless request. */
export async function onboardingSyncDue(account: AccountStore): Promise<boolean> {
  const record = await account.experience.getOnboarding();
  if (record && (record.needsPush || record.profileNeedsPush)) return true;
  return (await account.experience.getTour()).needsPush;
}
