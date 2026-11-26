import { Redirect, useFocusEffect, useRouter } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import type { AttentionItem } from '../core/db/accountStore';
import { FLAGS } from '../core/experience/flags';
import { startTour, TOUR_STEPS } from '../core/experience/tour';
import { serviceUnreachable } from '../core/sync/engine';
import { LessonStanding, PREF_GRADE, PREF_SUBJECT, learningStandings, syncDisplayOf, totalsOf } from '../core/learning/overview';
import { AppText, Button, Card, Chip, ListRow, LoadingState, Notice, Pill, SectionHeader, space, SyncStatusCard, useLayout } from '../design';
import { RewardsCard } from '../ui/experience/Rewards';
import { useRemote } from '../ui/remote';
import { TabScreen, useSignOut } from '../ui/shell';
import { useSignedIn } from '../ui/useSession';

interface ProfileView {
  standings: LessonStanding[];
  attention: AttentionItem[];
  /** e.g. "Mathématiques · 9AF", or null when nothing is chosen or the catalog is unknown. */
  selection: string | null;
  /** The class chosen, even when no subject has been chosen yet. */
  grade: string | null;
  /** False when the catalog has no course for that class: then no "choose a subject" hint can be given. */
  gradeListed?: boolean;
}

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

/**
 * Profil: who is signed in, their progress, synchronisation, language and sign-out.
 * Progress comes first but the screen is not only a progress page.
 */
export default function Profile() {
  const app = useSignedIn();
  const router = useRouter();
  const remote = useRemote();
  const { leaving, confirmSignOut } = useSignOut();
  const [view, setView] = useState<ProfileView | null>(null);
  const session = app?.session;
  const locale = app?.locale;
  // Re-read after every sync run so confirmations and other devices' work appear.
  const syncedAt = app?.sync.summary.lastSyncAt;
  const pending = app?.sync.summary.pending;

  useFocusEffect(
    useCallback(() => {
      if (!app || !session || !locale) return;
      let live = true;
      (async () => {
        const { content } = app.services;
        const standings = await learningStandings(content, session.account, locale);
        const attention = await session.account.attentionItems();
        const grade = await session.account.getPreference(PREF_GRADE);
        const subject = await session.account.getPreference(PREF_SUBJECT);
        const cached = await content.getCatalog(locale);
        const course = cached?.catalog.courses.find((c) => c.grade.code === grade && c.subject.slug === subject);
        const gradeListed = cached?.catalog.courses.some((c) => c.grade.code === grade) ?? false;
        if (!live || !session.isActive()) return;
        setView({ standings, attention, grade, gradeListed, selection: course ? `${course.subject.label} · ${course.grade.code}` : null });
        await app.refreshSummary();
      })().catch(() => live && setView((current) => current ?? { standings: [], attention: [], selection: null, grade: null }));
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [session, locale, syncedAt, pending]),
  );

  if (!app) return <Redirect href="/sign-in" />;
  const { t, sync, needsReauth, syncNow, setLocale } = app;
  const { phase, summary, lastReport } = sync;
  const busy = phase !== 'idle';

  const display = syncDisplayOf(summary, busy ? null : (lastReport?.outcome ?? null));
  const notes: string[] = [];
  if (needsReauth) notes.push(t('syncAuthRequired'));
  else if (!busy && serviceUnreachable(sync)) notes.push(t('syncOffline'));
  const details: string[] = [];
  if (!busy && lastReport?.outcome === 'error') details.push(t('syncError', { code: lastReport.errorCode ?? '?' }));
  for (const item of view?.attention ?? []) details.push(t('attentionExplain', { code: item.problemCode }));
  const lastConfirmed = summary.lastSyncAt ? new Date(summary.lastSyncAt).toLocaleString(app.locale === 'ht' ? 'fr-HT' : 'fr-FR') : null;

  const totals = totalsOf(view?.standings ?? []);

  return (
    <TabScreen tab="profile">
      <AppText variant="display" accessibilityRole="header">
        {t('tabProfile')}
      </AppText>

      <Card>
        <View style={{ gap: space.xs }}>
          <AppText variant="label" color="textSecondary">{t('profileEmail')}</AppText>
          <AppText variant="bodyStrong">{app.session.email}</AppText>
        </View>
        <View style={{ gap: space.xs, marginTop: space.sm }}>
          <AppText variant="label" color="textSecondary">{t('selectTitle')}</AppText>
          <AppText variant="bodyStrong">{view?.selection ?? (view?.grade ? (view.gradeListed ? t('profileGradeOnly', { grade: view.grade }) : view.grade) : t('homeNoSelection'))}</AppText>
        </View>
        <Button variant="secondary" label={t('homeChoose')} onPress={() => router.replace('/learn')} />
      </Card>

      {needsReauth ? (
        <View style={{ gap: space.sm }}>
          <Notice>{t('sessionExpiredBanner')}</Notice>
          <Button variant="secondary" label={t('signInAgainTitle')} onPress={() => router.push('/sign-in')} />
        </View>
      ) : null}

      <View style={{ gap: space.sm }}>
        <SectionHeader title={t('profileProgress')} />
        {view === null ? <LoadingState label={t('loading')} /> : null}
        {view !== null && view.standings.length === 0 ? <AppText color="textSecondary">{t('progressNone')}</AppText> : null}
        {view !== null && view.standings.length > 0 ? (
          <>
            <View style={styles.stats}>
              <Stat value={`${totals.lessonsCompleted}/${totals.lessonsStudied}`} label={t('lessonsCompleted')} />
              <Stat value={`${totals.questionsCorrect}/${totals.questionsAnswered}`} label={t('correctAnswers')} />
            </View>
            {view.standings.map((lesson) => (
              <Card key={lesson.lessonId}>
                <AppText variant="bodyStrong">{lesson.title}</AppText>
                <AppText>
                  {lesson.questionCount === null
                    ? t('progressAnsweredOnline', { answered: lesson.answered })
                    : t('progressAnswered', { answered: lesson.answered, total: lesson.questionCount })}
                </AppText>
                <AppText>{t('progressCorrect', { correct: lesson.correct })}</AppText>
                <View style={styles.pills}>
                  {lesson.completed ? <Pill tone="success" icon="check" label={t('lessonCompleted')} /> : null}
                  {/* "Synchronisé" is shown only when no answer of this lesson is waiting for, or was refused by, the server. */}
                  {lesson.waiting > 0 ? (
                    <Pill tone="warning" icon="ring" label={`${t('stateWaiting')} (${lesson.waiting})`} />
                  ) : lesson.refused > 0 ? (
                    <Pill tone="danger" icon="cross" label={t('stateAttention')} />
                  ) : lesson.answered > 0 ? (
                    <Pill tone="neutral" label={t('stateSynced')} />
                  ) : null}
                </View>
              </Card>
            ))}
          </>
        ) : null}
      </View>

      {FLAGS.rewards ? (
        <RewardsCard
          t={t}
          locale={app.locale}
          account={app.session.account}
          remote={remote}
          pendingActions={summary.pending}
          syncedAt={summary.lastSyncAt}
          now={app.services.env.now}
          isActive={() => app.session.isActive()}
        />
      ) : null}

      <SyncStatusCard
        state={display}
        pendingCount={summary.pending}
        attentionCount={summary.needsAttention}
        lastConfirmed={lastConfirmed}
        notes={notes}
        technicalDetail={details.length > 0 ? details.join('\n') : undefined}
        busyLabel={phase === 'waiting_to_retry' ? t('syncRetrying') : busy ? t('syncRunning') : undefined}
        onSync={() => void syncNow()}
      />

      <View style={{ gap: space.sm }}>
        <SectionHeader title={t('homeLanguage')} />
        <ScrollView horizontal showsHorizontalScrollIndicator={false} accessibilityRole="radiogroup" contentContainerStyle={styles.chips}>
          <Chip label="Français" selected={app.locale === 'fr'} onPress={() => void setLocale('fr')} />
          <Chip label="Kreyòl" selected={app.locale === 'ht'} onPress={() => void setLocale('ht')} />
        </ScrollView>
      </View>

      {FLAGS.tour ? (
        <ListRow
          icon="hint"
          tone="accent"
          title={t('tourReplay')}
          subtitle={t('tourReplayHint', { count: TOUR_STEPS.length })}
          onPress={() => {
            void startTour(app.session.account, app.services.env.now(), { replay: true })
              .catch(() => undefined)
              .then(() => router.push('/tour'));
          }}
        />
      ) : null}

      {FLAGS.leaderboardReview ? (
        <ListRow
          icon="review"
          tone="highlight"
          title={t('lbProfileEntry')}
          subtitle={t('lbProfileEntryHint')}
          onPress={() => router.push('/leaderboard')}
        />
      ) : null}

      <View style={{ gap: space.sm }}>
        <SectionHeader title={t('profileAccount')} />
        <Button label={t('homeSignOut')} variant="secondary" busy={leaving} onPress={() => void confirmSignOut()} />
        {summary.pending > 0 ? <AppText color="textSecondary">{t('stateWaiting')}</AppText> : null}
      </View>
    </TabScreen>
  );
}

const styles = StyleSheet.create({
  stats: { flexDirection: 'row', flexWrap: 'wrap', gap: space.md },
  stat: { flexGrow: 1, flexBasis: 130 },
  statWide: { flexBasis: '100%' },
  pills: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  chips: { flexDirection: 'row', gap: space.sm, paddingRight: space.lg },
});
