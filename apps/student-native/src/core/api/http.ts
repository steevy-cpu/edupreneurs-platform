import { ApiError } from './errors';

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface JsonResult {
  status: number;
  body: unknown;
}

/**
 * fetch + timeout + cancellation + JSON parsing, with every failure mapped to ApiError.
 *
 * A response whose body is cut off or is not JSON (interrupted download, captive
 * portal page, proxy error) is reported as a transient `network` failure — never
 * as data.
 */
export async function requestJson(
  fetchImpl: FetchLike,
  url: string,
  init: RequestInit,
  options: { timeoutMs: number; sessionSignal?: AbortSignal },
): Promise<JsonResult> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs);
  const onSessionEnd = () => controller.abort();
  const sessionSignal = options.sessionSignal;
  if (sessionSignal?.aborted) {
    clearTimeout(timer);
    throw new ApiError('aborted', 'session_ended');
  }
  sessionSignal?.addEventListener('abort', onSessionEnd);

  try {
    let response: Response;
    let text: string;
    try {
      response = await fetchImpl(url, { ...init, signal: controller.signal });
      text = await response.text();
    } catch {
      if (sessionSignal?.aborted) throw new ApiError('aborted', 'session_ended');
      if (timedOut) throw new ApiError('timeout', 'timeout');
      throw new ApiError('network', 'unreachable');
    }
    if (sessionSignal?.aborted) throw new ApiError('aborted', 'session_ended');

    let body: unknown = null;
    if (text.length > 0) {
      try {
        body = JSON.parse(text);
      } catch {
        if (response.status >= 500) throw new ApiError('server', 'bad_gateway', response.status);
        throw new ApiError('network', 'invalid_response', response.status);
      }
    }
    return { status: response.status, body };
  } finally {
    clearTimeout(timer);
    sessionSignal?.removeEventListener('abort', onSessionEnd);
  }
}
