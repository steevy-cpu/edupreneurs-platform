import { Redirect, useLocalSearchParams, useRouter } from 'expo-router';
import React from 'react';
import { View } from 'react-native';

import { AppText, ConnectivityPill, DesignLocale, DesignProvider, ScreenFrame, TabBar, TabKey, ThemeName, useDesign, WidthScope } from '..';

/**
 * Design previews are reachable only in development builds, or in a build made
 * with EXPO_PUBLIC_DESIGN_PREVIEW=1. No production screen links to them.
 */
export const PREVIEW_ENABLED = __DEV__ || process.env.EXPO_PUBLIC_DESIGN_PREVIEW === '1';

export interface PreviewParams {
  locale: DesignLocale;
  theme: ThemeName | undefined;
  state: string;
  width: number | undefined;
}

type RawParams = {
  locale?: string;
  theme?: string;
  state?: string;
  width?: string;
};

export function usePreviewParams(): PreviewParams & { raw: RawParams } {
  const raw = useLocalSearchParams<RawParams>();
  const width = raw.width ? Number(raw.width) : undefined;
  return {
    raw,
    locale: raw.locale === 'ht' ? 'ht' : 'fr',
    theme: raw.theme === 'dark' ? 'dark' : raw.theme === 'light' ? 'light' : undefined,
    state: raw.state ?? 'default',
    width: width && width >= 280 && width <= 480 ? width : undefined,
  };
}

export type PreviewScreen = 'home' | 'path' | 'lesson' | 'quiz' | 'progress';

/** Navigate between previews, carrying locale / theme / width (but not `state`) along. */
export function usePreviewNav() {
  const router = useRouter();
  const { raw } = usePreviewParams();
  return (screen: PreviewScreen | 'index', state?: string) => {
    const params: Record<string, string> = {};
    if (raw.locale) params.locale = raw.locale;
    if (raw.theme) params.theme = raw.theme;
    if (raw.width) params.width = raw.width;
    if (state) params.state = state;
    router.replace({
      pathname: screen === 'index' ? '/design' : `/design/${screen}`,
      params,
    });
  };
}

const TAB_TARGET: Record<TabKey, PreviewScreen> = {
  home: 'home',
  learn: 'path',
  review: 'quiz',
  profile: 'progress',
};

function Banner() {
  const { colors, t } = useDesign();
  return (
    <View
      style={{
        backgroundColor: colors.highlightSoft,
        paddingVertical: 2,
        paddingHorizontal: 12,
      }}
    >
      <AppText variant="caption" maxFontSizeMultiplier={1.2} align="center" style={{ color: colors.highlightText }}>
        {t('previewBadge')}
      </AppText>
    </View>
  );
}

/** Wraps one preview screen: guard, theme + locale from the URL, frame, tabs. */
export function PreviewScreenShell({
  tab,
  top,
  action,
  children,
  revealEndKey,
}: {
  tab: TabKey | null;
  top: (helpers: { online: React.ReactNode }) => React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  revealEndKey?: string | number | null;
}) {
  const params = usePreviewParams();
  const go = usePreviewNav();
  if (!PREVIEW_ENABLED) return <Redirect href="/" />;
  const offline = params.state === 'offline' || params.state === 'pending' || params.state === 'failed';
  return (
    <DesignProvider theme={params.theme} locale={params.locale}>
      <WidthScope width={params.width}>
        {/* Keyed by the URL parameters: opening the same preview in another state starts from a fresh screen. */}
        <ScreenFrame
          key={JSON.stringify(params.raw)}
          maxWidth={params.width}
          banner={<Banner />}
          top={top({ online: <ConnectivityPill online={!offline} /> })}
          action={action}
          revealEndKey={revealEndKey}
          tabs={tab ? <TabBar current={tab} onSelect={(key) => go(TAB_TARGET[key])} /> : undefined}
        >
          {children}
        </ScreenFrame>
      </WidthScope>
    </DesignProvider>
  );
}
