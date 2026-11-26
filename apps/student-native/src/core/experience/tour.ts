/**
 * The optional product tour: rules only (no screen, no network).
 *
 * - OPTIONAL. It is offered as a card on Accueil and never opens by itself.
 * - DISMISSIBLE at any step, and REPLAYABLE from Profil at any time.
 * - Its own full-screen route: it cannot appear on top of a lesson or a quiz.
 * - Stored per account as a version and two flags, in the account's database:
 *     versionSeen  highest tour version this account finished or closed
 *     dismissed    the learner closed a tour before its end, or declined the offer
 *   Offer rule: shown on Accueil while `versionSeen < TOUR_VERSION` and not
 *   `dismissed`. So a learner who FINISHED version 1 is offered version 2 when
 *   it exists; a learner who DECLINED is not asked again (Profil still has it).
 * - A run that was interrupted (app killed) can be continued at the same step.
 */
import type { AccountStore } from '../db/accountStore';
import type { StringKey } from '../i18n/strings';
import type { TourRecord } from './store';

/** Bump when the tour's content changes enough to be worth offering again. */
export const TOUR_VERSION = 1;

export interface TourStep {
  /** The tab this step is about (its translated name is shown as "where"). */
  tab: 'tabHome' | 'tabLearn' | 'tabReview' | 'tabProfile';
  title: StringKey;
  body: StringKey;
}

export const TOUR_STEPS: TourStep[] = [
  { tab: 'tabHome', title: 'tourHomeTitle', body: 'tourHomeBody' },
  { tab: 'tabLearn', title: 'tourLearnTitle', body: 'tourLearnBody' },
  { tab: 'tabReview', title: 'tourReviewTitle', body: 'tourReviewBody' },
  { tab: 'tabProfile', title: 'tourProfileTitle', body: 'tourProfileBody' },
];

export type TourOffer = 'none' | 'start' | 'resume';

/** What Accueil should offer, if anything. */
export function tourOffer(tour: TourRecord): TourOffer {
  if (tour.inProgress) return 'resume';
  return !tour.dismissed && tour.versionSeen < TOUR_VERSION ? 'start' : 'none';
}

function clampStep(step: number): number {
  return Math.max(0, Math.min(TOUR_STEPS.length - 1, Math.trunc(step) || 0));
}

/** Open the tour. `replay` always starts from the first step; otherwise an interrupted run continues. */
export async function startTour(account: AccountStore, now: Date, options: { replay?: boolean } = {}): Promise<TourRecord> {
  return account.experience.updateTour((current) => ({
    ...current,
    inProgress: true,
    step: options.replay || !current.inProgress ? 0 : clampStep(current.step),
    updatedAt: now.toISOString(),
  }));
}

export async function setTourStep(account: AccountStore, step: number, now: Date): Promise<TourRecord> {
  return account.experience.updateTour((current) =>
    current.inProgress && current.step !== clampStep(step) ? { ...current, step: clampStep(step), updatedAt: now.toISOString() } : null,
  );
}

/** The learner reached the end. */
export async function finishTour(account: AccountStore, now: Date): Promise<TourRecord> {
  return account.experience.updateTour((current) => ({
    ...current,
    inProgress: false,
    step: 0,
    versionSeen: Math.max(current.versionSeen, TOUR_VERSION),
    updatedAt: now.toISOString(),
    needsPush: current.needsPush || current.versionSeen < TOUR_VERSION,
  }));
}

/**
 * The learner closed the tour before the end, or declined the offer.
 * Closing a REPLAY of a tour already seen changes no flag: it just ends the run.
 */
export async function dismissTour(account: AccountStore, now: Date): Promise<TourRecord> {
  return account.experience.updateTour((current) => {
    const firstTime = current.versionSeen < TOUR_VERSION;
    if (!firstTime && !current.inProgress) return null;
    return {
      ...current,
      inProgress: false,
      step: 0,
      versionSeen: Math.max(current.versionSeen, TOUR_VERSION),
      dismissed: current.dismissed || firstTime,
      updatedAt: now.toISOString(),
      needsPush: current.needsPush || firstTime,
    };
  });
}
