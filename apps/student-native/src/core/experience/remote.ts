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
/** Response of `GET` and `PUT /v1/me/onboarding` (briefs/identity.md, slice 2). Extra fields are ignored. */
export interface RemoteOnboarding {
  state: ServerOnboardingState;
  onboarding_version: number;
  tour_version_seen: number;
  tour_dismissed: boolean;
}

/**
 * Body of `PUT /v1/me/onboarding`. The identity lane validates it strictly
 * (unknown fields are refused, `onboarding_version` must be at least 1), so
 * exactly these fields are sent and nothing else. `state` is left out when only
 * the tour flags are being reported.
 */
export interface RemoteOnboardingUpdate {
  state?: ServerOnboardingState;
  /** Version of the onboarding flow built into this app (>= 1). */
  onboarding_version: number;
  tour_version_seen?: number;
  tour_dismissed?: boolean;
}

/** `PATCH /v1/me` body (briefs/identity.md, slice 1). Only the fields this app edits. */
export interface ProfilePatch {
  grade_code?: string;
  preferred_locale?: Locale;
}

/**
 * `GET /v1/daily-word?locale=fr|ht` (briefs/vocab.md). The word fields are read
 * from a nested `word` object; if the backend ends up sending them at the top
 * level instead, they are read from there (see `parseRemoteDailyWord`).
 */
export interface RemoteDailyWord {
  haiti_date: string;
  /** Language of the content actually served. */
  locale: Locale;
  requested_locale: Locale;
  /** True when the requested language has no translation and French is served instead. */
  is_fallback_locale: boolean;
  /** Instant of the next Haiti midnight (ISO 8601). */
  valid_until: string;
  word: {
    word_id: string | null;
    revision_id: string | null;
    term: string;
    pronunciation: string | null;
    /** A language-neutral code from the server (`noun`, `verb`, …); the app shows its own label for the codes it knows. */
    part_of_speech: string | null;
    definition: string;
    example: string | null;
    gloss: string | null;
  };
  /** Metadata only; null when the word has no recording. Nothing is ever downloaded or played from it here. */
  audio: { mime: string | null; bytes: number | null; duration_ms: number | null } | null;
}

/**
 * `GET /v1/rewards/summary` (briefs/rewards.md). Only what this app displays is
 * kept. Every number comes from the server's ledger; the app sends none.
 */
export interface RemoteRewardsSummary {
  /** Confirmed Gold: the sum of the server's ledger for this learner. */
  balance: number;
  /** Days with accepted learning, by the server's Haiti calendar. Null when the server sent no streak. */
  streak: { current: number; longest: number } | null;
  /** The server's Haiti calendar date when it wrote this summary (`YYYY-MM-DD`), or null. The streak is true AS OF this day. */
  today: string | null;
  /** How many achievements the server has awarded. */
  achievements: number;
  /** False while the server still has accepted work to examine: the balance may be about to change. */
  up_to_date: boolean;
  /** `provisional` while the reward amounts are placeholders awaiting the product owner's decision. */
  rules_status: 'provisional' | null;
}

/** `serverDate` is the response's `Date` header (the server's clock), or null when it was not readable. */
export type DailyWordFetch =
  | { kind: 'word'; word: RemoteDailyWord; etag: string | null; serverDate: string | null }
  | { kind: 'not_modified'; serverDate: string | null };

/** The two fields of `GET /v1/me` (an existing, generated contract) that onboarding can prefill from. */
export interface RemoteProfile {
  grade_code: string | null;
  preferred_locale: Locale | null;
}

export function parseRemoteProfile(body: unknown): RemoteProfile {
  if (!isObject(body)) return invalid();
  const code = isObject(body.grade) && typeof body.grade.code === 'string' && /^[A-Z0-9]{2,8}$/.test(body.grade.code) ? body.grade.code : null;
  return { grade_code: code, preferred_locale: body.preferred_locale === 'fr' || body.preferred_locale === 'ht' ? body.preferred_locale : null };
}

export interface ExperienceRemote {
  /** The learner's server profile (`GET /v1/me`). */
  getProfile(): Promise<RemoteProfile>;
  getOnboarding(): Promise<RemoteOnboarding>;
  putOnboarding(body: RemoteOnboardingUpdate): Promise<RemoteOnboarding>;
  patchProfile(body: ProfilePatch): Promise<void>;
  /**
   * Today's word. `etag` (from an earlier answer) makes the request conditional.
   * Throws `ApiError` kind `client` with code `daily_word_not_available` when no
   * word is assigned today, and with another code when the feature is off on the server.
   */
  getDailyWord(locale: Locale, etag: string | null): Promise<DailyWordFetch>;
  /** The learner's confirmed Gold, streak and achievements. 404 (kind `client`) when the feature is off on the server. */
  getRewardsSummary(): Promise<RemoteRewardsSummary>;
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

function safeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) ? value : null;
}

function text(value: unknown, max: number): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed.length <= max ? trimmed : null;
}

function localeOf(value: unknown): Locale | null {
  return value === 'fr' || value === 'ht' ? value : null;
}

/** The contract promises about 1.5 KB; anything far beyond that is not a daily word. */
const DAILY_WORD_MAX_BYTES = 8_000;

export function parseRemoteDailyWord(body: unknown, requested: Locale): RemoteDailyWord {
  if (!isObject(body) || JSON.stringify(body).length > DAILY_WORD_MAX_BYTES) return invalid();
  const fields = isObject(body.word) ? body.word : body;
  const term = text(fields.term, 200);
  const definition = text(fields.definition, 2000);
  const haitiDate = typeof body.haiti_date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(body.haiti_date) ? body.haiti_date : null;
  const validUntil = typeof body.valid_until === 'string' && Number.isFinite(Date.parse(body.valid_until)) ? body.valid_until : null;
  const served = localeOf(body.locale);
  if (!term || !definition || !haitiDate || !validUntil || !served) return invalid();
  // An answer for another language than the one asked for is only acceptable as the declared French fallback.
  const isFallback = body.is_fallback_locale === true;
  if (served !== requested && !(isFallback && served === 'fr')) return invalid();
  const audio = isObject(body.audio)
    ? {
        // `mime_type` / `byte_size` are the vocab lane's names; the shorter ones are how this app stores them.
        mime: text(body.audio.mime_type ?? body.audio.mime, 100),
        bytes: safeInteger(body.audio.byte_size ?? body.audio.bytes),
        duration_ms: typeof body.audio.duration_ms === 'number' ? body.audio.duration_ms : null,
      }
    : null;
  return {
    haiti_date: haitiDate,
    locale: served,
    requested_locale: requested,
    is_fallback_locale: served !== requested,
    valid_until: validUntil,
    word: {
      word_id: text(fields.word_id ?? fields.id, 100),
      revision_id: text(fields.revision_id ?? fields.word_revision_id, 100),
      term,
      pronunciation: text(fields.pronunciation, 200),
      part_of_speech: text(fields.part_of_speech, 100),
      definition,
      example: text(fields.example, 2000),
      gloss: text(fields.gloss, 500),
    },
    audio,
  };
}

/**
 * Accepts `streak: {current, longest}` (assumed) and the flat spellings
 * `current_streak` / `longest_streak`, in case the backend settles on those.
 */
export function parseRemoteRewardsSummary(body: unknown): RemoteRewardsSummary {
  if (!isObject(body)) return invalid();
  const balance = safeInteger(body.balance);
  // A ledger of awards and reversals cannot sum below zero for a learner; a negative or fractional balance is not shown.
  if (balance === null || balance < 0) return invalid();
  const nested = isObject(body.streak) ? body.streak : null;
  const current = safeInteger(nested ? (nested.current ?? nested.current_days) : body.current_streak);
  const longest = safeInteger(nested ? (nested.longest ?? nested.longest_days) : body.longest_streak);
  const streak = current !== null && current >= 0 ? { current, longest: Math.max(current, longest ?? 0) } : null;
  // A list of awards (assumed) or, as this app stores it once validated, their count.
  const counted = safeInteger(body.achievements);
  const achievements = Array.isArray(body.achievements)
    ? body.achievements.filter((item) => isObject(item) && typeof item.code === 'string').length
    : counted !== null && counted >= 0
      ? counted
      : 0;
  return {
    balance,
    streak,
    achievements,
    today: typeof body.today === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(body.today) ? body.today : null,
    up_to_date: body.up_to_date !== false,
    rules_status: body.rules_status === 'provisional' ? 'provisional' : null,
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
  /** The `Date` response header, as sent. */
  serverDate: string | null;
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

  async getProfile(): Promise<RemoteProfile> {
    return parseRemoteProfile(this.ok(await this.send('GET', '/v1/me')).body);
  }

  async getOnboarding(): Promise<RemoteOnboarding> {
    return parseRemoteOnboarding(this.ok(await this.send('GET', '/v1/me/onboarding')).body);
  }

  async putOnboarding(body: RemoteOnboardingUpdate): Promise<RemoteOnboarding> {
    return parseRemoteOnboarding(this.ok(await this.send('PUT', '/v1/me/onboarding', { json: body })).body);
  }

  async patchProfile(body: ProfilePatch): Promise<void> {
    this.ok(await this.send('PATCH', '/v1/me', { json: body }));
  }

  async getDailyWord(locale: Locale, etag: string | null): Promise<DailyWordFetch> {
    const response = await this.send('GET', `/v1/daily-word?locale=${locale}`, {
      headers: etag ? { 'If-None-Match': etag } : undefined,
    });
    if (response.status === 304) return { kind: 'not_modified', serverDate: response.serverDate };
    return { kind: 'word', word: parseRemoteDailyWord(this.ok(response).body, locale), etag: response.etag, serverDate: response.serverDate };
  }

  async getRewardsSummary(): Promise<RemoteRewardsSummary> {
    return parseRemoteRewardsSummary(this.ok(await this.send('GET', '/v1/rewards/summary')).body);
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
      let serverDate: string | null = null;
      // `requestJson` owns timeout, cancellation and error mapping; the wrapper only notes the ETag on the way through.
      const noteEtag: FetchLike = async (input, init) => {
        const response = await this.fetchImpl(input, init);
        etag = response.headers.get('etag');
        serverDate = response.headers.get('date');
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
      return { status, body, etag, serverDate };
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
