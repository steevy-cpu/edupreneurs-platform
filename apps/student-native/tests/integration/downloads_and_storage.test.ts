import type { ActiveSession } from '../../src/core/auth/session';
import { SnapshotError } from '../../src/core/api/validate';
import { answerQuestion, refreshCatalog, saveLessonOffline } from '../../src/core/learning/actions';
import { credentials, Device, resetServerLearningState, RunningApp, SEED, serverFeed } from '../support/device';

let device: Device;
let app: RunningApp;
let session: ActiveSession;

beforeEach(async () => {
  resetServerLearningState();
  device = new Device();
  app = await device.boot();
  const { email, password } = await credentials('student_a');
  session = await app.sessions.signIn(email, password);
});

afterEach(async () => {
  device.faults = null;
  await device.dispose();
});

const save = () => saveLessonOffline(device.api(app.sessions, session), app.content, SEED.lessonId, 'fr', device.env);

describe('saving a lesson for offline study', () => {
  test('first download interrupted: nothing is saved; a later attempt succeeds', async () => {
    device.network.only = '/v1/lessons/';
    device.network.mode = 'truncate_response';
    await expect(save()).rejects.toMatchObject({ kind: 'network', code: 'invalid_response' });
    expect(await app.content.getLesson(SEED.lessonId, 'fr')).toBeNull();
    expect(await app.content.listSavedLessons('fr')).toEqual([]);

    device.network.mode = 'offline';
    await expect(save()).rejects.toMatchObject({ kind: 'network' });
    expect(await app.content.getLesson(SEED.lessonId, 'fr')).toBeNull();

    device.network.mode = 'online';
    expect((await save()).outcome).toBe('new');
    expect((await app.content.getLesson(SEED.lessonId, 'fr'))!.questions).toHaveLength(5);
  });

  test('a failed update never deletes the last working copy', async () => {
    await save();
    const before = await app.content.getLesson(SEED.lessonId, 'fr');

    // A new revision exists on the server, but each attempt to fetch it fails in a different way.
    const newRevision = 'c0000000-0000-4000-8000-0000000000ff';
    const failures: (() => void)[] = [
      () => { device.network.mode = 'offline'; },
      () => { device.network.mode = 'truncate_response'; },
      () => { device.network.mode = 'online'; device.network.rewrite = (_u, body: any) => ({ ...body, revision_id: newRevision, revision: 2, blocks: [] }); },
      () => { device.network.rewrite = (_u, body: any) => ({ ...body, revision_id: newRevision, revision: 2, locale: 'ht' }); },
      () => { device.network.rewrite = (_u, body: any) => ({ ...body, revision_id: newRevision, revision: 2, lesson_id: 'b0000000-0000-4000-8000-00000000dead' }); },
      () => { device.network.rewrite = (_u, body: any) => ({ ...body, revision_id: newRevision, revision: 2,
        questions: body.questions.map((q: any) => ({ ...q, answer_key: { correct_choice_id: 'not-a-choice' } })) }); },
      () => { device.network.rewrite = () => ({ error: { code: 'internal_error', message: 'x' } }); },
      () => { device.network.rewrite = () => '<html>captive portal</html>'; },
    ];
    device.network.only = '/v1/lessons/';
    for (const fail of failures) {
      fail();
      await expect(save()).rejects.toBeDefined();
      expect(await app.content.getLesson(SEED.lessonId, 'fr')).toEqual(before); // byte-for-byte the old copy
    }
  });

  test('a storage failure while replacing the copy rolls back to the old copy', async () => {
    await save();
    const before = await app.content.getLesson(SEED.lessonId, 'fr');
    await device.kill();
    device.faults = { shouldFail: (sql) => sql.includes('INSERT INTO saved_questions') };
    app = await device.boot();
    session = app.session!;
    device.network.only = '/v1/lessons/';
    device.network.rewrite = (_u, body: any) => ({ ...body, revision_id: 'c0000000-0000-4000-8000-0000000000ff', revision: 2, title: 'NEW' });
    await expect(save()).rejects.toThrow('simulated storage failure');
    expect(await app.content.getLesson(SEED.lessonId, 'fr')).toEqual(before);
  });

  test('a changed revision replaces the saved copy atomically; answers made on the old revision still sync', async () => {
    await save();
    const old = (await app.content.getLesson(SEED.lessonId, 'fr'))!;
    device.network.mode = 'offline';
    const opId = (await answerQuestion(session.account, old, old.questions[0], 'b', device.env)).opId;
    device.network.mode = 'online';

    // The server now publishes revision 2 with new question ids (simulated at the HTTP boundary).
    device.network.only = '/v1/lessons/';
    device.network.rewrite = (_u, body: any) => ({
      ...body, revision_id: 'c0000000-0000-4000-8000-0000000000ff', revision: 2, title: 'Révision 2',
      questions: body.questions.slice(0, 3).map((q: any, i: number) => ({ ...q, id: `d0000000-0000-4000-8000-0000000009${i}0` })),
    });
    expect(await save()).toEqual({ revisionId: 'c0000000-0000-4000-8000-0000000000ff', outcome: 'updated' });
    expect(await save()).toMatchObject({ outcome: 'unchanged' });
    device.network.rewrite = null;

    const current = (await app.content.getLesson(SEED.lessonId, 'fr'))!;
    expect(current).toMatchObject({ revision: 2, title: 'Révision 2' });
    expect(current.questions.map((q) => q.id)).toEqual([
      'd0000000-0000-4000-8000-000000000900', 'd0000000-0000-4000-8000-000000000910', 'd0000000-0000-4000-8000-000000000920']);
    expect(await app.content.listSavedLessons('fr')).toHaveLength(1); // one copy, not two

    // The pending answer still names the exact revision it was made on, and the server accepts it.
    const [pending] = await session.account.pendingOperations(10);
    expect(pending).toMatchObject({ opId, payload: { question_revision_id: old.questions[0].id } });
    expect(await device.engine(app.sessions, session).run()).toMatchObject({ outcome: 'ok', confirmed: 1 });
    expect((await serverFeed('student_a')).map((c) => c.op_id)).toEqual([opId]);
  });

  test('snapshot for the wrong lesson is refused with a precise reason', async () => {
    device.network.only = '/v1/lessons/';
    device.network.rewrite = (_u, body: any) => ({ ...body, lesson_id: 'b0000000-0000-4000-8000-00000000dead' });
    await expect(save()).rejects.toBeInstanceOf(SnapshotError);
    await expect(save()).rejects.toMatchObject({ reason: 'wrong_lesson' });
  });

  test('the catalog is cached and readable offline; a failed refresh keeps the cached one', async () => {
    const api = device.api(app.sessions, session);
    await refreshCatalog(api, app.content, 'ht', device.env);
    device.network.mode = 'offline';
    await expect(refreshCatalog(api, app.content, 'ht', device.env)).rejects.toBeDefined();
    const cached = await app.content.getCatalog('ht');
    expect(cached!.catalog.courses[0].title).toBe('Matematik 9èm AF');
    expect(await app.content.getCatalog('fr')).toBeNull();
  });
});

describe('local storage errors', () => {
  async function rebootWithFault(shouldFail: (sql: string) => boolean) {
    await device.kill();
    device.faults = { shouldFail };
    app = await device.boot();
    session = app.session!;
  }

  test('if any part of saving an answer fails, nothing is saved and nothing is confirmed', async () => {
    await save();
    for (const failing of ['INSERT INTO attempts', 'INSERT INTO question_progress', 'INSERT INTO outbox', 'COMMIT']) {
      await rebootWithFault((sql) => sql.includes(failing));
      const lesson = (await app.content.getLesson(SEED.lessonId, 'fr'))!;
      await expect(answerQuestion(session.account, lesson, lesson.questions[0], 'b', device.env)).rejects.toThrow(
        'simulated storage failure');
      // All-or-nothing: no attempt without its pending operation, no pending operation without its attempt.
      expect(await session.account.attemptCount()).toBe(0);
      expect((await session.account.questionProgress(SEED.lessonId)).size).toBe(0);
      expect((await session.account.syncSummary()).pending).toBe(0);
    }
    // Storage works again: the same question can be answered normally.
    await rebootWithFault(() => false);
    const lesson = (await app.content.getLesson(SEED.lessonId, 'fr'))!;
    await answerQuestion(session.account, lesson, lesson.questions[0], 'b', device.env);
    expect((await session.account.syncSummary()).pending).toBe(1);
  });

  test('storage fails while recording the server acknowledgement: the operation stays pending and is confirmed later without a duplicate', async () => {
    await save();
    const lesson = (await app.content.getLesson(SEED.lessonId, 'fr'))!;
    const opId = (await answerQuestion(session.account, lesson, lesson.questions[0], 'b', device.env)).opId;

    await rebootWithFault((sql) => sql.includes('DELETE FROM outbox'));
    const failed = await device.engine(app.sessions, session).run();
    expect(failed.outcome).toBe('error');
    expect(await serverFeed('student_a')).toHaveLength(1); // the server has it ...
    const state = await session.account.questionProgress(SEED.lessonId);
    expect([...state.values()][0].lastSyncState).toBe('pending'); // ... but the phone does not claim "synced"
    expect((await session.account.pendingOperations(10)).map((op) => op.opId)).toEqual([opId]);

    await rebootWithFault(() => false);
    expect(await device.engine(app.sessions, session).run()).toMatchObject({ outcome: 'ok', confirmed: 1 });
    expect((await serverFeed('student_a')).map((c) => c.op_id)).toEqual([opId]);
    expect(await session.account.attemptCount()).toBe(1);
  });

  test('storage fails while applying pulled changes: the cursor does not advance, and the page is applied on the next run', async () => {
    // Another device of the same account produced two changes.
    const other = new Device();
    try {
      const otherApp = await other.boot();
      const { email, password } = await credentials('student_a');
      const otherSession = await otherApp.sessions.signIn(email, password);
      await saveLessonOffline(other.api(otherApp.sessions, otherSession), otherApp.content, SEED.lessonId, 'fr', other.env);
      const lesson = (await otherApp.content.getLesson(SEED.lessonId, 'fr'))!;
      await answerQuestion(otherSession.account, lesson, lesson.questions[0], 'b', other.env);
      await answerQuestion(otherSession.account, lesson, lesson.questions[1], 'a', other.env);
      await other.engine(otherApp.sessions, otherSession).run();
    } finally {
      await other.dispose();
    }

    // Fail the cursor write specifically (it is the last statement of the pull transaction).
    await rebootWithFault((sql) => sql.startsWith('INSERT INTO meta'));
    const failed = await device.engine(app.sessions, session).run();
    expect(failed.outcome).toBe('error');
    expect(await session.account.getCursor()).toBeNull();
    expect(await session.account.attemptCount()).toBe(0); // the changes were rolled back together with the cursor

    await rebootWithFault(() => false);
    const ok = await device.engine(app.sessions, session).run();
    expect(ok).toMatchObject({ outcome: 'ok', pulled: 2 });
    expect(await session.account.attemptCount()).toBe(2);
    expect(await session.account.getCursor()).not.toBeNull();
    const again = await device.engine(app.sessions, session).run();
    expect(again.pulled).toBe(0);
    expect(await session.account.attemptCount()).toBe(2);
  });
});
