/**
 * The definition of success, at the level that can be executed without a phone:
 *
 *   sign in → save the seed lesson → airplane mode → answer five questions →
 *   force-quit → reopen (still offline) → reconnect → nothing lost, nothing duplicated.
 */
import { answerQuestion, completeLesson, refreshCatalog, saveLessonOffline } from '../../src/core/learning/actions';
import { credentials, Device, resetServerLearningState, SEED, serverFeed } from '../support/device';

let device: Device;

beforeEach(() => {
  resetServerLearningState();
  device = new Device();
});

afterEach(async () => {
  await device.dispose();
});

test('save lesson, go offline, answer five questions, force-quit, reopen, reconnect: no loss, no duplicate', async () => {
  const { email, password } = await credentials('student_a');

  // --- online: sign in, load the catalog, save the lesson ---------------------
  let app = await device.boot();
  expect(app.session).toBeNull();
  let session = await app.sessions.signIn(email, password);
  expect(session.userId).toBe(SEED.accounts.student_a.id);
  let api = device.api(app.sessions, session);
  await refreshCatalog(api, app.content, 'fr', device.env);
  const saved = await saveLessonOffline(api, app.content, SEED.lessonId, 'fr', device.env);
  expect(saved).toEqual({ revisionId: SEED.revisionFr, outcome: 'new' });

  // --- airplane mode ------------------------------------------------------------
  device.network.mode = 'offline';
  const callsBefore = device.network.calls.length;

  const lesson = await app.content.getLesson(SEED.lessonId, 'fr');
  expect(lesson).not.toBeNull();
  expect(lesson!.title).toBe('Résoudre une équation simple');
  expect(lesson!.blocks).toHaveLength(6);
  expect(lesson!.questions.map((q) => q.position)).toEqual([1, 2, 3, 4, 5]);
  const cachedCatalog = await app.content.getCatalog('fr');
  expect(cachedCatalog!.catalog.courses[0].grade.code).toBe('9AF');
  expect(device.network.calls.length).toBe(callsBefore); // reading saved content made NO network call

  // Four right answers and one wrong one.
  const chosen = ['b', 'a', 'c', 'd', 'a'];
  const opIds: string[] = [];
  for (const [index, question] of lesson!.questions.entries()) {
    const receipt = await answerQuestion(session.account, lesson!, question, chosen[index], device.env);
    opIds.push(receipt.opId);
    expect(receipt.isCorrect).toBe(chosen[index] === SEED.correctFr[index]);
    // The answer is durable the moment answerQuestion resolves:
    expect((await session.account.syncSummary()).pending).toBe(index + 1);
  }
  expect(new Set(opIds).size).toBe(5);
  expect(await completeLesson(session.account, lesson!, device.env)).toBe(true);
  expect(await completeLesson(session.account, lesson!, device.env)).toBe(false); // only once

  // Trying to sync offline changes nothing and reports "offline".
  const offlineRun = await device.engine(app.sessions, session).run();
  expect(offlineRun.outcome).toBe('offline');
  expect((await session.account.syncSummary()).pending).toBe(6);

  // --- force-quit and reopen, still offline --------------------------------------
  await device.kill();
  app = await device.boot();
  session = app.session!;
  expect(session).not.toBeNull(); // session restored from secure storage without any network
  expect(session.userId).toBe(SEED.accounts.student_a.id);

  const reopened = await app.content.getLesson(SEED.lessonId, 'fr');
  expect(reopened!.revisionId).toBe(SEED.revisionFr);
  const progress = await session.account.questionProgress(SEED.lessonId);
  expect(progress.size).toBe(5);
  expect([...progress.values()].filter((p) => p.lastIsCorrect).length).toBe(4);
  expect([...progress.values()].every((p) => p.lastSyncState === 'pending')).toBe(true);
  expect((await session.account.lessonProgress(SEED.lessonId))!.completed).toBe(true);
  const pending = await session.account.pendingOperations(50);
  expect(pending.map((op) => op.opId).slice(0, 5)).toEqual(opIds); // same ids, same order, after restart
  expect(await serverFeed('student_a')).toEqual([]); // the server has seen nothing yet

  // --- reconnect -------------------------------------------------------------------
  device.network.mode = 'online';
  const run = await device.engine(app.sessions, session).run();
  expect(run).toMatchObject({ outcome: 'ok', confirmed: 6, needsAttention: 0, errorCode: null });

  const summary = await session.account.syncSummary();
  expect(summary).toMatchObject({ pending: 0, needsAttention: 0 });
  expect(summary.lastSyncAt).not.toBeNull();
  const synced = await session.account.questionProgress(SEED.lessonId);
  expect([...synced.values()].every((p) => p.lastSyncState === 'synced')).toBe(true);
  expect([...synced.values()].filter((p) => p.lastIsCorrect).length).toBe(4); // server agrees: 4 of 5
  expect((await session.account.lessonProgress(SEED.lessonId))!.syncState).toBe('synced');

  // --- server truth: exactly our six operations, once each, in order -----------------
  const feed = await serverFeed('student_a');
  expect(feed.map((c) => c.version)).toEqual([1, 2, 3, 4, 5, 6]);
  expect(feed.slice(0, 5).map((c) => c.op_id)).toEqual(opIds);
  expect(feed.map((c) => c.entity_type)).toEqual([...Array(5).fill('practice_attempt'), 'lesson_progress']);

  // Syncing again (and again after another restart) creates nothing new.
  await device.engine(app.sessions, session).run();
  await device.kill();
  app = await device.boot();
  const again = await device.engine(app.sessions, app.session!).run();
  expect(again).toMatchObject({ outcome: 'ok', confirmed: 0, pulled: 0 });
  expect(await serverFeed('student_a')).toHaveLength(6);
  expect(await app.session!.account.attemptCount()).toBe(5);
  expect(await serverFeed('student_b')).toEqual([]);
});

test('the Haitian Creole lesson is a separate saved copy with its own questions', async () => {
  const { email, password } = await credentials('student_b');
  const app = await device.boot();
  const session = await app.sessions.signIn(email, password);
  const api = device.api(app.sessions, session);
  await saveLessonOffline(api, app.content, SEED.lessonId, 'fr', device.env);
  await saveLessonOffline(api, app.content, SEED.lessonId, 'ht', device.env);
  device.network.mode = 'offline';
  const fr = await app.content.getLesson(SEED.lessonId, 'fr');
  const ht = await app.content.getLesson(SEED.lessonId, 'ht');
  expect(ht!.title).toBe('Rezoud yon ekwasyon senp');
  expect(ht!.revisionId).toBe(SEED.revisionHt);
  expect(ht!.questions).toHaveLength(5);
  const frIds = new Set(fr!.questions.map((q) => q.id));
  expect(ht!.questions.some((q) => frIds.has(q.id))).toBe(false);
  expect(await app.content.listSavedLessons('ht')).toHaveLength(1);
});
