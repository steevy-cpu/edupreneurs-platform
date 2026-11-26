import { useRouter } from 'expo-router';
import React from 'react';
import { Alert } from 'react-native';

import { ConnectivityPill, DesignProvider, ScreenFrame, TabBar, TabKey, TopBar } from '../design';
import { serviceUnreachable } from '../core/sync/engine';
import { useApp } from './AppContext';

const TAB_ROUTE: Record<TabKey, '/home' | '/learn' | '/review' | '/profile'> = {
  home: '/home',
  learn: '/learn',
  review: '/review',
  profile: '/profile',
};

/**
 * The app uses the light palette only. Dark colours exist in the design tokens
 * but are deliberately not switched on yet (Mobile-02 decision).
 */
export function Themed({ children }: { children: React.ReactNode }) {
  const { locale } = useApp();
  return (
    <DesignProvider theme="light" locale={locale}>
      {children}
    </DesignProvider>
  );
}

/** Current service reachability is independent of the account’s last sync receipt. */
export function OfflinePill() {
  const { sync } = useApp();
  return sync.phase === 'idle' && serviceUnreachable(sync) ? <ConnectivityPill online={false} /> : null;
}

/** One of the four main destinations: wordmark on top, tab bar at the bottom. */
export function TabScreen({ tab, children, action }: { tab: TabKey; children: React.ReactNode; action?: React.ReactNode }) {
  const router = useRouter();
  const routerRef = React.useRef(router);
  routerRef.current = router;
  // Stable handler so the memoised tab bar is not re-rendered by every screen update.
  const select = React.useCallback(
    (next: TabKey) => {
      if (next !== tab) routerRef.current.replace(TAB_ROUTE[next]);
    },
    [tab],
  );
  return (
    <ScreenFrame top={<TopBar trailing={<OfflinePill />} />} action={action} tabs={<TabBar current={tab} onSelect={select} />}>
      {children}
    </ScreenFrame>
  );
}

/** A full-screen step reached from a tab (lesson, exercises): back button, no tab bar. */
export function DetailScreen({
  title,
  children,
  action,
  revealEndKey,
  fallback = '/learn',
}: {
  title?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
  revealEndKey?: string | number | null;
  /** Where "back" goes when there is no previous screen (e.g. opened from a link). */
  fallback?: '/home' | '/learn' | '/review' | '/profile';
}) {
  const router = useRouter();
  const back = () => (router.canGoBack() ? router.back() : router.replace(fallback));
  return (
    <ScreenFrame top={<TopBar title={title} onBack={back} trailing={<OfflinePill />} />} action={action} revealEndKey={revealEndKey}>
      {children}
    </ScreenFrame>
  );
}

/**
 * Sign-out with the unsynchronised-work warning (unchanged behaviour from Release-01).
 *
 * Signing out never deletes work. With unsynced operations the student is told
 * exactly what will happen and can sync first; "keep" leaves the operations in
 * this account's own database until the same account signs in again.
 */
export function useSignOut(): { leaving: boolean; confirmSignOut: () => Promise<void> } {
  const { t, session, signOut, syncNow } = useApp();
  const [leaving, setLeaving] = React.useState(false);

  const leave = async () => {
    setLeaving(true);
    try {
      await signOut();
    } finally {
      setLeaving(false);
    }
  };

  const confirmSignOut = async () => {
    if (!session) return;
    const summary = await session.account.syncSummary();
    if (summary.pending === 0) {
      await leave();
      return;
    }
    Alert.alert(t('signOutTitle'), t('signOutBody', { count: summary.pending }), [
      { text: t('cancel'), style: 'cancel' },
      {
        text: t('signOutSyncFirst'),
        onPress: () => {
          void (async () => {
            const report = await syncNow();
            const after = await session.account.syncSummary();
            if (report?.outcome === 'ok' && after.pending === 0) await leave();
            else Alert.alert(t('signOutTitle'), t('signOutSyncFailed'));
          })();
        },
      },
      { text: t('signOutKeep'), style: 'destructive', onPress: () => void leave() },
    ]);
  };

  return { leaving, confirmSignOut };
}
