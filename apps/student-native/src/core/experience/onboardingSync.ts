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
import { isAborted } from '../api/errors';
import type { Locale } from '../api/types';
import type { AccountStore } from '../db/accountStore';
import { PREF_GRADE } from '../learning/overview';
import { mergeServerOnboarding, ONBOARDING_FLOW_VERSION, serverRank, serverStateOf } from './onboarding';
import type { ExperienceRemote, ProfilePatch } from './remote';

export type OnboardingSyncOutcome = 'synced' | 'nothing_to_do' | 'failed';

export async function syncOnboarding(
  account: AccountStore,
  remote: ExperienceRemote,
  env: { now: () => Date; isActive?: () => boolean },
): Promise<OnboardingSyncOutcome> {
  const active = () => env.isActive?.() ?? true;
  try {
    const server = await remote.getOnboarding();
    if (!active()) return 'failed';

    // 1. forward-only merge of what the server has
    await account.experience.updateOnboarding((current) => mergeServerOnboarding(current, server.state, env.now()));
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
        state: stateAhead ? localState : server.state,
        onboarding_version: Math.max(server.onboarding_version, record?.flowVersion ?? 0, stateAhead ? ONBOARDING_FLOW_VERSION : 0),
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
        await remote.patchProfile(patch);
        if (!active()) return 'failed';
        pushed = true;
      }
      await account.experience.updateOnboarding((current) => (current ? { ...current, profileNeedsPush: false } : null));
    }
    return pushed ? 'synced' : 'nothing_to_do';
  } catch (error) {
    if (isAborted(error)) return 'failed';
    // Offline, server down, endpoint not deployed, refused value: keep the local flags and try again later.
    return 'failed';
  }
}

/** Is there anything this phone still owes the server? Read from SQLite; lets callers avoid a pointless request. */
export async function onboardingSyncDue(account: AccountStore): Promise<boolean> {
  const record = await account.experience.getOnboarding();
  if (record && (record.needsPush || record.profileNeedsPush)) return true;
  return (await account.experience.getTour()).needsPush;
}
