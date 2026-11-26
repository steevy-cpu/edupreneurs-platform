import { Redirect, useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import React, { useCallback, useEffect, useState } from 'react';
import { View } from 'react-native';

import { completeLesson } from '../../core/learning/actions';
import { downloadForOffline, getDownloaded, LessonFreshness, lessonFreshness, openLesson, OpenResult, ReadableLesson } from '../../core/learning/contentAccess';
import { findLessonContext, LessonContext, PREF_LAST_LESSON, shortDate } from '../../core/learning/overview';
import { AppText, Button, Card, LessonHeader, LoadingState, MessageState, Notice, SectionHeader, space, useDesign } from '../../design';
import { perfSinceTap } from '../../ui/perf';
import { DetailScreen } from '../../ui/shell';
import { useSignedIn } from '../../ui/useSession';

type Block = Record<string, unknown>;

/**
 * Draws one content block. Only the block types the lesson schema has today
 * are styled; an unknown type falls back to its text rather than disappearing.
 */
function BlockView({ block, exampleLabel }: { block: Block; exampleLabel: string }) {
  const { colors } = useDesign();
  const text = typeof block.text === 'string' ? block.text : '';
  switch (block.type) {
    case 'heading':
      return <SectionHeader title={text} />;
    case 'paragraph':
      return <AppText>{text}</AppText>;
    case 'example': {
      const steps = Array.isArray(block.steps) ? (block.steps as unknown[]) : [];
      return (
        <Card>
          <AppText variant="caption" color="actionText">
            {exampleLabel}
          </AppText>
          {typeof block.title === 'string' ? <AppText variant="maths">{block.title}</AppText> : null}
          {steps.map((step, index) => (
            <View key={index} style={{ flexDirection: 'row', gap: space.sm }}>
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
                  {index + 1}
                </AppText>
              </View>
              <AppText style={{ flex: 1 }}>{String(step)}</AppText>
            </View>
          ))}
        </Card>
      );
    }
    case 'callout':
      return (
        <Card tone="highlightSoft">
          <AppText variant="bodyStrong">{text}</AppText>
        </Card>
      );
    default:
      return text ? <AppText>{text}</AppText> : null;
  }
}

/**
 * Lesson reader. One screen for both modes:
 *   no `mode`        — the downloaded copy, from SQLite only: works with no connection at all
 *   `?mode=online`   — the lesson is read through the API and kept in memory; nothing is downloaded
 *                      unless the student presses "Télécharger"
 * The student's own work (answers, completion) is written to the account database either way.
 */
export default function LessonReader() {
  const app = useSignedIn();
  const router = useRouter();
  const { id, mode } = useLocalSearchParams<{ id: string; mode?: string }>();
  const online = mode === 'online';
  const [lesson, setLesson] = useState<ReadableLesson | null | undefined>(undefined);
  const [failure, setFailure] = useState<Extract<OpenResult, { kind: 'unavailable' }> | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [freshness, setFreshness] = useState<LessonFreshness | null>(null);
  const [downloadState, setDownloadState] = useState<'idle' | 'busy' | 'done' | 'failed'>('idle');
  const [context, setContext] = useState<LessonContext | null>(null);
  const [completed, setCompleted] = useState(false);
  const [marking, setMarking] = useState(false);
  const session = app?.session;
  const locale = app?.locale;

  useFocusEffect(
    useCallback(() => {
      if (!app || !session || !locale || !id) return;
      let live = true;
      (async () => {
        let saved: ReadableLesson | null;
        let unavailable: Extract<OpenResult, { kind: 'unavailable' }> | null = null;
        if (online) {
          // Explicit online reading: the network is used here, and only because the student asked.
          const result = await openLesson(
            { api: app.api, content: app.services.content, cache: app.services.lessonCache },
            id,
            locale,
            'online',
          );
          saved = result.kind === 'ready' ? result.lesson : null;
          unavailable = result.kind === 'unavailable' ? result : null;
        } else {
          // SQLite only: the downloaded reader never waits for the network.
          saved = await getDownloaded(app.services.content, id, locale);
        }
        const progress = await session.account.lessonProgress(id);
        const cached = await app.services.content.getCatalog(locale);
        if (!live) return;
        let fresh: LessonFreshness | null = null;
        if (saved?.source === 'downloaded') {
          const info = await app.services.content.getLessonInfo(id, locale);
          if (info) fresh = lessonFreshness(info, cached);
        }
        setLesson(saved);
        setFreshness(fresh);
        setFailure(unavailable);
        setDownloadState('idle');
        setContext(findLessonContext(cached?.catalog ?? null, id));
        setCompleted(Boolean(progress?.completed));
        // Remember where this student was, for "Continue learning" (account-scoped preference).
        // Any lesson the student actually opened, downloaded or online: Home offers it with the right label.
        if (saved && session.isActive()) {
          await session.account.setPreference(PREF_LAST_LESSON, id);
          await session.account.touchLessonRef({
            lessonId: saved.lessonId,
            locale: saved.locale,
            title: saved.title,
            revisionId: saved.revisionId,
            revision: saved.revision,
            at: app.services.env.now().toISOString(),
          });
        }
      })().catch(() => live && setLesson((current) => current ?? null));
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [session, locale, id, online, attempt]),
  );

  // Measurement builds only (see ui/perf.ts): runs after the lesson content has been committed.
  const shown = Boolean(lesson);
  useEffect(() => {
    if (shown) perfSinceTap('lesson_open_ms');
  }, [shown]);

  if (!app) return <Redirect href="/sign-in" />;
  const { t } = app;

  if (lesson === undefined) {
    return (
      <DetailScreen>
        <LoadingState label={t('loading')} />
      </DetailScreen>
    );
  }
  if (lesson === null && failure) {
    const reasonText = {
      offline: t('readerFailOffline'),
      service: t('readerFailService'),
      not_found: t('readerFailNotFound'),
      session: t('readerFailSession'),
      invalid: t('readerFailInvalid'),
    }[failure.reason];
    return (
      <DetailScreen
        action={
          failure.downloaded ? (
            <Button
              variant="secondary"
              label={t('readerUseSaved')}
              onPress={() => router.replace(`/lesson/${failure.downloaded?.lessonId}`)}
            />
          ) : undefined
        }
      >
        <MessageState
          tone="danger"
          title={t('readerOnlineTitle')}
          body={reasonText}
          actionLabel={failure.reason === 'not_found' ? t('lessonsTitle') : t('readerRetry')}
          onAction={() => {
            if (failure.reason === 'not_found') router.replace('/learn');
            else {
              setLesson(undefined);
              setAttempt((n) => n + 1);
            }
          }}
        />
      </DetailScreen>
    );
  }
  if (lesson === null) {
    return (
      <DetailScreen>
        <MessageState
          title={t('lessonNotSaved')}
          body={t('readerNotSaved')}
          actionLabel={t('lessonsTitle')}
          onAction={() => router.replace('/learn')}
        />
      </DetailScreen>
    );
  }

  const markDone = async () => {
    setMarking(true);
    try {
      await completeLesson(app.session.account, lesson, app.services.env); // saved locally first
      setCompleted(true);
      await app.refreshSummary();
      void app.syncNow();
    } finally {
      setMarking(false);
    }
  };

  const version = t('readerRevision', { revision: lesson.revision });
  const isOnlineOnly = lesson.source === 'online' && downloadState !== 'done';

  const download = async () => {
    if (!app.api || downloadState === 'busy') return;
    setDownloadState('busy');
    try {
      const result = await downloadForOffline(app.api, app.services.content, lesson.lessonId, lesson.locale, app.services.env);
      if (result.outcome === 'superseded') {
        setDownloadState('idle');
        return;
      }
      setDownloadState('done'); // set only after the local transaction committed
      if (lesson.source === 'downloaded') setAttempt((n) => n + 1); // an update: reload the new revision
    } catch {
      setDownloadState('failed'); // nothing was saved; the lesson on screen is unchanged
    }
  };
  return (
    <DetailScreen
      action={
        lesson.questions.length > 0 ? (
          <Button
            label={t('readerPractice')}
            icon="play"
            onPress={() => router.push(`/quiz/${lesson.lessonId}${isOnlineOnly ? '?mode=online' : ''}`)}
          />
        ) : undefined
      }
    >
      <LessonHeader
        subject={context ? `${context.subjectLabel} · ${context.gradeCode}` : undefined}
        title={lesson.title}
        meta={context ? `${context.unitTitle} · ${version}` : version}
        offline={isOnlineOnly ? undefined : t('availableOffline')}
        online={isOnlineOnly ? t('readerOnlineBadge') : undefined}
      />
      {lesson.source === 'downloaded' && freshness ? (
        <View style={{ gap: space.sm }}>
          {freshness.state === 'not_listed' ? (
            <Notice tone="info">{t('readerNotListedNotice', { date: shortDate(freshness.verifiedAt) })}</Notice>
          ) : freshness.state === 'withdrawn_confirmed' ? (
            <Notice tone="info">{t('readerGoneNotice')}</Notice>
          ) : freshness.state === 'update_available' ? (
            <>
              <Notice tone="info">{t('lessonUpdateAvailable')}</Notice>
              {app.api ? (
                <Button
                  variant="secondary"
                  icon="download"
                  busy={downloadState === 'busy'}
                  label={downloadState === 'busy' ? t('readerDownloading') : t('lessonUpdate')}
                  onPress={() => void download()}
                />
              ) : null}
              {downloadState === 'failed' ? <Notice tone="danger">{t('lessonSaveFailed')}</Notice> : null}
            </>
          ) : null}
          <AppText variant="caption" color="textSecondary">
            {freshness.state === 'unverified' || freshness.verifiedAt === null
              ? t('readerUnverified')
              : t('readerVerifiedOn', { date: shortDate(freshness.verifiedAt) })}
          </AppText>
        </View>
      ) : null}
      {(lesson.blocks as Block[]).map((block, index) => (
        <BlockView key={typeof block.key === 'string' ? block.key : index} block={block} exampleLabel={t('workedExample')} />
      ))}
      {isOnlineOnly ? (
        <View style={{ gap: space.sm }}>
          <Button
            variant="secondary"
            icon="download"
            busy={downloadState === 'busy'}
            label={downloadState === 'busy' ? t('readerDownloading') : t('readerDownload')}
            testID="download-this-lesson"
            onPress={() => void download()}
          />
          {downloadState === 'failed' ? <Notice tone="danger">{t('lessonSaveFailedFirst')}</Notice> : null}
        </View>
      ) : null}
      <Button
        variant="secondary"
        icon={completed ? 'check' : undefined}
        disabled={completed}
        busy={marking}
        label={completed ? t('readerDone') : t('readerMarkDone')}
        onPress={() => void markDone()}
      />
    </DetailScreen>
  );
}
