/**
 * A simulated phone for integration tests.
 *
 *  storage   a temp directory of real SQLite files (survives `kill()` + `boot()`, like a force-quit)
 *  secure    an in-memory stand-in for SecureStore (also survives kill/boot)
 *  network   real HTTP to the local API and Auth, with switchable failure modes
 *
 * Everything above the adapters is the app's real code from src/core.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { ApiClient } from '../../src/core/api/client';
import type { FetchLike } from '../../src/core/api/http';
import { SupabaseAuthClient } from '../../src/core/auth/authClient';
import { ActiveSession, SessionManager, StoredSession, TokenStore } from '../../src/core/auth/session';
import { ContentStore } from '../../src/core/db/contentStore';
import type { Environment } from '../../src/core/learning/actions';
import { SyncEngine, SyncEngineOptions } from '../../src/core/sync/engine';
import { FaultPlan, nodeDatabases } from './nodeSqlite';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { API_PORT, readRootEnv, resetLearningState } = require('./localStack') as {
  API_PORT: number;
  readRootEnv: () => Record<string, string>;
  resetLearningState: () => unknown;
};

const env = readRootEnv();
export const API_URL = `http://127.0.0.1:${API_PORT}`;
export const SUPABASE_URL = env.LOCAL_SUPABASE_URL;
export const PUBLISHABLE_KEY = env.LOCAL_SUPABASE_PUBLISHABLE_KEY;

export const SEED = {
  lessonId: 'b0000000-0000-4000-8000-000000000005',
  revisionFr: 'c0000000-0000-4000-8000-000000000001',
  revisionHt: 'c0000000-0000-4000-8000-000000000002',
  correctFr: ['b', 'a', 'c', 'd', 'b'],
  accounts: {
    student_a: { id: 'a0000000-0000-4000-8000-000000000001', email: 'student.a@edupreneur.test' },
    student_b: { id: 'a0000000-0000-4000-8000-000000000002', email: 'student.b@edupreneur.test' },
  },
} as const;

export type AccountName = keyof typeof SEED.accounts;

const passwords = new Map<AccountName, string>();

/** Seed accounts have no password; set a random one through the LOCAL admin API (once per test file). */
export async function credentials(name: AccountName): Promise<{ email: string; password: string }> {
  const account = SEED.accounts[name];
  let password = passwords.get(name);
  if (!password) {
    password = crypto.randomBytes(24).toString('base64url');
    const response = await fetch(`${SUPABASE_URL}/auth/v1/admin/users/${account.id}`, {
      method: 'PUT',
      headers: {
        apikey: env.LOCAL_SUPABASE_SECRET_KEY,
        Authorization: `Bearer ${env.LOCAL_SUPABASE_SECRET_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ password }),
    });
    if (!response.ok) throw new Error(`could not set a test password: HTTP ${response.status}`);
    passwords.set(name, password);
  }
  return { email: account.email, password };
}

/** Empty the server's learning tables in the LOCAL database so every test starts clean. */
export function resetServerLearningState(): void {
  // The target container is derived from THIS checkout's supabase/config.toml; it throws rather than
  // touch any other stack (see tests/support/localStack.js).
  resetLearningState();
}

export type NetworkMode =
  | 'online'
  | 'offline' //            airplane mode: nothing leaves the phone
  | 'lose_response' //      the request reaches the server, the reply never arrives
  | 'truncate_response'; // the reply is cut off mid-body (interrupted download)

export class Network {
  mode: NetworkMode = 'online';
  /** Only apply `mode` to URLs containing this text (others stay online). */
  only: string | null = null;
  readonly calls: { method: string; url: string }[] = [];
  /** Runs after the real response is received and before it is handed to the app. */
  afterResponse: ((url: string) => Promise<void> | void) | null = null;
  /** Rewrite a JSON response body (to simulate a server returning something different). */
  rewrite: ((url: string, body: unknown) => unknown) | null = null;

  count(fragment: string): number {
    return this.calls.filter((call) => call.url.includes(fragment)).length;
  }

  readonly fetch: FetchLike = async (url, init) => {
    const mode = this.only === null || url.includes(this.only) ? this.mode : 'online';
    this.calls.push({ method: init?.method ?? 'GET', url });
    if (mode === 'offline') throw new TypeError('Network request failed');
    const response = await fetch(url, init);
    const text = await response.text();
    await this.afterResponse?.(url);
    if (mode === 'lose_response') throw new TypeError('Network request failed');
    if (mode === 'truncate_response') {
      return new Response(text.slice(0, Math.floor(text.length / 2)), { status: response.status });
    }
    if (this.rewrite && text) {
      return new Response(JSON.stringify(this.rewrite(url, JSON.parse(text))), { status: response.status });
    }
    return new Response(text, { status: response.status });
  };
}

class MemorySecureStore implements TokenStore {
  value: StoredSession | null = null;
  async load(): Promise<StoredSession | null> {
    return this.value ? { ...this.value } : null;
  }
  async save(session: StoredSession): Promise<void> {
    this.value = { ...session };
  }
  async clear(): Promise<void> {
    this.value = null;
  }
}

export interface RunningApp {
  sessions: SessionManager;
  content: ContentStore;
  session: ActiveSession | null;
}

let idCounter = 0;

export class Device {
  readonly storageDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edu-device-'));
  readonly secure = new MemorySecureStore();
  readonly network = new Network();
  readonly sleeps: number[] = [];
  faults: FaultPlan | null = null;
  apiUrl = API_URL;
  private running: RunningApp | null = null;

  readonly env: Environment = {
    newId: () => crypto.randomUUID(),
    now: () => new Date(Date.now() + (idCounter += 1)), // strictly increasing timestamps
  };

  /** Cold start of the app: open storage, restore the session from secure storage. No network. */
  async boot(): Promise<RunningApp> {
    if (this.running) throw new Error('already running');
    const openDatabase = nodeDatabases(this.storageDir, this.faults);
    const sessions = new SessionManager({
      auth: new SupabaseAuthClient({
        supabaseUrl: SUPABASE_URL,
        publishableKey: PUBLISHABLE_KEY,
        fetchImpl: this.network.fetch,
      }),
      tokens: this.secure,
      openDatabase,
    });
    const content = await ContentStore.open(await openDatabase('content'));
    const session = await sessions.restore();
    this.running = { sessions, content, session };
    return this.running;
  }

  /** Force-quit: the process disappears. Nothing is flushed or "saved on exit". */
  async kill(): Promise<void> {
    const app = this.running;
    this.running = null;
    if (!app) return;
    await app.content.close().catch(() => undefined);
    await app.sessions.session?.account.close().catch(() => undefined);
  }

  api(sessions: SessionManager, session: ActiveSession): ApiClient {
    return new ApiClient({
      baseUrl: this.apiUrl,
      fetchImpl: this.network.fetch,
      sessionSignal: session.signal,
      timeoutMs: 5_000,
      getAccessToken: (options) => sessions.accessToken(session, options),
    });
  }

  engine(sessions: SessionManager, session: ActiveSession, overrides: Partial<SyncEngineOptions> = {}): SyncEngine {
    return new SyncEngine({
      account: session.account,
      api: this.api(sessions, session),
      isActive: () => session.isActive(),
      sleep: async (ms) => {
        this.sleeps.push(ms); // recorded, not waited: keeps the tests fast and the delays assertable
      },
      ...overrides,
    });
  }

  async dispose(): Promise<void> {
    await this.kill();
    fs.rmSync(this.storageDir, { recursive: true, force: true });
  }
}

/** Server truth for an account, read through the API with a fresh sign-in (independent of the device under test). */
export async function serverFeed(name: AccountName): Promise<{ op_id: string; entity_type: string; version: number }[]> {
  const { email, password } = await credentials(name);
  const auth = new SupabaseAuthClient({ supabaseUrl: SUPABASE_URL, publishableKey: PUBLISHABLE_KEY });
  const tokens = await auth.signInWithPassword(email, password);
  const api = new ApiClient({ baseUrl: API_URL, getAccessToken: async () => tokens.accessToken });
  const out: { op_id: string; entity_type: string; version: number }[] = [];
  let cursor: string | null = null;
  for (;;) {
    const page = await api.pull(cursor, 200);
    for (const change of page.changes) {
      out.push({
        op_id: String((change.data as { op_id?: unknown }).op_id),
        entity_type: change.entity_type,
        version: change.version,
      });
    }
    cursor = page.next_cursor;
    if (!page.has_more) return out;
  }
}
