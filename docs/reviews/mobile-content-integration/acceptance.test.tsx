// Copy into apps/student-native/tests/delivery/ in a disposable candidate checkout.
import React from 'react';
import Home from '../../src/app/home';
import Review from '../../src/app/review';
import { ApiError } from '../../src/core/api/errors';
import { requestJson } from '../../src/core/api/http';
import { answerQuestion, completeLesson } from '../../src/core/learning/actions';
import { checkForUpdates, downloadForOffline, openLesson, readOnline } from '../../src/core/learning/contentAccess';
import { Phone, lessonSnapshot, OTHER_LESSON_ID as id } from '../support/screenHarness';

const mockPhone: { current?: Phone } = {};
jest.mock('../../src/ui/AppContext', () => ({ useApp: () => mockPhone.current!.app }));

function revision(n: number) {
  const snapshot = lessonSnapshot('fr', id);
  const uuid = (k: number) => '00000000-0000-4000-a000-' + String(k).padStart(12, '0');
  return { ...snapshot, revision: n, revision_id: uuid(n),
    questions: snapshot.questions.map((q, i) => ({ ...q, id: uuid(10 * n + i) })) };
}

let phone: Phone;
beforeEach(async () => {
  phone = await new Phone().start();
  mockPhone.current = phone;
  await phone.signIn('student.a');
});
afterEach(async () => phone.dispose());

const api = (n: number) => ({ getLesson: async () => revision(n) });

it.each([['Home', Home, 'homeEmptyTitle'], ['Réviser', Review, 'reviewEmptyTitle']] as const)(
  '%s shows online-only work instead of the first-use state', async (_name, Screen, emptyTitle) => {
    const { services, session, t } = phone.app;
    const lesson = await readOnline(api(1), services.lessonCache, id, 'fr');
    await answerQuestion(session.account, lesson, lesson.questions[0], 'a', services.env);
    await completeLesson(session.account, lesson, services.env);
    expect(await session.account.attemptCount()).toBe(1);
    expect(await phone.content.getLesson(id, 'fr')).toBeNull();
    const screen = await phone.render(<Screen />);
    expect(screen.has(t(emptyTitle))).toBe(false);
  });

it('a delayed earlier download cannot replace a later explicit download', async () => {
  const { env } = phone.app.services;
  let release!: () => void;
  let started!: () => void;
  const entered = new Promise<void>(r => { started = r; });
  const gate = new Promise<void>(r => { release = r; });
  const slow = { getLesson: async () => { started(); await gate; return revision(1); } };
  const first = downloadForOffline(slow, phone.content, id, 'fr', env);
  await entered;
  try { await downloadForOffline(api(2), phone.content, id, 'fr', env); }
  finally { release(); await first; }
  expect((await phone.content.getLesson(id, 'fr'))?.revision).toBe(2);
});

it('an incomplete paragraph cannot replace a readable saved revision', async () => {
  const { env } = phone.app.services;
  await downloadForOffline(api(1), phone.content, id, 'fr', env);
  const incomplete = { ...revision(2), blocks: [{ key: 'p', type: 'paragraph' }] };
  try { await downloadForOffline({ getLesson: async () => incomplete }, phone.content, id, 'fr', env); }
  catch { /* refusal is fine; the previous revision must survive */ }
  expect((await phone.content.getLesson(id, 'fr'))?.revision).toBe(1);
});

it('a saved lesson absent from a fresh catalog cannot be declared current', async () => {
  const { env } = phone.app.services;
  await downloadForOffline(api(1), phone.content, id, 'fr', env);
  await phone.content.saveCatalog({ locale: 'fr', courses: [] }, env.now().toISOString());
  expect(await checkForUpdates(phone.content, id, 'fr')).not.toBe('up_to_date');
});

it('a reachable service returning 503 is not evidence that the phone is offline', async () => {
  const failing = { getLesson: async () => { throw new ApiError('server', 'unavailable', 503); } };
  const result = await openLesson({ api: failing, content: phone.content, cache: phone.app.services.lessonCache }, id, 'fr', 'online');
  expect(result.kind).toBe('unavailable');
  expect(result).not.toMatchObject({ reason: 'offline' });
});

it('a response outside the practice contract never enters the practice store', async () => {
  const snapshot = { ...revision(2), assessment_mode: 'synthetic_unsupported_mode' };
  // Deliberately untyped wire response, as with runtime JSON decoding.
  const malformed = { getLesson: async () => JSON.parse(JSON.stringify(snapshot)) };
  try { await downloadForOffline(malformed, phone.content, id, 'fr', phone.app.services.env); }
  catch { /* assert the observable storage outcome below */ }
  expect(await phone.content.getLesson(id, 'fr')).toBeNull();
});

it('a late body is discarded after the session aborts', async () => {
  const ctrl = new AbortController();
  let finish!: (value: string) => void;
  let reading!: () => void;
  const entered = new Promise<void>(r => { reading = r; });
  const body = new Promise<string>(r => { finish = r; });
  const response = { status: 200, text: () => { reading(); return body; } } as Response;
  const pending = requestJson(async () => response, 'https://unused.invalid', {},
    { timeoutMs: 1000, sessionSignal: ctrl.signal });
  await entered;
  ctrl.abort();
  finish('{}');
  await expect(pending).rejects.toMatchObject({ kind: 'aborted' });
});

it('keeps queued work with its learner across A to B to A', async () => {
  const a = phone.app;
  const lesson = await readOnline(api(1), a.services.lessonCache, id, 'fr');
  await answerQuestion(a.session.account, lesson, lesson.questions[0], 'b', a.services.env);
  const b = await phone.signIn('student.b');
  expect(await b.session.account.attemptCount()).toBe(0);
  expect((await b.session.account.syncSummary()).pending).toBe(0);
  const back = await phone.signIn('student.a');
  expect(await back.session.account.attemptCount()).toBe(1);
  expect((await back.session.account.syncSummary()).pending).toBe(1);
});

it('preflight rejects a service DSN from a different disposable port', () => {
  const { deriveTarget } = require('../support/localStack');
  const configText = 'project_id = "qa-example"\n[api]\nport = 41001\n[db]\nport = 41002\n';
  const env = {
    LOCAL_ADMIN_DATABASE_URL: 'postgresql://localhost:41002/postgres',
    LOCAL_SUPABASE_URL: 'http://localhost:41001',
    EDU_DATABASE_URL: 'postgresql+asyncpg://localhost:42002/postgres',
  };
  expect(() => deriveTarget({ configText, env, processEnv: {}, isRunning: () => true })).toThrow();
});
