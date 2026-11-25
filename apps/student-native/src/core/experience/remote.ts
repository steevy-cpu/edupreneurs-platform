/**
 * Thin, typed adapter for the endpoints the experience features talk to.
 *
 * These endpoints are being built by other lanes and are NOT in the generated
 * OpenAPI types yet (`schema.d.ts` is generated, never hand-edited). Until they
 * are, the shapes this file ASSUMES are written here, in one place, and every
 * response is validated before anything is stored or shown. When the contract
 * lands: regenerate the types, replace the interfaces below with the generated
 * ones, and keep the validators.
 *
 * Nothing in this file is called unless its client flag is on (flags.ts).
 */
import { ApiError } from '../api/errors';
import { FetchLike, requestJson } from '../api/http';
import type { Locale } from '../api/types';
import type { ServerOnboardingState } from './store';

// ---------------------------------------------------------------- assumed shapes
/** `GET` and `PUT /v1/me/onboarding` (briefs/identity.md, slice 2). */
export interface RemoteOnboarding {
  state: ServerOnboardingState;
  onboarding_version: number;
  tour_version_seen: number;
  tour_dismissed: boolean;
}

/** `PATCH /v1/me` body (briefs/identity.md, slice 1). Only the fields this app edits. */
export interface ProfilePatch {
  grade_code?: string;
  preferred_locale?: Locale;
}

export interface ExperienceRemote {
  getOnboarding(): Promise<RemoteOnboarding>;
  putOnboarding(body: RemoteOnboarding): Promise<RemoteOnboarding>;
  patchProfile(body: ProfilePatch): Promise<void>;
}

// -------------------------------------------------------------------- validators
function invalid(): never {
  // Same classification as an unparseable body in http.ts: do not store it, try again later.
  throw new ApiError('network', 'invalid_response');
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function wholeNumber(value: unknown): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : invalid();
}

const STATES: ServerOnboardingState[] = ['new', 'profile_selected', 'downloads_informed', 'ready'];

export function parseRemoteOnboarding(body: unknown): RemoteOnboarding {
  if (!isObject(body)) return invalid();
  const state = STATES.find((known) => known === body.state);
  if (!state) return invalid();
  return {
    state,
    onboarding_version: wholeNumber(body.onboarding_version ?? 0),
    tour_version_seen: wholeNumber(body.tour_version_seen ?? 0),
    tour_dismissed: body.tour_dismissed === true,
  };
}

// ------------------------------------------------------------------------ client
export interface ExperienceApiOptions {
  baseUrl: string;
  /** Returns a usable access token; `forceRefresh` is set after the API answered 401. */
  getAccessToken: (options?: { forceRefresh?: boolean }) => Promise<string>;
  fetchImpl?: FetchLike;
  timeoutMs?: number;
  /** Aborted when the session ends (sign-out / account switch). */
  sessionSignal?: AbortSignal;
}

export interface RawResponse {
  status: number;
  body: unknown;
  etag: string | null;
}

/**
 * Same transport rules as `ApiClient` (bearer token, one retry after a 401,
 * timeout, cancellation at sign-out, one error model) for requests `ApiClient`
 * does not offer: other verbs, and conditional GETs that need the ETag header.
 */
export class ExperienceApi implements ExperienceRemote {
  private readonly baseUrl: string;
  private readonly fetchImpl: FetchLike;
  private readonly timeoutMs: number;

  constructor(private readonly options: ExperienceApiOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.fetchImpl = options.fetchImpl ?? ((input, init) => fetch(input, init));
    this.timeoutMs = options.timeoutMs ?? 15_000;
  }

  async getOnboarding(): Promise<RemoteOnboarding> {
    return parseRemoteOnboarding(this.ok(await this.send('GET', '/v1/me/onboarding')).body);
  }

  async putOnboarding(body: RemoteOnboarding): Promise<RemoteOnboarding> {
    return parseRemoteOnboarding(this.ok(await this.send('PUT', '/v1/me/onboarding', { json: body })).body);
  }

  async patchProfile(body: ProfilePatch): Promise<void> {
    this.ok(await this.send('PATCH', '/v1/me', { json: body }));
  }

  /** Throws the app's usual error for a non-2xx answer. */
  protected ok(response: RawResponse): RawResponse {
    if (response.status >= 200 && response.status < 300) return response;
    throw toApiError(response);
  }

  protected async send(
    method: 'GET' | 'PUT' | 'PATCH',
    path: string,
    extra: { json?: unknown; headers?: Record<string, string> } = {},
  ): Promise<RawResponse> {
    let forceRefresh = false;
    for (;;) {
      const token = await this.options.getAccessToken({ forceRefresh });
      const headers: Record<string, string> = { Accept: 'application/json', Authorization: `Bearer ${token}`, ...extra.headers };
      if (extra.json !== undefined) headers['Content-Type'] = 'application/json';
      let etag: string | null = null;
      // `requestJson` owns timeout, cancellation and error mapping; the wrapper only notes the ETag on the way through.
      const noteEtag: FetchLike = async (input, init) => {
        const response = await this.fetchImpl(input, init);
        etag = response.headers.get('etag');
        return response;
      };
      const { status, body } = await requestJson(
        noteEtag,
        this.baseUrl + path,
        { method, headers, body: extra.json === undefined ? undefined : JSON.stringify(extra.json) },
        { timeoutMs: this.timeoutMs, sessionSignal: this.options.sessionSignal },
      );
      if (status === 401 && !forceRefresh) {
        forceRefresh = true; // the token may simply have expired between our check and the server's
        continue;
      }
      return { status, body, etag };
    }
  }
}

export function readErrorCode(body: unknown): string | null {
  if (isObject(body) && isObject(body.error) && typeof body.error.code === 'string') return body.error.code;
  return null;
}

function toApiError(response: RawResponse): ApiError {
  const code = readErrorCode(response.body);
  if (response.status === 401) return new ApiError('auth_required', code ?? 'unauthenticated', response.status);
  if (response.status >= 500) return new ApiError('server', code ?? 'server_error', response.status);
  return new ApiError('client', code ?? 'request_failed', response.status);
}
