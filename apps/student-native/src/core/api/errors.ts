/**
 * One error model for everything that can go wrong talking to a server.
 *
 * `kind` answers the only question the app really has: "what should I do now?"
 *   network / timeout / server  → transient: keep the work, try again later
 *   auth_required               → the session can no longer be refreshed: ask to sign in again
 *   aborted                     → the session ended while the request was in flight: drop the response
 *   client                      → the request itself is wrong (4xx): retrying unchanged will not help
 */
export type FailureKind = 'network' | 'timeout' | 'server' | 'auth_required' | 'aborted' | 'client';

export class ApiError extends Error {
  readonly kind: FailureKind;
  readonly status: number | null;
  /** Stable machine code from the API error body (`error.code`) or a local one. */
  readonly code: string;

  constructor(kind: FailureKind, code: string, status: number | null = null, message?: string) {
    super(message ?? `${kind}:${code}`);
    this.name = 'ApiError';
    this.kind = kind;
    this.code = code;
    this.status = status;
  }
}

// A proxy or service can return an unreadable body. Its HTTP status still rules out "no Internet".
export function receivedHttpResponse(error: ApiError): boolean {
  return error.kind === 'server' || (error.status !== null && error.status >= 100);
}

export function isTransient(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.kind === 'network' || error.kind === 'timeout' || error.kind === 'server')
  );
}

export function isAborted(error: unknown): boolean {
  return error instanceof ApiError && error.kind === 'aborted';
}

export function isAuthRequired(error: unknown): boolean {
  return error instanceof ApiError && error.kind === 'auth_required';
}

export function errorCode(error: unknown): string {
  if (error instanceof ApiError) return error.code;
  if (error instanceof Error) return error.name;
  return 'unknown';
}
