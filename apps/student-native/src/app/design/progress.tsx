import React from 'react';
import { StyleSheet, View } from 'react-native';

import {
  AppText,
  Button,
  Card,
  ListRow,
  MessageState,
  ProgressBar,
  SectionHeader,
  space,
  SyncDisplayState,
  SyncStatusCard,
  TopBar,
  useDesign,
  useLayout,
} from '../../design';
import { copy, PROGRESS, SYNC } from '../../design/preview/fixtures';
import { PreviewScreenShell, usePreviewNav, usePreviewParams, usePreviewT } from '../../design/preview/shell';

function Stat({ value, label }: { value: string; label: string }) {
  const { textScale } = useLayout();
  // Side by side at normal text sizes; one per row once the text is enlarged.
  return (
    <Card style={textScale > 1.2 ? styles.statWide : styles.stat}>
      <AppText variant="display" color="actionText">
        {value}
      </AppText>
      <AppText variant="caption" color="textSecondary">
        {label}
      </AppText>
    </Card>
  );
}

/** Progress: accomplishments first, review next, synchronisation last and quiet. */
function Content() {
  const { locale } = useDesign();
  const t = usePreviewT();
  const { state } = usePreviewParams();
  const go = usePreviewNav();
  const c = copy(locale);
  const syncState: SyncDisplayState = state === 'pending' || state === 'failed' || state === 'attention' ? state : 'synced';
  const summary = SYNC[syncState];

  if (state === 'empty') {
    return (
      <>
        <AppText variant="display" accessibilityRole="header">
          {t('progressTitle')}
        </AppText>
        <MessageState
          title={t('progressEmptyTitle')}
          body={t('progressEmptyBody')}
          actionLabel={t('homeEmptyAction')}
          onAction={() => go('path')}
        />
        <SyncStatusCard state="synced" pendingCount={0} lastConfirmed={null} />
      </>
    );
  }

  return (
    <>
      <View style={{ gap: space.xs }}>
        <AppText variant="display" accessibilityRole="header">
          {t('progressTitle')}
        </AppText>
        <AppText color="textSecondary">{t('progressSub')}</AppText>
      </View>

      <View style={styles.stats}>
        <Stat value={`${PROGRESS.lessonsDone}/${PROGRESS.lessonsTotal}`} label={t('lessonsCompleted')} />
        <Stat value={`${PROGRESS.correct}/${PROGRESS.answered}`} label={t('correctAnswers')} />
      </View>

      <Card>
        <AppText variant="heading">{t('weeklyGoal')}</AppText>
        <ProgressBar
          value={PROGRESS.weeklyDone / PROGRESS.weeklyTotal}
          tone="highlight"
          label={t('weeklyGoalValue', {
            done: PROGRESS.weeklyDone,
            total: PROGRESS.weeklyTotal,
          })}
        />
        <AppText color="textSecondary">
          {t('weeklyGoalValue', {
            done: PROGRESS.weeklyDone,
            total: PROGRESS.weeklyTotal,
          })}
        </AppText>
      </Card>

      <View style={{ gap: space.sm }}>
        <SectionHeader title={t('reviewNext')} />
        <ListRow
          icon="review"
          tone="accent"
          title={t('reviewMistakes')}
          subtitle={`${c.unit} · ${t('questionsToReview', { count: PROGRESS.toReview })}`}
          onPress={() => go('quiz')}
        />
        <Button label={t('startReview')} variant="secondary" onPress={() => go('quiz')} />
      </View>

      <SyncStatusCard
        state={syncState}
        pendingCount={syncState === 'attention' ? summary.needsAttention : summary.pending}
        lastConfirmed={summary.lastSyncAt ? c.lastConfirmed : null}
        onSync={syncState === 'synced' ? undefined : () => undefined}
        technicalDetail={syncState === 'failed' ? c.detail : undefined}
      />
    </>
  );
}

export default function ProgressPreview() {
  return (
    <PreviewScreenShell tab="profile" top={({ online }) => <TopBar trailing={online} />}>
      <Content />
    </PreviewScreenShell>
  );
}

const styles = StyleSheet.create({
  stats: { flexDirection: 'row', flexWrap: 'wrap', gap: space.md },
  stat: { flexGrow: 1, flexBasis: 130 },
  statWide: { flexBasis: '100%' },
});
