import React, { useEffect, useRef } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { LayoutWidthProvider, useDesign, useLayout } from '../theme';
import { radius, size, space, touch } from '../tokens';
import { Button } from './Button';
import { Icon, IconName } from './Icon';
import { AppText } from './Text';

export type TabKey = 'home' | 'learn' | 'review' | 'profile';

/** Four destinations, each with an icon AND a label, each at least 48 dp tall. */
export function TabBar({ current, onSelect }: { current: TabKey; onSelect: (tab: TabKey) => void }) {
  const { colors, t } = useDesign();
  const insets = useSafeAreaInsets();
  const tabs: { key: TabKey; icon: IconName; label: string }[] = [
    { key: 'home', icon: 'home', label: t('tabHome') },
    { key: 'learn', icon: 'learn', label: t('tabLearn') },
    { key: 'review', icon: 'review', label: t('tabReview') },
    { key: 'profile', icon: 'profile', label: t('tabProfile') },
  ];
  return (
    <View
      accessibilityRole="tablist"
      style={[
        styles.tabBar,
        {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
          paddingBottom: Math.max(insets.bottom, space.xs),
        },
      ]}
    >
      {tabs.map((tab) => {
        const active = tab.key === current;
        const color = active ? colors.actionText : colors.textSecondary;
        return (
          <Pressable
            key={tab.key}
            accessibilityRole="tab"
            accessibilityLabel={tab.label}
            accessibilityState={{ selected: active }}
            testID={`tab-${tab.key}`}
            onPress={() => onSelect(tab.key)}
            style={styles.tab}
          >
            <View style={[styles.tabIndicator, { backgroundColor: active ? colors.action : 'transparent' }]} />
            <Icon name={tab.icon} color={color} size={22} />
            <AppText
              variant="caption"
              numberOfLines={1}
              maxFontSizeMultiplier={1.3}
              adjustsFontSizeToFit
              minimumFontScale={0.75}
              align="center"
              style={{
                color,
                fontWeight: active ? '800' : '600',
                alignSelf: 'stretch',
              }}
            >
              {tab.label}
            </AppText>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Top bar: wordmark on root screens, back button on drill-down screens. */
export function TopBar({ title, onBack, trailing }: { title?: string; onBack?: () => void; trailing?: React.ReactNode }) {
  const { colors, t } = useDesign();
  const { compact } = useLayout();
  return (
    <View style={styles.topBar}>
      {onBack ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t('back')}
          onPress={onBack}
          style={[styles.backButton, { backgroundColor: colors.surface, borderColor: colors.border }]}
        >
          <Icon name="back" color={colors.text} size={18} />
        </Pressable>
      ) : (
        <View style={styles.wordmark} accessible accessibilityRole="header" accessibilityLabel={t('appName')}>
          <View style={[styles.mark, { backgroundColor: colors.hero }]}>
            <AppText variant="heading" allowFontScaling={false} style={{ color: '#FFD47D' }}>
              E
            </AppText>
          </View>
          {compact ? null : (
            <AppText variant="heading" maxFontSizeMultiplier={1.3} numberOfLines={1} style={{ flexShrink: 1 }}>
              {t('appName')}
            </AppText>
          )}
        </View>
      )}
      {title ? (
        <AppText variant="label" numberOfLines={1} style={{ flex: 1 }} align="center">
          {title}
        </AppText>
      ) : (
        <View style={{ flexGrow: 1 }} />
      )}
      <View style={styles.trailing}>{trailing}</View>
    </View>
  );
}

/**
 * Screen scaffold: safe areas, scrolling content, an optional action bar that
 * stays above the tab bar (so the primary action is always within thumb reach),
 * and the tab bar itself.
 */
export function ScreenFrame({
  top,
  children,
  action,
  tabs,
  maxWidth,
  banner,
  revealEndKey,
}: {
  top: React.ReactNode;
  children: React.ReactNode;
  action?: React.ReactNode;
  tabs?: React.ReactNode;
  /** Preview only: constrain the layout to a narrower phone width. */
  maxWidth?: number;
  banner?: React.ReactNode;
  /** When this value changes (and is set), scroll to the end so new content, e.g. answer feedback, is in view. */
  revealEndKey?: string | number | null;
}) {
  const { colors, reduceMotion } = useDesign();
  const insets = useSafeAreaInsets();
  const scroll = useRef<React.ComponentRef<typeof ScrollView> | null>(null);
  useEffect(() => {
    if (revealEndKey === undefined || revealEndKey === null) return;
    // Wait one frame so the new content has been laid out. No animation when the OS asks for reduced motion.
    const timer = setTimeout(() => scroll.current?.scrollToEnd({ animated: !reduceMotion }), 60);
    return () => clearTimeout(timer);
  }, [revealEndKey, reduceMotion]);
  const { roomy } = useLayout();
  const pinned = action && roomy;
  return (
    <View style={[styles.outer, { backgroundColor: maxWidth ? '#000000' : colors.canvas }]}>
      <View
        style={[
          styles.frame,
          {
            backgroundColor: colors.canvas,
            paddingTop: insets.top,
            maxWidth: maxWidth ?? undefined,
            width: '100%',
          },
        ]}
      >
        {banner}
        {top}
        <ScrollView ref={scroll} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          {children}
          {/* Very large text: the action follows the content so it never covers half the screen. */}
          {action && !pinned ? <View style={{ gap: space.sm }}>{action}</View> : null}
        </ScrollView>
        {pinned ? (
          <View
            style={[
              styles.actionBar,
              {
                backgroundColor: colors.canvas,
                borderTopColor: colors.border,
                paddingBottom: tabs ? space.md : Math.max(insets.bottom, space.md),
              },
            ]}
          >
            {action}
          </View>
        ) : null}
        {tabs}
      </View>
    </View>
  );
}

/** Wraps a screen whose width is artificially limited (design previews) so components measure the right width. */
export function WidthScope({ width, children }: { width?: number; children: React.ReactNode }) {
  return <LayoutWidthProvider value={width}>{children}</LayoutWidthProvider>;
}

// ----------------------------------------------------------------------- states
export function LoadingState({ label }: { label: string }) {
  const { colors } = useDesign();
  return (
    <View accessible accessibilityRole="progressbar" accessibilityLabel={label} style={{ gap: space.md }}>
      <View style={styles.loadingRow}>
        <ActivityIndicator color={colors.action} />
        <AppText color="textSecondary">{label}</AppText>
      </View>
      {[120, 72, 72].map((height, i) => (
        <View
          key={i}
          style={{
            height,
            borderRadius: radius.lg,
            backgroundColor: colors.surfaceSunken,
          }}
        />
      ))}
    </View>
  );
}

export function MessageState({
  title,
  body,
  actionLabel,
  onAction,
  tone = 'neutral',
}: {
  title: string;
  body: string;
  actionLabel?: string;
  onAction?: () => void;
  tone?: 'neutral' | 'danger';
}) {
  const { colors } = useDesign();
  return (
    <View
      style={[
        styles.message,
        {
          backgroundColor: tone === 'danger' ? colors.dangerSoft : colors.surface,
          borderColor: tone === 'danger' ? colors.danger : colors.border,
        },
      ]}
    >
      <View
        style={[
          styles.messageIcon,
          {
            backgroundColor: tone === 'danger' ? colors.danger : colors.actionSoft,
          },
        ]}
      >
        <Icon name={tone === 'danger' ? 'cross' : 'learn'} color={tone === 'danger' ? colors.surface : colors.actionText} size={24} />
      </View>
      <AppText variant="title" align="center" accessibilityRole="header">
        {title}
      </AppText>
      <AppText color="textSecondary" align="center">
        {body}
      </AppText>
      {actionLabel ? <Button label={actionLabel} onPress={onAction} variant={tone === 'danger' ? 'secondary' : 'primary'} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  outer: { flex: 1, alignItems: 'center' },
  frame: { flex: 1 },
  content: {
    paddingHorizontal: space.lg,
    paddingTop: space.sm,
    paddingBottom: space.xl,
    gap: space.lg,
  },
  actionBar: {
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    gap: space.sm,
  },
  tabBar: { flexDirection: 'row', borderTopWidth: StyleSheet.hairlineWidth },
  tab: {
    flex: 1,
    minHeight: size.tabBarHeight,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
    paddingBottom: space.xs,
  },
  tabIndicator: {
    width: 28,
    height: 3,
    borderRadius: 2,
    marginBottom: space.xs,
  },
  topBar: {
    minHeight: 56,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingHorizontal: space.lg,
  },
  backButton: {
    width: touch.min,
    height: touch.min,
    borderRadius: touch.min / 2,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  wordmark: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    flexShrink: 1,
  },
  mark: {
    width: 32,
    height: 32,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  trailing: { flexDirection: 'row', gap: space.sm, alignItems: 'center' },
  loadingRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  message: {
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: space.xl,
    gap: space.md,
    alignItems: 'stretch',
  },
  messageIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'center',
  },
});
