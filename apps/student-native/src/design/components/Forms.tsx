import React from 'react';
import { Pressable, StyleSheet, TextInput, TextInputProps, View } from 'react-native';

import { useDesign } from '../theme';
import { maxScale, radius, space, touch, type } from '../tokens';
import { Icon, IconName } from './Icon';
import { AppText } from './Text';

/** A selectable pill (grade, subject, language). Behaves as a radio button. */
export function Chip({ label, selected, onPress, testID }: { label: string; selected: boolean; onPress: () => void; testID?: string }) {
  const { colors } = useDesign();
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={label}
      onPress={onPress}
      testID={testID}
      style={[
        styles.chip,
        {
          backgroundColor: selected ? colors.hero : colors.surface,
          borderColor: selected ? colors.hero : colors.borderControl,
        },
      ]}
    >
      <AppText variant="label" style={{ color: selected ? colors.textOnHero : colors.text }}>
        {label}
      </AppText>
    </Pressable>
  );
}

export type NoticeTone = 'info' | 'warning' | 'danger' | 'success';

/** A short inline message. The icon and the words carry the meaning, not the colour alone. */
export function Notice({ children, tone = 'warning', role = 'alert' }: { children: string; tone?: NoticeTone; role?: 'alert' | 'text' }) {
  const { colors } = useDesign();
  const look: Record<NoticeTone, { bg: string; fg: string; icon: IconName }> = {
    info: { bg: colors.actionSoft, fg: colors.actionText, icon: 'dot' },
    warning: { bg: colors.warningSoft, fg: colors.warning, icon: 'ring' },
    danger: { bg: colors.dangerSoft, fg: colors.danger, icon: 'cross' },
    success: { bg: colors.successSoft, fg: colors.success, icon: 'check' },
  };
  const { bg, fg, icon } = look[tone];
  return (
    <View accessible accessibilityRole={role} style={[styles.notice, { backgroundColor: bg, borderColor: fg }]}>
      <View style={{ marginTop: 2 }}>
        <Icon name={icon} color={fg} size={16} />
      </View>
      <AppText style={{ color: colors.text, flex: 1 }}>{children}</AppText>
    </View>
  );
}

/** A labelled text input that follows the design tokens. */
export function TextField({ label, ...input }: { label: string } & TextInputProps) {
  const { colors } = useDesign();
  return (
    <View style={{ gap: space.xs }}>
      <AppText variant="label" color="textSecondary">
        {label}
      </AppText>
      <TextInput
        accessibilityLabel={label}
        maxFontSizeMultiplier={maxScale}
        placeholderTextColor={colors.textSecondary}
        {...input}
        style={[
          type.body,
          styles.input,
          { color: colors.text, backgroundColor: colors.surface, borderColor: colors.borderControl },
          input.editable === false ? { backgroundColor: colors.disabledSurface, color: colors.disabledText } : null,
        ]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    minHeight: touch.min,
    minWidth: touch.min,
    paddingHorizontal: space.lg,
    borderRadius: radius.pill,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
  notice: {
    flexDirection: 'row',
    gap: space.sm,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: space.md,
  },
  input: {
    minHeight: touch.min + 4,
    borderWidth: 1.5,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
  },
});
