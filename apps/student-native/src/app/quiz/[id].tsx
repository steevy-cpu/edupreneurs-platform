import { Redirect, useLocalSearchParams, useRouter } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { SavedLesson } from '../../core/db/contentStore';
import { answerQuestion, choicesOf, correctChoiceOf, textOf } from '../../core/learning/actions';
import { Banner, Body, Button, Card, colors, Loading, Screen } from '../../ui/components';
import { useSignedIn } from '../../ui/useSession';

interface Feedback {
  isCorrect: boolean;
  correctChoiceId: string | null;
}

export default function Quiz() {
  const app = useSignedIn();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [lesson, setLesson] = useState<SavedLesson | null | undefined>(undefined);
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [correctCount, setCorrectCount] = useState(0);
  const [finished, setFinished] = useState(false);
  const session = app?.session;
  const locale = app?.locale;
  useEffect(() => {
    if (!app || !session || !locale || !id) return;
    let live = true;
    app.services.content
      .getLesson(id, locale) // SQLite only
      .then((saved) => live && setLesson(saved))
      .catch(() => live && setLesson(null));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, locale, id]);

  if (!app) return <Redirect href="/sign-in" />;
  const { t } = app;

  if (lesson === undefined) {
    return (
      <Screen>
        <Loading label={t('loading')} />
      </Screen>
    );
  }
  const questions = (lesson?.questions ?? []).filter((q) => q.kind === 'mcq');
  if (!lesson || questions.length === 0) {
    return (
      <Screen>
        <Body muted>{lesson ? t('quizNoQuestions') : t('readerNotSaved')}</Body>
        <Button label={t('back')} onPress={() => router.back()} />
      </Screen>
    );
  }

  if (finished) {
    return (
      <Screen>
        <Card>
          <Body style={{ fontWeight: '700' }}>{t('quizResult', { correct: correctCount, total: questions.length })}</Body>
          <Body muted>{t('quizProvisional')}</Body>
        </Card>
        <Button label={t('homeProgress')} onPress={() => router.replace('/progress')} />
        <Button
          variant="secondary"
          label={t('quizAgain')}
          onPress={() => {
            setIndex(0);
            setSelected(null);
            setFeedback(null);
            setCorrectCount(0);
            setFinished(false);
          }}
        />
      </Screen>
    );
  }

  const question = questions[index];
  const choices = choicesOf(question);

  /**
   * Order is the whole point of this screen:
   *   1. write the answer to SQLite (attempt + progress + pending operation, one transaction);
   *   2. only when that has resolved, show the feedback and "saved on this phone";
   *   3. then try to sync in the background — the UI does not wait for the network.
   */
  const validate = async () => {
    if (!selected || saving || feedback) return;
    setSaving(true);
    setSaveFailed(false);
    try {
      const receipt = await answerQuestion(app.session.account, lesson, question, selected, app.services.env);
      setFeedback({ isCorrect: receipt.isCorrect, correctChoiceId: correctChoiceOf(question) });
      if (receipt.isCorrect) setCorrectCount((count) => count + 1);
      await app.refreshSummary();
      void app.syncNow();
    } catch {
      setSaveFailed(true); // nothing was saved, so nothing is confirmed
    } finally {
      setSaving(false);
    }
  };

  const next = () => {
    if (index + 1 >= questions.length) {
      setFinished(true);
      return;
    }
    setIndex(index + 1);
    setSelected(null);
    setFeedback(null);
  };

  return (
    <Screen revealEndKey={feedback ? `${index}` : null}>
      <Body muted>{t('quizQuestionOf', { current: index + 1, total: questions.length })}</Body>
      <Text style={styles.prompt}>{textOf(question.prompt)}</Text>
      <View style={{ gap: 8 }} accessibilityRole="radiogroup">
        {choices.map((choice) => {
          const isSelected = selected === choice.id;
          const showCorrect = feedback !== null && feedback.correctChoiceId === choice.id;
          const showWrong = feedback !== null && isSelected && !feedback.isCorrect;
          return (
            <Pressable
              key={choice.id}
              accessibilityRole="radio"
              accessibilityState={{ selected: isSelected, disabled: feedback !== null }}
              disabled={feedback !== null || saving}
              onPress={() => setSelected(choice.id)}
              style={[
                styles.choice,
                isSelected && styles.choiceSelected,
                showCorrect && { borderColor: colors.good },
                showWrong && { borderColor: colors.bad },
              ]}
            >
              <Text style={styles.choiceText}>
                {showCorrect ? '✓ ' : showWrong ? '✗ ' : ''}
                {choice.text}
              </Text>
            </Pressable>
          );
        })}
      </View>
      {saveFailed ? <Banner tone="bad">{t('quizSaveFailed')}</Banner> : null}
      {feedback === null ? (
        <Button label={t('quizValidate')} disabled={!selected} busy={saving} onPress={() => void validate()} />
      ) : (
        <>
          <Banner tone={feedback.isCorrect ? 'good' : 'bad'}>
            {feedback.isCorrect ? t('quizCorrect') : t('quizIncorrect')}
          </Banner>
          <Body>{textOf(question.explanation)}</Body>
          <Body muted>{t('quizSavedLocal')}</Body>
          <Button label={index + 1 >= questions.length ? t('quizFinish') : t('quizNext')} onPress={next} />
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  prompt: { fontSize: 22, fontWeight: '600', color: colors.text, lineHeight: 30 },
  choice: {
    minHeight: 52,
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: colors.border,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    backgroundColor: colors.surface,
  },
  choiceSelected: { borderColor: colors.primary },
  choiceText: { fontSize: 18, color: colors.text },
});
