/**
 * Gold and streak on the phone: a display copy of what the SERVER confirmed.
 *
 * The one rule: the phone never produces a Gold number.
 *  - CONFIRMED Gold is the balance from the server's last summary, shown with
 *    the time it was received.
 *  - Work that is still on the phone (unsynced answers and completions) is
 *    shown as PENDING, by COUNT OF ACTIONS only. It has no Gold value here: the
 *    server decides what, if anything, it earns once it accepts the work. It is
 *    never added to the confirmed balance and never estimated.
 *  - With no summary yet there is no number at all — not even zero.
 */
import { ApiError, isAborted } from '../api/errors';
import type { AccountStore } from '../db/accountStore';
import { ExperienceRemote, parseRemoteRewardsSummary, RemoteRewardsSummary } from './remote';
import type { RewardsRow } from './store';

/** Minimum wait between two downloads of the summary when nothing new was synchronised. */
export const REWARDS_RETRY_AFTER_MS = 10 * 60 * 1000;

/** A copy older than this no longer describes "now": its streak is shown as of its date, or not at all. */
export const STREAK_CURRENT_FOR_MS = 24 * 60 * 60 * 1000;

export type StreakDisplay = { kind: 'current'; days: number } | { kind: 'as_of'; days: number; date: string } | { kind: 'none' };

/**
 * How the streak may be worded. "En cours" is a claim about the present, so it is only made
 * while the copy is less than a day old (by elapsed time on this phone). An older copy is
 * stated as of the server's date, and left out when that date is unknown. Zero is never announced.
 */
export function streakDisplay(confirmed: NonNullable<RewardsView['confirmed']>, now: Date): StreakDisplay {
  const days = confirmed.streak?.current ?? 0;
  if (days <= 0) return { kind: 'none' };
  const age = now.getTime() - Date.parse(confirmed.fetchedAt);
  if (Number.isFinite(age) && age >= 0 && age < STREAK_CURRENT_FOR_MS) return { kind: 'current', days };
  return confirmed.today ? { kind: 'as_of', days, date: confirmed.today } : { kind: 'none' };
}

export interface RewardsView {
  /** Null until the server has sent a summary to this phone. */
  confirmed: (RemoteRewardsSummary & { fetchedAt: string }) | null;
  /** Learning actions saved on this phone that the server has not accepted yet. A count of actions, not Gold. */
  pendingActions: number;
}

export function rewardsView(row: RewardsRow | null, pendingActions: number): RewardsView {
  let confirmed: RewardsView['confirmed'] = null;
  if (row?.body != null && row.fetchedAt) {
    try {
      confirmed = { ...parseRemoteRewardsSummary(row.body), fetchedAt: row.fetchedAt };
    } catch {
      confirmed = null; // a row this version cannot validate is not shown
    }
  }
  return { confirmed, pendingActions: Math.max(0, Math.trunc(pendingActions) || 0) };
}

export type RewardsRefresh = 'updated' | 'throttled' | 'unavailable' | 'unreachable' | 'aborted';

/**
 * Download the summary if it is worth a request: never downloaded, or work was
 * synchronised since the last attempt, or the last attempt is old enough.
 * Never throws. NETWORK: callers only invoke this when the `rewards` flag is on.
 */
export async function refreshRewards(
  account: AccountStore,
  remote: ExperienceRemote,
  env: { now: () => Date; isActive?: () => boolean },
): Promise<RewardsRefresh> {
  const active = () => env.isActive?.() ?? true;
  try {
    const row = await account.experience.getRewards();
    if (row?.lastAttemptAt) {
      const since = env.now().getTime() - Date.parse(row.lastAttemptAt);
      const { lastSyncAt } = await account.syncSummary();
      const syncedSince = lastSyncAt !== null && Date.parse(lastSyncAt) > Date.parse(row.lastAttemptAt);
      if (!syncedSince && since >= 0 && since < REWARDS_RETRY_AFTER_MS) return 'throttled';
    }
    try {
      const summary = await remote.getRewardsSummary();
      if (!active()) return 'aborted';
      await account.experience.putRewards(summary, env.now().toISOString());
      return 'updated';
    } catch (error) {
      if (isAborted(error) || !active()) return 'aborted';
      const outcome = error instanceof ApiError && error.kind === 'client' ? 'unavailable' : 'unreachable';
      await account.experience.noteRewardsAttempt(env.now().toISOString(), outcome);
      return outcome;
    }
  } catch {
    return 'unreachable';
  }
}
