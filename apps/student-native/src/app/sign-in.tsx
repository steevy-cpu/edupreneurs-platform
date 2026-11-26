import { Redirect } from 'expo-router';
import React, { useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { ApiError } from '../core/api/errors';
import { AuthRefusedError } from '../core/auth/authClient';
import { WrongAccountError } from '../core/auth/session';
import type { StringKey } from '../core/i18n/strings';
import { AppText, Button, Chip, Notice, ScreenFrame, SectionHeader, space, TextField, TopBar } from '../design';
import { useApp } from '../ui/AppContext';

export default function SignIn() {
  const { t, session, needsReauth, signIn, locale, setLocale } = useApp();
  const reauth = Boolean(session && needsReauth);
  const [email, setEmail] = useState(session?.email ?? '');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<StringKey | null>(null);

  if (session && !needsReauth) return <Redirect href="/home" />;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
      setPassword('');
    } catch (failure) {
      if (failure instanceof AuthRefusedError) setError('signInInvalid');
      else if (failure instanceof WrongAccountError) setError('signInWrongAccount');
      else if (failure instanceof ApiError) setError('signInOffline');
      else setError('signInOffline');
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScreenFrame top={<TopBar />}>
      <AppText variant="display" accessibilityRole="header">
        {reauth ? t('signInAgainTitle') : t('signInTitle')}
      </AppText>
      {reauth ? <Notice>{t('signInAgainBody')}</Notice> : null}
      <TextField
        label={t('signInEmail')}
        value={email}
        onChangeText={setEmail}
        editable={!reauth && !busy}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="email-address"
        textContentType="username"
        testID="sign-in-email"
      />
      <TextField
        label={t('signInPassword')}
        value={password}
        onChangeText={setPassword}
        editable={!busy}
        secureTextEntry
        autoCapitalize="none"
        autoCorrect={false}
        textContentType="password"
        testID="sign-in-password"
        onSubmitEditing={() => void submit()}
      />
      {error ? <Notice tone="danger">{t(error)}</Notice> : null}
      <Button
        label={busy ? t('signInBusy') : t('signInButton')}
        busy={busy}
        disabled={email.trim().length === 0 || password.length === 0}
        testID="sign-in-submit"
        onPress={() => void submit()}
      />
      <View style={{ gap: space.sm }}>
        <SectionHeader title={t('homeLanguage')} />
        <ScrollView horizontal showsHorizontalScrollIndicator={false} accessibilityRole="radiogroup" contentContainerStyle={styles.chips}>
          <Chip label="Français" selected={locale === 'fr'} onPress={() => void setLocale('fr')} />
          <Chip label="Kreyòl" selected={locale === 'ht'} onPress={() => void setLocale('ht')} />
        </ScrollView>
      </View>
    </ScreenFrame>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', gap: space.sm, paddingRight: space.lg },
});
