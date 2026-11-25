/** What the class step may claim about the connection: only what is known. */
import { gradeListNotice } from '../../src/core/experience/grades';
import { SyncReport, wasUnreachable } from '../../src/core/sync/engine';

const report = (overrides: Partial<SyncReport>): SyncReport => ({
  outcome: 'ok', confirmed: 0, needsAttention: 0, pulled: 0, errorCode: null, ...overrides,
});
const offline = report({ outcome: 'offline', errorCode: 'unreachable' });
const serverError = report({ outcome: 'offline', errorCode: 'dependency_unavailable', serverAnswered: true });

describe('gradeListNotice', () => {
  test('a downloaded catalogue needs no notice, whatever the last sync said', () => {
    expect(gradeListNotice(true, { phase: 'idle', lastReport: offline })).toBe('none');
    expect(gradeListNotice(true, { phase: 'syncing', lastReport: null })).toBe('none');
  });

  test('no attempt made yet: not "offline", just "not downloaded"', () => {
    expect(gradeListNotice(false, { phase: 'idle', lastReport: null })).toBe('not_downloaded');
  });

  test('the last request succeeded: never "offline"', () => {
    expect(gradeListNotice(false, { phase: 'idle', lastReport: report({ outcome: 'ok' }) })).toBe('not_downloaded');
  });

  test('the server answered with an error: reachable, so not "offline"', () => {
    expect(gradeListNotice(false, { phase: 'idle', lastReport: serverError })).toBe('not_downloaded');
  });

  test('other failures (sign-in needed, local error) are not "offline" either', () => {
    expect(gradeListNotice(false, { phase: 'idle', lastReport: report({ outcome: 'auth_required' }) })).toBe('not_downloaded');
    expect(gradeListNotice(false, { phase: 'idle', lastReport: report({ outcome: 'error' }) })).toBe('not_downloaded');
  });

  test('a sync in progress is "loading", even if the previous one failed', () => {
    expect(gradeListNotice(false, { phase: 'syncing', lastReport: offline })).toBe('loading');
    expect(gradeListNotice(false, { phase: 'waiting_to_retry', lastReport: null })).toBe('loading');
  });

  test('only a run that could not reach the server at all is "offline"', () => {
    expect(gradeListNotice(false, { phase: 'idle', lastReport: offline })).toBe('offline');
    expect(wasUnreachable(offline)).toBe(true);
    expect(wasUnreachable(serverError)).toBe(false);
    expect(wasUnreachable(null)).toBe(false);
  });
});
