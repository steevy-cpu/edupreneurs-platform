import React, { useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { AppText, Card, Chip, PathNode, ProgressBar, space, TopBar, useDesign } from '../../design';
import { copy, GRADES, pathSteps, subjects } from '../../design/preview/fixtures';
import { PreviewScreenShell, usePreviewNav, usePreviewParams, usePreviewT } from '../../design/preview/shell';

/** Learning Path: choose grade and subject, then follow (or freely revisit) the steps. */
function Content() {
  const { locale } = useDesign();
  const t = usePreviewT();
  const { state } = usePreviewParams();
  const go = usePreviewNav();
  const c = copy(locale);
  const subjectList = subjects(locale);
  const [grade, setGrade] = useState('9AF');
  const [subject, setSubject] = useState(subjectList[0]);
  const steps = pathSteps(locale, state === 'offline');
  const kindLabel = {
    understand: t('stepUnderstand'),
    example: t('stepExample'),
    practice: t('stepPractice'),
    review: t('stepReview'),
  };
  const done = steps.filter((s) => s.state === 'completed').length;

  return (
    <>
      <AppText variant="display" accessibilityRole="header">
        {t('pathTitle')}
      </AppText>

      <View style={{ gap: space.sm }}>
        <AppText variant="label" color="textSecondary">
          {t('grade')}
        </AppText>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} accessibilityRole="radiogroup" contentContainerStyle={styles.chips}>
          {GRADES.map((g) => (
            <Chip key={g} label={g} selected={g === grade} onPress={() => setGrade(g)} />
          ))}
        </ScrollView>
        <AppText variant="label" color="textSecondary">
          {t('subject')}
        </AppText>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} accessibilityRole="radiogroup" contentContainerStyle={styles.chips}>
          {subjectList.map((s) => (
            <Chip key={s} label={s} selected={s === subject} onPress={() => setSubject(s)} />
          ))}
        </ScrollView>
      </View>

      <Card tone="actionSoft">
        <AppText variant="caption" color="actionText">
          {t('unitLabel', { number: 1 })}
        </AppText>
        <AppText variant="heading">{c.unit}</AppText>
        <ProgressBar value={done / steps.length} label={`${done}/${steps.length}`} />
        <AppText variant="caption" color="textSecondary">
          {done}/{steps.length} · {t('stateDone')}
        </AppText>
      </Card>

      <View>
        {steps.map((step, i) => (
          <PathNode
            key={i}
            index={i}
            kind={kindLabel[step.kind]}
            title={step.title}
            state={step.state}
            first={i === 0}
            last={i === steps.length - 1}
            onPress={() => go(step.kind === 'practice' || step.kind === 'review' ? 'quiz' : 'lesson')}
          />
        ))}
      </View>
    </>
  );
}

export default function PathPreview() {
  return (
    <PreviewScreenShell tab="learn" top={({ online }) => <TopBar trailing={online} />}>
      <Content />
    </PreviewScreenShell>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', gap: space.sm, paddingRight: space.lg },
});
