import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import React from 'react';
import { LogBox } from 'react-native';

import { AppProvider, useApp } from '../ui/AppContext';
import { Banner, Body, Loading, Screen } from '../ui/components';

// React Navigation emits this development-only warning on every transition; it is
// harmless but its on-screen banner covers the bottom buttons in debug builds.
LogBox.ignoreLogs(['Sending `onAnimatedValueUpdate` with no listeners registered']);

function Root() {
  const { boot, bootError, t } = useApp();
  if (boot === 'starting') {
    return (
      <Screen>
        <Loading label={t('loading')} />
      </Screen>
    );
  }
  if (boot === 'failed') {
    return (
      <Screen>
        <Banner tone="bad">{bootError ?? 'Start-up failed'}</Banner>
        <Body muted>Edupreneurs</Body>
      </Screen>
    );
  }
  return (
    <Stack screenOptions={{ headerBackTitle: t('back'), animation: 'none' }}>
      <Stack.Screen name="index" options={{ headerShown: false }} />
      <Stack.Screen name="sign-in" options={{ title: t('signInTitle'), headerBackVisible: false }} />
      <Stack.Screen name="home" options={{ title: t('appName'), headerBackVisible: false }} />
      <Stack.Screen name="select" options={{ title: t('selectTitle') }} />
      <Stack.Screen name="lessons" options={{ title: t('lessonsTitle') }} />
      <Stack.Screen name="lesson/[id]" options={{ title: '' }} />
      <Stack.Screen name="quiz/[id]" options={{ title: t('quizTitle') }} />
      <Stack.Screen name="progress" options={{ title: t('progressTitle') }} />
    </Stack>
  );
}

export default function Layout() {
  return (
    <AppProvider>
      <StatusBar style="dark" />
      <Root />
    </AppProvider>
  );
}
