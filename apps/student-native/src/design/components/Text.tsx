import React from 'react';
import { Text, TextProps, TextStyle } from 'react-native';

import { useDesign } from '../theme';
import { ColorScheme, maxScale, type, TypeVariant } from '../tokens';

export interface AppTextProps extends TextProps {
  variant?: TypeVariant;
  /** Semantic colour name from the active palette. */
  color?: keyof ColorScheme;
  align?: TextStyle['textAlign'];
}

/**
 * The only text primitive. It follows the phone's text-size setting (up to
 * `maxScale`) and always takes its colour from the theme.
 */
export function AppText({ variant = 'body', color = 'text', align, style, ...rest }: AppTextProps) {
  const { colors } = useDesign();
  return <Text maxFontSizeMultiplier={maxScale} {...rest} style={[type[variant], { color: colors[color], textAlign: align }, style]} />;
}
