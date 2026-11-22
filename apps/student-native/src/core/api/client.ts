import { ApiError } from './errors';
import { FetchLike, requestJson } from './http';
import type {
  CatalogResponse,
  LessonResponse,
  Locale,
  MeResponse,
  PullResponse,
  PushResponse,
  SyncOperation,
} from './types';

export interface ApiClientOptions {
  baseUrl: string;
  /** Returns a usable access token; `forceRefresh` is set after the API answered 401. */
  getAccessToken: (options?: { forceRefresh?: boolean }) => Promise<string>;
  fetchImpl?: FetchLike;
  timeoutMs?: number;
  /** Aborted when the session ends (sign-out / account switch). */
  sessionSignal?: AbortSignal;
}

/**
 * Typed client for the Mon Edupreneur API (docs/API_CONTRACT.md).
 *
 * The learner's identity is never sent: the server takes it from the token.
 */
export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: FetchLike;
  private readonly timeoutMs: number;

  constructor(private readonly options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.fetchImpl = options.fetchImpl ?? ((input, init) => fetch(input, init));
    this.timeoutMs = options.timeoutMs ?? 15_000;
  }

  getMe(): Promise<MeResponse> {
    return this.request<MeResponse>('GET', '/v1/me');
  }

  getCatalog(locale: Locale): Promise<CatalogResponse> {
    return this.request<CatalogResponse>('GET', `/v1/catalog?locale=${locale}`);
  }

  getLesson(lessonId: string, locale: Locale): Promise<LessonResponse> {
    return this.request<LessonResponse>(
      'GET',
      `/v1/lessons/${encodeURIComponent(lessonId)}?locale=${locale}`,
    );
  }

  push(ops: SyncOperation[]): Promise<PushResponse> {
    return this.request<PushResponse>('POST', '/v1/sync/push', { ops });
  }

  pull(cursor: string | null, limit?: number): Promise<PullResponse> {
    const params: string[] = [];
    if (cursor) params.push(`cursor=${encodeURIComponent(cursor)}`);
    if (limit) params.push(`limit=${limit}`);
    return this.request<PullResponse>(
      'GET',
      `/v1/sync/pull${params.length ? `?${params.join('&')}` : ''}`,
    );
  }

  private async request<T>(method: 'GET' | 'POST', path: string, json?: unknown): Promise<T> {
    let forceRefresh = false;
    for (;;) {
      const token = await this.options.getAccessToken({ forceRefresh });
      const headers: Record<string, string> = {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
      };
      if (json !== undefined) headers['Content-Type'] = 'application/json';
      const { status, body } = await requestJson(
        this.fetchImpl,
        this.baseUrl + path,
        { method, headers, body: json === undefined ? undefined : JSON.stringify(json) },
        { timeoutMs: this.timeoutMs, sessionSignal: this.options.sessionSignal },
      );
      if (status >= 200 && status < 300) return body as T;

      const code = readErrorCode(body);
      if (status === 401 && !forceRefresh) {
        // The token may simply have expired between our check and the server's.
        forceRefresh = true;
        continue;
      }
      if (status === 401) throw new ApiError('auth_required', code ?? 'unauthenticated', status);
      if (status >= 500) throw new ApiError('server', code ?? 'server_error', status);
      throw new ApiError('client', code ?? 'request_failed', status);
    }
  }
}

function readErrorCode(body: unknown): string | null {
  if (body && typeof body === 'object' && 'error' in body) {
    const error = (body as { error?: { code?: unknown } }).error;
    if (error && typeof error.code === 'string') return error.code;
  }
  return null;
}
