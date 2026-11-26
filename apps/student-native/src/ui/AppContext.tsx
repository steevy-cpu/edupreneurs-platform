import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AppState } from 'react-native';

import type { ApiClient } from '../core/api/client';
import type { Locale } from '../core/api/types';
import type { ActiveSession } from '../core/auth/session';
import type { SyncSummary } from '../core/db/accountStore';
import { Translate, translator } from '../core/i18n/strings';
import type { SyncEngine, SyncPhase, SyncReport } from '../core/sync/engine';
import { createServices, Services } from '../platform/services';

export interface SyncStatus {
  serviceReachable: boolean | null;
  phase: SyncPhase;
  summary: SyncSummary;
  lastReport: SyncReport | null;
}

interface AppState_ {
  boot: 'starting' | 'ready' | 'failed';
  bootError: string | null;
  services: Services | null;
  session: ActiveSession | null;
  /** True when the session can no longer be refreshed and the student must sign in again. */
  needsReauth: boolean;
  locale: Locale;
  t: Translate;
  sync: SyncStatus;
  api: ApiClient | null;
  setLocale(locale: Locale): Promise<void>;
  signIn(email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
  /** Start (or join) a sync run. Never throws. */
  syncNow(): Promise<SyncReport | null>;
  /** Re-read the pending / needs-attention counters from SQLite. */
  refreshSummary(): Promise<void>;
}

const EMPTY_SUMMARY: SyncSummary = { pending: 0, needsAttention: 0, lastSyncAt: null };
const AppContext = createContext<AppState_ | null>(null);

export function useApp(): AppState_ {
  const value = useContext(AppContext);
  if (!value) throw new Error('useApp must be used inside <AppProvider>');
  return value;
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [boot, setBoot] = useState<AppState_['boot']>('starting');
  const [bootError, setBootError] = useState<string | null>(null);
  const [services, setServices] = useState<Services | null>(null);
  const [session, setSession] = useState<ActiveSession | null>(null);
  const [needsReauth, setNeedsReauth] = useState(false);
  const [locale, setLocaleState] = useState<Locale>('fr');
  const [serviceReachable, setServiceReachable] = useState<boolean | null>(null);
  const [phase, setPhase] = useState<SyncPhase>('idle');
  const [summary, setSummary] = useState<SyncSummary>(EMPTY_SUMMARY);
  const [lastReport, setLastReport] = useState<SyncReport | null>(null);
  const engineRef = useRef<{ session: ActiveSession; engine: SyncEngine } | null>(null);

  // --- start-up: open storage and restore the session. No network is needed. ---
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const created = await createServices(setServiceReachable);
        const restored = await created.sessions.restore();
        if (cancelled) return;
        setServices(created);
        if (restored) await adopt(restored);
        setBoot('ready');
      } catch (error) {
        if (cancelled) return;
        setBootError(error instanceof Error ? error.message : String(error));
        setBoot('failed');
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const adopt = useCallback(async (active: ActiveSession) => {
    const savedLocale = await active.account.getPreference('locale');
    if (savedLocale === 'fr' || savedLocale === 'ht') setLocaleState(savedLocale);
    setSummary(await active.account.syncSummary());
    setNeedsReauth(active.needsReauth());
    setLastReport(null);
    setServiceReachable(null);
    setSession(active);
  }, []);

  const refreshSummary = useCallback(async () => {
    if (!session || !session.isActive()) return;
    try {
      const next = await session.account.syncSummary();
      if (session.isActive()) setSummary(next);
    } catch {
      // the session ended while we were reading: nothing to show
    }
  }, [session]);

  const syncNow = useCallback(async (): Promise<SyncReport | null> => {
    if (!services || !session || !session.isActive()) return null;
    if (engineRef.current?.session !== session) {
      engineRef.current = {
        session,
        engine: services.engineFor(session, (next) => {
          if (session.isActive()) setPhase(next);
        }),
      };
    }
    const report = await engineRef.current.engine.run();
    if (!session.isActive()) return report; // account switched meanwhile: show nothing of the old one
    setLastReport(report);
    setNeedsReauth(session.needsReauth());
    await refreshSummary();
    return report;
  }, [services, session, refreshSummary]);

  // Sync when a session becomes active and whenever the app returns to the foreground.
  // There is deliberately no timer: nothing polls in the background.
  useEffect(() => {
    if (!session) return;
    void syncNow();
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') void syncNow();
    });
    return () => subscription.remove();
  }, [session, syncNow]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      if (!services) throw new Error('not ready');
      await adopt(await services.sessions.signIn(email, password));
    },
    [services, adopt],
  );

  const signOut = useCallback(async () => {
    if (!services) return;
    engineRef.current = null;
    services.lessonCache.clear();
    setSession(null);
    setNeedsReauth(false);
    setSummary(EMPTY_SUMMARY);
    setLastReport(null);
    setServiceReachable(null);
    setPhase('idle');
    await services.sessions.signOut();
  }, [services]);

  const setLocale = useCallback(
    async (next: Locale) => {
      setLocaleState(next);
      if (session?.isActive()) await session.account.setPreference('locale', next);
    },
    [session],
  );

  const api = useMemo(
    () => (services && session ? services.apiFor(session) : null),
    [services, session],
  );
  const t = useMemo(() => translator(locale), [locale]);

  const value: AppState_ = {
    boot,
    bootError,
    services,
    session,
    needsReauth,
    locale,
    t,
    sync: { phase, summary, lastReport, serviceReachable },
    api,
    setLocale,
    signIn,
    signOut,
    syncNow,
    refreshSummary,
  };
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
