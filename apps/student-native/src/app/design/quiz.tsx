import React, { useEffect, useState } from 'react';
import { View } from 'react-native';

import { AnswerOption, AppText, Button, FeedbackPanel, OptionState, ProgressBar, space, TopBar, useDesign } from '../../design';
import { question as questionFixture } from '../../design/preview/fixtures';
import { PreviewScreenShell, usePreviewNav, usePreviewParams } from '../../design/preview/shell';

interface QuizState {
  selected: string | null;
  checked: boolean;
}

/** Initial state from the URL so every visual state can be captured: selected, correct, incorrect, long. */
function initial(state: string): QuizState {
  if (state === 'selected') return { selected: 'b', checked: false };
  if (state === 'correct' || state === 'long-correct') return { selected: 'b', checked: true };
  if (state === 'incorrect') return { selected: 'c', checked: true };
  return { selected: null, checked: false };
}

/**
 * Practice Quiz. Local component state only: this preview does not call the
 * app's answer-saving code and writes nothing. In Mobile-02 "Vérifier" will
 * await the existing answerQuestion() transaction BEFORE showing the feedback.
 */
function useQuiz() {
  const { state } = usePreviewParams();
  const [quiz, setQuiz] = useState<QuizState>(() => initial(state));
  // The same screen can be re-opened by link in another state; follow the URL.
  useEffect(() => setQuiz(initial(state)), [state]);
  return { quiz, setQuiz, long: state.startsWith('long') };
}

function Body({ quiz, setQuiz, long }: ReturnType<typeof useQuiz>) {
  const { t, locale } = useDesign();
  const q = questionFixture(locale, long);
  const choices = (q.response_spec as { choices: { id: string; text: string }[] }).choices;
  const correctId = (q.answer_key as { correct_choice_id: string }).correct_choice_id;
  const correctText = choices.find((choice) => choice.id === correctId)?.text ?? '';
  const isCorrect = quiz.selected === correctId;

  const stateOf = (id: string): OptionState => {
    if (!quiz.checked) return quiz.selected === id ? 'selected' : 'idle';
    if (id === correctId) return 'correct';
    if (id === quiz.selected) return 'incorrect';
    return 'dimmed';
  };

  return (
    <>
      <View style={{ gap: space.sm }}>
        <AppText variant="label" color="textSecondary">
          {t('questionOf', { current: 1, total: 5 })}
        </AppText>
        <ProgressBar value={0.2} label={t('questionOf', { current: 1, total: 5 })} />
      </View>
      <AppText variant={long ? 'heading' : 'title'} accessibilityRole="header">
        {(q.prompt as { text: string }).text}
      </AppText>
      <View accessibilityRole="radiogroup" style={{ gap: space.sm }}>
        {choices.map((choice) => (
          <AnswerOption
            key={choice.id}
            label={choice.text}
            state={stateOf(choice.id)}
            resultLabel={
              quiz.checked
                ? choice.id === correctId
                  ? t('correctTitle')
                  : choice.id === quiz.selected
                    ? t('yourAnswer')
                    : undefined
                : undefined
            }
            onPress={() => setQuiz({ selected: choice.id, checked: false })}
          />
        ))}
      </View>
      {quiz.checked ? (
        <FeedbackPanel
          correct={isCorrect}
          title={isCorrect ? t('correctTitle') : t('incorrectTitle')}
          detail={isCorrect ? undefined : t('correctAnswerIs', { answer: correctText })}
          explanation={(q.explanation as { text: string }).text + (isCorrect ? '' : ` ${t('incorrectEncourage')}`)}
          savedLabel={t('savedOnPhone')}
        />
      ) : null}
    </>
  );
}

function Action({ quiz, setQuiz }: ReturnType<typeof useQuiz>) {
  const { t } = useDesign();
  if (quiz.checked) return <Button label={t('nextQuestion')} onPress={() => setQuiz({ selected: null, checked: false })} />;
  return (
    <>
      {quiz.selected === null ? (
        <AppText variant="caption" color="textSecondary" align="center">
          {t('chooseAnswer')}
        </AppText>
      ) : null}
      <Button label={t('checkAnswer')} disabled={quiz.selected === null} onPress={() => setQuiz({ ...quiz, checked: true })} />
    </>
  );
}

export default function QuizPreview() {
  const go = usePreviewNav();
  const quiz = useQuiz();
  return (
    <PreviewScreenShell
      tab={null}
      top={({ online }) => <TopBar onBack={() => go('lesson')} trailing={online} />}
      action={<Action {...quiz} />}
      revealEndKey={quiz.quiz.checked ? 'feedback' : null}
    >
      <Body {...quiz} />
    </PreviewScreenShell>
  );
}
