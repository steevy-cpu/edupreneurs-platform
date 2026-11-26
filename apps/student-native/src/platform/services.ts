import * as Crypto from 'expo-crypto';

import { ApiClient } from '../core/api/client';
import { SupabaseAuthClient } from '../core/auth/authClient';
import { ActiveSession, SessionManager } from '../core/auth/session';
import { ContentStore } from '../core/db/contentStore';
import type { Environment } from '../core/learning/actions';
import { SessionLessonCache } from '../core/learning/contentAccess';
import { SyncEngine, SyncPhase } from '../core/sync/engine';
import { loadConfig } from './config';
import { openExpoDatabase } from './expoSqlite';
import { secureTokenStore } from './secureTokenStore';

export interface Services {
  sessions: SessionManager;
  content: ContentStore;
  env: Environment;
  /** Lessons read online during this run. Memory only; not a download. */
  lessonCache: SessionLessonCache;
  apiFor(session: ActiveSession): ApiClient;
  engineFor(session: ActiveSession, onPhase: (phase: SyncPhase) => void): SyncEngine;
}

/** Wires the platform adapters into the core. Called once at app start. */
export async function createServices(onReachability: (reachable: boolean) => void): Promise<Services> {
  const config = loadConfig();
  const sessions = new SessionManager({
    auth: new SupabaseAuthClient({
      supabaseUrl: config.supabaseUrl,
      publishableKey: config.supabasePublishableKey,
    }),
    tokens: secureTokenStore,
    openDatabase: openExpoDatabase,
  });
  const content = await ContentStore.open(await openExpoDatabase('content'));
  const env: Environment = { newId: () => Crypto.randomUUID(), now: () => new Date() };

  const apiFor = (session: ActiveSession) =>
    new ApiClient({
      baseUrl: config.apiUrl,
      onReachability: (reachable) => { if (session.isActive()) onReachability(reachable); },
      sessionSignal: session.signal,
      getAccessToken: (options) => sessions.accessToken(session, options),
    });

  return {
    sessions,
    content,
    env,
    lessonCache: new SessionLessonCache(),
    apiFor,
    engineFor: (session, onPhase) =>
      new SyncEngine({
        account: session.account,
        api: apiFor(session),
        isActive: () => session.isActive(),
        onPhase,
      }),
  };
}
