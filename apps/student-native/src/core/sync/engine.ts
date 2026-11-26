import { ApiClient } from '../api/client';
import { ApiError, errorCode, isAborted, isAuthRequired, isTransient } from '../api/errors';
import { AccountStore, PendingOperation } from '../db/accountStore';

export type SyncOutcome = 'ok' | 'offline' | 'auth_required' | 'aborted' | 'error';

export interface SyncReport {
  outcome: SyncOutcome;
  /** Operations the server confirmed during this run. */
  confirmed: number;
  /** Operations the server permanently refused during this run. */
  needsAttention: number;
  /** Changes applied from the server feed. */
  pulled: number;
  errorCode: string | null;
  /**
   * True when the run ended `offline` although the server DID answer (an error reply such as 503 from
   * the API itself). Such a run is retried like an offline one, but must not be shown as "no connection".
   */
  serverAnswered?: boolean;
}

/** The last run could not reach the server at all (no reply, timeout, proxy/portal page). */
export function wasUnreachable(report: SyncReport | null | undefined): boolean {
  return report?.outcome === 'offline' && report.serverAnswered !== true;
}

export function serviceUnreachable(status: { serviceReachable?: boolean | null; lastReport: SyncReport | null }): boolean {
  return status.serviceReachable == null ? wasUnreachable(status.lastReport) : !status.serviceReachable;
}

export type SyncPhase = 'idle' | 'syncing' | 'waiting_to_retry';

export interface SyncEngineOptions {
  account: AccountStore;
  api: Pick<ApiClient, 'push' | 'pull'>;
  /** False once the session has ended; checked before every local write. */
  isActive: () => boolean;
  now?: () => Date;
  sleep?: (ms: number) => Promise<void>;
  random?: () => number;
  /** Attempts per network step before giving up until the next trigger. */
  maxAttempts?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  batchSize?: number;
  pullPageSize?: number;
  onPhase?: (phase: SyncPhase) => void;
}

const SERVER_MAX_BATCH = 50;

/** Delay before retry number `attempt` (0-based): exponential, capped, with jitter. */
export function backoffDelay(
  attempt: number,
  baseDelayMs: number,
  maxDelayMs: number,
  random: () => number,
): number {
  const exponential = Math.min(maxDelayMs, baseDelayMs * 2 ** attempt);
  return Math.round(exponential * (0.5 + random() * 0.5));
}

class Aborted extends Error {}

/**
 * Pushes this account's pending operations, then pulls the server's changes.
 *
 *  - Single flight: calling `run()` while a run is in progress returns that run.
 *  - Operation ids are created when the action happens and are never changed here,
 *    so resending after a lost response is safe (the server replays its stored result).
 *  - Transient failures are retried a bounded number of times with exponential
 *    backoff, then the run ends as `offline`; nothing polls in the background.
 *  - Permanently refused operations are flagged "needs attention" and not resent.
 *  - Bound to one session: once `isActive()` is false nothing more is written.
 */
export class SyncEngine {
  private inFlight: Promise<SyncReport> | null = null;
  private readonly sleep: (ms: number) => Promise<void>;
  private readonly random: () => number;
  private readonly maxAttempts: number;
  private readonly baseDelayMs: number;
  private readonly maxDelayMs: number;
  private batchSize: number;

  constructor(private readonly options: SyncEngineOptions) {
    this.sleep = options.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
    this.random = options.random ?? Math.random;
    this.maxAttempts = Math.max(1, options.maxAttempts ?? 4);
    this.baseDelayMs = options.baseDelayMs ?? 1_000;
    this.maxDelayMs = options.maxDelayMs ?? 30_000;
    this.batchSize = Math.min(SERVER_MAX_BATCH, Math.max(1, options.batchSize ?? SERVER_MAX_BATCH));
  }

  get running(): boolean {
    return this.inFlight !== null;
  }

  run(): Promise<SyncReport> {
    this.inFlight ??= this.execute().finally(() => {
      this.inFlight = null;
      this.options.onPhase?.('idle');
    });
    return this.inFlight;
  }

  private async execute(): Promise<SyncReport> {
    const report: SyncReport = {
      outcome: 'ok',
      confirmed: 0,
      needsAttention: 0,
      pulled: 0,
      errorCode: null,
    };
    this.options.onPhase?.('syncing');
    try {
      await this.pushAll(report);
      await this.pullAll(report);
      this.ensureActive();
      await this.options.account.markSynced((this.options.now?.() ?? new Date()).toISOString());
    } catch (error) {
      report.errorCode = errorCode(error);
      if (error instanceof Aborted || isAborted(error) || !this.options.isActive()) {
        report.outcome = 'aborted';
        report.errorCode = 'session_ended';
      } else if (isAuthRequired(error)) {
        report.outcome = 'auth_required';
      } else if (isTransient(error)) {
        report.outcome = 'offline';
        // A 5xx whose body is the API's own error JSON proves the server is reachable; a bare gateway error does not.
        report.serverAnswered = error instanceof ApiError && error.kind === 'server' && error.code !== 'bad_gateway';
      } else {
        report.outcome = 'error';
      }
    }
    return report;
  }

  private ensureActive(): void {
    if (!this.options.isActive()) throw new Aborted();
  }

  /** Run one network step, retrying transient failures with bounded backoff. */
  private async withRetry<T>(step: () => Promise<T>, onFailure?: (code: string) => Promise<void>): Promise<T> {
    for (let attempt = 0; ; attempt += 1) {
      this.ensureActive();
      try {
        return await step();
      } catch (error) {
        if (!isTransient(error)) throw error;
        this.ensureActive();
        await onFailure?.(errorCode(error));
        if (attempt + 1 >= this.maxAttempts) throw error;
        this.options.onPhase?.('waiting_to_retry');
        await this.sleep(backoffDelay(attempt, this.baseDelayMs, this.maxDelayMs, this.random));
        this.options.onPhase?.('syncing');
      }
    }
  }

  private async pushAll(report: SyncReport): Promise<void> {
    const { account, api } = this.options;
    for (;;) {
      this.ensureActive();
      const batch = await account.pendingOperations(this.batchSize);
      if (batch.length === 0) return;

      let results;
      try {
        const response = await this.withRetry(
          () => api.push(batch.map(AccountStore.toWire)),
          (code) => account.noteSendFailure(batch.map((op) => op.opId), code),
        );
        results = response.results;
      } catch (error) {
        if (await this.handleRequestRefusal(error, batch, report)) continue;
        throw error;
      }

      this.ensureActive(); // an answer that arrives after sign-out is dropped, not stored
      const outcome = await account.applyPushResults(batch, results);
      report.confirmed += outcome.confirmed;
      report.needsAttention += outcome.needsAttention;
      if (outcome.confirmed + outcome.needsAttention === 0) {
        // The server answered but resolved none of what we sent: stop instead of looping.
        throw new ApiError('client', 'push_made_no_progress');
      }
    }
  }

  /**
   * The server refused the REQUEST (not individual operations). Shrink the batch
   * until the offending operation is alone, then set it aside so that one bad
   * operation cannot block every later one. Returns true if the push loop should go on.
   */
  private async handleRequestRefusal(
    error: unknown,
    batch: PendingOperation[],
    report: SyncReport,
  ): Promise<boolean> {
    if (!(error instanceof ApiError) || error.kind !== 'client') return false;
    if (error.status !== 413 && error.status !== 422) return false;
    this.ensureActive();
    if (batch.length > 1) {
      this.batchSize = Math.max(1, Math.floor(batch.length / 2));
      return true;
    }
    await this.options.account.flagOperation(batch[0], `request_${error.code}`);
    report.needsAttention += 1;
    return true;
  }

  private async pullAll(report: SyncReport): Promise<void> {
    const { account, api } = this.options;
    let resets = 0;
    for (;;) {
      this.ensureActive();
      const cursor = await account.getCursor();
      let page;
      try {
        page = await this.withRetry(() => api.pull(cursor, this.options.pullPageSize));
      } catch (error) {
        if (error instanceof ApiError && error.status === 410 && resets === 0) {
          // Documented recovery: drop the cursor and replay from the beginning.
          // Pending operations stay in the outbox.
          resets += 1;
          this.ensureActive();
          await account.beginCursorReset();
          continue;
        }
        throw error;
      }
      this.ensureActive();
      report.pulled += await account.applyPulledPage(page.changes, page.next_cursor);
      if (!page.has_more) return;
      if (page.changes.length === 0) throw new ApiError('client', 'pull_made_no_progress');
    }
  }
}
