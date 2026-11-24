import { Redirect, useFocusEffect, useRouter } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { View } from 'react-native';

import type { CatalogResponse } from '../core/api/types';
import {
  findLessonContext,
  LessonStanding,
  pickContinueLesson,
  PREF_LAST_LESSON,
  savedLessonStandings,
  totalsOf,
} from '../core/learning/overview';
import { AppText, Button, HeroCard, Icon, ListRow, LoadingState, MessageState, Notice, ProgressBar, SectionHeader, space } from '../design';
import { TabScreen } from '../ui/shell';
import { useSignedIn } from '../ui/useSession';

interface HomeView {
  standings: LessonStanding[];
  lastLessonId: string | null;
  catalog: CatalogResponse | null;
}

/** Accueil: one clear primary action — continue learning. Every value comes from SQLite. */
export default function Home() {
  const app = useSignedIn();
  const router = useRouter();
  const [view, setView] = useState<HomeView | null>(null);
  const [failed, setFailed] = useState(false);
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
        const standings = await savedLessonStandings(content, session.account, locale);
        const lastLessonId = await session.account.getPreference(PREF_LAST_LESSON);
        const cached = await content.getCatalog(locale);
        if (live && session.isActive()) {
          setView({ standings, lastLessonId, catalog: cached?.catalog ?? null });
          setFailed(false);
        }
        await app.refreshSummary();
      })().catch(() => live && setFailed(true));
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [session, locale, pending, syncedAt]),
  );

  if (!app) return <Redirect href="/sign-in" />;
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
          onPress={() => router.push(`/lesson/${next.lessonId}`)}
        />
      </HeroCard>

      {pendingRow}

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
    </TabScreen>
  );
}
