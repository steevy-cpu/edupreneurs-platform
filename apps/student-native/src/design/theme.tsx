import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { AccessibilityInfo, useColorScheme, useWindowDimensions } from 'react-native';

import { type StringKey, translator } from '../core/i18n/strings';
import { ColorScheme, darkColors, lightColors, maxScale } from './tokens';

export type ThemeName = 'light' | 'dark';
export type DesignLocale = 'fr' | 'ht';
/** Kept as an alias: components were written against this name in Design-00. */
export type DesignStringKey = StringKey;

export interface DesignContextValue {
  theme: ThemeName;
  colors: ColorScheme;
  locale: DesignLocale;
  /** Translate a key; `{name}` placeholders are filled from `values`. */
  t: (key: StringKey, values?: Record<string, string | number>) => string;
  /** True when the OS asks apps to avoid animation. Components must not animate when set. */
  reduceMotion: boolean;
}

const DesignContext = createContext<DesignContextValue | null>(null);

/** Tracks the OS "reduce motion" setting. */
export function useReduceMotion(): boolean {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    let live = true;
    AccessibilityInfo.isReduceMotionEnabled()
      .then((value) => live && setReduce(value))
      .catch(() => undefined);
    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduce);
    return () => {
      live = false;
      subscription.remove();
    };
  }, []);
  return reduce;
}

export function DesignProvider({
  children,
  theme,
  locale = 'fr',
}: {
  children: React.ReactNode;
  /** Force a theme. Omit to follow the phone's setting. */
  theme?: ThemeName;
  locale?: DesignLocale;
}) {
  const system = useColorScheme();
  const reduceMotion = useReduceMotion();
  const resolved: ThemeName = theme ?? (system === 'dark' ? 'dark' : 'light');
  const value = useMemo<DesignContextValue>(() => {
    return {
      theme: resolved,
      colors: resolved === 'dark' ? darkColors : lightColors,
      locale,
      // One catalog for the whole app: src/core/i18n/strings.ts.
      t: translator(locale),
      reduceMotion,
    };
  }, [resolved, locale, reduceMotion]);
  return <DesignContext.Provider value={value}>{children}</DesignContext.Provider>;
}

export function useDesign(): DesignContextValue {
  const value = useContext(DesignContext);
  if (!value) throw new Error('useDesign must be used inside <DesignProvider>');
  return value;
}

/**
 * How much room the layout really has. `textScale` is the phone's text-size
 * setting (1 = default, capped at the design system's maximum). `compact` is
 * true when large text on a narrow screen leaves little horizontal room;
 * components then stack or drop decoration instead of clipping.
 */
export interface LayoutInfo {
  width: number;
  textScale: number;
  compact: boolean;
  /** Very large text: the primary action scrolls with the content instead of being pinned. */
  roomy: boolean;
}

const LayoutContext = createContext<number | undefined>(undefined);

/** Lets a container (e.g. a narrow preview frame) report its own width to the components inside it. */
export const LayoutWidthProvider = LayoutContext.Provider;

export function useLayout(): LayoutInfo {
  const window = useWindowDimensions();
  const override = useContext(LayoutContext);
  const width = override ? Math.min(override, window.width) : window.width;
  const textScale = Math.min(window.fontScale || 1, maxScale);
  return {
    width,
    textScale,
    compact: width / textScale < 250,
    roomy: textScale < 1.6,
  };
}
