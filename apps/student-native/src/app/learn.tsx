import { Redirect, useFocusEffect, useRouter } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { refreshCatalog } from '../core/learning/actions';
import { downloadForOffline } from '../core/learning/contentAccess';
import { loadPath, PathLesson, PathView, PREF_GRADE, PREF_SUBJECT, shortDate } from '../core/learning/overview';
import {
  AppText,
  Button,
  Card,
  Chip,
  ListRow,
  LoadingState,
  MessageState,
  Notice,
  PathNode,
  ProgressBar,
  SectionHeader,
  space,
} from '../design';
import { TabScreen } from '../ui/shell';
import { useSignedIn } from '../ui/useSession';

/**
 * Apprendre: choose a grade and subject, then follow the path lesson by lesson.
 * The path is drawn from SQLite first; the network is only used to refresh the
 * catalog and to download a lesson the student asks for.
 */
export default function Learn() {
  const app = useSignedIn();
  const router = useRouter();
  const [view, setView] = useState<PathView | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [failed, setFailed] = useState<{ lessonId: string; hadCopy: boolean } | null>(null);
  const session = app?.session;
  const locale = app?.locale;
  const syncedAt = app?.sync.summary.lastSyncAt;

  /** Build the screen from SQLite only. Never waits for the network. */
  const loadLocal = useCallback(async () => {
    if (!app || !session || !locale) return;
    const grade = await session.account.getPreference(PREF_GRADE);
    const subject = await session.account.getPreference(PREF_SUBJECT);
    const next = await loadPath(app.services.content, session.account, locale, { grade, subject });
    if (session.isActive()) setView(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, locale]);

  useFocusEffect(
    useCallback(() => {
      if (!app || !session || !locale) return;
      let live = true;
      (async () => {
        await loadLocal();
        if (!app.api) return;
        try {
          await refreshCatalog(app.api, app.services.content, locale, app.services.env);
          if (live) {
            setFromCache(false);
            await loadLocal();
          }
        } catch {
          if (live) setFromCache(true); // offline or session ended: keep showing the cached list
        }
      })().catch(() => undefined);
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [session, locale, syncedAt]),
  );

  if (!app) return <Redirect href="/sign-in" />;
  const { t } = app;

  if (!view) {
    return (
      <TabScreen tab="learn">
        <LoadingState label={t('loading')} />
      </TabScreen>
    );
  }

  const choose = async (grade: string, subject: string) => {
    await app.session.account.setPreference(PREF_GRADE, grade);
    await app.session.account.setPreference(PREF_SUBJECT, subject);
    await loadLocal();
  };

  const save = async (lesson: PathLesson) => {
    if (!app.api) return;
    setSaving(lesson.lessonId);
    setFailed(null);
    try {
      await downloadForOffline(app.api, app.services.content, lesson.lessonId, app.locale, app.services.env);
    } catch {
      // The previously saved copy (if any) was not touched.
      setFailed({ lessonId: lesson.lessonId, hadCopy: lesson.saved !== null });
    } finally {
      setSaving(null);
      await loadLocal();
    }
  };

  const title = (
    <AppText variant="display" accessibilityRole="header">
      {t('pathTitle')}
    </AppText>
  );

  const otherSaved =
    view.otherSaved.length > 0 ? (
      <View style={{ gap: space.sm }}>
        <SectionHeader title={view.units.length > 0 ? t('pathOtherSaved') : t('downloadedLessons')} />
        {view.otherSaved.map((lesson) => (
          <ListRow
            key={lesson.lessonId}
            icon="download"
            title={lesson.title}
            subtitle={t('availableOffline')}
            onPress={() => router.push(`/lesson/${lesson.lessonId}`)}
          />
        ))}
      </View>
    ) : null;

  if (view.grades.length === 0) {
    return (
      <TabScreen tab="learn">
        {title}
        <MessageState title={t('selectTitle')} body={t('selectEmpty')} />
        {otherSaved}
      </TabScreen>
    );
  }

  return (
    <TabScreen tab="learn">
      {title}
      {fromCache ? (
        <Notice tone="info" role="text">
          {t('catalogStale')}
        </Notice>
      ) : null}

      <View style={{ gap: space.sm }}>
        <AppText variant="label" color="textSecondary">
          {t('selectGrade')}
        </AppText>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} accessibilityRole="radiogroup" contentContainerStyle={styles.chips}>
          {view.grades.map((grade) => (
            <Chip key={grade.code} label={grade.code} selected={grade.code === view.grade} onPress={() => void choose(grade.code, '')} />
          ))}
        </ScrollView>
        {view.grade ? (
          <>
            <AppText variant="label" color="textSecondary">
              {t('selectSubject')}
            </AppText>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              accessibilityRole="radiogroup"
              contentContainerStyle={styles.chips}
            >
              {view.subjects.map((subject) => (
                <Chip
                  key={subject.slug}
                  label={subject.label}
                  selected={subject.slug === view.subject}
                  onPress={() => void choose(view.grade as string, subject.slug)}
                />
              ))}
            </ScrollView>
          </>
        ) : null}
        {!view.grade && view.gradeWithoutCourses ? (
          <AppText color="textSecondary">{t('selectGradeNoCourses', { grade: view.gradeWithoutCourses })}</AppText>
        ) : !view.grade ? (
          <AppText color="textSecondary">{t('homeNoSelection')}</AppText>
        ) : !view.subject ? (
          <AppText color="textSecondary">{t('selectSubjectHint')}</AppText>
        ) : null}
      </View>

      {view.grade && view.subject && view.units.every((unit) => unit.lessons.length === 0) ? (
        <AppText color="textSecondary">{t('lessonsEmpty')}</AppText>
      ) : null}

      {view.units.map((unit) => {
        const progress = t('unitProgress', { done: unit.completedCount, total: unit.lessons.length });
        return (
          <View key={unit.id} style={{ gap: space.md }}>
            <Card tone="actionSoft">
              <AppText variant="caption" color="actionText">
                {t('unitLabel', { number: unit.number })}
              </AppText>
              <AppText variant="heading" accessibilityRole="header">
                {unit.title}
              </AppText>
              {unit.lessons.length > 0 ? (
                <>
                  <ProgressBar value={unit.completedCount / unit.lessons.length} label={progress} />
                  <AppText variant="caption" color="textSecondary">
                    {progress}
                  </AppText>
                </>
              ) : null}
            </Card>
            <View>
              {unit.lessons.map((lesson, index) => {
                const busy = saving === lesson.lessonId;
                const needsDownload = lesson.saved === null || lesson.updateAvailable;
                const readOnlineNow = () => router.push(`/lesson/${lesson.lessonId}?mode=online`);
                return (
                  <View key={lesson.lessonId}>
                    <PathNode
                      index={index}
                      kind={t('lessonNumber', { number: lesson.number })}
                      title={lesson.title}
                      state={lesson.state === 'unavailable' ? 'available' : lesson.state}
                      first={index === 0}
                      last={index === unit.lessons.length - 1}
                      detail={
                        lesson.saved === null
                          ? t('lessonOnlineOnly')
                          : lesson.freshness?.state === 'withdrawn_confirmed'
                            ? t('lessonGone')
                            : lesson.freshness?.state === 'not_listed'
                              ? t('lessonNotListed', { date: shortDate(lesson.freshness.verifiedAt) })
                              : lesson.updateAvailable
                                ? `${t('lessonSaved')} · ${t('lessonUpdateAvailable')}`
                                : t('lessonSaved')
                      }
                      onPress={lesson.saved ? () => router.push(`/lesson/${lesson.lessonId}`) : readOnlineNow}
                      action={
                        needsDownload ? (
                          <View style={{ gap: space.sm }}>
                            {lesson.saved === null ? (
                              <Button
                                icon="play"
                                label={t('readNow')}
                                accessibilityHint={lesson.title}
                                testID={`read-${lesson.number}`}
                                onPress={readOnlineNow}
                              />
                            ) : null}
                            <Button
                              variant="secondary"
                              icon="download"
                              busy={busy}
                              disabled={saving !== null && !busy}
                              label={busy ? t('lessonSaving') : lesson.saved ? t('lessonUpdate') : t('download')}
                              accessibilityHint={lesson.title}
                              testID={`download-${lesson.number}`}
                              onPress={() => void save(lesson)}
                            />
                          </View>
                        ) : undefined
                      }
                    />
                    {failed?.lessonId === lesson.lessonId ? (
                      <Notice tone="danger">{t(failed.hadCopy ? 'lessonSaveFailed' : 'lessonSaveFailedFirst')}</Notice>
                    ) : null}
                  </View>
                );
              })}
            </View>
          </View>
        );
      })}

      {otherSaved}
    </TabScreen>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', gap: space.sm, paddingRight: space.lg },
});
