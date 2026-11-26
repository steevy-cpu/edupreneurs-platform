import { Redirect, useFocusEffect, useRouter } from 'expo-router';
import React, { useCallback, useState } from 'react';

import { FLAGS } from '../core/experience/flags';
import type { TourRecord } from '../core/experience/store';
import { dismissTour, finishTour, setTourStep, startTour, TOUR_STEPS } from '../core/experience/tour';
import { AppText, Button, Card, LoadingState, Pill, ScreenFrame, StepStrip, TopBar } from '../design';
import { OfflinePill } from '../ui/shell';
import { useSignedIn } from '../ui/useSession';

/**
 * The optional product tour: a few plain pages about the four tabs.
 *
 * It is its own full-screen route, opened only by a tap on Accueil or Profil,
 * so it can never sit on top of a lesson or an exercise. It reads and writes
 * this account's SQLite database only (which step, seen, dismissed) and works
 * with no connection. It can be closed at every step.
 */
export default function Tour() {
  const app = useSignedIn();
  const router = useRouter();
  const [tour, setTour] = useState<TourRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const session = app?.session;

  useFocusEffect(
    useCallback(() => {
      if (!FLAGS.tour || !app || !session) return;
      let live = true;
      // Opened directly (not through the buttons that start a run): begin, or continue an interrupted run.
      startTour(session.account, app.services.env.now())
        .then((opened) => live && session.isActive() && setTour(opened))
        .catch(() => undefined);
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [session]),
  );

  if (!app) return <Redirect href="/sign-in" />;
  if (!FLAGS.tour) return <Redirect href="/home" />;
  const { t } = app;
  const account = app.session.account;
  const now = () => app.services.env.now();
  const leave = () => (router.canGoBack() ? router.back() : router.replace('/home'));

  if (!tour) {
    return (
      <ScreenFrame top={<TopBar title={t('tourTitle')} onBack={leave} trailing={<OfflinePill />} />}>
        <LoadingState label={t('loading')} />
      </ScreenFrame>
    );
  }

  const index = Math.min(tour.step, TOUR_STEPS.length - 1);
  const step = TOUR_STEPS[index];
  const last = index === TOUR_STEPS.length - 1;

  const run = async (work: () => Promise<TourRecord>, then?: () => void) => {
    if (busy) return;
    setBusy(true);
    try {
      const next = await work();
      if (then) then();
      else if (app.session.isActive()) setTour(next);
    } catch {
      // The tour is a convenience: if its state cannot be written, leaving is always possible.
      if (then) then();
    } finally {
      setBusy(false);
    }
  };

  const close = () => void run(() => dismissTour(account, now()), leave);
  const back = () => (index === 0 ? close() : void run(() => setTourStep(account, index - 1, now())));

  return (
    <ScreenFrame
      top={<TopBar title={t('tourTitle')} onBack={back} trailing={<OfflinePill />} />}
      action={
        <>
          {last ? (
            <Button label={t('tourFinish')} busy={busy} testID="tour-finish" onPress={() => void run(() => finishTour(account, now()), leave)} />
          ) : (
            <Button label={t('tourNext')} busy={busy} testID="tour-next" onPress={() => void run(() => setTourStep(account, index + 1, now()))} />
          )}
          {last ? null : <Button label={t('tourClose')} variant="secondary" disabled={busy} testID="tour-close" onPress={close} />}
        </>
      }
    >
      <StepStrip steps={TOUR_STEPS.map((each) => t(each.tab))} current={index} />
      <AppText variant="display" accessibilityRole="header">
        {t(step.title)}
      </AppText>
      <Card>
        <Pill tone="action" label={t('tourWhere', { tab: t(step.tab) })} />
        <AppText>{t(step.body)}</AppText>
      </Card>
    </ScreenFrame>
  );
}
