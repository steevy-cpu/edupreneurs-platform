import { Redirect, useFocusEffect, useRouter } from 'expo-router';
import React, { useCallback, useEffect, useState } from 'react';
import { View } from 'react-native';

import type { CatalogResponse } from '../core/api/types';
import { FLAGS } from '../core/experience/flags';
import { onboardingGate } from '../core/experience/onboarding';
import { onboardingSyncDue, syncOnboarding } from '../core/experience/onboardingSync';
import { EMPTY_TOUR, TourRecord } from '../core/experience/store';
import { dismissTour, startTour, tourOffer } from '../core/experience/tour';
import {
  findLessonContext,
  LessonStanding,
  pickContinueLesson,
  PREF_LAST_LESSON,
  savedLessonStandings,
  totalsOf,
} from '../core/learning/overview';
import { AppText, Button, HeroCard, Icon, ListRow, LoadingState, MessageState, Notice, ProgressBar, SectionHeader, space } from '../design';
import { DailyWordCard } from '../ui/experience/DailyWordCard';
import { TourInvite } from '../ui/experience/TourInvite';
import { perfHomeReady, perfTap } from '../ui/perf';
import { useRemote } from '../ui/remote';
import { TabScreen } from '../ui/shell';
import { useSignedIn } from '../ui/useSession';

interface HomeView {
  standings: LessonStanding[];
  lastLessonId: string | null;
  catalog: CatalogResponse | null;
  /** Product tour state; the untouched default when the `tour` flag is off (nothing is then offered). */
  tour: TourRecord;
}

/** Accueil: one clear primary action — continue learning. Every value comes from SQLite. */
export default function Home() {
  const app = useSignedIn();
  const router = useRouter();
  const remote = useRemote();
  const [view, setView] = useState<HomeView | null>(null);
  const [failed, setFailed] = useState(false);
  // First-run onboarding (flag off by default: the check is then skipped entirely).
  const [onboardingDue, setOnboardingDue] = useState(false);
  const session = app?.session;
  const locale = app?.locale;
  // Re-read after every sync run so confirmations and other devices' work appear.
  const pending = app?.sync.summary.pending;
  const syncedAt = app?.sync.summary.lastSyncAt;

  useFocusEffect(
    useCallback(() => {
      if (!app || !session || !locale) return;
      let live = true;
      (async () => {
        const { content } = app.services;
        if (FLAGS.onboarding && (await onboardingGate(session.account, app.services.env.now())) === 'required') {
          if (live && session.isActive()) setOnboardingDue(true);
          return;
        }
        const standings = await savedLessonStandings(content, session.account, locale);
        const lastLessonId = await session.account.getPreference(PREF_LAST_LESSON);
        const cached = await content.getCatalog(locale);
        const tour = FLAGS.tour ? await session.account.experience.getTour() : EMPTY_TOUR;
        if (live && session.isActive()) {
          setView({ standings, lastLessonId, catalog: cached?.catalog ?? null, tour });
          setFailed(false);
          setOnboardingDue(false);
        }
        await app.refreshSummary();
        // Network flag (off by default): tell the server what this phone finished, only when something is owed.
        if (FLAGS.onboardingSync && remote && (await onboardingSyncDue(session.account))) {
          void syncOnboarding(session.account, remote, { now: app.services.env.now, isActive: () => session.isActive() });
        }
      })().catch(() => live && setFailed(true));
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [session, locale, pending, syncedAt, remote]),
  );

  // Measurement builds only (see ui/perf.ts): runs after the Home content has been committed.
  const ready = view !== null;
  useEffect(() => {
    if (ready) perfHomeReady();
  }, [ready]);

  if (!app) return <Redirect href="/sign-in" />;
  if (onboardingDue) return <Redirect href="/onboarding" />;
  const { t, sync, needsReauth } = app;
  const name = app.session.email.split('@')[0];

  const greeting = (
    <AppText variant="display" accessibilityRole="header">
      {t('homeHello')} {name}
    </AppText>
  );
  const reauth = needsReauth ? (
    <View style={{ gap: space.sm }}>
      <Notice>{t('sessionExpiredBanner')}</Notice>
      <Button variant="secondary" label={t('signInAgainTitle')} onPress={() => router.push('/sign-in')} />
    </View>
  ) : null;

  if (failed && !view) {
    return (
      <TabScreen tab="home">
        {greeting}
        <MessageState tone="danger" title={t('errorTitle')} body={t('errorBody')} />
      </TabScreen>
    );
  }
  if (!view) {
    return (
      <TabScreen tab="home">
        <LoadingState label={t('loading')} />
      </TabScreen>
    );
  }

  // Optional tour (flag off by default): an inline card under the learning content, never a pop-up.
  const tourInvite = FLAGS.tour ? (
    <TourInvite
      offer={tourOffer(view.tour)}
      t={t}
      onStart={() => {
        void startTour(app.session.account, app.services.env.now())
          .catch(() => undefined)
          .then(() => router.push('/tour'));
      }}
      onDecline={() => {
        void dismissTour(app.session.account, app.services.env.now())
          .then((tour) => app.session.isActive() && setView((current) => (current ? { ...current, tour } : current)))
          .catch(() => undefined);
      }}
    />
  ) : null;

  // Word of the Day (flag off by default): drawn from the account's cache, refreshed in the background.
  const dailyWord = FLAGS.dailyWord ? (
    <DailyWordCard
      account={app.session.account}
      remote={remote}
      locale={app.locale}
      t={t}
      now={app.services.env.now}
      isActive={() => app.session.isActive()}
    />
  ) : null;

  const next = pickContinueLesson(view.standings, view.lastLessonId);
  const context = next ? findLessonContext(view.catalog, next.lessonId) : null;
  const totals = totalsOf(view.standings);
  const pendingRow =
    sync.summary.pending > 0 ? (
      <ListRow
        icon="ring"
        tone="highlight"
        title={t('syncPending', { count: sync.summary.pending })}
        subtitle={t('stateSaved')}
        onPress={() => router.replace('/profile')}
      />
    ) : null;

  if (!next) {
    return (
      <TabScreen tab="home">
        {greeting}
        {reauth}
        <MessageState
          title={t('homeEmptyTitle')}
          body={t('homeEmptyBody')}
          actionLabel={t('homeEmptyAction')}
          onAction={() => router.replace('/learn')}
        />
        {pendingRow}
        {dailyWord}
        {tourInvite}
      </TabScreen>
    );
  }

  const progressLabel = t('homeContinueProgress', { answered: next.answered, total: next.questionCount });
  return (
    <TabScreen tab="home">
      {greeting}
      {reauth}

      <HeroCard>
        {context ? (
          <AppText variant="caption" color="textOnHeroSecondary">
            {context.subjectLabel} · {context.gradeCode} · {t('lessonNumber', { number: context.lessonNumber })}
          </AppText>
        ) : null}
        <AppText variant="title" color="textOnHero">
          {next.title}
        </AppText>
        {next.questionCount > 0 ? (
          <>
            <ProgressBar value={next.answered / next.questionCount} onHero label={progressLabel} />
            <AppText variant="caption" color="textOnHeroSecondary">
              {progressLabel}
              {next.completed ? ` · ${t('lessonCompleted')}` : ''}
            </AppText>
          </>
        ) : null}
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.xs }}>
          <Icon name="check" color="#8FE3CF" size={16} />
          <AppText variant="caption" color="textOnHeroSecondary" style={{ flex: 1 }}>
            {t('availableOffline')}
          </AppText>
        </View>
        <Button
          label={t('continueLesson')}
          variant="onHero"
          icon="play"
          testID="home-continue"
          onPress={() => {
            perfTap();
            router.push(`/lesson/${next.lessonId}`);
          }}
        />
      </HeroCard>

      {pendingRow}

      {dailyWord}

      <View style={{ gap: space.sm }}>
        <SectionHeader title={t('tabReview')} />
        <ListRow
          icon="review"
          tone="accent"
          title={totals.questionsMissed > 0 ? t('reviewMistakes') : t('reviewAll')}
          subtitle={totals.questionsMissed > 0 ? t('questionsToReview', { count: totals.questionsMissed }) : undefined}
          onPress={() => router.replace('/review')}
        />
      </View>

      <View style={{ gap: space.sm }}>
        <SectionHeader title={t('downloadedLessons')} />
        {view.standings.map((lesson) => (
          <ListRow
            key={lesson.lessonId}
            icon="download"
            title={lesson.title}
            subtitle={lesson.completed ? `${t('availableOffline')} · ${t('lessonCompleted')}` : t('availableOffline')}
            onPress={() => router.push(`/lesson/${lesson.lessonId}`)}
          />
        ))}
      </View>

      {tourInvite}
    </TabScreen>
  );
}
