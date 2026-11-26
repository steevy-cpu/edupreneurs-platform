import React, { useState } from 'react';
import { View } from 'react-native';

import { AppText, Button, Card, Icon, LessonHeader, SectionHeader, space, StepStrip, TopBar, useDesign } from '../../design';
import { copy, lesson } from '../../design/preview/fixtures';
import { PreviewScreenShell, usePreviewNav, usePreviewT } from '../../design/preview/shell';

/** Lesson Reader: objective → explanation → worked example → key ideas → practice. One guided flow, no tabs. */
function Content() {
  const { locale, colors } = useDesign();
  const t = usePreviewT();
  const c = copy(locale);
  const data = lesson(locale);
  const [hintOpen, setHintOpen] = useState(false);
  const paragraphs = data.blocks.filter((b) => b.type === 'paragraph') as {
    key: string;
    text: string;
  }[];

  return (
    <>
      <StepStrip steps={[t('stepUnderstand'), t('stepExample'), t('stepPractice'), t('stepReview')]} current={0} />
      <LessonHeader
        subject={`${c.subject} · 9AF`}
        title={data.title}
        meta={`${c.unit} · ${t('revision', { revision: data.revision })}`}
        offline={t('availableOffline')}
      />

      <Card tone="actionSoft">
        <AppText variant="caption" color="actionText">
          {t('objective')}
        </AppText>
        <AppText variant="bodyStrong">{c.objective}</AppText>
      </Card>

      <View style={{ gap: space.md }}>
        <SectionHeader title={t('explanation')} />
        {paragraphs.map((block) => (
          <AppText key={block.key}>{block.text}</AppText>
        ))}
      </View>

      <Card>
        <AppText variant="caption" color="actionText">
          {t('workedExample')}
        </AppText>
        <AppText variant="maths">{c.exampleTitle}</AppText>
        {c.exampleSteps.map((step, i) => (
          <View key={i} style={{ flexDirection: 'row', gap: space.sm }}>
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
                {i + 1}
              </AppText>
            </View>
            <AppText style={{ flex: 1 }}>{step}</AppText>
          </View>
        ))}
      </Card>

      <View style={{ gap: space.sm }}>
        <SectionHeader title={t('keyConcepts')} />
        {c.concepts.map((concept, i) => (
          <View
            key={i}
            style={{
              flexDirection: 'row',
              gap: space.sm,
              alignItems: 'flex-start',
            }}
          >
            <View style={{ marginTop: 3 }}>
              <Icon name="check" color={colors.actionText} size={18} />
            </View>
            <AppText style={{ flex: 1 }}>{concept}</AppText>
          </View>
        ))}
      </View>

      <Card tone="accentSoft">
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
          <Icon name="hint" color={colors.accentText} size={22} />
          <AppText variant="heading" style={{ flex: 1 }}>
            {t('judeTitle')}
          </AppText>
        </View>
        <AppText color="textSecondary">{t('judeBody')}</AppText>
        {hintOpen ? (
          <AppText variant="bodyStrong">{c.hint}</AppText>
        ) : (
          <Button label={t('judeAction')} variant="accent" onPress={() => setHintOpen(true)} />
        )}
        <AppText variant="caption" color="accentText">
          {t('judeOfflineNote')}
        </AppText>
      </Card>
    </>
  );
}

export default function LessonPreview() {
  const go = usePreviewNav();
  return (
    <PreviewScreenShell tab={null} top={({ online }) => <TopBar onBack={() => go('path')} trailing={online} />} action={<LessonAction />}>
      <Content />
    </PreviewScreenShell>
  );
}

function LessonAction() {
  const t = usePreviewT();
  const go = usePreviewNav();
  return <Button label={t('tryQuestion')} icon="play" onPress={() => go('quiz')} />;
}
