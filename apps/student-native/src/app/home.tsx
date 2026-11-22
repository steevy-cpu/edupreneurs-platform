import { Redirect, useFocusEffect, useRouter } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { Alert, View } from 'react-native';

import { Banner, Body, Button, Card, Screen, Title } from '../ui/components';
import { SyncCard } from '../ui/SyncCard';
import { useSignedIn } from '../ui/useSession';

export default function Home() {
  const app = useSignedIn();
  const router = useRouter();
  const [selection, setSelection] = useState<{ grade: string | null; subject: string | null }>({
    grade: null,
    subject: null,
  });
  const [leaving, setLeaving] = useState(false);

  useFocusEffect(
    useCallback(() => {
      if (!app) return;
      let live = true;
      (async () => {
        const grade = await app.session.account.getPreference('grade_code');
        const subject = await app.session.account.getPreference('subject_slug');
        if (live) setSelection({ grade, subject });
        await app.refreshSummary();
      })().catch(() => undefined);
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [app?.session]),
  );

  if (!app) return <Redirect href="/sign-in" />;
  const { t, session, sync, needsReauth, locale, setLocale, signOut, syncNow } = app;

  const leave = async () => {
    setLeaving(true);
    try {
      await signOut();
    } finally {
      setLeaving(false);
    }
  };

  /**
   * Signing out never deletes work. With unsynced operations the student is told
   * exactly what will happen and can sync first; "keep" leaves the operations in
   * this account's own database until the same account signs in again.
   */
  const confirmSignOut = async () => {
    const summary = await session.account.syncSummary();
    if (summary.pending === 0) {
      await leave();
      return;
    }
    Alert.alert(t('signOutTitle'), t('signOutBody', { count: summary.pending }), [
      { text: t('cancel'), style: 'cancel' },
      {
        text: t('signOutSyncFirst'),
        onPress: () => {
          void (async () => {
            const report = await syncNow();
            const after = await session.account.syncSummary();
            if (report?.outcome === 'ok' && after.pending === 0) await leave();
            else Alert.alert(t('signOutTitle'), t('signOutSyncFailed'));
          })();
        },
      },
      { text: t('signOutKeep'), style: 'destructive', onPress: () => void leave() },
    ]);
  };

  return (
    <Screen>
      <Title>
        {t('homeHello')} {session.email.split('@')[0]}
      </Title>
      {needsReauth ? (
        <Card>
          <Banner>{t('sessionExpiredBanner')}</Banner>
          <Button label={t('signInAgainTitle')} onPress={() => router.push('/sign-in')} />
        </Card>
      ) : null}
      <Button label={t('homeChoose')} onPress={() => router.push('/select')} />
      <Button
        label={t('homeLessons')}
        variant="secondary"
        onPress={() => router.push(selection.grade && selection.subject ? '/lessons' : '/select')}
      />
      {!selection.grade ? <Body muted>{t('homeNoSelection')}</Body> : null}
      <Button label={t('homeProgress')} variant="secondary" onPress={() => router.push('/progress')} />
      <SyncCard />
      <Card>
        <Body muted>{t('homeLanguage')}</Body>
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <View style={{ flex: 1 }}>
            <Button variant={locale === 'fr' ? 'primary' : 'secondary'} label="Français" onPress={() => void setLocale('fr')} />
          </View>
          <View style={{ flex: 1 }}>
            <Button variant={locale === 'ht' ? 'primary' : 'secondary'} label="Kreyòl" onPress={() => void setLocale('ht')} />
          </View>
        </View>
      </Card>
      <Button label={t('homeSignOut')} variant="secondary" busy={leaving} onPress={() => void confirmSignOut()} />
      {sync.summary.pending > 0 ? <Body muted>{t('stateWaiting')}</Body> : null}
    </Screen>
  );
}
