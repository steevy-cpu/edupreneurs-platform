import { Redirect, useFocusEffect, useRouter } from 'expo-router';
import React, { useCallback, useState } from 'react';

import type { CatalogLesson } from '../core/api/types';
import type { SavedLessonInfo } from '../core/db/contentStore';
import { refreshCatalog, saveLessonOffline } from '../core/learning/actions';
import { Banner, Body, Button, Card, Loading, Screen } from '../ui/components';
import { useSignedIn } from '../ui/useSession';

interface Row {
  lessonId: string;
  title: string;
  /** Revision currently published, when the catalog is known. */
  publishedRevisionId: string | null;
  saved: SavedLessonInfo | null;
  completed: boolean;
}

export default function Lessons() {
  const app = useSignedIn();
  const router = useRouter();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [failed, setFailed] = useState<{ lessonId: string; hadCopy: boolean } | null>(null);
  const session = app?.session;
  const locale = app?.locale;

  /** Build the list from SQLite only. Never waits for the network. */
  const loadLocal = useCallback(async () => {
    if (!app || !session || !locale) return;
    const { content } = app.services;
    const grade = await session.account.getPreference('grade_code');
    const subject = await session.account.getPreference('subject_slug');
    const cached = await content.getCatalog(locale);
    const course = cached?.catalog.courses.find(
      (c) => c.grade.code === grade && c.subject.slug === subject,
    );
    const published: CatalogLesson[] = course ? course.units.flatMap((unit) => unit.lessons) : [];
    const savedList = await content.listSavedLessons(locale);
    const savedById = new Map(savedList.map((lesson) => [lesson.lessonId, lesson]));

    const next: Row[] = [];
    for (const lesson of published) {
      next.push({
        lessonId: lesson.id,
        title: lesson.title,
        publishedRevisionId: lesson.revision_id,
        saved: savedById.get(lesson.id) ?? null,
        completed: false,
      });
      savedById.delete(lesson.id);
    }
    // Saved lessons stay reachable even if the catalog is missing or no longer lists them.
    if (!course) {
      for (const lesson of savedById.values()) {
        next.push({
          lessonId: lesson.lessonId,
          title: lesson.title,
          publishedRevisionId: null,
          saved: lesson,
          completed: false,
        });
      }
    }
    for (const row of next) {
      row.completed = Boolean((await session.account.lessonProgress(row.lessonId))?.completed);
    }
    if (session.isActive()) setRows(next);
  }, [app, session, locale]);

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
          if (live) setFromCache(true);
        }
      })().catch(() => undefined);
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [session, locale]),
  );

  if (!app) return <Redirect href="/sign-in" />;
  const { t } = app;

  const save = async (row: Row) => {
    if (!app.api) return;
    setSaving(row.lessonId);
    setFailed(null);
    try {
      await saveLessonOffline(app.api, app.services.content, row.lessonId, app.locale, app.services.env);
    } catch {
      // The previously saved copy (if any) was not touched.
      setFailed({ lessonId: row.lessonId, hadCopy: row.saved !== null });
    } finally {
      setSaving(null);
      await loadLocal();
    }
  };

  if (rows === null) {
    return (
      <Screen>
        <Loading label={t('loading')} />
      </Screen>
    );
  }

  return (
    <Screen>
      {fromCache ? <Body muted>{t('catalogStale')}</Body> : null}
      {rows.length === 0 ? <Body muted>{t('lessonsEmpty')}</Body> : null}
      {rows.map((row) => {
        const updateAvailable =
          row.saved !== null &&
          row.publishedRevisionId !== null &&
          row.publishedRevisionId !== row.saved.revisionId;
        return (
          <Card key={row.lessonId}>
            <Body style={{ fontWeight: '700' }}>{row.saved?.title ?? row.title}</Body>
            <Body muted>
              {row.saved
                ? `${t('lessonSaved')} · ${t('readerRevision', { revision: row.saved.revision })}`
                : t('lessonNotSaved')}
              {row.completed ? ` · ${t('lessonCompleted')}` : ''}
            </Body>
            {updateAvailable ? <Body muted>{t('lessonUpdateAvailable')}</Body> : null}
            {failed?.lessonId === row.lessonId ? (
              <Banner tone="bad">{t(failed.hadCopy ? 'lessonSaveFailed' : 'lessonSaveFailedFirst')}</Banner>
            ) : null}
            {row.saved ? (
              <Button label={t('lessonOpen')} onPress={() => router.push(`/lesson/${row.lessonId}`)} />
            ) : null}
            {!row.saved || updateAvailable ? (
              <Button
                variant={row.saved ? 'secondary' : 'primary'}
                busy={saving === row.lessonId}
                disabled={saving !== null}
                label={
                  saving === row.lessonId
                    ? t('lessonSaving')
                    : row.saved
                      ? t('lessonUpdate')
                      : t('lessonSave')
                }
                onPress={() => void save(row)}
              />
            ) : null}
          </Card>
        );
      })}
    </Screen>
  );
}
