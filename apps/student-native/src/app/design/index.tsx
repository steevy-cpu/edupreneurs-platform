import { Redirect, useRouter } from 'expo-router';
import React, { useState } from 'react';
import { ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppText, Button, Card, DesignLocale, DesignProvider, space, ThemeName, useDesign, useLayout } from '../../design';
import { PREVIEW_ENABLED } from '../../design/preview/shell';

const SCREENS: { path: string; title: string; states: string[] }[] = [
  {
    path: 'home',
    title: 'Home',
    states: ['default', 'offline', 'pending', 'loading', 'empty', 'error'],
  },
  { path: 'path', title: 'Learning Path', states: ['default', 'offline'] },
  { path: 'lesson', title: 'Lesson Reader', states: ['default', 'offline'] },
  {
    path: 'quiz',
    title: 'Practice Quiz',
    states: ['default', 'selected', 'correct', 'incorrect', 'long', 'long-correct'],
  },
  {
    path: 'progress',
    title: 'Progress',
    states: ['default', 'pending', 'failed', 'attention', 'empty'],
  },
];

/** Gallery of every preview screen and state, for design review on a device. */
function Gallery({
  locale,
  setLocale,
  theme,
  setTheme,
}: {
  locale: DesignLocale;
  setLocale: (l: DesignLocale) => void;
  theme: ThemeName;
  setTheme: (t: ThemeName) => void;
}) {
  const router = useRouter();
  const { colors, reduceMotion } = useDesign();
  const layout = useLayout();
  const insets = useSafeAreaInsets();
  return (
    <ScrollView
      style={{ backgroundColor: colors.canvas }}
      contentContainerStyle={{
        padding: space.lg,
        paddingTop: insets.top + space.lg,
        gap: space.lg,
      }}
    >
      <AppText variant="display" accessibilityRole="header">
        Design-00
      </AppText>
      <AppText color="textSecondary">
        Edupreneurs design previews. Fixture data only; nothing here reads or writes the student database.
      </AppText>
      {/* What the design system currently reads from the phone's accessibility settings. */}
      <AppText variant="caption" color="textSecondary" testID="design-env">
        {`Reduce motion: ${reduceMotion ? 'ON' : 'off'} · Text scale: ${layout.textScale.toFixed(2)} · Width: ${Math.round(layout.width)}`}
      </AppText>
      <View style={{ flexDirection: 'row', gap: space.sm }}>
        <View style={{ flex: 1 }}>
          <Button label="Français" variant={locale === 'fr' ? 'primary' : 'secondary'} onPress={() => setLocale('fr')} />
        </View>
        <View style={{ flex: 1 }}>
          <Button label="Kreyòl" variant={locale === 'ht' ? 'primary' : 'secondary'} onPress={() => setLocale('ht')} />
        </View>
      </View>
      <View style={{ flexDirection: 'row', gap: space.sm }}>
        <View style={{ flex: 1 }}>
          <Button label="Light" variant={theme === 'light' ? 'primary' : 'secondary'} onPress={() => setTheme('light')} />
        </View>
        <View style={{ flex: 1 }}>
          <Button label="Dark" variant={theme === 'dark' ? 'primary' : 'secondary'} onPress={() => setTheme('dark')} />
        </View>
      </View>
      {SCREENS.map((screen) => (
        <Card key={screen.path}>
          <AppText variant="heading">{screen.title}</AppText>
          {screen.states.map((state) => (
            <Button
              key={state}
              label={state}
              variant="secondary"
              onPress={() =>
                router.push({
                  pathname: `/design/${screen.path}`,
                  params: { locale, theme, state },
                })
              }
            />
          ))}
        </Card>
      ))}
    </ScrollView>
  );
}

export default function DesignIndex() {
  const [locale, setLocale] = useState<DesignLocale>('fr');
  const [theme, setTheme] = useState<ThemeName>('light');
  if (!PREVIEW_ENABLED) return <Redirect href="/" />;
  return (
    <DesignProvider locale={locale} theme={theme}>
      <Gallery locale={locale} setLocale={setLocale} theme={theme} setTheme={setTheme} />
    </DesignProvider>
  );
}
