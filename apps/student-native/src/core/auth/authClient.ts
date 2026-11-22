import { ApiError } from '../api/errors';
import { FetchLike, requestJson } from '../api/http';

export interface AuthTokens {
  userId: string;
  email: string;
  accessToken: string;
  refreshToken: string;
  /** Seconds since the Unix epoch at which the access token expires. */
  expiresAt: number;
}

/** Sign-in or refresh was REFUSED by the Auth server (as opposed to unreachable). */
export class AuthRefusedError extends Error {
  constructor(readonly code: string) {
    super(`auth refused: ${code}`);
    this.name = 'AuthRefusedError';
  }
}

export interface AuthClient {
  signInWithPassword(email: string, password: string): Promise<AuthTokens>;
  refresh(refreshToken: string): Promise<AuthTokens>;
  /** Best effort: revokes the session on the server. Never throws. */
  signOut(accessToken: string): Promise<void>;
}

/**
 * Minimal client for Supabase Auth's REST API (sign in, refresh, sign out).
 *
 * The app deliberately does not ship the full Supabase SDK: these three calls
 * are all it needs, and every extra megabyte costs on a low-end phone.
 * The publishable key is not a secret; it only identifies the project.
 */
export class SupabaseAuthClient implements AuthClient {
  private readonly base: string;
  private readonly fetchImpl: FetchLike;

  constructor(
    private readonly options: {
      supabaseUrl: string;
      publishableKey: string;
      fetchImpl?: FetchLike;
      timeoutMs?: number;
      now?: () => number;
    },
  ) {
    this.base = `${options.supabaseUrl.replace(/\/+$/, '')}/auth/v1`;
    this.fetchImpl = options.fetchImpl ?? ((input, init) => fetch(input, init));
  }

  signInWithPassword(email: string, password: string): Promise<AuthTokens> {
    return this.token('password', { email: email.trim().toLowerCase(), password });
  }

  refresh(refreshToken: string): Promise<AuthTokens> {
    return this.token('refresh_token', { refresh_token: refreshToken });
  }

  async signOut(accessToken: string): Promise<void> {
    try {
      await requestJson(
        this.fetchImpl,
        `${this.base}/logout?scope=local`,
        {
          method: 'POST',
          headers: { apikey: this.options.publishableKey, Authorization: `Bearer ${accessToken}` },
        },
        { timeoutMs: 5_000 },
      );
    } catch {
      // Offline sign-out is fine: local credentials are cleared regardless.
    }
  }

  private async token(grantType: string, payload: Record<string, string>): Promise<AuthTokens> {
    const { status, body } = await requestJson(
      this.fetchImpl,
      `${this.base}/token?grant_type=${grantType}`,
      {
        method: 'POST',
        headers: { apikey: this.options.publishableKey, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
      { timeoutMs: this.options.timeoutMs ?? 15_000 },
    );
    const data = (body ?? {}) as Record<string, unknown>;
    if (status >= 500 || status === 429) {
      throw new ApiError('server', 'auth_unavailable', status);
    }
    if (status < 200 || status >= 300) {
      const code = typeof data.error_code === 'string' ? data.error_code : 'refused';
      throw new AuthRefusedError(code);
    }
    const user = data.user as { id?: unknown; email?: unknown } | undefined;
    if (
      typeof data.access_token !== 'string' ||
      typeof data.refresh_token !== 'string' ||
      !user ||
      typeof user.id !== 'string'
    ) {
      throw new ApiError('network', 'invalid_response', status);
    }
    const nowSeconds = Math.floor((this.options.now?.() ?? Date.now()) / 1000);
    const expiresAt =
      typeof data.expires_at === 'number'
        ? data.expires_at
        : nowSeconds + (typeof data.expires_in === 'number' ? data.expires_in : 3600);
    return {
      userId: user.id.toLowerCase(),
      email: typeof user.email === 'string' ? user.email : '',
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      expiresAt,
    };
  }
}
