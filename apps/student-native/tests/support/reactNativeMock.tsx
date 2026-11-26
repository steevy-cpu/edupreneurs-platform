/**
 * A minimal stand-in for `react-native` so real screens can be rendered in Node
 * by react-test-renderer. Components become plain host elements ("View",
 * "Text", "Pressable", …) that keep every prop, so tests can read the text a
 * student would see and press what a student would press.
 * It imitates layout-free behaviour only; pixels are checked on the emulators.
 */
import React from 'react';

type AnyProps = Record<string, unknown> & { children?: React.ReactNode };

/** Every `scrollTo` a ScrollView received, so a test can check that a screen returns to its top. */
export const scrollCalls: { y?: number; animated?: boolean }[] = [];

function host(name: string) {
  const Component = React.forwardRef<unknown, AnyProps>((props, ref) => {
    React.useImperativeHandle(ref, () => ({
      scrollToEnd: () => undefined,
      scrollTo: (options: { y?: number; animated?: boolean }) => void scrollCalls.push(options),
      focus: () => undefined,
    }));
    const style =
      typeof props.style === 'function' ? (props.style as (s: { pressed: boolean }) => unknown)({ pressed: false }) : props.style;
    return React.createElement(name, { ...props, style }, props.children as React.ReactNode);
  });
  Component.displayName = name;
  return Component;
}

export const View = host('View');
export const Text = host('Text');
export const Pressable = host('Pressable');
export const ScrollView = host('ScrollView');
export const TextInput = host('TextInput');
export const ActivityIndicator = host('ActivityIndicator');

export const StyleSheet = {
  create: <T,>(styles: T): T => styles,
  hairlineWidth: 1,
  flatten: (style: unknown) => style,
};

export const testDevice = { width: 320, height: 640, fontScale: 1, reduceMotion: false };

export function useWindowDimensions() {
  return { width: testDevice.width, height: testDevice.height, fontScale: testDevice.fontScale, scale: 1.5 };
}
export function useColorScheme() {
  return 'light';
}
export const AccessibilityInfo = {
  isReduceMotionEnabled: async () => testDevice.reduceMotion,
  addEventListener: () => ({ remove: () => undefined }),
};
export const Platform = { OS: 'android', select: <T,>(options: { android?: T; default?: T }) => options.android ?? options.default };
export const AppState = { addEventListener: () => ({ remove: () => undefined }) };
export const LogBox = { ignoreLogs: () => undefined };

export interface AlertCall {
  title: string;
  message?: string;
  buttons: { text: string; style?: string; onPress?: () => void }[];
}
export const Alert = {
  calls: [] as AlertCall[],
  alert(title: string, message?: string, buttons: AlertCall['buttons'] = []) {
    Alert.calls.push({ title, message, buttons });
  },
};
