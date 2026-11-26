/** Stand-in for expo-router in component tests: records navigation instead of performing it. */
import React from 'react';

export const navigation = { calls: [] as string[], params: {} as Record<string, string>, canGoBack: false };

export function useRouter() {
  return {
    push: (to: string) => void navigation.calls.push(`push ${to}`),
    replace: (to: string) => void navigation.calls.push(`replace ${to}`),
    back: () => void navigation.calls.push('back'),
    canGoBack: () => navigation.canGoBack,
  };
}
export function useLocalSearchParams() {
  return navigation.params;
}
/** A screen under test is always "focused": run the effect like useEffect. */
export function useFocusEffect(effect: () => void | (() => void)) {
  React.useEffect(effect, [effect]);
}
export function Redirect({ href }: { href: string }) {
  return React.createElement('Redirect', { href });
}
export function Stack({ children }: { children?: React.ReactNode }) {
  return React.createElement('Stack', null, children);
}
Stack.Screen = () => null;
