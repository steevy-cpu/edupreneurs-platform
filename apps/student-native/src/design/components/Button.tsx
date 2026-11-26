import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import { useDesign } from '../theme';
import { radius, size, space } from '../tokens';
import { Icon, IconName } from './Icon';
import { AppText } from './Text';

export type ButtonVariant = 'primary' | 'secondary' | 'onHero' | 'accent';

/**
 * One dominant action per screen uses `primary`. Labels wrap instead of being
 * cut off, so long French/Creole text and large text sizes stay readable.
 */
export function Button({
  label,
  onPress,
  variant = 'primary',
  icon,
  disabled,
  busy,
  accessibilityHint,
  testID,
}: {
  label: string;
  onPress?: () => void;
  variant?: ButtonVariant;
  icon?: IconName;
  disabled?: boolean;
  /** Work in progress: shows a spinner and ignores taps. */
  busy?: boolean;
  accessibilityHint?: string;
  testID?: string;
}) {
  const { colors } = useDesign();
  const palette = {
    primary: {
      bg: colors.action,
      pressed: colors.actionPressed,
      fg: colors.onAction,
      border: colors.action,
    },
    secondary: {
      bg: colors.surface,
      pressed: colors.actionSoft,
      fg: colors.actionText,
      border: colors.action,
    },
    onHero: {
      bg: '#FFFFFF',
      pressed: '#E3F2EF',
      fg: '#142337',
      border: '#FFFFFF',
    },
    accent: {
      bg: colors.accent,
      pressed: colors.accent,
      fg: colors.onAccent,
      border: colors.accent,
    },
  }[variant];
  const inactive = Boolean(disabled || busy);
  const fg = disabled ? colors.disabledText : palette.fg;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: inactive, busy: Boolean(busy) }}
      disabled={inactive}
      testID={testID}
      onPress={onPress}
      style={({ pressed }) => [
        styles.base,
        {
          backgroundColor: disabled ? colors.disabledSurface : pressed ? palette.pressed : palette.bg,
          borderColor: disabled ? colors.disabledSurface : palette.border,
        },
      ]}
    >
      {busy ? <ActivityIndicator color={fg} /> : icon ? <Icon name={icon} color={fg} size={20} /> : null}
      <View style={styles.label}>
        <AppText variant="label" align="center" style={{ color: fg, fontSize: 17, lineHeight: 22 }}>
          {label}
        </AppText>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: size.buttonHeight,
    borderRadius: radius.md,
    borderWidth: 2,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.sm,
  },
  label: { flexShrink: 1 },
});
