import { ApiError } from '../api/errors';
import { AccountStore } from '../db/accountStore';
import type { OpenDatabase } from '../db/driver';
import { AuthClient, AuthRefusedError, AuthTokens } from './authClient';

/**
 * What is kept in the device's secure storage (Keychain / Keystore) — and
 * nowhere else. `accessToken`/`refreshToken` are null once the Auth server has
 * refused to refresh the session (`needsReauth`).
 */
export interface StoredSession {
  userId: string;
  email: string;
  accessToken: string | null;
  refreshToken: string | null;
  expiresAt: number;
  needsReauth: boolean;
}

export interface TokenStore {
  load(): Promise<StoredSession | null>;
  save(session: StoredSession): Promise<void>;
  clear(): Promise<void>;
}

/** A signed-in account on this device, with its private database open. */
export interface ActiveSession {
  readonly userId: string;
  readonly email: string;
  readonly account: AccountStore;
  /** Aborted at sign-out: cancels this session's in-flight requests. */
  readonly signal: AbortSignal;
  /** False as soon as the user signs out or another account takes over. */
  isActive(): boolean;
  needsReauth(): boolean;
}

interface InternalSession extends ActiveSession {
  controller: AbortController;
  stored: StoredSession;
  refreshing: Promise<string> | null;
}

export class WrongAccountError extends Error {
  constructor() {
    super('another account is signed in on this device');
    this.name = 'WrongAccountError';
  }
}

const REFRESH_MARGIN_SECONDS = 60;

/**
 * Owns "who is signed in on this phone".
 *
 * Guarantees:
 *  - only ONE account is active at a time, and only that account's database is open;
 *  - signing out clears the credentials, cancels in-flight requests and closes
 *    the account database, so a late response has nothing to write into;
 *  - the app can restart OFFLINE and keep working: restoring a session needs no network;
 *  - a refused token refresh never deletes local work — it only flags `needsReauth`.
 */
export class SessionManager {
  private current: InternalSession | null = null;

  constructor(
    private readonly deps: {
      auth: AuthClient;
      tokens: TokenStore;
      openDatabase: OpenDatabase;
      now?: () => number;
    },
  ) {}

  get session(): ActiveSession | null {
    return this.current;
  }

  /** App start: reopen the last session from secure storage. No network involved. */
  async restore(): Promise<ActiveSession | null> {
    if (this.current) return this.current;
    const stored = await this.deps.tokens.load();
    if (!stored) return null;
    return this.activate(stored);
  }

  /**
   * Sign in with email + password.
   * If a session is already active it must be the same account (re-authentication
   * after an expired session); otherwise the caller has to sign out first.
   */
  async signIn(email: string, password: string): Promise<ActiveSession> {
    const tokens = await this.deps.auth.signInWithPassword(email, password);
    const stored = toStored(tokens);
    if (this.current) {
      if (this.current.userId !== tokens.userId) {
        // Do not keep the other account's fresh tokens around.
        void this.deps.auth.signOut(tokens.accessToken);
        throw new WrongAccountError();
      }
      await this.deps.tokens.save(stored);
      this.current.stored = stored;
      return this.current;
    }
    await this.deps.tokens.save(stored);
    try {
      return await this.activate(stored);
    } catch (error) {
      await this.deps.tokens.clear();
      throw error;
    }
  }

  /**
   * End the session on this device. Local learning data stays in the account's
   * own database file (it can only be opened again by signing in as that account).
   */
  async signOut(): Promise<void> {
    const session = this.current;
    if (!session) {
      await this.deps.tokens.clear();
      return;
    }
    this.current = null; // from here on `isActive()` is false for every holder of the session
    session.controller.abort();
    const accessToken = session.stored.accessToken;
    await this.deps.tokens.clear();
    try {
      await session.account.close();
    } finally {
      if (accessToken) void this.deps.auth.signOut(accessToken);
    }
  }

  /**
   * A valid access token for `session`, refreshing it when it is about to
   * expire (or when the API has just answered 401: `forceRefresh`).
   */
  async accessToken(session: ActiveSession, options?: { forceRefresh?: boolean }): Promise<string> {
    const internal = this.current;
    if (!internal || internal !== session) throw new ApiError('aborted', 'session_ended');
    if (internal.stored.needsReauth || !internal.stored.refreshToken) {
      throw new ApiError('auth_required', 'session_expired');
    }
    const nowSeconds = Math.floor((this.deps.now?.() ?? Date.now()) / 1000);
    const fresh = internal.stored.expiresAt - nowSeconds > REFRESH_MARGIN_SECONDS;
    if (fresh && !options?.forceRefresh && internal.stored.accessToken) {
      return internal.stored.accessToken;
    }
    // Single flight: concurrent callers share one refresh (refresh tokens are single-use).
    internal.refreshing ??= this.refresh(internal).finally(() => {
      internal.refreshing = null;
    });
    return internal.refreshing;
  }

  private async refresh(internal: InternalSession): Promise<string> {
    const refreshToken = internal.stored.refreshToken;
    if (!refreshToken) throw new ApiError('auth_required', 'session_expired');
    let tokens: AuthTokens;
    try {
      tokens = await this.deps.auth.refresh(refreshToken);
    } catch (error) {
      if (error instanceof AuthRefusedError) {
        if (this.current === internal) {
          const expired: StoredSession = {
            ...internal.stored,
            accessToken: null,
            refreshToken: null,
            needsReauth: true,
          };
          internal.stored = expired;
          await this.deps.tokens.save(expired);
        }
        throw new ApiError('auth_required', 'session_expired');
      }
      throw error; // network / timeout / server: transient, the old tokens are kept
    }
    if (this.current !== internal) throw new ApiError('aborted', 'session_ended');
    if (tokens.userId !== internal.userId) throw new ApiError('auth_required', 'session_expired');
    const stored = toStored(tokens);
    await this.deps.tokens.save(stored); // persist the rotated refresh token BEFORE using the new access token
    internal.stored = stored;
    return tokens.accessToken;
  }

  private async activate(stored: StoredSession): Promise<InternalSession> {
    const database = await this.deps.openDatabase(`account-${stored.userId}`);
    const account = await AccountStore.open(database, stored.userId);
    const controller = new AbortController();
    const session: InternalSession = {
      userId: stored.userId,
      email: stored.email,
      account,
      controller,
      signal: controller.signal,
      stored,
      refreshing: null,
      isActive: () => this.current === session,
      needsReauth: () => session.stored.needsReauth,
    };
    this.current = session;
    return session;
  }
}

function toStored(tokens: AuthTokens): StoredSession {
  return {
    userId: tokens.userId,
    email: tokens.email,
    accessToken: tokens.accessToken,
    refreshToken: tokens.refreshToken,
    expiresAt: tokens.expiresAt,
    needsReauth: false,
  };
}
