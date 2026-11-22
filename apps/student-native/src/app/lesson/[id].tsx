import { Redirect, Stack, useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { SavedLesson } from '../../core/db/contentStore';
import { completeLesson } from '../../core/learning/actions';
import { Banner, Body, Button, colors, Loading, Screen, Title } from '../../ui/components';
import { useSignedIn } from '../../ui/useSession';

type Block = Record<string, unknown>;

function BlockView({ block }: { block: Block }) {
  const text = typeof block.text === 'string' ? block.text : '';
  switch (block.type) {
    case 'heading':
      return (
        <Text style={styles.heading} accessibilityRole="header">
          {text}
        </Text>
      );
    case 'paragraph':
      return <Body>{text}</Body>;
    case 'example': {
      const steps = Array.isArray(block.steps) ? (block.steps as unknown[]) : [];
      return (
        <View style={styles.example}>
          {typeof block.title === 'string' ? <Body style={{ fontWeight: '700' }}>{block.title}</Body> : null}
          {steps.map((step, index) => (
            <Body key={index}>{String(step)}</Body>
          ))}
        </View>
      );
    }
    case 'callout':
      return (
        <View style={styles.callout}>
          <Body>{text}</Body>
        </View>
      );
    default:
      // A block type this app version does not know: show its text rather than nothing.
      return text ? <Body>{text}</Body> : null;
  }
}

export default function LessonReader() {
  const app = useSignedIn();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [lesson, setLesson] = useState<SavedLesson | null | undefined>(undefined);
  const [completed, setCompleted] = useState(false);
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
        if (!live) return;
        setLesson(saved);
        setCompleted(Boolean(progress?.completed));
      })().catch(() => live && setLesson(null));
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [session, locale, id]),
  );

  if (!app) return <Redirect href="/sign-in" />;
  const { t } = app;

  if (lesson === undefined) {
    return (
      <Screen>
        <Loading label={t('loading')} />
      </Screen>
    );
  }
  if (lesson === null) {
    return (
      <Screen>
        <Banner>{t('readerNotSaved')}</Banner>
        <Button label={t('lessonsTitle')} onPress={() => router.replace('/lessons')} />
      </Screen>
    );
  }

  const markDone = async () => {
    await completeLesson(app.session.account, lesson, app.services.env); // saved locally first
    setCompleted(true);
    await app.refreshSummary();
    void app.syncNow();
  };

  return (
    <Screen>
      <Stack.Screen options={{ title: lesson.title }} />
      <Title>{lesson.title}</Title>
      <Body muted>{t('readerRevision', { revision: lesson.revision })}</Body>
      {(lesson.blocks as Block[]).map((block, index) => (
        <BlockView key={typeof block.key === 'string' ? block.key : index} block={block} />
      ))}
      {lesson.questions.length > 0 ? (
        <Button label={t('readerPractice')} onPress={() => router.push(`/quiz/${lesson.lessonId}`)} />
      ) : null}
      <Button
        variant="secondary"
        disabled={completed}
        label={completed ? t('readerDone') : t('readerMarkDone')}
        onPress={() => void markDone()}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  heading: { fontSize: 20, fontWeight: '700', color: colors.text, marginTop: 8 },
  example: {
    backgroundColor: colors.surface,
    borderLeftWidth: 4,
    borderLeftColor: colors.primary,
    padding: 12,
    gap: 4,
  },
  callout: { backgroundColor: colors.warnSurface, borderRadius: 10, padding: 12 },
});
