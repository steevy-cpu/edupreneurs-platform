import React, { useEffect, useRef } from 'react';
import { ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

/** Plain, text-first building blocks. System fonts, no images, no animation libraries. */
export const colors = {
  background: '#F7F7F4',
  surface: '#FFFFFF',
  text: '#1B1B1F',
  muted: '#5B5B66',
  primary: '#0B5FA5',
  primaryText: '#FFFFFF',
  border: '#D9D9DE',
  good: '#1B7F3B',
  bad: '#B3261E',
  warn: '#8A5A00',
  warnSurface: '#FFF4D6',
};

export function Screen({
  children,
  scroll = true,
  revealEndKey,
}: {
  children: React.ReactNode;
  scroll?: boolean;
  /**
   * When this value changes, new content was added at the bottom (e.g. quiz
   * feedback). If the content no longer fits on screen, scroll to show it.
   * Nothing moves when everything already fits.
   */
  revealEndKey?: unknown;
}) {
  const scrollRef = useRef<React.ComponentRef<typeof ScrollView> | null>(null);
  const sizes = useRef({ content: 0, viewport: 0 });
  const insets = useSafeAreaInsets();
  // On iOS the scroll view extends under the translucent navigation bar.
  const coveredTop = Platform.OS === 'ios' ? insets.top + 56 : 0;

  useEffect(() => {
    if (revealEndKey === undefined || revealEndKey === null || revealEndKey === false) return;
    const timer = setTimeout(() => {
      const { content, viewport } = sizes.current;
      if (content > viewport - coveredTop) scrollRef.current?.scrollToEnd({ animated: false });
    }, 80);
    return () => clearTimeout(timer);
  }, [revealEndKey, coveredTop]);

  return (
    <SafeAreaView style={styles.safe} edges={['bottom', 'left', 'right']}>
      {scroll ? (
        <ScrollView
          ref={scrollRef}
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          // iOS 26 navigation bars are translucent: without this the first rows
          // of every screen render underneath the header (found in native testing).
          contentInsetAdjustmentBehavior="automatic"
          onLayout={(event) => {
            sizes.current.viewport = event.nativeEvent.layout.height;
          }}
          onContentSizeChange={(_width, height) => {
            sizes.current.content = height;
          }}
        >
          {children}
        </ScrollView>
      ) : (
        <View style={styles.content}>{children}</View>
      )}
    </SafeAreaView>
  );
}

export function Title({ children }: { children: React.ReactNode }) {
  return (
    <Text style={styles.title} accessibilityRole="header">
      {children}
    </Text>
  );
}

export function Body({ children, muted, style }: { children: React.ReactNode; muted?: boolean; style?: object }) {
  return <Text style={[styles.body, muted && { color: colors.muted }, style]}>{children}</Text>;
}

export function Card({ children }: { children: React.ReactNode }) {
  return <View style={styles.card}>{children}</View>;
}

export function Button({
  label,
  onPress,
  disabled,
  busy,
  variant = 'primary',
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  busy?: boolean;
  variant?: 'primary' | 'secondary';
}) {
  const primary = variant === 'primary';
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: Boolean(disabled || busy), busy: Boolean(busy) }}
      disabled={disabled || busy}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        primary ? styles.buttonPrimary : styles.buttonSecondary,
        (disabled || busy) && styles.buttonDisabled,
        pressed && { opacity: 0.8 },
      ]}
    >
      {busy ? <ActivityIndicator color={primary ? colors.primaryText : colors.primary} /> : null}
      <Text style={[styles.buttonLabel, { color: primary ? colors.primaryText : colors.primary }]}>
        {label}
      </Text>
    </Pressable>
  );
}

export function Banner({ children, tone = 'warn' }: { children: React.ReactNode; tone?: 'warn' | 'bad' | 'good' }) {
  const color = tone === 'bad' ? colors.bad : tone === 'good' ? colors.good : colors.warn;
  const background = tone === 'good' ? '#E7F5EC' : tone === 'bad' ? '#FDECEA' : colors.warnSurface;
  return (
    <View style={[styles.banner, { borderColor: color, backgroundColor: background }]} accessibilityRole="alert">
      <Text style={[styles.body, { color }]}>{children}</Text>
    </View>
  );
}

export function Loading({ label }: { label: string }) {
  return (
    <View style={styles.loading}>
      <ActivityIndicator color={colors.primary} />
      <Text style={[styles.body, { color: colors.muted }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { padding: 16, gap: 12 },
  title: { fontSize: 24, fontWeight: '700', color: colors.text },
  body: { fontSize: 17, lineHeight: 25, color: colors.text },
  card: {
    backgroundColor: colors.surface,
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: 14,
    gap: 8,
  },
  button: {
    minHeight: 48,
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 10,
    flexDirection: 'row',
    gap: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonPrimary: { backgroundColor: colors.primary },
  buttonSecondary: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.primary },
  buttonDisabled: { opacity: 0.5 },
  buttonLabel: { fontSize: 17, fontWeight: '600', textAlign: 'center', flexShrink: 1 },
  banner: { backgroundColor: colors.warnSurface, borderRadius: 10, borderWidth: 1, padding: 12 },
  loading: { padding: 24, alignItems: 'center', gap: 8 },
});
