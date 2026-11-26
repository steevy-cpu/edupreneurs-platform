/**
 * Online reading, through the real Apprendre / Leçon / Exercices screens over real SQLite,
 * with a fake API that the test can switch off. No network, no local stack.
 */
import React from 'react';

import Learn from '../../src/app/learn';
import LessonReader from '../../src/app/lesson/[id]';
import Quiz from '../../src/app/quiz/[id]';
import { ApiError } from '../../src/core/api/errors';
import type { LessonResponse, Locale } from '../../src/core/api/types';
import { PREF_GRADE, PREF_LAST_LESSON, PREF_SUBJECT } from '../../src/core/learning/overview';
import { navigation } from '../support/expoRouterMock';
import { catalog, lessonSnapshot, OTHER_LESSON_ID, Phone } from '../support/screenHarness';

const mockHolder: { phone: Phone | null } = { phone: null };
jest.mock('../../src/ui/AppContext', () => ({ useApp: () => mockHolder.phone!.app }));

const uuid = (n: number) => `a0000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

/** The harness snapshot, with the UUID identifiers a real server sends (the app validates them). */
function serverLesson(locale: Locale = 'fr'): LessonResponse {
  const base = lessonSnapshot(locale, OTHER_LESSON_ID);
  return {
    ...base,
    revision_id: uuid(1),
    questions: base.questions.map((q, i) => ({ ...q, id: uuid(100 + i) })),
  } as LessonResponse;
}

class FakeApi {
  online = true;
  calls = 0;
  async getLesson(lessonId: string, locale: Locale): Promise<LessonResponse> {
    this.calls += 1;
    if (!this.online) throw new ApiError('network', 'network_error');
    expect(lessonId).toBe(OTHER_LESSON_ID);
    return serverLesson(locale);
  }
}

let phone: Phone;
let api: FakeApi;

beforeEach(async () => {
  phone = await new Phone().start();
  mockHolder.phone = phone;
  navigation.calls.length = 0;
  navigation.params = {};
  api = new FakeApi();
});
afterEach(async () => phone.dispose());

async function signIn(locale: Locale = 'fr') {
  const app = await phone.signIn('student.a', locale);
  app.api = api;
  return app;
}

describe('read online', () => {
  test('shows the lesson as online-only, saves nothing, and is remembered as an online lesson', async () => {
    const app = await signIn();
    navigation.params = { id: OTHER_LESSON_ID, mode: 'online' };
    const screen = await phone.render(<LessonReader />);
    expect(screen.text()).toContain('Une équation est une égalité.');
    expect(screen.has('En ligne · non téléchargée')).toBe(true);
    expect(screen.has('Disponible hors connexion')).toBe(false);
    expect(screen.labels()).toContain('Télécharger pour étudier hors ligne');

    expect(await phone.content.listSavedLessons('fr')).toEqual([]);
    // Remembered for Home/Review as an ONLINE lesson: a minimal reference, not the lesson.
    expect(await app.session.account.getPreference(PREF_LAST_LESSON)).toBe(OTHER_LESSON_ID);
    expect((await app.session.account.listLessonRefs('fr')).map((r) => r.lessonId)).toEqual([OTHER_LESSON_ID]);

    await screen.press('Faire les exercices');
    expect(navigation.calls).toContain(`push /quiz/${OTHER_LESSON_ID}?mode=online`);
  });

  test('"Télécharger" saves it; only then is it shown as available offline', async () => {
    await signIn();
    navigation.params = { id: OTHER_LESSON_ID, mode: 'online' };
    const screen = await phone.render(<LessonReader />);
    expect(await phone.content.getLesson(OTHER_LESSON_ID, 'fr')).toBeNull();
    await screen.press('Télécharger pour étudier hors ligne');
    await screen.settle();
    expect((await phone.content.getLesson(OTHER_LESSON_ID, 'fr'))!.revisionId).toBe(uuid(1));
    expect(screen.has('Disponible hors connexion')).toBe(true);
    expect(screen.has('En ligne · non téléchargée')).toBe(false);
    await screen.press('Faire les exercices');
    expect(navigation.calls).toContain(`push /quiz/${OTHER_LESSON_ID}`); // no ?mode=online any more
  });

  test('a failed download says so and stays online-only', async () => {
    await signIn();
    navigation.params = { id: OTHER_LESSON_ID, mode: 'online' };
    const screen = await phone.render(<LessonReader />);
    api.online = false;
    await screen.press('Télécharger pour étudier hors ligne');
    await screen.settle();
    expect(screen.has('Téléchargement impossible. Réessaie quand tu as une connexion.')).toBe(true);
    expect(screen.has('En ligne · non téléchargée')).toBe(true);
    expect(await phone.content.getLesson(OTHER_LESSON_ID, 'fr')).toBeNull();
  });

  test('no connection and no saved copy: a truthful error with a retry, nothing invented', async () => {
    await signIn();
    api.online = false;
    navigation.params = { id: OTHER_LESSON_ID, mode: 'online' };
    const screen = await phone.render(<LessonReader />);
    expect(screen.has('Impossible de charger la leçon : pas de connexion Internet.')).toBe(true);
    expect(screen.labels()).toContain('Réessayer');
    expect(screen.labels()).not.toContain('Ouvrir la version enregistrée');

    api.online = true; // back online: retry loads it
    await screen.press('Réessayer');
    await screen.settle();
    expect(screen.has('En ligne · non téléchargée')).toBe(true);
  });

  test('no connection but a saved copy exists: the saved copy is offered', async () => {
    await signIn();
    await phone.content.replaceLesson(serverLesson(), '2026-11-24T10:00:00.000Z');
    api.online = false;
    navigation.params = { id: OTHER_LESSON_ID, mode: 'online' };
    const screen = await phone.render(<LessonReader />);
    expect(screen.has('Impossible de charger la leçon : pas de connexion Internet.')).toBe(true);
    await screen.press('Ouvrir la version enregistrée');
    expect(navigation.calls).toContain(`replace /lesson/${OTHER_LESSON_ID}`);
  });

  test('Haitian Creole labels render (draft strings, pending educator review)', async () => {
    await signIn('ht');
    navigation.params = { id: OTHER_LESSON_ID, mode: 'online' };
    const screen = await phone.render(<LessonReader />);
    expect(screen.has('Sou entènèt · pa telechaje')).toBe(true);
    expect(screen.labels()).toContain('Telechaje pou etidye san entènèt');
  });
});

describe('answers while reading online', () => {
  test('the answer is committed locally and stays pending when the connection drops right after', async () => {
    const app = await signIn();
    navigation.params = { id: OTHER_LESSON_ID, mode: 'online' };
    await phone.render(<LessonReader />); // fills the in-memory copy
    api.online = false; // the connection disappears
    const screen = await phone.render(<Quiz />);
    // (same params: the quiz reuses the in-memory copy, so it needs no network)
    expect(screen.has('Question 1 sur 2')).toBe(true);
    expect(screen.has('Tes réponses sont enregistrées sur ce téléphone, même sans connexion.')).toBe(true);

    await screen.press('x = 7');
    await screen.press('Valider');
    await screen.settle();
    expect(screen.has('Réponse enregistrée sur ce téléphone')).toBe(true);
    const account = app.session.account;
    expect(await account.attemptCount()).toBe(1);
    expect((await account.syncSummary()).pending).toBe(1);
    expect(await phone.content.getLesson(OTHER_LESSON_ID, 'fr')).toBeNull(); // still not downloaded
  });

  test('the next student on the phone sees none of it', async () => {
    const a = await signIn();
    navigation.params = { id: OTHER_LESSON_ID, mode: 'online' };
    const reader = await phone.render(<LessonReader />);
    await reader.press('J’ai terminé la leçon');
    expect((await a.session.account.lessonProgress(OTHER_LESSON_ID))!.completed).toBe(true);

    const b = await phone.signIn('student.b');
    expect(await b.session.account.lessonProgress(OTHER_LESSON_ID)).toBeNull();
    expect((await b.session.account.syncSummary()).pending).toBe(0);
    expect(await b.session.account.getPreference(PREF_GRADE)).toBeNull();
    expect(await b.session.account.getPreference(PREF_SUBJECT)).toBeNull();
  });
});

describe('Apprendre offers both modes', () => {
  test('a lesson that is not downloaded has "Lire maintenant" and "Télécharger"; a downloaded one has neither', async () => {
    const app = await signIn();
    await phone.content.saveCatalog(catalog('fr'), '2026-11-24T10:00:00.000Z');
    await phone.content.replaceLesson(lessonSnapshot('fr'), '2026-11-24T10:00:00.000Z');
    await app.session.account.setPreference(PREF_GRADE, '9AF');
    await app.session.account.setPreference(PREF_SUBJECT, 'mathematiques');
    const screen = await phone.render(<Learn />);
    expect(screen.labels().filter((l) => l === 'Lire maintenant')).toHaveLength(1);
    expect(screen.labels().filter((l) => l === 'Télécharger')).toHaveLength(1);
  });
});
