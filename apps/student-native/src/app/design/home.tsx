import React from 'react';
import { View } from 'react-native';

import {
  AppText,
  Button,
  HeroCard,
  Icon,
  ListRow,
  LoadingState,
  MessageState,
  Pill,
  ProgressBar,
  SectionHeader,
  space,
  TopBar,
  useDesign,
} from '../../design';
import { copy, PROGRESS } from '../../design/preview/fixtures';
import { PreviewScreenShell, usePreviewNav, usePreviewParams, usePreviewT } from '../../design/preview/shell';

/** Student Home: one clear primary action — continue learning. */
function Content() {
  const { locale } = useDesign();
  const t = usePreviewT();
  const { state } = usePreviewParams();
  const go = usePreviewNav();
  const c = copy(locale);

  if (state === 'loading') return <LoadingState label={t('loading')} />;
  if (state === 'empty') {
    return (
      <MessageState title={t('homeEmptyTitle')} body={t('homeEmptyBody')} actionLabel={t('homeEmptyAction')} onAction={() => go('path')} />
    );
  }

  return (
    <>
      <View style={{ gap: space.xs }}>
        <AppText variant="display" accessibilityRole="header">
          {t('homeGreeting')}
        </AppText>
        <AppText color="textSecondary">{t('homeSub')}</AppText>
      </View>

      {state === 'error' ? <MessageState tone="danger" title={t('errorTitle')} body={t('errorBody')} actionLabel={t('retry')} /> : null}

      <HeroCard>
        <AppText variant="caption" color="textOnHeroSecondary">
          {c.subject} · 9AF · {t('lessonOf', { current: 2, total: 5 })}
        </AppText>
        <AppText variant="title" color="textOnHero">
          {c.lessonTitle}
        </AppText>
        <ProgressBar value={0.4} onHero label={`${t('lessonOf', { current: 2, total: 5 })}, ${t('percent', { value: 40 })}`} />
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.xs }}>
          <Icon name="check" color="#8FE3CF" size={16} />
          <AppText variant="caption" color="textOnHeroSecondary" style={{ flex: 1 }}>
            {t('availableOffline')}
          </AppText>
        </View>
        <Button label={t('continueLesson')} variant="onHero" icon="play" onPress={() => go('lesson')} />
      </HeroCard>

      {state === 'pending' ? (
        <ListRow
          icon="ring"
          tone="highlight"
          title={t('syncPending', { count: 5 })}
          subtitle={t('savedOnPhone')}
          onPress={() => go('progress', 'pending')}
        />
      ) : null}

      <View style={{ gap: space.sm }}>
        <SectionHeader title={t('tabReview')} />
        <ListRow
          icon="review"
          tone="accent"
          title={t('reviewMistakes')}
          subtitle={t('questionsToReview', { count: PROGRESS.toReview })}
          onPress={() => go('quiz')}
        />
      </View>

      <View style={{ gap: space.sm }}>
        <SectionHeader title={t('downloadedLessons')} />
        <ListRow icon="download" title={c.otherLessons[0]} subtitle={t('availableOffline')} onPress={() => go('lesson')} />
        <ListRow icon="download" title={c.otherLessons[1]} subtitle={t('availableOffline')} onPress={() => go('lesson')} />
      </View>
    </>
  );
}

export default function HomePreview() {
  return (
    <PreviewScreenShell tab="home" top={({ online }) => <TopBar trailing={online} />}>
      <Content />
    </PreviewScreenShell>
  );
}
