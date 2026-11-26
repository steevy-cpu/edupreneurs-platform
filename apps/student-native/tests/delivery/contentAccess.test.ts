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
  openLesson,
  readOnline,
  removeDownloaded,
  SessionLessonCache,
} from '../../src/core/learning/contentAccess';
import { FaultPlan, nodeDatabases } from '../support/nodeSqlite';

const LESSON = 'b0000000-0000-4000-8000-000000000005';
const REV1 = 'c0000000-0000-4000-8000-000000000001';
const REV2 = 'c0000000-0000-4000-8000-000000000002';
const Q1 = 'd0000000-0000-4000-8000-000000000101';
const Q2 = 'd0000000-0000-4000-8000-000000000102';

function lesson(revisionId = REV1, revision = 1): LessonResponse {
  return {
    lesson_id: LESSON,
    revision_id: revisionId,
    revision,
    locale: 'fr',
    title: 'Les fractions',
    blocks: [{ key: 'p1', type: 'paragraph', text: 'Une fraction…' }],
    questions: [Q1, Q2].map((id, i) => ({
      id,
      question_key: `q${i + 1}`,
      position: i + 1,
      kind: 'mcq',
      prompt: { text: `Question ${i + 1}` },
      response_spec: { choices: [{ id: 'a', text: '1' }, { id: 'b', text: '2' }] },
      answer_key: { correct_choice_id: 'b' },
      explanation: { text: '.' },
    })),
    assessment_mode: 'offline_practice',
  } as unknown as LessonResponse;
}

/** A fake API whose behaviour the test controls. Counts every lesson request. */
class FakeApi {
  calls = 0;
  mode: 'ok' | 'offline' | 'truncated' | 'not_found' = 'ok';
  body: unknown = lesson();
  async getLesson(): Promise<LessonResponse> {
    this.calls += 1;
    if (this.mode === 'offline') throw new ApiError('network', 'network_error');
    if (this.mode === 'not_found') throw new ApiError('client', 'lesson_not_found', 404);
    if (this.mode === 'truncated') throw new ApiError('network', 'invalid_response');
    return this.body as LessonResponse;
  }
}

const env = (() => {
  let n = 0;
  return {
    newId: () => `00000000-0000-4000-8000-${String(++n).padStart(12, '0')}`,
    now: () => new Date('2026-11-26T10:00:00.000Z'),
  };
})();

let dir: string;
let faults: FaultPlan | null;
const open = () => nodeDatabases(dir, faults ? { shouldFail: (sql) => Boolean(faults?.shouldFail(sql)) } : null);

async function device() {
  const dbs = open();
  const content = await ContentStore.open(await dbs('content'));
  const accountA = await AccountStore.open(await dbs('account_a'), 'acct-a');
  const accountB = await AccountStore.open(await dbs('account_b'), 'acct-b');
  return { content, accountA, accountB, close: () => Promise.all([content.close(), accountA.close(), accountB.close()]) };
}

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'edu-delivery-'));
  faults = null;
});
afterEach(() => fs.rmSync(dir, { recursive: true, force: true }));

describe('read online', () => {
  test('loads through the API without saving anything permanently', async () => {
    const d = await device();
    const api = new FakeApi();
    const cache = new SessionLessonCache();
    const result = await openLesson({ api, content: d.content, cache }, LESSON, 'fr', 'online');
    expect(result.kind).toBe('ready');
    if (result.kind === 'ready') {
      expect(result.lesson.source).toBe('online');
      expect(result.lesson.savedAt).toBeNull();
      expect(result.lesson.questions).toHaveLength(2);
    }
    expect(await d.content.listSavedLessons('fr')).toEqual([]);
    expect(await d.content.getLesson(LESSON, 'fr')).toBeNull();
    await d.close();
  });

  test('the in-memory copy is reused (no refetch for the exercises) and is not persisted', async () => {
    const d = await device();
    const api = new FakeApi();
    const cache = new SessionLessonCache();
    await readOnline(api, cache, LESSON, 'fr');
    await readOnline(api, cache, LESSON, 'fr');
    expect(api.calls).toBe(1);
    await readOnline(api, cache, LESSON, 'fr', { refresh: true });
    expect(api.calls).toBe(2);
    // A restart is a new cache: the lesson is not there.
    expect(new SessionLessonCache().get(LESSON, 'fr')).toBeNull();
    await d.close();
  });

  test('the cache is bounded and expires', async () => {
    let now = 0;
    const cache = new SessionLessonCache({ maxEntries: 2, ttlMs: 1000, clock: () => now });
    const make = (id: string) => ({ ...(({ lessonId: id, locale: 'fr', revisionId: REV1, revision: 1, title: 't', blocks: [], questions: [], source: 'online', savedAt: null }) as any) });
    cache.put(make('a'));
    cache.put(make('b'));
    cache.put(make('c'));
    expect(cache.size).toBe(2);
    expect(cache.get('a', 'fr')).toBeNull();
    now = 5000;
    expect(cache.get('c', 'fr')).toBeNull();
  });

  test('network failure: truthful reason, and the saved copy is offered when there is one', async () => {
    const d = await device();
    const api = new FakeApi();
    const cache = new SessionLessonCache();
    api.mode = 'offline';
    let result = await openLesson({ api, content: d.content, cache }, LESSON, 'fr', 'online');
    expect(result).toEqual({ kind: 'unavailable', reason: 'offline', downloaded: null });

    api.mode = 'ok';
    await downloadForOffline(api, d.content, LESSON, 'fr', env);
    api.mode = 'offline';
    result = await openLesson({ api, content: d.content, cache }, LESSON, 'fr', 'online');
    expect(result.kind).toBe('unavailable');
    if (result.kind === 'unavailable') expect(result.downloaded?.source).toBe('downloaded');

    api.mode = 'not_found';
    result = await openLesson({ api, content: d.content, cache: new SessionLessonCache() }, LESSON, 'fr', 'online');
    expect(result).toMatchObject({ kind: 'unavailable', reason: 'not_found' });
    await d.close();
  });

  test('a signed-out session cannot read online', async () => {
    const d = await device();
    const result = await openLesson({ api: null, content: d.content, cache: new SessionLessonCache() }, LESSON, 'fr', 'online');
    expect(result).toMatchObject({ kind: 'unavailable', reason: 'session' });
    await d.close();
  });

  test('truncated or corrupted content is rejected and never cached or saved', async () => {
    const d = await device();
    const api = new FakeApi();
    const cache = new SessionLessonCache();
    const bad: Array<(l: any) => void> = [
      (l) => { l.blocks = []; },
      (l) => { l.locale = 'ht'; },
      (l) => { l.lesson_id = 'b0000000-0000-4000-8000-00000000dead'; },
      (l) => { delete l.revision_id; },
      (l) => { l.questions[0].id = 'not-a-uuid'; },
    ];
    for (const corrupt of bad) {
      const body: any = lesson();
      corrupt(body);
      api.body = body;
      const result = await openLesson({ api, content: d.content, cache }, LESSON, 'fr', 'online');
      expect(result).toMatchObject({ kind: 'unavailable', reason: 'invalid' });
    }
    api.body = '<html>captive portal</html>';
    expect(await openLesson({ api, content: d.content, cache }, LESSON, 'fr', 'online')).toMatchObject({ kind: 'unavailable' });
    expect(cache.size).toBe(0);
    expect(await d.content.listSavedLessons('fr')).toEqual([]);
    await d.close();
  });

  test('opening without the network and without a saved copy is "missing", not an error', async () => {
    const d = await device();
    const api = new FakeApi();
    api.mode = 'offline';
    const result = await openLesson({ api, content: d.content, cache: new SessionLessonCache() }, LESSON, 'fr', 'saved');
    expect(result).toEqual({ kind: 'missing' });
    expect(api.calls).toBe(0);
    await d.close();
  });
});

describe('download for offline study', () => {
  test('downloaded lesson opens with no network after a full restart', async () => {
    let d = await device();
    const api = new FakeApi();
    expect((await downloadForOffline(api, d.content, LESSON, 'fr', env)).outcome).toBe('new');
    await d.close();

    d = await device(); // force-quit and relaunch: new connections, same files
    api.mode = 'offline';
    const result = await openLesson({ api, content: d.content, cache: new SessionLessonCache() }, LESSON, 'fr', 'saved');
    expect(result.kind).toBe('ready');
    if (result.kind === 'ready') {
      expect(result.lesson.source).toBe('downloaded');
      expect(result.lesson.questions).toHaveLength(2);
    }
    expect(api.calls).toBe(1); // only the download itself
    await d.close();
  });

  test('an interrupted or failing update leaves the previous copy intact', async () => {
    const d = await device();
    const api = new FakeApi();
    await downloadForOffline(api, d.content, LESSON, 'fr', env);

    api.body = lesson(REV2, 2);
    api.mode = 'truncated';
    await expect(downloadForOffline(api, d.content, LESSON, 'fr', env)).rejects.toBeInstanceOf(ApiError);
    expect((await getDownloaded(d.content, LESSON, 'fr'))!.revisionId).toBe(REV1);

    // Storage failure while writing the new revision (disk full): the transaction rolls back.
    api.mode = 'ok';
    faults = { shouldFail: (sql) => /INSERT INTO saved_questions/.test(sql) };
    const failing = await device();
    await expect(downloadForOffline(api, failing.content, LESSON, 'fr', env)).rejects.toThrow(/SQLITE_FULL/);
    await failing.close();
    faults = null;
    const after = await device();
    const kept = await getDownloaded(after.content, LESSON, 'fr');
    expect(kept!.revisionId).toBe(REV1);
    expect(kept!.questions).toHaveLength(2);

    expect((await downloadForOffline(api, after.content, LESSON, 'fr', env)).outcome).toBe('updated');
    expect((await getDownloaded(after.content, LESSON, 'fr'))!.revisionId).toBe(REV2);
    await after.close();
    await d.close();
  });

  test('update status comes from the cached catalog', async () => {
    const d = await device();
    const api = new FakeApi();
    expect(await checkForUpdates(d.content, LESSON, 'fr')).toBe('not_downloaded');
    await downloadForOffline(api, d.content, LESSON, 'fr', env);
    const catalog = (revisionId: string) => ({
      locale: 'fr',
      courses: [{ units: [{ lessons: [{ id: LESSON, revision_id: revisionId }] }] }],
    });
    await d.content.saveCatalog(catalog(REV1) as any, '2026-11-26T10:00:00Z');
    expect(await checkForUpdates(d.content, LESSON, 'fr')).toBe('up_to_date');
    await d.content.saveCatalog(catalog(REV2) as any, '2026-11-26T10:00:00Z');
    expect(await checkForUpdates(d.content, LESSON, 'fr')).toBe('update_available');
    await d.close();
  });
});

describe("the student's work is durable and independent of how the lesson was opened", () => {
  test('answers to an ONLINE-ONLY lesson are saved locally and stay pending with no network', async () => {
    const d = await device();
    const api = new FakeApi();
    const read = await readOnline(api, new SessionLessonCache(), LESSON, 'fr');
    api.mode = 'offline'; // the connection disappears right after the lesson was read

    const question = read.questions[0];
    const receipt = await answerQuestion(d.accountA, read, question, 'b', env);
    expect(receipt.isCorrect).toBe(true);

    const pending = await d.accountA.pendingOperations(10);
    expect(pending).toHaveLength(1);
    expect(pending[0].opId).toBe(receipt.opId);
    expect(pending[0].payload).toMatchObject({
      question_revision_id: Q1,
      response: { choice_id: 'b' },
    });
    expect((await d.accountA.questionProgress(LESSON)).get(Q1)?.lastIsCorrect).toBe(true);
    // And still nothing was downloaded.
    expect(await d.content.listSavedLessons('fr')).toEqual([]);

    // Survives a restart.
    await d.close();
    const again = await device();
    expect(await again.accountA.pendingOperations(10)).toHaveLength(1);
    await again.close();
  });

  test('completing an online-read lesson is recorded once', async () => {
    const d = await device();
    const read = await readOnline(new FakeApi(), new SessionLessonCache(), LESSON, 'fr');
    expect(await completeLesson(d.accountA, read, env)).toBe(true);
    expect(await completeLesson(d.accountA, read, env)).toBe(false);
    expect((await d.accountA.lessonProgress(LESSON))?.completed).toBe(true);
    await d.close();
  });

  test('removing a download never deletes progress, attempts or pending operations', async () => {
    const d = await device();
    const api = new FakeApi();
    await downloadForOffline(api, d.content, LESSON, 'fr', env);
    const saved = (await getDownloaded(d.content, LESSON, 'fr'))!;
    await answerQuestion(d.accountA, saved, saved.questions[0], 'a', env);
    await completeLesson(d.accountA, saved, env);

    expect(await removeDownloaded(d.content, LESSON, 'fr')).toBe(true);
    expect(await removeDownloaded(d.content, LESSON, 'fr')).toBe(false);
    expect(await getDownloaded(d.content, LESSON, 'fr')).toBeNull();
    expect(await d.content.getLessonInfo(LESSON, 'fr')).toBeNull();

    expect(await d.accountA.pendingOperations(10)).toHaveLength(2);
    expect((await d.accountA.questionProgress(LESSON)).get(Q1)?.lastIsCorrect).toBe(false);
    expect((await d.accountA.lessonProgress(LESSON))?.completed).toBe(true);
    await d.close();
  });

  test('another account on the same phone sees none of this student’s records, online or downloaded', async () => {
    const d = await device();
    const api = new FakeApi();
    const read = await readOnline(api, new SessionLessonCache(), LESSON, 'fr');
    await answerQuestion(d.accountA, read, read.questions[0], 'b', env);
    await completeLesson(d.accountA, read, env);

    expect(await d.accountB.pendingOperations(10)).toEqual([]);
    expect((await d.accountB.questionProgress(LESSON)).size).toBe(0);
    expect(await d.accountB.lessonProgress(LESSON)).toBeNull();
    await d.close();
  });
});
