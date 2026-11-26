import crypto from 'node:crypto';

import { ApiClient } from '../../src/core/api/client';
import { ApiError } from '../../src/core/api/errors';
import type { ActiveSession } from '../../src/core/auth/session';
import { wasUnreachable } from '../../src/core/sync/engine';
import { answerQuestion, completeLesson, saveLessonOffline } from '../../src/core/learning/actions';
import { API_URL, credentials, Device, resetServerLearningState, RunningApp, SEED, serverFeed } from '../support/device';

let device: Device;
let app: RunningApp;
let session: ActiveSession;

async function answer(indexes: number[], choice?: string): Promise<string[]> {
  const lesson = (await app.content.getLesson(SEED.lessonId, 'fr'))!;
  const ids: string[] = [];
  for (const index of indexes) {
    const receipt = await answerQuestion(
      session.account, lesson, lesson.questions[index], choice ?? SEED.correctFr[index], device.env);
    ids.push(receipt.opId);
  }
  return ids;
}

beforeEach(async () => {
  resetServerLearningState();
  device = new Device();
  app = await device.boot();
  const { email, password } = await credentials('student_a');
  session = await app.sessions.signIn(email, password);
  await saveLessonOffline(device.api(app.sessions, session), app.content, SEED.lessonId, 'fr', device.env);
});

afterEach(async () => {
  await device.dispose();
});

test('server commits but the response is lost: retry confirms the same operations, nothing is duplicated', async () => {
  const opIds = await answer([0, 1, 2, 3, 4]);

  device.network.only = '/v1/sync/push';
  device.network.mode = 'lose_response';
  const lost = await device.engine(app.sessions, session, { maxAttempts: 1 }).run();
  expect(lost.outcome).toBe('offline');
  // The server DID store all five, but the phone does not know and must not claim it:
  expect(await serverFeed('student_a')).toHaveLength(5);
  expect((await session.account.syncSummary()).pending).toBe(5);
  const stillWaiting = await session.account.questionProgress(SEED.lessonId);
  expect([...stillWaiting.values()].every((p) => p.lastSyncState === 'pending')).toBe(true);

  // Force-quit in that state, come back, connection works again.
  await device.kill();
  device.network.mode = 'online';
  app = await device.boot();
  session = app.session!;
  expect((await session.account.pendingOperations(50)).map((op) => op.opId)).toEqual(opIds);
  const retry = await device.engine(app.sessions, session).run();
  expect(retry).toMatchObject({ outcome: 'ok', confirmed: 5, needsAttention: 0 });

  const feed = await serverFeed('student_a');
  expect(feed.map((c) => c.op_id)).toEqual(opIds); // five, not ten
  expect((await session.account.syncSummary()).pending).toBe(0);
  expect(await session.account.attemptCount()).toBe(5);
});

test('lost response is also healed by pull alone (the feed proves the server has the operation)', async () => {
  const opIds = await answer([0, 1]);
  device.network.only = '/v1/sync/push';
  device.network.mode = 'lose_response';
  await device.engine(app.sessions, session, { maxAttempts: 1 }).run();
  device.network.mode = 'online';

  // Apply only the pull half, as if the next push were delayed.
  const api = device.api(app.sessions, session);
  const page = await api.pull(await session.account.getCursor());
  await session.account.applyPulledPage(page.changes, page.next_cursor);
  expect((await session.account.syncSummary()).pending).toBe(0);
  const progress = await session.account.questionProgress(SEED.lessonId);
  expect([...progress.values()].map((p) => p.lastSyncState)).toEqual(['synced', 'synced']);
  expect(await session.account.attemptCount()).toBe(2); // merged with the local rows, not added
  expect((await serverFeed('student_a')).map((c) => c.op_id)).toEqual(opIds);
});

test('overlapping sync calls share one run and send each operation once', async () => {
  await answer([0, 1, 2]);
  const engine = device.engine(app.sessions, session);
  const [first, second, third] = [engine.run(), engine.run(), engine.run()];
  expect(second).toBe(first);
  expect(third).toBe(first);
  expect(engine.running).toBe(true);
  expect((await first).confirmed).toBe(3);
  expect(engine.running).toBe(false);
  expect(device.network.count('/v1/sync/push')).toBe(1);
  expect(await serverFeed('student_a')).toHaveLength(3);
});

test('outage: bounded exponential backoff, then stop; work stays pending and syncs later', async () => {
  await answer([0, 1, 2, 3, 4]);
  device.apiUrl = 'http://127.0.0.1:9'; // nothing listens here: connection refused
  const run = await device.engine(app.sessions, session, { maxAttempts: 4, baseDelayMs: 1000, maxDelayMs: 30000, random: () => 1 }).run();
  expect(run).toMatchObject({ outcome: 'offline', confirmed: 0, errorCode: 'unreachable' });
  expect(device.sleeps).toEqual([1000, 2000, 4000]); // 4 attempts => 3 waits, doubling
  expect(device.network.count('/v1/sync/push')).toBe(4);
  expect((await session.account.syncSummary()).pending).toBe(5);

  device.apiUrl = API_URL;
  expect((await device.engine(app.sessions, session).run()).confirmed).toBe(5);
});

test('server errors (503 / 500) are retried; a recovering server is picked up within the same run', async () => {
  await answer([0]);
  let failures = 2;
  const original = device.network.fetch;
  const flaky = async (url: string, init?: RequestInit) => {
    if (url.includes('/v1/sync/push') && failures > 0) {
      failures -= 1;
      return new Response(JSON.stringify({ error: { code: 'dependency_unavailable', message: 'x' } }), { status: 503 });
    }
    return original(url, init);
  };
  const api = new ApiClient({
    baseUrl: device.apiUrl, fetchImpl: flaky, getAccessToken: (o) => app.sessions.accessToken(session, o) });
  const run = await device.engine(app.sessions, session, { api }).run();
  expect(run).toMatchObject({ outcome: 'ok', confirmed: 1 });
  expect(device.sleeps).toHaveLength(2);
  expect(await serverFeed('student_a')).toHaveLength(1);
});

test('a server that keeps answering 503 is retried but is not reported as unreachable; a dead port is', async () => {
  await answer([0]);
  const original = device.network.fetch;
  const failing = async (url: string, init?: RequestInit) =>
    url.includes('/v1/sync/push')
      ? new Response(JSON.stringify({ error: { code: 'dependency_unavailable', message: 'x' } }), { status: 503 })
      : original(url, init);
  const api = new ApiClient({
    baseUrl: device.apiUrl, fetchImpl: failing, getAccessToken: (o) => app.sessions.accessToken(session, o) });
  const answered = await device.engine(app.sessions, session, { api, maxAttempts: 2 }).run();
  expect(answered).toMatchObject({ outcome: 'offline', errorCode: 'dependency_unavailable', serverAnswered: true });
  expect(wasUnreachable(answered)).toBe(false);

  device.apiUrl = 'http://127.0.0.1:9';
  const dead = await device.engine(app.sessions, session, { maxAttempts: 2 }).run();
  expect(dead).toMatchObject({ outcome: 'offline', errorCode: 'unreachable', serverAnswered: false });
  expect(wasUnreachable(dead)).toBe(true);
});

test('permanently rejected operations are flagged once, never resent, and do not block later work', async () => {
  // An answer to a question revision the server does not know (e.g. content withdrawn).
  const ghost = crypto.randomUUID();
  await session.account.recordAnswer({
    opId: ghost, questionRevisionId: crypto.randomUUID(), lessonRevisionId: crypto.randomUUID(),
    lessonId: SEED.lessonId, choiceId: 'a', localIsCorrect: true, recordedAt: new Date().toISOString() });
  const [good] = await answer([0]);

  const first = await device.engine(app.sessions, session).run();
  expect(first).toMatchObject({ outcome: 'ok', confirmed: 1, needsAttention: 1 });
  expect(await session.account.syncSummary()).toMatchObject({ pending: 0, needsAttention: 1 });
  expect(await session.account.attentionItems()).toEqual([
    expect.objectContaining({ opId: ghost, kind: 'practice_answer', problemCode: 'content_not_available' })]);
  expect((await serverFeed('student_a')).map((c) => c.op_id)).toEqual([good]);

  const pushesBefore = device.network.count('/v1/sync/push');
  for (let i = 0; i < 3; i += 1) await device.engine(app.sessions, session).run();
  expect(device.network.count('/v1/sync/push')).toBe(pushesBefore); // nothing left to send: no retry storm
  expect(await session.account.pendingOperations(50)).toEqual([]);
});

test('an operation the server refuses at request level is isolated instead of blocking the batch', async () => {
  await answer([0, 1]);
  // A locally corrupted operation: its kind is longer than the API allows => HTTP 422 for the whole request.
  await session.account.recordAnswer({
    opId: crypto.randomUUID(), questionRevisionId: crypto.randomUUID(), lessonRevisionId: crypto.randomUUID(),
    lessonId: SEED.lessonId, choiceId: 'x'.repeat(5000), localIsCorrect: false, recordedAt: 'not-a-date' });
  await answer([2, 3]);

  const run = await device.engine(app.sessions, session).run();
  expect(run.outcome).toBe('ok');
  expect(run.confirmed).toBe(4);
  expect(run.needsAttention).toBe(1);
  expect(await session.account.syncSummary()).toMatchObject({ pending: 0, needsAttention: 1 });
  expect((await session.account.attentionItems())[0].problemCode).toBe('request_validation_error');
  expect(await serverFeed('student_a')).toHaveLength(4);
});

test('more than 50 pending operations are sent in several batches, in order', async () => {
  const ids: string[] = [];
  for (let round = 0; round < 23; round += 1) ids.push(...(await answer([0, 1, 2, 3, 4])));
  expect(ids).toHaveLength(115);
  const run = await device.engine(app.sessions, session).run();
  expect(run).toMatchObject({ outcome: 'ok', confirmed: 115 });
  expect(device.network.count('/v1/sync/push')).toBe(3);
  expect((await serverFeed('student_a')).map((c) => c.op_id)).toEqual(ids);
});

test('an unusable cursor (410) resets the pull without touching pending work', async () => {
  await answer([0, 1]);
  await device.engine(app.sessions, session).run();
  expect(await session.account.attemptCount()).toBe(2);

  // Simulate a restored backup / wrong environment: a cursor the server refuses.
  await session.account.applyPulledPage([], 'bm90LWEtdmFsaWQtY3Vyc29y');
  const [pendingOp] = await answer([2]);
  device.network.only = '/v1/sync/push';
  device.network.mode = 'offline'; // push fails, so the pending op must survive the reset
  const api = device.api(app.sessions, session);
  await expect(api.pull(await session.account.getCursor())).rejects.toMatchObject({ status: 410, code: 'sync_cursor_invalid' });

  device.network.mode = 'online';
  const run = await device.engine(app.sessions, session).run();
  expect(run).toMatchObject({ outcome: 'ok', confirmed: 1 });
  expect(await session.account.attemptCount()).toBe(3);
  expect((await serverFeed('student_a')).map((c) => c.op_id)).toContain(pendingOp);
  const next = await api.pull(await session.account.getCursor());
  expect(next.changes).toEqual([]); // cursor is valid again and at the head
});

test('progress is reconciled across two devices of the same account', async () => {
  const phoneB = new Device();
  try {
    const { email, password } = await credentials('student_a');
    const appB = await phoneB.boot();
    const sessionB = await appB.sessions.signIn(email, password);
    await saveLessonOffline(phoneB.api(appB.sessions, sessionB), appB.content, SEED.lessonId, 'fr', phoneB.env);

    // Phone 1 answers three questions and finishes the lesson; phone 2 answers two (one of them the same question).
    const lesson = (await app.content.getLesson(SEED.lessonId, 'fr'))!;
    await answer([0, 1, 2]);
    await completeLesson(session.account, lesson, device.env);
    await answerQuestion(sessionB.account, lesson, lesson.questions[2], 'a', phoneB.env); // wrong, later than phone 1
    await answerQuestion(sessionB.account, lesson, lesson.questions[4], 'b', phoneB.env);
    await completeLesson(sessionB.account, lesson, phoneB.env); // both phones "complete" offline

    await device.engine(app.sessions, session).run();
    const runB = await phoneB.engine(appB.sessions, sessionB).run();
    expect(runB).toMatchObject({ outcome: 'ok', confirmed: 3 }); // 2 answers + completion (merged by the server)
    await device.engine(app.sessions, session).run(); // phone 1 pulls phone 2's work

    for (const account of [session.account, sessionB.account]) {
      expect(await account.attemptCount()).toBe(5);
      const progress = await account.questionProgress(SEED.lessonId);
      expect(progress.size).toBe(4); // questions 1,2,3,5
      expect(progress.get(lesson.questions[2].id)).toMatchObject({ attemptsCount: 2, lastChoiceId: 'a', lastIsCorrect: false });
      expect([...progress.values()].every((p) => p.lastSyncState === 'synced')).toBe(true);
      expect(await account.lessonProgress(SEED.lessonId)).toMatchObject({
        completed: true, completedRevisionId: SEED.revisionFr, syncState: 'synced' });
      expect(await account.syncSummary()).toMatchObject({ pending: 0, needsAttention: 0 });
    }
    const feed = await serverFeed('student_a');
    expect(feed.filter((c) => c.entity_type === 'lesson_progress')).toHaveLength(1); // one completion, not two
    expect(feed).toHaveLength(6);
  } finally {
    await phoneB.dispose();
  }
});

test('the API client reports HTTP failures with their machine code', async () => {
  const api = device.api(app.sessions, session);
  await expect(api.getLesson(crypto.randomUUID(), 'fr')).rejects.toMatchObject({ kind: 'client', status: 404, code: 'lesson_not_found' });
  await expect(api.pull('garbage')).rejects.toBeInstanceOf(ApiError);
  expect((await api.getMe()).user_id).toBe(SEED.accounts.student_a.id);
});
