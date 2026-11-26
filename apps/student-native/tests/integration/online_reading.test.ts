/**
 * Online reading, continuity and withdrawn content against the REAL local API and Auth
 * (the disposable stack the hardened harness derived from this checkout).
 */
import { execFileSync } from 'node:child_process';

import { answerQuestion, completeLesson, refreshCatalog } from '../../src/core/learning/actions';
import {
  checkForUpdates,
  downloadForOffline,
  getDownloaded,
  openLesson,
  readOnline,
  removeDownloaded,
  SessionLessonCache,
} from '../../src/core/learning/contentAccess';
import { learningStandings } from '../../src/core/learning/overview';
import { credentials, Device, resetServerLearningState, SEED, serverFeed } from '../support/device';

// The hardened harness's own target derivation: refuses the shared stack.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { deriveRepoTarget } = require('../support/localStack.js') as { deriveRepoTarget: () => { dbContainer: string } };

let device: Device;
beforeEach(() => {
  resetServerLearningState();
  device = new Device();
});
afterEach(async () => {
  await device.dispose();
});

const CHOSEN = ['b', 'a', 'c', 'd', 'a']; // 4 of 5 correct against SEED.correctFr

describe('read online, answer, lose the connection, restart, reconnect', () => {
  test('nothing is downloaded; answers are durable; the server scores them after the restart', async () => {
    const { email, password } = await credentials('student_a');
    let app = await device.boot();
    let session = await app.sessions.signIn(email, password);
    const api = device.api(app.sessions, session);

    const cache = new SessionLessonCache();
    const lesson = await readOnline(api, cache, SEED.lessonId, 'fr');
    expect(lesson.source).toBe('online');
    expect(lesson.revisionId).toBe(SEED.revisionFr);
    expect(await app.content.listSavedLessons('fr')).toEqual([]); // no download was created
    expect(await app.content.getLesson(SEED.lessonId, 'fr')).toBeNull();

    device.network.mode = 'offline'; // the connection disappears right after reading
    const opIds: string[] = [];
    for (const [i, question] of lesson.questions.entries()) {
      const receipt = await answerQuestion(session.account, lesson, question, CHOSEN[i], device.env);
      opIds.push(receipt.opId);
      expect((await session.account.syncSummary()).pending).toBe(i + 1); // durable the moment it resolves
    }
    await completeLesson(session.account, lesson, device.env);
    expect(await serverFeed('student_a')).toEqual([]); // the server has seen nothing

    await device.kill(); // force-quit
    app = await device.boot();
    session = app.session!;
    expect(await app.content.listSavedLessons('fr')).toEqual([]);
    const before = await learningStandings(app.content, session.account, 'fr');
    expect(before).toHaveLength(1);
    expect(before[0]).toMatchObject({ lessonId: SEED.lessonId, availability: 'online', questionCount: null, answered: 5, waiting: 5, completed: true });
    expect((await session.account.pendingOperations(50)).slice(0, 5).map((o) => o.opId)).toEqual(opIds);

    device.network.mode = 'online';
    const run = await device.engine(app.sessions, session).run();
    expect(run).toMatchObject({ outcome: 'ok', confirmed: 6, needsAttention: 0 });
    const after = await learningStandings(app.content, session.account, 'fr');
    expect(after[0]).toMatchObject({ answered: 5, correct: 4, waiting: 0, refused: 0, completed: true }); // server verdict: 4 of 5
    const feed = await serverFeed('student_a');
    expect(feed).toHaveLength(6);
    expect(feed.slice(0, 5).map((c) => c.op_id)).toEqual(opIds);
    expect(await app.content.listSavedLessons('fr')).toEqual([]); // still nothing downloaded
  });

  test('online reading with no connection and no copy fails truthfully; nothing is saved', async () => {
    const { email, password } = await credentials('student_a');
    const app = await device.boot();
    const session = await app.sessions.signIn(email, password);
    device.network.mode = 'offline';
    const result = await openLesson(
      { api: device.api(app.sessions, session), content: app.content, cache: new SessionLessonCache() },
      SEED.lessonId,
      'fr',
      'online',
    );
    expect(result).toEqual({ kind: 'unavailable', reason: 'offline', downloaded: null });
    expect(await app.content.listSavedLessons('fr')).toEqual([]);
  });
});

describe('download, restart offline, remove', () => {
  test('a downloaded lesson opens offline after a restart; removing it keeps all academic progress', async () => {
    const { email, password } = await credentials('student_a');
    let app = await device.boot();
    let session = await app.sessions.signIn(email, password);
    const api = device.api(app.sessions, session);
    expect((await downloadForOffline(api, app.content, SEED.lessonId, 'fr', device.env)).outcome).toBe('new');
    const saved = (await getDownloaded(app.content, SEED.lessonId, 'fr'))!;
    await answerQuestion(session.account, saved, saved.questions[0], 'b', device.env);
    await completeLesson(session.account, saved, device.env);

    device.network.mode = 'offline';
    await device.kill();
    app = await device.boot();
    session = app.session!;
    const calls = device.network.calls.length;
    const reopened = await openLesson({ api: null, content: app.content, cache: new SessionLessonCache() }, SEED.lessonId, 'fr', 'saved');
    expect(reopened.kind).toBe('ready');
    expect(device.network.calls.length).toBe(calls); // no network call

    expect(await removeDownloaded(app.content, SEED.lessonId, 'fr', { account: session.account, now: device.env.now })).toBe(true);
    expect(await getDownloaded(app.content, SEED.lessonId, 'fr')).toBeNull();
    expect(await session.account.pendingOperations(50)).toHaveLength(2);
    expect((await session.account.lessonProgress(SEED.lessonId))!.completed).toBe(true);
    const standings = await learningStandings(app.content, session.account, 'fr');
    expect(standings[0]).toMatchObject({ lessonId: SEED.lessonId, availability: 'online', answered: 1, completed: true });

    device.network.mode = 'online';
    expect(await device.engine(app.sessions, session).run()).toMatchObject({ outcome: 'ok', confirmed: 2 }); // work still syncs
    expect(await serverFeed('student_a')).toHaveLength(2);
  });
});

describe('two accounts on one phone', () => {
  test('the second student sees none of the first student’s online lessons, answers or references', async () => {
    const a = await credentials('student_a');
    const b = await credentials('student_b');
    const app = await device.boot();
    const sessionA = await app.sessions.signIn(a.email, a.password);
    const lesson = await readOnline(device.api(app.sessions, sessionA), new SessionLessonCache(), SEED.lessonId, 'fr');
    await answerQuestion(sessionA.account, lesson, lesson.questions[0], 'b', device.env);
    await completeLesson(sessionA.account, lesson, device.env);

    await app.sessions.signOut();
    const sessionB = await app.sessions.signIn(b.email, b.password);
    expect(await sessionB.account.listLessonRefs('fr')).toEqual([]);
    expect(await learningStandings(app.content, sessionB.account, 'fr')).toEqual([]);
    expect(await sessionB.account.lessonProgress(SEED.lessonId)).toBeNull();
    expect((await sessionB.account.syncSummary()).pending).toBe(0);

    await app.sessions.signOut();
    const again = await app.sessions.signIn(a.email, a.password);
    expect(await learningStandings(app.content, again.account, 'fr')).toHaveLength(1); // A's own record is intact
  });
});

describe('withdrawn content, against the real server', () => {
  /** Archive the seed course (so RLS hides it, exactly like a withdrawal) and always restore it. */
  async function withCourseArchived<T>(fn: () => Promise<T>): Promise<T> {
    const container = deriveRepoTarget().dbContainer;
    const psql = (sql: string) => execFileSync('docker', ['exec', container, 'psql', '-U', 'postgres', '-q', '-tAc', sql]).toString();
    psql(`UPDATE app.courses SET visibility = 'archived' WHERE visibility = 'published'`);
    try {
      return await fn();
    } finally {
      psql(`UPDATE app.courses SET visibility = 'published' WHERE visibility = 'archived'`);
    }
  }

  test('a downloaded lesson the server stops publishing is flagged, kept, and its work still syncs; republishing clears it', async () => {
    const { email, password } = await credentials('student_a');
    const app = await device.boot();
    const session = await app.sessions.signIn(email, password);
    const api = device.api(app.sessions, session);
    await refreshCatalog(api, app.content, 'fr', device.env);
    await downloadForOffline(api, app.content, SEED.lessonId, 'fr', device.env);
    expect(await checkForUpdates(app.content, SEED.lessonId, 'fr')).toBe('current');
    const saved = (await getDownloaded(app.content, SEED.lessonId, 'fr'))!;
    await answerQuestion(session.account, saved, saved.questions[0], 'b', device.env);

    await withCourseArchived(async () => {
      // A catalog fetch alone says "not listed" — not proof, but never "current".
      await refreshCatalog(api, app.content, 'fr', device.env);
      expect(await checkForUpdates(app.content, SEED.lessonId, 'fr')).toBe('not_listed');
      // The lesson endpoint itself answers 404; online opening and re-downloading record it.
      const online = await openLesson({ api, content: app.content, cache: new SessionLessonCache() }, SEED.lessonId, 'fr', 'online');
      expect(online).toMatchObject({ kind: 'unavailable', reason: 'not_found' });
      expect(online.kind === 'unavailable' && online.downloaded?.source).toBe('downloaded'); // the copy is offered
      await expect(downloadForOffline(api, app.content, SEED.lessonId, 'fr', device.env)).rejects.toMatchObject({ status: 404 });
      expect(await checkForUpdates(app.content, SEED.lessonId, 'fr')).toBe('withdrawn_confirmed');
    });

    // Copy and work survive the withdrawal.
    expect((await getDownloaded(app.content, SEED.lessonId, 'fr'))!.questions).toHaveLength(5);
    expect(await session.account.pendingOperations(10)).toHaveLength(1);
    expect(await device.engine(app.sessions, session).run()).toMatchObject({ outcome: 'ok', confirmed: 1 });

    // Republished: a newer catalog that lists it again overrides the old "gone" mark.
    await refreshCatalog(api, app.content, 'fr', { now: () => new Date(Date.now() + 60_000) });
    expect(await checkForUpdates(app.content, SEED.lessonId, 'fr')).toBe('current');
  });

  test('an offline phone cannot know about a withdrawal: it keeps showing its last check, never "now"', async () => {
    const { email, password } = await credentials('student_a');
    const app = await device.boot();
    const session = await app.sessions.signIn(email, password);
    const api = device.api(app.sessions, session);
    await refreshCatalog(api, app.content, 'fr', device.env);
    await downloadForOffline(api, app.content, SEED.lessonId, 'fr', device.env);
    const checkedAt = (await app.content.getCatalog('fr'))!.fetchedAt;
    await withCourseArchived(async () => {
      device.network.mode = 'offline'; // the withdrawal happens while the phone has no connection
      expect(await checkForUpdates(app.content, SEED.lessonId, 'fr')).toBe('current'); // as of the last check…
      expect((await app.content.getCatalog('fr'))!.fetchedAt).toBe(checkedAt); // …and the time of that check is what the UI shows
    });
  });
});
