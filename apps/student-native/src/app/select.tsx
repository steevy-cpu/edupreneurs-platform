import { Redirect, useRouter } from 'expo-router';
import React, { useEffect, useMemo, useState } from 'react';

import type { CatalogResponse } from '../core/api/types';
import { refreshCatalog } from '../core/learning/actions';
import { Body, Button, Card, Loading, Screen } from '../ui/components';
import { useSignedIn } from '../ui/useSession';

export default function Select() {
  const app = useSignedIn();
  const router = useRouter();
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [grade, setGrade] = useState<string | null>(null);
  const [subject, setSubject] = useState<string | null>(null);
  const session = app?.session;
  const locale = app?.locale;

  useEffect(() => {
    if (!app || !session || !locale) return;
    let live = true;
    (async () => {
      // 1. Show what the phone already has, immediately.
      const cached = await app.services.content.getCatalog(locale);
      const savedGrade = await session.account.getPreference('grade_code');
      const savedSubject = await session.account.getPreference('subject_slug');
      if (!live) return;
      if (cached) setCatalog(cached.catalog);
      setGrade(savedGrade);
      setSubject(savedSubject);
      setLoaded(Boolean(cached));
      // 2. Then try to refresh from the network; failure just keeps the cached list.
      if (app.api) {
        try {
          await refreshCatalog(app.api, app.services.content, locale, app.services.env);
          const fresh = await app.services.content.getCatalog(locale);
          if (live && fresh) setCatalog(fresh.catalog);
        } catch {
          // offline or session ended
        }
      }
      if (live) setLoaded(true);
    })().catch(() => live && setLoaded(true));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, locale]);

  const grades = useMemo(() => {
    const seen = new Map<string, string>();
    for (const course of catalog?.courses ?? []) seen.set(course.grade.code, course.grade.label);
    return [...seen.entries()];
  }, [catalog]);

  const subjects = useMemo(() => {
    const seen = new Map<string, string>();
    for (const course of catalog?.courses ?? []) {
      if (course.grade.code === grade) seen.set(course.subject.slug, course.subject.label);
    }
    return [...seen.entries()];
  }, [catalog, grade]);

  if (!app) return <Redirect href="/sign-in" />;
  const { t } = app;

  const confirm = async () => {
    if (!grade || !subject) return;
    await app.session.account.setPreference('grade_code', grade);
    await app.session.account.setPreference('subject_slug', subject);
    router.replace('/lessons');
  };

  if (!loaded) {
    return (
      <Screen>
        <Loading label={t('loading')} />
      </Screen>
    );
  }

  return (
    <Screen>
      {grades.length === 0 ? <Body muted>{t('selectEmpty')}</Body> : null}
      {grades.length > 0 ? (
        <Card>
          <Body style={{ fontWeight: '700' }}>{t('selectGrade')}</Body>
          {grades.map(([code, label]) => (
            <Button
              key={code}
              variant={grade === code ? 'primary' : 'secondary'}
              label={`${code} · ${label}`}
              onPress={() => {
                setGrade(code);
                setSubject(null);
              }}
            />
          ))}
        </Card>
      ) : null}
      {grade && subjects.length > 0 ? (
        <Card>
          <Body style={{ fontWeight: '700' }}>{t('selectSubject')}</Body>
          {subjects.map(([slug, label]) => (
            <Button
              key={slug}
              variant={subject === slug ? 'primary' : 'secondary'}
              label={label}
              onPress={() => setSubject(slug)}
            />
          ))}
        </Card>
      ) : null}
      <Button label={t('selectConfirm')} disabled={!grade || !subject} onPress={() => void confirm()} />
    </Screen>
  );
}
