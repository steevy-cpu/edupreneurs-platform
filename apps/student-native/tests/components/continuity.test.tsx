/**
 * Home / Review / Profile / reader / quiz for a student who studies ONLINE, and for content that was
 * updated or withdrawn. Real screens over real SQLite, fake API, no stack.
 */
import React from 'react';

import Home from '../../src/app/home';
import Learn from '../../src/app/learn';
import LessonReader from '../../src/app/lesson/[id]';
import Profile from '../../src/app/profile';
import Quiz from '../../src/app/quiz/[id]';
import Review from '../../src/app/review';
import { ApiError } from '../../src/core/api/errors';
import type { LessonResponse, Locale } from '../../src/core/api/types';
import { answerQuestion } from '../../src/core/learning/actions';
import { downloadForOffline, readOnline, removeDownloaded } from '../../src/core/learning/contentAccess';
import { PREF_GRADE, PREF_SUBJECT } from '../../src/core/learning/overview';
import { navigation } from '../support/expoRouterMock';
import { catalog, lessonSnapshot, OTHER_LESSON_ID, Phone } from '../support/screenHarness';

const mockHolder: { phone: Phone | null } = { phone: null };
jest.mock('../../src/ui/AppContext', () => ({ useApp: () => mockHolder.phone!.app }));

const uuid = (n: number) => `a0000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
function serverLesson(locale: Locale = 'fr'): LessonResponse {
  const base = lessonSnapshot(locale, OTHER_LESSON_ID);
  return { ...base, revision_id: uuid(1), questions: base.questions.map((q, i) => ({ ...q, id: uuid(100 + i) })) } as LessonResponse;
}
class FakeApi {
  mode: 'ok' | 'offline' | 'gone' = 'ok';
  async getLesson(_id: string, locale: Locale): Promise<LessonResponse> {
    if (this.mode === 'offline') throw new ApiError('network', 'network_error');
    if (this.mode === 'gone') throw new ApiError('client', 'lesson_not_found', 404);
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
/** The student read the lesson online and answered the first question (correct), then the network went away. */
async function studyOnline(app: Awaited<ReturnType<typeof signIn>>) {
  navigation.params = { id: OTHER_LESSON_ID, mode: 'online' };
  await phone.render(<LessonReader />);
  const read = await readOnline(api, app.services.lessonCache, OTHER_LESSON_ID, app.locale);
  await answerQuestion(app.session.account, read, read.questions[0], 'b', app.services.env);
  api.mode = 'offline';
}

describe('Accueil continues an online lesson, and says so', () => {
  test('hero shows the online badge and "Continuer en ligne"; it opens the lesson in online mode', async () => {
    const app = await signIn();
    await studyOnline(app);
    const screen = await phone.render(<Home />);
    expect(screen.labels()).toContain('Continuer en ligne');
    expect(screen.labels()).not.toContain('Continuer ma leçon');
    expect(screen.text()).toContain('En ligne · non téléchargée');
    expect(screen.text()).not.toContain('Disponible hors connexion');
    expect(screen.has('Leçons étudiées en ligne')).toBe(true);
    expect(screen.has('Mes leçons téléchargées')).toBe(false);
    await screen.press('Continuer en ligne');
    expect(navigation.calls).toContain(`push /lesson/${OTHER_LESSON_ID}?mode=online`);
  });

  test('with no connection the online continuation explains it instead of failing silently', async () => {
    const app = await signIn();
    await studyOnline(app); // network is now off
    navigation.params = { id: OTHER_LESSON_ID, mode: 'online' };
    app.services.lessonCache.clear(); // a new app run: nothing in memory
    const screen = await phone.render(<LessonReader />);
    expect(screen.has('Impossible de charger la leçon : pas de connexion Internet.')).toBe(true);
    expect(screen.labels()).toContain('Réessayer');
  });

  test('a downloaded lesson keeps the normal "Continuer ma leçon"', async () => {
    const app = await signIn();
    await phone.content.saveCatalog(catalog('fr'), '2026-11-24T10:00:00.000Z');
    await phone.content.replaceLesson(lessonSnapshot('fr'), '2026-11-24T10:00:00.000Z');
    navigation.params = { id: 'lesson-1' };
    await phone.render(<LessonReader />); // opened → remembered
    const screen = await phone.render(<Home />);
    expect(screen.labels()).toContain('Continuer ma leçon');
    expect(screen.text()).toContain('Disponible hors connexion');
    expect(app.session.account).toBeTruthy();
  });

  test('after the download is removed, Home still offers the lesson (online) with the same progress', async () => {
    const app = await signIn();
    await downloadForOffline(api, phone.content, OTHER_LESSON_ID, 'fr', app.services.env);
    const saved = (await phone.content.getLesson(OTHER_LESSON_ID, 'fr'))!;
    await answerQuestion(app.session.account, saved, saved.questions[0], 'b', app.services.env);
    await removeDownloaded(phone.content, OTHER_LESSON_ID, 'fr', { account: app.session.account, now: app.services.env.now });
    const screen = await phone.render(<Home />);
    expect(screen.labels()).toContain('Continuer en ligne');
    expect((await app.session.account.syncSummary()).pending).toBe(1);
  });
});

describe('Réviser and Profil include online activity', () => {
  test('Réviser lists the online lesson with its real counts and a retry-by-mistakes path in online mode', async () => {
    const app = await signIn();
    await studyOnline(app);
    const read = await readOnline({ getLesson: async () => serverLesson() }, app.services.lessonCache, OTHER_LESSON_ID, 'fr');
    await answerQuestion(app.session.account, read, read.questions[1], 'b', app.services.env); // wrong for q2 (correct is 'a')
    const screen = await phone.render(<Review />);
    expect(screen.text()).toContain('2 faits · 1 bonne(s) réponse(s)');
    expect(screen.text()).toContain('Lecture en ligne : une connexion est nécessaire.');
    await screen.press(/^Revoir/);
    expect(navigation.calls.some((c) => c === `push /quiz/${OTHER_LESSON_ID}?only=missed&mode=online`)).toBe(true);
  });

  test('Profil counts online lessons and answers, without inventing a question total', async () => {
    const app = await signIn();
    await studyOnline(app);
    const screen = await phone.render(<Profile />);
    expect(screen.text()).toContain('1 question(s) répondue(s)');
    expect(screen.text()).not.toMatch(/répondue\(s\) sur/);
    expect(screen.text()).toContain('1/1'); // correct answers
  });

  test('the next student on the phone sees none of it', async () => {
    const app = await signIn();
    await studyOnline(app);
    await phone.signIn('student.b');
    const screen = await phone.render(<Home />);
    expect(screen.labels()).not.toContain('Continuer en ligne');
    expect(screen.has('Leçons étudiées en ligne')).toBe(false);
    void app;
  });
});

describe('Exercices online: a clear failure, then retry', () => {
  test('no connection and no copy: reason + Réessayer; retry works when back online', async () => {
    const app = await signIn();
    api.mode = 'offline';
    navigation.params = { id: OTHER_LESSON_ID, mode: 'online' };
    const screen = await phone.render(<Quiz />);
    expect(screen.has('Impossible de charger la leçon : pas de connexion Internet.')).toBe(true);
    api.mode = 'ok';
    await screen.press('Réessayer');
    await screen.settle();
    expect(screen.has('Question 1 sur 2')).toBe(true);
    void app;
  });
});

describe('updated and withdrawn lessons', () => {
  async function savedWithCatalog(listed: boolean, fetchedAt = '2026-11-24T10:00:00.000Z') {
    const app = await signIn();
    const cat = catalog('fr');
    if (!listed) cat.courses[0].units[0].lessons = cat.courses[0].units[0].lessons.filter((l) => l.id !== 'lesson-1');
    await phone.content.saveCatalog(cat, fetchedAt);
    await phone.content.replaceLesson(lessonSnapshot('fr'), '2026-11-24T09:00:00.000Z');
    await app.session.account.setPreference(PREF_GRADE, '9AF');
    await app.session.account.setPreference(PREF_SUBJECT, 'mathematiques');
    return app;
  }

  test('not listed in the last catalog: the reader says so, with the date, and keeps the lesson readable', async () => {
    await savedWithCatalog(false);
    navigation.params = { id: 'lesson-1' };
    const screen = await phone.render(<LessonReader />);
    expect(screen.text()).toContain('Cette leçon n’est plus proposée (vérifié le ');
    expect(screen.text()).toContain('Hors connexion, ce téléphone ne peut pas voir les changements plus récents.');
    expect(screen.text()).toContain('Une équation est une égalité.'); // still readable
    expect(screen.labels()).toContain('J’ai terminé la leçon'); // progress still possible
  });

  test('listed and current: the reader shows the last verification date, not "up to date"', async () => {
    await savedWithCatalog(true);
    navigation.params = { id: 'lesson-1' };
    const screen = await phone.render(<LessonReader />);
    expect(screen.text()).toMatch(/Dernière vérification : \d\d\/\d\d\/\d{4}/);
    expect(screen.text()).not.toContain('n’est plus proposée');
  });

  test('no catalog ever fetched: "not verified yet"', async () => {
    await signIn();
    await phone.content.replaceLesson(lessonSnapshot('fr'), '2026-11-24T09:00:00.000Z');
    navigation.params = { id: 'lesson-1' };
    const screen = await phone.render(<LessonReader />);
    expect(screen.has('Mise à jour pas encore vérifiée')).toBe(true);
  });

  test('a newer published revision: notice and an Update button in the reader', async () => {
    await savedWithCatalog(true);
    const cat = catalog('fr');
    cat.courses[0].units[0].lessons[0].revision_id = 'lesson-1-fr-r4';
    await phone.content.saveCatalog(cat, '2026-11-25T10:00:00.000Z');
    navigation.params = { id: 'lesson-1' };
    const screen = await phone.render(<LessonReader />);
    expect(screen.has('Nouvelle version disponible')).toBe(true);
    expect(screen.labels()).toContain('Mettre à jour');
  });

  test('server confirmed withdrawal: path row says so, reader keeps the copy and the student’s work', async () => {
    const app = await savedWithCatalog(true);
    await phone.content.markServerGone('lesson-1', 'fr', '2026-11-25T12:00:00.000Z');
    const path = await phone.render(<Learn />);
    expect(path.text()).toContain('Retirée par le serveur · ta progression est conservée');
    navigation.params = { id: 'lesson-1' };
    const reader = await phone.render(<LessonReader />);
    expect(reader.text()).toContain('Le serveur indique que cette leçon est retirée.');
    await reader.press('J’ai terminé la leçon');
    expect((await app.session.account.lessonProgress('lesson-1'))!.completed).toBe(true);
  });

  test('Haitian Creole: the withdrawal and verification texts render', async () => {
    await phone.signIn('student.a', 'ht');
    await phone.content.saveCatalog(catalog('ht'), '2026-11-24T10:00:00.000Z');
    await phone.content.replaceLesson(lessonSnapshot('ht'), '2026-11-24T09:00:00.000Z');
    await phone.content.markServerGone('lesson-1', 'ht', '2026-11-25T12:00:00.000Z');
    navigation.params = { id: 'lesson-1' };
    const reader = await phone.render(<LessonReader />);
    expect(reader.text()).toContain('Sèvè a di leson sa a retire.');
  });
});

describe('after choosing only a class (e.g. 7AF)', () => {
  test('Apprendre asks for the subject specifically, and Profil shows the class', async () => {
    const app = await signIn();
    await phone.content.saveCatalog(catalog('fr'), '2026-11-24T10:00:00.000Z');
    await app.session.account.setPreference(PREF_GRADE, '9AF');
    const learn = await phone.render(<Learn />);
    expect(learn.has('Choisis ta matière pour voir les leçons.')).toBe(true);
    expect(learn.has('Choisis d’abord ta classe et ta matière.')).toBe(false);
    const profile = await phone.render(<Profile />);
    expect(profile.text()).toContain('9AF · matière à choisir');
    expect(profile.text()).not.toContain('Choisis d’abord ta classe et ta matière.');
  });

  test('a class with no courses on this phone (7AF): says so, instead of asking to choose a class again', async () => {
    const app = await signIn();
    await phone.content.saveCatalog(catalog('fr'), '2026-11-24T10:00:00.000Z'); // only 9AF
    await app.session.account.setPreference(PREF_GRADE, '7AF');
    const learn = await phone.render(<Learn />);
    expect(learn.has('Pas encore de cours pour 7AF. Choisis une autre classe, ou connecte-toi pour mettre la liste à jour.')).toBe(true);
    expect(learn.has('Choisis d’abord ta classe et ta matière.')).toBe(false);
    const profile = await phone.render(<Profile />);
    expect(profile.text()).toContain('7AF');
    expect(profile.text()).not.toContain('7AF · matière à choisir');
  });

  test('Haitian Creole', async () => {
    const app = await signIn('ht');
    await phone.content.saveCatalog(catalog('ht'), '2026-11-24T10:00:00.000Z');
    await app.session.account.setPreference(PREF_GRADE, '9AF');
    const learn = await phone.render(<Learn />);
    expect(learn.has('Chwazi matyè ou pou wè leson yo.')).toBe(true);
  });

  test('nothing chosen yet keeps the original wording', async () => {
    await signIn();
    await phone.content.saveCatalog(catalog('fr'), '2026-11-24T10:00:00.000Z');
    const learn = await phone.render(<Learn />);
    expect(learn.has('Choisis d’abord ta classe et ta matière.')).toBe(true);
  });
});
