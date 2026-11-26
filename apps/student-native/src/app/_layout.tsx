import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import React from 'react';
import { LogBox } from 'react-native';

import { LoadingState, MessageState, ScreenFrame, TopBar } from '../design';
import { AppProvider, useApp } from '../ui/AppContext';
import { Themed } from '../ui/shell';

// React Navigation emits this development-only warning on every transition; it is
// harmless but its on-screen banner covers the bottom buttons in debug builds.
LogBox.ignoreLogs(['Sending `onAnimatedValueUpdate` with no listeners registered']);

function Root() {
  const { boot, bootError, t } = useApp();
  if (boot === 'starting') {
    return (
      <ScreenFrame top={<TopBar />}>
        <LoadingState label={t('loading')} />
      </ScreenFrame>
    );
  }
  if (boot === 'failed') {
    return (
      <ScreenFrame top={<TopBar />}>
        <MessageState tone="danger" title={t('errorTitle')} body={bootError ?? 'Start-up failed'} />
      </ScreenFrame>
    );
  }
  // Every screen draws its own top bar and (for the four main destinations) tab bar.
  return (
    <Stack screenOptions={{ headerShown: false, animation: 'none' }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="sign-in" />
      <Stack.Screen name="home" />
      <Stack.Screen name="learn" />
      <Stack.Screen name="review" />
      <Stack.Screen name="profile" />
      <Stack.Screen name="lesson/[id]" />
      <Stack.Screen name="quiz/[id]" />
    </Stack>
  );
}

export default function Layout() {
  return (
    <AppProvider>
      <Themed>
        <StatusBar style="dark" />
        <Root />
      </Themed>
    </AppProvider>
  );
}
