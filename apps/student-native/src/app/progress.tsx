import { Redirect, useFocusEffect } from 'expo-router';
import React, { useCallback, useState } from 'react';

import type { AttentionItem } from '../core/db/accountStore';
import { Body, Card, Loading, Screen } from '../ui/components';
import { SyncCard } from '../ui/SyncCard';
import { useSignedIn } from '../ui/useSession';

interface LessonSummary {
  lessonId: string;
  title: string;
  total: number;
  answered: number;
  correct: number;
  waiting: number;
  completed: boolean;
}

export default function Progress() {
  const app = useSignedIn();
  const [lessons, setLessons] = useState<LessonSummary[] | null>(null);
  const [attention, setAttention] = useState<AttentionItem[]>([]);
  const session = app?.session;
  const locale = app?.locale;
  // Re-read after every sync run so confirmations and other devices' work appear.
  const syncedAt = app?.sync.summary.lastSyncAt;
  const pending = app?.sync.summary.pending;

  useFocusEffect(
    useCallback(() => {
      if (!app || !session || !locale) return;
      let live = true;
      (async () => {
        const saved = await app.services.content.listSavedLessons(locale);
        const out: LessonSummary[] = [];
        for (const info of saved) {
          const lesson = await app.services.content.getLesson(info.lessonId, locale);
          if (!lesson) continue;
          const progress = await session.account.questionProgress(info.lessonId);
          const current = lesson.questions.map((q) => progress.get(q.id)).filter((p) => p !== undefined);
          out.push({
            lessonId: info.lessonId,
            title: info.title,
            total: lesson.questions.length,
            answered: current.length,
            correct: current.filter((p) => p.lastIsCorrect === true).length,
            waiting: current.filter((p) => p.lastSyncState === 'pending').length,
            completed: Boolean((await session.account.lessonProgress(info.lessonId))?.completed),
          });
        }
        const items = await session.account.attentionItems();
        if (!live) return;
        setLessons(out);
        setAttention(items);
      })().catch(() => live && setLessons([]));
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [session, locale, syncedAt, pending]),
  );

  if (!app) return <Redirect href="/sign-in" />;
  const { t } = app;

  return (
    <Screen>
      <SyncCard />
      {lessons === null ? <Loading label={t('loading')} /> : null}
      {lessons !== null && lessons.length === 0 ? <Body muted>{t('progressNone')}</Body> : null}
      {(lessons ?? []).map((lesson) => (
        <Card key={lesson.lessonId}>
          <Body style={{ fontWeight: '700' }}>{lesson.title}</Body>
          <Body>{t('progressAnswered', { answered: lesson.answered, total: lesson.total })}</Body>
          <Body>{t('progressCorrect', { correct: lesson.correct })}</Body>
          {lesson.completed ? <Body>{t('lessonCompleted')}</Body> : null}
          <Body muted>
            {lesson.waiting > 0 ? `${t('stateWaiting')} (${lesson.waiting})` : lesson.answered > 0 ? t('stateSynced') : ''}
          </Body>
        </Card>
      ))}
      {attention.length > 0 ? (
        <Card>
          <Body style={{ fontWeight: '700' }}>{t('stateAttention')}</Body>
          {attention.map((item) => (
            <Body key={item.opId} muted>
              {t('attentionExplain', { code: item.problemCode })}
            </Body>
          ))}
        </Card>
      ) : null}
    </Screen>
  );
}
