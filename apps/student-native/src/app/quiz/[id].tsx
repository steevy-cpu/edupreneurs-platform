import { Redirect, useLocalSearchParams, useRouter } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { View } from 'react-native';

import type { PracticeQuestion } from '../../core/api/types';
import { answerQuestion, choicesOf, correctChoiceOf, textOf } from '../../core/learning/actions';
import { getDownloaded, openLesson, ReadableLesson } from '../../core/learning/contentAccess';
import type { OpenResult } from '../../core/learning/contentAccess';
import {
  AnswerOption,
  AppText,
  Button,
  Card,
  FeedbackPanel,
  LoadingState,
  MessageState,
  Notice,
  OptionState,
  ProgressBar,
  space,
} from '../../design';
import { DetailScreen } from '../../ui/shell';
import { useSignedIn } from '../../ui/useSession';

interface Feedback {
  isCorrect: boolean;
  correctChoiceId: string | null;
}

interface Loaded {
  lesson: ReadableLesson;
  /** The questions of this run, fixed when the screen opens so the list never shifts while answering. */
  questions: PracticeQuestion[];
}

/**
 * Exercises: one question per screen.
 * `?only=missed` limits the run to questions whose last answer was wrong
 * (from the local records); with nothing missed it falls back to every question.
 */
export default function Quiz() {
  const app = useSignedIn();
  const router = useRouter();
  const { id, only, mode } = useLocalSearchParams<{ id: string; only?: string; mode?: string }>();
  const [loaded, setLoaded] = useState<Loaded | null | undefined>(undefined);
  const [failure, setFailure] = useState<Extract<OpenResult, { kind: 'unavailable' }>['reason'] | null>(null);
  const [attempt, setAttempt] = useState(0);
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
    (async () => {
      // Downloaded lesson: SQLite only. `?mode=online`: the copy the reader just fetched (memory), or a fresh fetch.
      let lesson: ReadableLesson | null;
      if (mode === 'online') {
        const result = await openLesson(
          { api: app.api, content: app.services.content, cache: app.services.lessonCache },
          id,
          locale,
          'online',
        );
        lesson = result.kind === 'ready' ? result.lesson : result.kind === 'unavailable' ? result.downloaded : null;
        if (result.kind === 'unavailable' && !result.downloaded && live) setFailure(result.reason);
        else if (live) setFailure(null);
      } else {
        lesson = await getDownloaded(app.services.content, id, locale);
      }
      if (!lesson) {
        if (live) setLoaded(null);
        return;
      }
      let questions = lesson.questions.filter((q) => q.kind === 'mcq');
      if (only === 'missed') {
        const progress = await session.account.questionProgress(id);
        const missed = questions.filter((q) => progress.get(q.id)?.lastIsCorrect === false);
        if (missed.length > 0) questions = missed;
      }
      if (live) setLoaded({ lesson, questions });
    })().catch(() => live && setLoaded(null));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, locale, id, only, mode, attempt]);

  if (!app) return <Redirect href="/sign-in" />;
  const { t } = app;

  if (loaded === undefined) {
    return (
      <DetailScreen title={t('quizTitle')}>
        <LoadingState label={t('loading')} />
      </DetailScreen>
    );
  }
  if (!loaded && failure) {
    const reasonText = {
      offline: t('readerFailOffline'),
      not_found: t('readerFailNotFound'),
      session: t('readerFailSession'),
      invalid: t('readerFailInvalid'),
    }[failure];
    return (
      <DetailScreen title={t('quizTitle')}>
        <MessageState
          tone="danger"
          title={t('readerOnlineTitle')}
          body={reasonText}
          actionLabel={failure === 'not_found' ? t('back') : t('readerRetry')}
          onAction={() => {
            if (failure === 'not_found') router.canGoBack() ? router.back() : router.replace('/learn');
            else {
              setLoaded(undefined);
              setAttempt((n) => n + 1);
            }
          }}
        />
      </DetailScreen>
    );
  }
  if (!loaded || loaded.questions.length === 0) {
    return (
      <DetailScreen title={t('quizTitle')}>
        <MessageState
          title={t('quizTitle')}
          body={loaded ? t('quizNoQuestions') : t('readerNotSaved')}
          actionLabel={t('back')}
          onAction={() => (router.canGoBack() ? router.back() : router.replace('/learn'))}
        />
      </DetailScreen>
    );
  }
  const { lesson, questions } = loaded;

  if (finished) {
    return (
      <DetailScreen
        title={t('quizTitle')}
        action={
          <>
            <Button label={t('homeProgress')} onPress={() => router.replace('/profile')} />
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
          </>
        }
      >
        <Card>
          <AppText variant="title" accessibilityRole="header">
            {t('quizResult', { correct: correctCount, total: questions.length })}
          </AppText>
          {/* The phone's verdict is provisional until the server has scored the answers. */}
          <AppText color="textSecondary">{t('quizProvisional')}</AppText>
        </Card>
      </DetailScreen>
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

  const position = t('quizQuestionOf', { current: index + 1, total: questions.length });
  const correctChoice = feedback ? choices.find((choice) => choice.id === feedback.correctChoiceId) : undefined;

  return (
    <DetailScreen
      title={t('quizTitle')}
      revealEndKey={feedback ? `${index}` : null}
      action={
        feedback === null ? (
          <Button label={t('quizValidate')} disabled={!selected} busy={saving} onPress={() => void validate()} />
        ) : (
          <Button label={index + 1 >= questions.length ? t('quizFinish') : t('quizNext')} onPress={next} />
        )
      }
    >
      <View style={{ gap: space.sm }}>
        <AppText variant="label" color="textSecondary">
          {position}
        </AppText>
        <ProgressBar value={(index + (feedback ? 1 : 0)) / questions.length} label={position} />
        {lesson.source === 'online' ? <Notice tone="info">{t('quizOnlineNote')}</Notice> : null}
      </View>
      <AppText variant="title" accessibilityRole="header">
        {textOf(question.prompt)}
      </AppText>
      <View style={{ gap: space.sm }} accessibilityRole="radiogroup">
        {choices.map((choice) => {
          const isSelected = selected === choice.id;
          let state: OptionState = isSelected ? 'selected' : 'idle';
          let resultLabel: string | undefined;
          if (feedback !== null) {
            if (feedback.correctChoiceId === choice.id) {
              state = 'correct';
              resultLabel = t('quizCorrect');
            } else if (isSelected) {
              state = 'incorrect';
              resultLabel = t('quizIncorrect');
            } else state = 'dimmed';
          }
          return (
            <AnswerOption
              key={choice.id}
              label={choice.text}
              state={state}
              resultLabel={resultLabel}
              onPress={saving ? undefined : () => setSelected(choice.id)}
            />
          );
        })}
      </View>
      {saveFailed ? <Notice tone="danger">{t('quizSaveFailed')}</Notice> : null}
      {feedback !== null ? (
        <FeedbackPanel
          correct={feedback.isCorrect}
          title={feedback.isCorrect ? t('quizCorrect') : t('quizIncorrect')}
          detail={!feedback.isCorrect && correctChoice ? t('correctAnswerIs', { answer: correctChoice.text }) : undefined}
          explanation={textOf(question.explanation)}
          savedLabel={t('quizSavedLocal')}
        />
      ) : null}
    </DetailScreen>
  );
}
