import React from 'react';
import { Pressable, StyleSheet, View, ViewStyle } from 'react-native';

import { useDesign } from '../theme';
import { ColorScheme, elevation, radius, size, space, touch } from '../tokens';
import { Icon, IconName } from './Icon';
import { AppText } from './Text';

/** Standard reading surface. */
export function Card({
  children,
  tone = 'surface',
  style,
}: {
  children: React.ReactNode;
  tone?: 'surface' | 'actionSoft' | 'accentSoft' | 'highlightSoft';
  style?: ViewStyle;
}) {
  const { colors, theme } = useDesign();
  return (
    <View
      style={[
        styles.card,
        {
          backgroundColor: colors[tone],
          borderColor: tone === 'surface' ? colors.border : 'transparent',
        },
        tone === 'surface' && theme === 'light' ? elevation.card : null,
        style,
      ]}
    >
      {children}
    </View>
  );
}

/** The single high-emphasis card of a screen (navy). */
export function HeroCard({ children }: { children: React.ReactNode }) {
  const { colors } = useDesign();
  return <View style={[styles.hero, { backgroundColor: colors.hero }]}>{children}</View>;
}

export type PillTone = 'neutral' | 'action' | 'accent' | 'highlight' | 'success' | 'danger' | 'warning' | 'onHero';

/** Small status label. Always has text: colour alone never carries the meaning. */
export function Pill({ label, tone = 'neutral', icon }: { label: string; tone?: PillTone; icon?: IconName }) {
  const { colors } = useDesign();
  const map: Record<PillTone, { bg: string; fg: string }> = {
    neutral: { bg: colors.surfaceSunken, fg: colors.text },
    action: { bg: colors.actionSoft, fg: colors.actionText },
    accent: { bg: colors.accentSoft, fg: colors.accentText },
    highlight: { bg: colors.highlight, fg: colors.onHighlight },
    success: { bg: colors.successSoft, fg: colors.success },
    danger: { bg: colors.dangerSoft, fg: colors.danger },
    warning: { bg: colors.warningSoft, fg: colors.warning },
    onHero: { bg: 'rgba(255,255,255,0.16)', fg: colors.textOnHero },
  };
  const { bg, fg } = map[tone];
  return (
    <View style={[styles.pill, { backgroundColor: bg }]}>
      {icon ? <Icon name={icon} color={fg} size={14} /> : null}
      {/* Long labels at large text sizes wrap inside the pill instead of running off the screen. */}
      <AppText variant="caption" style={{ color: fg, flexShrink: 1 }}>
        {label}
      </AppText>
    </View>
  );
}

/** Network reachability only. It never implies that work has been synchronised. */
export function ConnectivityPill({ online }: { online: boolean }) {
  const { t } = useDesign();
  return <Pill label={online ? t('online') : t('offline')} tone={online ? 'action' : 'warning'} icon={online ? 'dot' : 'ring'} />;
}

export function ProgressBar({
  value,
  tone = 'action',
  onHero,
  label,
}: {
  value: number;
  tone?: 'action' | 'accent' | 'highlight';
  onHero?: boolean;
  label: string;
}) {
  const { colors } = useDesign();
  const clamped = Math.max(0, Math.min(1, value));
  const fill: Record<string, string> = {
    action: colors.action,
    accent: colors.accent,
    highlight: colors.highlight,
  };
  return (
    <View
      accessible
      accessibilityRole="progressbar"
      accessibilityLabel={label}
      accessibilityValue={{ min: 0, max: 100, now: Math.round(clamped * 100) }}
      style={[
        styles.track,
        {
          backgroundColor: onHero ? 'rgba(255,255,255,0.25)' : colors.surfaceSunken,
        },
      ]}
    >
      <View
        style={{
          width: `${clamped * 100}%`,
          height: '100%',
          borderRadius: radius.pill,
          backgroundColor: onHero ? '#55D3B6' : fill[tone],
        }}
      />
    </View>
  );
}

export function SectionHeader({ title }: { title: string }) {
  return (
    <AppText variant="heading" accessibilityRole="header">
      {title}
    </AppText>
  );
}

/** A tappable row: leading icon bubble, title, supporting text, trailing chevron. */
export function ListRow({
  title,
  subtitle,
  icon,
  tone = 'action',
  onPress,
  trailing,
}: {
  title: string;
  subtitle?: string;
  icon: IconName;
  tone?: 'action' | 'accent' | 'highlight';
  onPress?: () => void;
  trailing?: React.ReactNode;
}) {
  const { colors } = useDesign();
  const soft: Record<string, keyof ColorScheme> = {
    action: 'actionSoft',
    accent: 'accentSoft',
    highlight: 'highlightSoft',
  };
  const strong: Record<string, keyof ColorScheme> = {
    action: 'actionText',
    accent: 'accentText',
    highlight: 'highlightText',
  };
  return (
    <Pressable
      accessibilityRole={onPress ? 'button' : undefined}
      accessibilityLabel={subtitle ? `${title}. ${subtitle}` : title}
      onPress={onPress}
      disabled={!onPress}
      style={({ pressed }) => [
        styles.row,
        {
          backgroundColor: pressed ? colors.surfaceSunken : colors.surface,
          borderColor: colors.border,
        },
      ]}
    >
      <View style={[styles.bubble, { backgroundColor: colors[soft[tone]] }]}>
        <Icon name={icon} color={colors[strong[tone]]} size={22} />
      </View>
      <View style={styles.rowText}>
        <AppText variant="bodyStrong">{title}</AppText>
        {subtitle ? (
          <AppText variant="caption" color="textSecondary">
            {subtitle}
          </AppText>
        ) : null}
      </View>
      {trailing ?? (onPress ? <Icon name="chevron" color={colors.textSecondary} size={18} /> : null)}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: space.lg,
    gap: space.sm,
  },
  hero: { borderRadius: radius.lg, padding: space.lg, gap: space.md },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.xs,
    alignSelf: 'flex-start',
    maxWidth: '100%',
    borderRadius: radius.pill,
    paddingHorizontal: space.md,
    paddingVertical: 6,
  },
  track: {
    height: size.progressBar,
    borderRadius: radius.pill,
    overflow: 'hidden',
  },
  row: {
    minHeight: touch.min + space.lg,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: space.md,
  },
  bubble: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  rowText: { flex: 1, gap: 2 },
});
