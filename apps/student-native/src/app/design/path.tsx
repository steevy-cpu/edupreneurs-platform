import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { AppText, Card, PathNode, ProgressBar, radius, space, TopBar, touch, useDesign } from '../../design';
import { copy, GRADES, pathSteps, subjects } from '../../design/preview/fixtures';
import { PreviewScreenShell, usePreviewNav, usePreviewParams } from '../../design/preview/shell';

function Chip({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  const { colors } = useDesign();
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={label}
      onPress={onPress}
      style={[
        styles.chip,
        {
          backgroundColor: selected ? colors.hero : colors.surface,
          borderColor: selected ? colors.hero : colors.borderControl,
        },
      ]}
    >
      <AppText variant="label" style={{ color: selected ? colors.textOnHero : colors.text }}>
        {label}
      </AppText>
    </Pressable>
  );
}

/** Learning Path: choose grade and subject, then follow (or freely revisit) the steps. */
function Content() {
  const { t, locale } = useDesign();
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
  chip: {
    minHeight: touch.min,
    minWidth: touch.min,
    paddingHorizontal: space.lg,
    borderRadius: radius.pill,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
