import { Redirect, useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import React, { useCallback, useEffect, useState } from 'react';
import { View } from 'react-native';

import type { SavedLesson } from '../../core/db/contentStore';
import { completeLesson } from '../../core/learning/actions';
import { findLessonContext, LessonContext, PREF_LAST_LESSON } from '../../core/learning/overview';
import { AppText, Button, Card, LessonHeader, LoadingState, MessageState, SectionHeader, space, useDesign } from '../../design';
import { perfSinceTap } from '../../ui/perf';
import { DetailScreen } from '../../ui/shell';
import { useSignedIn } from '../../ui/useSession';

type Block = Record<string, unknown>;

/**
 * Draws one content block. Only the block types the lesson schema has today
 * are styled; an unknown type falls back to its text rather than disappearing.
 */
function BlockView({ block, exampleLabel }: { block: Block; exampleLabel: string }) {
  const { colors } = useDesign();
  const text = typeof block.text === 'string' ? block.text : '';
  switch (block.type) {
    case 'heading':
      return <SectionHeader title={text} />;
    case 'paragraph':
      return <AppText>{text}</AppText>;
    case 'example': {
      const steps = Array.isArray(block.steps) ? (block.steps as unknown[]) : [];
      return (
        <Card>
          <AppText variant="caption" color="actionText">
            {exampleLabel}
          </AppText>
          {typeof block.title === 'string' ? <AppText variant="maths">{block.title}</AppText> : null}
          {steps.map((step, index) => (
            <View key={index} style={{ flexDirection: 'row', gap: space.sm }}>
              <View
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: 13,
                  backgroundColor: colors.actionSoft,
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <AppText variant="caption" color="actionText" maxFontSizeMultiplier={1.2}>
                  {index + 1}
                </AppText>
              </View>
              <AppText style={{ flex: 1 }}>{String(step)}</AppText>
            </View>
          ))}
        </Card>
      );
    }
    case 'callout':
      return (
        <Card tone="highlightSoft">
          <AppText variant="bodyStrong">{text}</AppText>
        </Card>
      );
    default:
      return text ? <AppText>{text}</AppText> : null;
  }
}

/** Lesson reader. Reads SQLite only: it works with no connection at all. */
export default function LessonReader() {
  const app = useSignedIn();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [lesson, setLesson] = useState<SavedLesson | null | undefined>(undefined);
  const [context, setContext] = useState<LessonContext | null>(null);
  const [completed, setCompleted] = useState(false);
  const [marking, setMarking] = useState(false);
  const session = app?.session;
  const locale = app?.locale;

  useFocusEffect(
    useCallback(() => {
      if (!app || !session || !locale || !id) return;
      let live = true;
      (async () => {
        // SQLite only: this screen never waits for the network.
        const saved = await app.services.content.getLesson(id, locale);
        const progress = await session.account.lessonProgress(id);
        const cached = await app.services.content.getCatalog(locale);
        if (!live) return;
        setLesson(saved);
        setContext(findLessonContext(cached?.catalog ?? null, id));
        setCompleted(Boolean(progress?.completed));
        // Remember where this student was, for "Continue learning" (account-scoped preference).
        if (saved && session.isActive()) await session.account.setPreference(PREF_LAST_LESSON, id);
      })().catch(() => live && setLesson((current) => current ?? null));
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [session, locale, id]),
  );

  // Measurement builds only (see ui/perf.ts): runs after the lesson content has been committed.
  const shown = Boolean(lesson);
  useEffect(() => {
    if (shown) perfSinceTap('lesson_open_ms');
  }, [shown]);

  if (!app) return <Redirect href="/sign-in" />;
  const { t } = app;

  if (lesson === undefined) {
    return (
      <DetailScreen>
        <LoadingState label={t('loading')} />
      </DetailScreen>
    );
  }
  if (lesson === null) {
    return (
      <DetailScreen>
        <MessageState
          title={t('lessonNotSaved')}
          body={t('readerNotSaved')}
          actionLabel={t('lessonsTitle')}
          onAction={() => router.replace('/learn')}
        />
      </DetailScreen>
    );
  }

  const markDone = async () => {
    setMarking(true);
    try {
      await completeLesson(app.session.account, lesson, app.services.env); // saved locally first
      setCompleted(true);
      await app.refreshSummary();
      void app.syncNow();
    } finally {
      setMarking(false);
    }
  };

  const version = t('readerRevision', { revision: lesson.revision });
  return (
    <DetailScreen
      action={
        lesson.questions.length > 0 ? (
          <Button label={t('readerPractice')} icon="play" onPress={() => router.push(`/quiz/${lesson.lessonId}`)} />
        ) : undefined
      }
    >
      <LessonHeader
        subject={context ? `${context.subjectLabel} · ${context.gradeCode}` : undefined}
        title={lesson.title}
        meta={context ? `${context.unitTitle} · ${version}` : version}
        offline={t('availableOffline')}
      />
      {(lesson.blocks as Block[]).map((block, index) => (
        <BlockView key={typeof block.key === 'string' ? block.key : index} block={block} exampleLabel={t('workedExample')} />
      ))}
      <Button
        variant="secondary"
        icon={completed ? 'check' : undefined}
        disabled={completed}
        busy={marking}
        label={completed ? t('readerDone') : t('readerMarkDone')}
        onPress={() => void markDone()}
      />
    </DetailScreen>
  );
}
