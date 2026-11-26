/**
 * The data behind the redesigned screens (Mobile-02), exercised the way the
 * screens use it: real SQLite files, the real local API and Auth.
 *
 * What these tests protect:
 *   - every number a screen shows comes from local records (nothing invented);
 *   - "synced" is never displayed while work is waiting for the server;
 *   - one student's progress and "continue" lesson are invisible to the next student.
 */
import { answerQuestion, completeLesson, refreshCatalog, saveLessonOffline } from '../../src/core/learning/actions';
import {
  findLessonContext,
  loadPath,
  pickContinueLesson,
  PREF_GRADE,
  PREF_LAST_LESSON,
  PREF_SUBJECT,
  savedLessonStandings,
  syncDisplayOf,
  totalsOf,
} from '../../src/core/learning/overview';
import { credentials, Device, resetServerLearningState, SEED } from '../support/device';

let device: Device;

beforeEach(() => {
  resetServerLearningState();
  device = new Device();
});

afterEach(async () => {
  await device.dispose();
});

test('new student: nothing saved means no Continue card, an empty path and zero totals', async () => {
  const { email, password } = await credentials('student_a');
  const app = await device.boot();
  const session = await app.sessions.signIn(email, password);

  const standings = await savedLessonStandings(app.content, session.account, 'fr');
  expect(standings).toEqual([]);
  expect(pickContinueLesson(standings, null)).toBeNull();
  expect(totalsOf(standings)).toEqual({
    lessonsSaved: 0,
    lessonsStudied: 0,
    lessonsCompleted: 0,
    questionsAnswered: 0,
    questionsCorrect: 0,
    questionsMissed: 0,
    answersWaiting: 0,
  });

  // No catalog cached yet: the path says so instead of showing placeholder lessons.
  const path = await loadPath(app.content, session.account, 'fr', { grade: null, subject: null });
  expect(path).toMatchObject({ catalogKnown: false, grades: [], subjects: [], units: [], otherSaved: [] });
});

test('learning path: real catalog, download state and lesson-level completion only', async () => {
  const { email, password } = await credentials('student_a');
  const app = await device.boot();
  const session = await app.sessions.signIn(email, password);
  const api = device.api(app.sessions, session);
  await refreshCatalog(api, app.content, 'fr', device.env);

  // Nothing chosen yet: grades are offered, no units are shown.
  let path = await loadPath(app.content, session.account, 'fr', { grade: null, subject: null });
  expect(path.catalogKnown).toBe(true);
  expect(path.grades.map((g) => g.code)).toContain('9AF');
  expect(path.units).toEqual([]);

  // A grade with an empty subject (what the screen stores right after a grade tap).
  path = await loadPath(app.content, session.account, 'fr', { grade: '9AF', subject: '' });
  expect(path.grade).toBe('9AF');
  expect(path.subject).toBeNull();
  expect(path.subjects.length).toBeGreaterThan(0);
  const subject = path.subjects[0].slug;

  // Lesson not downloaded: it is listed, cannot be opened, and is not "recommended".
  path = await loadPath(app.content, session.account, 'fr', { grade: '9AF', subject });
  const first = path.units[0].lessons.find((lesson) => lesson.lessonId === SEED.lessonId)!;
  expect(first).toMatchObject({ saved: null, completed: false, state: 'unavailable', updateAvailable: false });
  expect(path.units[0].completedCount).toBe(0);

  // Downloaded: it becomes the next step.
  await saveLessonOffline(api, app.content, SEED.lessonId, 'fr', device.env);
  device.network.mode = 'offline';
  const callsBefore = device.network.calls.length;
  path = await loadPath(app.content, session.account, 'fr', { grade: '9AF', subject });
  const saved = path.units[0].lessons.find((lesson) => lesson.lessonId === SEED.lessonId)!;
  expect(saved.state).toBe('recommended');
  expect(saved.saved!.revisionId).toBe(SEED.revisionFr);
  expect(path.otherSaved).toEqual([]);

  // Answering questions does NOT complete the lesson: completion is its own record.
  const lesson = (await app.content.getLesson(SEED.lessonId, 'fr'))!;
  await answerQuestion(session.account, lesson, lesson.questions[0], SEED.correctFr[0], device.env);
  path = await loadPath(app.content, session.account, 'fr', { grade: '9AF', subject });
  expect(path.units[0].lessons.find((l) => l.lessonId === SEED.lessonId)!.state).toBe('recommended');

  await completeLesson(session.account, lesson, device.env);
  path = await loadPath(app.content, session.account, 'fr', { grade: '9AF', subject });
  expect(path.units[0].lessons.find((l) => l.lessonId === SEED.lessonId)!).toMatchObject({ completed: true, state: 'completed' });
  expect(path.units[0].completedCount).toBe(1);

  // With another grade selected the saved lesson stays reachable.
  path = await loadPath(app.content, session.account, 'fr', { grade: 'does-not-exist', subject: null });
  expect(path.otherSaved.map((l) => l.lessonId)).toEqual([SEED.lessonId]);

  expect(device.network.calls.length).toBe(callsBefore); // the path never used the network
  expect(findLessonContext((await app.content.getCatalog('fr'))!.catalog, SEED.lessonId)).toMatchObject({
    gradeCode: '9AF',
    lessonNumber: 1,
  });
  expect(findLessonContext(null, SEED.lessonId)).toBeNull();
});

test('offline exercise → force-quit → reopen → Profil shows the work as waiting, never as synced → reconnect', async () => {
  const { email, password } = await credentials('student_a');
  let app = await device.boot();
  let session = await app.sessions.signIn(email, password);
  const api = device.api(app.sessions, session);
  await refreshCatalog(api, app.content, 'fr', device.env);
  await saveLessonOffline(api, app.content, SEED.lessonId, 'fr', device.env);
  await session.account.setPreference(PREF_LAST_LESSON, SEED.lessonId); // what the reader does on open

  device.network.mode = 'offline';
  const lesson = (await app.content.getLesson(SEED.lessonId, 'fr'))!;
  const chosen = ['b', 'a', 'c', 'd', 'a']; // four right, the last one wrong
  for (const [index, question] of lesson.questions.entries()) {
    await answerQuestion(session.account, lesson, question, chosen[index], device.env);
  }
  const offlineRun = await device.engine(app.sessions, session).run();
  expect(offlineRun.outcome).toBe('offline');

  // --- force-quit and reopen with no network -------------------------------------
  await device.kill();
  app = await device.boot();
  session = app.session!;
  const callsBefore = device.network.calls.length;

  const standings = await savedLessonStandings(app.content, session.account, 'fr');
  expect(standings).toHaveLength(1);
  expect(standings[0]).toMatchObject({
    lessonId: SEED.lessonId,
    questionCount: 5,
    answered: 5,
    correct: 4,
    waiting: 5,
    refused: 0,
    completed: false,
    completionState: null,
  });
  expect(standings[0].missedQuestionIds).toEqual([lesson.questions[4].id]);
  expect(totalsOf(standings)).toMatchObject({ questionsAnswered: 5, questionsCorrect: 4, questionsMissed: 1, answersWaiting: 5 });
  // Continue card: the lesson opened last, restored from the account's own preferences.
  expect(pickContinueLesson(standings, await session.account.getPreference(PREF_LAST_LESSON))!.lessonId).toBe(SEED.lessonId);
  expect(device.network.calls.length).toBe(callsBefore); // Home / Réviser / Profil data needed no network

  // Sync display: with work waiting it is "pending" or "failed" — never "synced".
  const waiting = await session.account.syncSummary();
  expect(waiting.pending).toBe(5);
  for (const outcome of [null, 'ok', 'offline', 'error', 'auth_required', 'aborted']) {
    expect(syncDisplayOf(waiting, outcome)).not.toBe('synced');
  }
  expect(syncDisplayOf(waiting, 'offline')).toBe('failed');
  expect(syncDisplayOf(waiting, null)).toBe('pending');

  // --- reconnect ------------------------------------------------------------------
  device.network.mode = 'online';
  const run = await device.engine(app.sessions, session).run();
  expect(run).toMatchObject({ outcome: 'ok', confirmed: 5 });
  const after = await session.account.syncSummary();
  expect(syncDisplayOf(after, run.outcome)).toBe('synced');
  const confirmed = await savedLessonStandings(app.content, session.account, 'fr');
  expect(confirmed[0]).toMatchObject({ answered: 5, correct: 4, waiting: 0, refused: 0 });
  expect(confirmed[0].missedQuestionIds).toEqual([lesson.questions[4].id]); // the server agrees on the wrong answer

  // Redoing only the missed question and getting it right clears the review list.
  await answerQuestion(session.account, lesson, lesson.questions[4], SEED.correctFr[4], device.env);
  const redone = await savedLessonStandings(app.content, session.account, 'fr');
  expect(redone[0]).toMatchObject({ answered: 5, correct: 5, waiting: 1 });
  expect(redone[0].missedQuestionIds).toEqual([]);
});

test('switching accounts: the next student sees none of the first student’s progress, selection or Continue lesson', async () => {
  const a = await credentials('student_a');
  const b = await credentials('student_b');
  const app = await device.boot();
  let session = await app.sessions.signIn(a.email, a.password);
  const api = device.api(app.sessions, session);
  await refreshCatalog(api, app.content, 'fr', device.env);
  await saveLessonOffline(api, app.content, SEED.lessonId, 'fr', device.env);
  await session.account.setPreference(PREF_GRADE, '9AF');
  await session.account.setPreference(PREF_SUBJECT, 'mathematiques');
  await session.account.setPreference(PREF_LAST_LESSON, SEED.lessonId);
  const lesson = (await app.content.getLesson(SEED.lessonId, 'fr'))!;
  await answerQuestion(session.account, lesson, lesson.questions[0], SEED.correctFr[0], device.env);
  await completeLesson(session.account, lesson, device.env);
  await device.engine(app.sessions, session).run();
  await app.sessions.signOut();

  // Student B on the same phone. The lesson file is shared content; the progress is not.
  session = await app.sessions.signIn(b.email, b.password);
  expect(await session.account.getPreference(PREF_LAST_LESSON)).toBeNull();
  expect(await session.account.getPreference(PREF_GRADE)).toBeNull();
  const standings = await savedLessonStandings(app.content, session.account, 'fr');
  expect(standings).toHaveLength(1);
  expect(standings[0]).toMatchObject({ answered: 0, correct: 0, waiting: 0, completed: false });
  expect(standings[0].missedQuestionIds).toEqual([]);
  const path = await loadPath(app.content, session.account, 'fr', { grade: '9AF', subject: null });
  expect(path.subject).toBeNull();
  expect((await session.account.syncSummary()).pending).toBe(0);
  await app.sessions.signOut();

  // Student A returns: their own records are still there.
  session = await app.sessions.signIn(a.email, a.password);
  const back = await savedLessonStandings(app.content, session.account, 'fr');
  expect(back[0]).toMatchObject({ answered: 1, correct: 1, completed: true, completionState: 'synced' });
  expect(await session.account.getPreference(PREF_LAST_LESSON)).toBe(SEED.lessonId);
});
