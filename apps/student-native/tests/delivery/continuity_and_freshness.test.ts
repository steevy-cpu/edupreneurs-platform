/**
 * Online-only continuity (Home/Review/Profile data) and withdrawn/updated content, against real SQLite
 * and a fake API. No local stack.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { ApiError } from '../../src/core/api/errors';
import type { LessonResponse } from '../../src/core/api/types';
import { AccountStore } from '../../src/core/db/accountStore';
import { ContentStore } from '../../src/core/db/contentStore';
import { answerQuestion, completeLesson } from '../../src/core/learning/actions';
import {
  checkForUpdates,
  downloadForOffline,
  getDownloaded,
  lessonFreshness,
  openLesson,
  readOnline,
  removeDownloaded,
  SessionLessonCache,
} from '../../src/core/learning/contentAccess';
import { learningStandings, pickContinueLesson, totalsOf } from '../../src/core/learning/overview';
import { buildV1AccountDatabase, dumpV1Tables } from '../support/legacySchema';
import { nodeDatabases } from '../support/nodeSqlite';

const LESSON = 'b0000000-0000-4000-8000-000000000005';
const OTHER = 'b0000000-0000-4000-8000-000000000006';
const REV1 = 'c0000000-0000-4000-8000-000000000001';
const REV2 = 'c0000000-0000-4000-8000-000000000002';
const Q = (n: number) => `d0000000-0000-4000-8000-00000000010${n}`;

function lesson(id = LESSON, revisionId = REV1, revision = 1): LessonResponse {
  return {
    lesson_id: id,
    revision_id: revisionId,
    revision,
    locale: 'fr',
    title: id === LESSON ? 'Les fractions' : 'Les décimaux',
    blocks: [{ key: 'p1', type: 'paragraph', text: 'Texte' }],
    questions: [1, 2].map((n) => ({
      id: Q(id === LESSON ? n : n + 2),
      question_key: `q${n}`,
      position: n,
      kind: 'mcq',
      prompt: { text: `Question ${n}` },
      response_spec: { choices: [{ id: 'a', text: '1' }, { id: 'b', text: '2' }] },
      answer_key: { correct_choice_id: 'b' },
      explanation: { text: '.' },
    })),
    assessment_mode: 'offline_practice',
  } as unknown as LessonResponse;
}

class FakeApi {
  mode: 'ok' | 'offline' | 'gone' = 'ok';
  revision = { id: REV1, n: 1 };
  async getLesson(lessonId: string): Promise<LessonResponse> {
    if (this.mode === 'offline') throw new ApiError('network', 'network_error');
    if (this.mode === 'gone') throw new ApiError('client', 'lesson_not_found', 404);
    return lesson(lessonId, this.revision.id, this.revision.n);
  }
}

const catalogWith = (lessons: { id: string; revision_id: string }[]) =>
  ({ locale: 'fr', courses: [{ units: [{ lessons }] }] }) as any;

let dir: string;
let counter = 0;
const env = {
  newId: () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`,
  now: () => new Date('2026-11-26T10:00:00.000Z'),
};
beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'edu-continuity-'));
});
afterEach(() => fs.rmSync(dir, { recursive: true, force: true }));

async function device() {
  const dbs = nodeDatabases(dir);
  return {
    dbs,
    content: await ContentStore.open(await dbs('content')),
    a: await AccountStore.open(await dbs('account_a'), 'acct-a'),
    b: await AccountStore.open(await dbs('account_b'), 'acct-b'),
  };
}

describe('online-only continuity', () => {
  test('an answer writes the lesson reference in the same transaction, with public metadata only', async () => {
    const d = await device();
    const read = await readOnline(new FakeApi(), new SessionLessonCache(), LESSON, 'fr');
    await answerQuestion(d.a, read, read.questions[0], 'b', env);
    expect(await d.a.listLessonRefs('fr')).toEqual([
      { lessonId: LESSON, locale: 'fr', title: 'Les fractions', revisionId: REV1, revision: 1, at: env.now().toISOString() },
    ]);
    const raw = await d.dbs('account_a');
    const columns = (await raw.all<{ name: string }>('PRAGMA table_info(lesson_refs)')).map((c) => c.name);
    expect(columns).toEqual(['lesson_id', 'locale', 'title', 'revision_id', 'revision', 'last_opened_at']); // no content, no answers
    await raw.close();
  });

  test('if the answer cannot be written, no reference appears either', async () => {
    const d = await device();
    const read = await readOnline(new FakeApi(), new SessionLessonCache(), LESSON, 'fr');
    const failing = await AccountStore.open(await nodeDatabases(dir, { shouldFail: (sql) => /INSERT INTO outbox/.test(sql) })('account_a'), 'acct-a');
    await expect(answerQuestion(failing, read, read.questions[0], 'b', env)).rejects.toThrow(/SQLITE_FULL/);
    expect(await d.a.listLessonRefs('fr')).toEqual([]);
    expect(await d.a.attemptCount()).toBe(0);
  });

  test('an online-only lesson shows up as studied, with honest counts and no invented question total', async () => {
    const d = await device();
    const read = await readOnline(new FakeApi(), new SessionLessonCache(), LESSON, 'fr');
    await answerQuestion(d.a, read, read.questions[0], 'b', env); // correct
    await answerQuestion(d.a, read, read.questions[1], 'a', env); // wrong
    const standings = await learningStandings(d.content, d.a, 'fr');
    expect(standings).toHaveLength(1);
    expect(standings[0]).toMatchObject({
      lessonId: LESSON, availability: 'online', questionCount: null, answered: 2, correct: 1, waiting: 2, completed: false,
    });
    expect(standings[0].missedQuestionIds).toEqual([Q(2)]);
    expect(totalsOf(standings)).toMatchObject({ lessonsSaved: 0, lessonsStudied: 1, questionsAnswered: 2, questionsMissed: 1 });
    expect(pickContinueLesson(standings, LESSON)?.availability).toBe('online');
  });

  test('downloaded lessons come first; downloading an online lesson turns it into a downloaded one', async () => {
    const d = await device();
    const api = new FakeApi();
    const online = await readOnline(api, new SessionLessonCache(), LESSON, 'fr');
    await answerQuestion(d.a, online, online.questions[0], 'b', env);
    await downloadForOffline(api, d.content, OTHER, 'fr', env);
    let standings = await learningStandings(d.content, d.a, 'fr');
    expect(standings.map((s) => [s.lessonId, s.availability])).toEqual([[OTHER, 'downloaded'], [LESSON, 'online']]);
    await downloadForOffline(api, d.content, LESSON, 'fr', env);
    standings = await learningStandings(d.content, d.a, 'fr');
    expect(standings.map((s) => s.availability)).toEqual(['downloaded', 'downloaded']);
    expect(standings.find((s) => s.lessonId === LESSON)).toMatchObject({ availability: 'downloaded', answered: 1 });
  });

  test('removing a download keeps progress, pending operations and the lesson on Home as an online lesson', async () => {
    const d = await device();
    const api = new FakeApi();
    await downloadForOffline(api, d.content, LESSON, 'fr', env);
    const saved = (await getDownloaded(d.content, LESSON, 'fr'))!;
    await answerQuestion(d.a, saved, saved.questions[0], 'a', env);
    await completeLesson(d.a, saved, env);
    expect(await removeDownloaded(d.content, LESSON, 'fr', { account: d.a, now: env.now })).toBe(true);

    const standings = await learningStandings(d.content, d.a, 'fr');
    expect(standings).toHaveLength(1);
    expect(standings[0]).toMatchObject({ lessonId: LESSON, availability: 'online', answered: 1, completed: true, waiting: 1 });
    expect(await d.a.pendingOperations(10)).toHaveLength(2);
    expect(await d.content.getLessonInfo(LESSON, 'fr')).toBeNull();
  });

  test('another account never sees these references or this progress', async () => {
    const d = await device();
    const read = await readOnline(new FakeApi(), new SessionLessonCache(), LESSON, 'fr');
    await answerQuestion(d.a, read, read.questions[0], 'b', env);
    await d.a.touchLessonRef({ lessonId: OTHER, locale: 'fr', title: 'x', revisionId: REV1, revision: 1, at: env.now().toISOString() });
    expect(await d.b.listLessonRefs('fr')).toEqual([]);
    expect(await learningStandings(d.content, d.b, 'fr')).toEqual([]);
    expect(await d.a.listLessonRefs('ht')).toEqual([]); // per language
  });
});

describe('updated, withdrawn and unverifiable content', () => {
  const saved = (over: object = {}) => ({ lessonId: LESSON, revisionId: REV1, serverGoneAt: null, ...over });

  test('no catalog on the phone → unverified, never "current"', () => {
    expect(lessonFreshness(saved(), null)).toEqual({ state: 'unverified' });
  });

  test('a missing catalog entry is "not listed" — not proof that the saved lesson is current', () => {
    const cached = { catalog: catalogWith([{ id: OTHER, revision_id: REV1 }]), fetchedAt: '2026-11-25T08:00:00Z' };
    expect(lessonFreshness(saved(), cached)).toEqual({ state: 'not_listed', verifiedAt: '2026-11-25T08:00:00Z' });
  });

  test('same revision → current; different revision → update_available; both carry the verification time', () => {
    const at = '2026-11-25T08:00:00Z';
    expect(lessonFreshness(saved(), { catalog: catalogWith([{ id: LESSON, revision_id: REV1 }]), fetchedAt: at })).toEqual({ state: 'current', verifiedAt: at });
    expect(lessonFreshness(saved(), { catalog: catalogWith([{ id: LESSON, revision_id: REV2 }]), fetchedAt: at })).toEqual({ state: 'update_available', verifiedAt: at });
  });

  test('the server saying "not published" marks the copy withdrawn_confirmed; the copy and progress are kept', async () => {
    const d = await device();
    const api = new FakeApi();
    await downloadForOffline(api, d.content, LESSON, 'fr', env);
    const copy = (await getDownloaded(d.content, LESSON, 'fr'))!;
    await answerQuestion(d.a, copy, copy.questions[0], 'b', env);

    api.mode = 'gone';
    await expect(downloadForOffline(api, d.content, LESSON, 'fr', env)).rejects.toMatchObject({ status: 404 });
    expect(await checkForUpdates(d.content, LESSON, 'fr')).toBe('withdrawn_confirmed');
    expect((await getDownloaded(d.content, LESSON, 'fr'))!.questions).toHaveLength(2); // still readable
    expect(await d.a.pendingOperations(10)).toHaveLength(1); // pending answer kept
    expect((await d.a.questionProgress(LESSON)).size).toBe(1);
  });

  test('opening online with a saved copy and a 404 also records it, and offers the saved copy', async () => {
    const d = await device();
    const api = new FakeApi();
    await downloadForOffline(api, d.content, LESSON, 'fr', env);
    api.mode = 'gone';
    const result = await openLesson({ api, content: d.content, cache: new SessionLessonCache() }, LESSON, 'fr', 'online');
    expect(result).toMatchObject({ kind: 'unavailable', reason: 'not_found' });
    expect(result.kind === 'unavailable' && result.downloaded?.source).toBe('downloaded');
    expect(await checkForUpdates(d.content, LESSON, 'fr')).toBe('withdrawn_confirmed');
  });

  test('a network failure is NOT treated as withdrawal', async () => {
    const d = await device();
    const api = new FakeApi();
    await downloadForOffline(api, d.content, LESSON, 'fr', env);
    api.mode = 'offline';
    await openLesson({ api, content: d.content, cache: new SessionLessonCache() }, LESSON, 'fr', 'online');
    await expect(downloadForOffline(api, d.content, LESSON, 'fr', env)).rejects.toMatchObject({ kind: 'network' });
    expect(await checkForUpdates(d.content, LESSON, 'fr')).toBe('unverified'); // no catalog: nothing claimed either way
  });

  test('re-publishing: a later catalog that lists the lesson overrides the "gone" mark; a fresh download clears it', async () => {
    const d = await device();
    const api = new FakeApi();
    await downloadForOffline(api, d.content, LESSON, 'fr', env);
    await d.content.markServerGone(LESSON, 'fr', '2026-11-25T00:00:00Z');
    const info = (await d.content.getLessonInfo(LESSON, 'fr'))!;
    expect(lessonFreshness(info, null).state).toBe('withdrawn_confirmed');
    const later = { catalog: catalogWith([{ id: LESSON, revision_id: REV1 }]), fetchedAt: '2026-11-26T00:00:00Z' };
    expect(lessonFreshness(info, later).state).toBe('current');
    const earlier = { catalog: catalogWith([{ id: LESSON, revision_id: REV1 }]), fetchedAt: '2026-11-24T00:00:00Z' };
    expect(lessonFreshness(info, earlier).state).toBe('withdrawn_confirmed');

    api.revision = { id: REV2, n: 2 };
    await downloadForOffline(api, d.content, LESSON, 'fr', env);
    expect((await d.content.getLessonInfo(LESSON, 'fr'))!.serverGoneAt).toBeNull();
  });

  test('offline, the phone keeps reporting the time of its last check — it never claims a newer one', async () => {
    const d = await device();
    await downloadForOffline(new FakeApi(), d.content, LESSON, 'fr', env);
    await d.content.saveCatalog(catalogWith([{ id: LESSON, revision_id: REV1 }]), '2026-11-20T08:00:00Z');
    const info = (await d.content.getLessonInfo(LESSON, 'fr'))!;
    expect(lessonFreshness(info, await d.content.getCatalog('fr'))).toEqual({ state: 'current', verifiedAt: '2026-11-20T08:00:00Z' });
  });
});

describe('local schema upgrades', () => {
  test('account v4 → v5 keeps every row; lesson_refs is added empty', async () => {
    const open = nodeDatabases(dir);
    const raw = await open('account-up');
    await buildV1AccountDatabase(raw, 'acct-up');
    const before = await dumpV1Tables(raw);
    await raw.close();
    const store = await AccountStore.open(await open('account-up'), 'acct-up');
    expect(await store.listLessonRefs('fr')).toEqual([]);
    await store.close();
    const after = await open('account-up');
    expect(await dumpV1Tables(after)).toEqual(before);
    expect((await after.first<{ user_version: number }>('PRAGMA user_version'))!.user_version).toBe(5);
    await after.close();
  });

  test('content v1 → v3 keeps saved lessons and questions and adds server_gone_at (null)', async () => {
    const dbs = nodeDatabases(dir);
    const first = await ContentStore.open(await dbs('content'));
    await first.replaceLesson(lesson() as any, '2026-11-24T10:00:00.000Z');
    await first.close();
    // Simulate a phone that is still on content schema v1.
    const raw = await dbs('content');
    await raw.run('DROP TABLE download_requests');
    await raw.run('ALTER TABLE saved_lessons DROP COLUMN server_gone_at');
    await raw.run('PRAGMA user_version = 1');
    await raw.close();
    const upgraded = await ContentStore.open(await dbs('content'));
    const info = (await upgraded.getLessonInfo(LESSON, 'fr'))!;
    expect(info).toMatchObject({ revisionId: REV1, serverGoneAt: null });
    expect((await upgraded.getLesson(LESSON, 'fr'))!.questions).toHaveLength(2);
  });
});
