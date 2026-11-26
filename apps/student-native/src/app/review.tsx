import { Redirect, useFocusEffect, useRouter } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { View } from 'react-native';

import { LessonStanding, learningStandings } from '../core/learning/overview';
import { AppText, Button, Card, LoadingState, MessageState, Pill, space } from '../design';
import { TabScreen } from '../ui/shell';
import { useSignedIn } from '../ui/useSession';

/**
 * Réviser: redo the exercises of lessons saved on this phone.
 * There is no recommendation engine: the only "personalised" element is the
 * list of questions whose last recorded answer was wrong, read from SQLite.
 */
export default function Review() {
  const app = useSignedIn();
  const router = useRouter();
  const [lessons, setLessons] = useState<LessonStanding[] | null>(null);
  const session = app?.session;
  const locale = app?.locale;
  const pending = app?.sync.summary.pending;
  const syncedAt = app?.sync.summary.lastSyncAt;

  useFocusEffect(
    useCallback(() => {
      if (!app || !session || !locale) return;
      let live = true;
      learningStandings(app.services.content, session.account, locale)
        .then(
          (all) =>
            live &&
            session.isActive() &&
            // A downloaded lesson needs exercises; an online one is listed once the student has answered something.
            setLessons(all.filter((lesson) => (lesson.questionCount ?? 0) > 0 || (lesson.availability === 'online' && lesson.answered > 0))),
        )
        .catch(() => live && setLessons([]));
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [session, locale, pending, syncedAt]),
  );

  if (!app) return <Redirect href="/sign-in" />;
  const { t } = app;

  const title = (
    <View style={{ gap: space.xs }}>
      <AppText variant="display" accessibilityRole="header">
        {t('tabReview')}
      </AppText>
      <AppText color="textSecondary">{t('reviewIntro')}</AppText>
    </View>
  );

  if (lessons === null) {
    return (
      <TabScreen tab="review">
        <LoadingState label={t('loading')} />
      </TabScreen>
    );
  }
  if (lessons.length === 0) {
    return (
      <TabScreen tab="review">
        {title}
        <MessageState
          title={t('reviewEmptyTitle')}
          body={t('reviewEmptyBody')}
          actionLabel={t('homeEmptyAction')}
          onAction={() => router.replace('/learn')}
        />
      </TabScreen>
    );
  }

  return (
    <TabScreen tab="review">
      {title}
      {lessons.map((lesson) => {
        const missed = lesson.missedQuestionIds.length;
        const online = lesson.availability === 'online';
        const mode = online ? '&mode=online' : '';
        return (
          <Card key={lesson.lessonId} tone="accentSoft">
            <AppText variant="heading" accessibilityRole="header">
              {lesson.title}
            </AppText>
            <AppText color="textSecondary">
              {lesson.answered === 0
                ? t('reviewNotStarted')
                : lesson.questionCount === null
                  ? t('reviewSummaryOnline', { answered: lesson.answered, correct: lesson.correct })
                  : t('reviewSummary', { answered: lesson.answered, total: lesson.questionCount, correct: lesson.correct })}
            </AppText>
            {online ? <Pill tone="neutral" label={`${t('readerOnlineBadge')}`} /> : null}
            {online ? (
              <AppText variant="caption" color="textSecondary">
                {t('reviewOnlineHint')}
              </AppText>
            ) : null}
            {lesson.waiting > 0 ? <Pill tone="warning" icon="ring" label={t('stateWaiting')} /> : null}
            {missed > 0 ? (
              <Button
                label={t('reviewMissed', { count: missed })}
                icon="review"
                onPress={() => router.push(`/quiz/${lesson.lessonId}?only=missed${mode}`)}
              />
            ) : null}
            <Button
              variant={missed > 0 ? 'secondary' : 'primary'}
              label={t('reviewAll')}
              accessibilityHint={lesson.title}
              onPress={() => router.push(`/quiz/${lesson.lessonId}${online ? '?mode=online' : ''}`)}
            />
          </Card>
        );
      })}
    </TabScreen>
  );
}
