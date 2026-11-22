import { Redirect } from 'expo-router';
import React, { useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';

import { ApiError } from '../core/api/errors';
import { AuthRefusedError } from '../core/auth/authClient';
import { WrongAccountError } from '../core/auth/session';
import type { StringKey } from '../core/i18n/strings';
import { useApp } from '../ui/AppContext';
import { Banner, Body, Button, colors, Screen, Title } from '../ui/components';

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
    <Screen>
      <Title>{reauth ? t('signInAgainTitle') : t('appName')}</Title>
      {reauth ? <Banner>{t('signInAgainBody')}</Banner> : null}
      <View style={styles.field}>
        <Text style={styles.label}>{t('signInEmail')}</Text>
        <TextInput
          style={styles.input}
          value={email}
          onChangeText={setEmail}
          editable={!reauth && !busy}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          textContentType="username"
          accessibilityLabel={t('signInEmail')}
        />
      </View>
      <View style={styles.field}>
        <Text style={styles.label}>{t('signInPassword')}</Text>
        <TextInput
          style={styles.input}
          value={password}
          onChangeText={setPassword}
          editable={!busy}
          secureTextEntry
          autoCapitalize="none"
          autoCorrect={false}
          textContentType="password"
          accessibilityLabel={t('signInPassword')}
          onSubmitEditing={() => void submit()}
        />
      </View>
      {error ? <Banner tone="bad">{t(error)}</Banner> : null}
      <Button
        label={busy ? t('signInBusy') : t('signInButton')}
        busy={busy}
        disabled={email.trim().length === 0 || password.length === 0}
        onPress={() => void submit()}
      />
      <View style={styles.languages}>
        <Body muted>{t('homeLanguage')}</Body>
        <Button variant={locale === 'fr' ? 'primary' : 'secondary'} label="Français" onPress={() => void setLocale('fr')} />
        <Button variant={locale === 'ht' ? 'primary' : 'secondary'} label="Kreyòl" onPress={() => void setLocale('ht')} />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  field: { gap: 4 },
  label: { fontSize: 15, color: colors.muted },
  input: {
    minHeight: 48,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingHorizontal: 12,
    fontSize: 17,
    color: colors.text,
    backgroundColor: colors.surface,
  },
  languages: { marginTop: 16, gap: 8 },
});
