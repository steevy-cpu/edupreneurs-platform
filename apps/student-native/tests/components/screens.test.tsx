/**
 * The redesigned screens, rendered for real (Mobile-02).
 *
 * Each test puts records into real SQLite files, renders the actual screen
 * component and reads back what a student would see or have read aloud.
 * See tests/support/screenHarness.tsx for what is real and what is a stand-in.
 */
import React from 'react';

import { PREF_GRADE, PREF_LAST_LESSON, PREF_SUBJECT } from '../../src/core/learning/overview';
import { answerQuestion, completeLesson } from '../../src/core/learning/actions';
import Home from '../../src/app/home';
import Learn from '../../src/app/learn';
import LessonReader from '../../src/app/lesson/[id]';
import Profile from '../../src/app/profile';
import Quiz from '../../src/app/quiz/[id]';
import Review from '../../src/app/review';
import { navigation } from '../support/expoRouterMock';
import { Alert } from '../support/reactNativeMock';
import { catalog, LESSON_ID, lessonSnapshot, OTHER_LESSON_ID, Phone } from '../support/screenHarness';

const mockHolder: { phone: Phone | null } = { phone: null };
jest.mock('../../src/ui/AppContext', () => ({ useApp: () => mockHolder.phone!.app }));

let phone: Phone;
const SAVED_AT = '2026-11-24T10:00:00.000Z';

beforeEach(async () => {
  phone = await new Phone().start();
  mockHolder.phone = phone;
  navigation.calls.length = 0;
  navigation.params = {};
  Alert.calls.length = 0;
});

afterEach(async () => {
  await phone.dispose();
});

async function saveLesson() {
  await phone.content.saveCatalog(catalog('fr'), SAVED_AT);
  await phone.content.replaceLesson(lessonSnapshot('fr'), SAVED_AT);
  return (await phone.content.getLesson(LESSON_ID, 'fr'))!;
}

describe('Accueil', () => {
  test('nothing saved: an invitation to choose a lesson, no Continue card, no statistics', async () => {
    await phone.signIn('student.a');
    const screen = await phone.render(<Home />);
    expect(screen.has('Bonjour student.a')).toBe(true);
    expect(screen.has('Choisis ta première leçon')).toBe(true);
    expect(screen.labels()).not.toContain('Continuer ma leçon');
    expect(screen.text()).not.toMatch(/\d+ sur \d+|%/); // no numbers at all on an empty home
    await screen.press('Voir les matières');
    expect(navigation.calls).toEqual(['replace /learn']);
  });

  test('the four tabs are Accueil, Apprendre, Réviser, Profil', async () => {
    await phone.signIn('student.a');
    const screen = await phone.render(<Home />);
    const tabs = screen.pressables().filter((node) => node.props.accessibilityRole === 'tab');
    expect(tabs.map((tab) => tab.props.accessibilityLabel)).toEqual(['Accueil', 'Apprendre', 'Réviser', 'Profil']);
    expect(tabs.map((tab) => tab.props.accessibilityState.selected)).toEqual([true, false, false, false]);
    await screen.press('Profil');
    expect(navigation.calls).toEqual(['replace /profile']);
  });

  test('Haitian Creole: the tabs read Akèy, Aprann, Revize, Pwofil', async () => {
    await phone.signIn('student.a', 'ht');
    const screen = await phone.render(<Home />);
    const tabs = screen.pressables().filter((node) => node.props.accessibilityRole === 'tab');
    expect(tabs.map((tab) => tab.props.accessibilityLabel)).toEqual(['Akèy', 'Aprann', 'Revize', 'Pwofil']);
    expect(screen.has('Bonjou student.a')).toBe(true);
  });

  test('a saved lesson: Continue card with the real answered count and pending work', async () => {
    const app = await phone.signIn('student.a');
    const lesson = await saveLesson();
    await answerQuestion(app.session.account, lesson, lesson.questions[0], 'b', app.services.env);
    await app.refreshSummary();
    const screen = await phone.render(<Home />);
    expect(screen.has('Résoudre une équation simple')).toBe(true);
    expect(screen.has('Mathématiques · 9AF · Leçon 1')).toBe(true);
    expect(screen.has('1 sur 2 exercices faits')).toBe(true);
    expect(screen.has('Disponible hors connexion')).toBe(true);
    expect(screen.labels()).toContain('1 action(s) en attente de synchronisation. Enregistré sur ce téléphone');
    expect(screen.has('Tout est synchronisé')).toBe(false);
    await screen.press('Continuer ma leçon');
    expect(navigation.calls).toEqual([`push /lesson/${LESSON_ID}`]);
  });

  test('signed out: the screen redirects to sign-in instead of showing anything', async () => {
    const app = await phone.signIn('student.a');
    (app as { session: unknown }).session = null;
    const screen = await phone.render(<Home />);
    expect(screen.redirect()).toBe('/sign-in');
    expect(screen.texts()).toEqual([]);
  });
});

describe('Apprendre', () => {
  test('path from the cached catalog: downloaded lesson is the next step, the other must be downloaded', async () => {
    const app = await phone.signIn('student.a');
    const lesson = await saveLesson();
    await app.session.account.setPreference(PREF_GRADE, '9AF');
    await app.session.account.setPreference(PREF_SUBJECT, 'mathematiques');
    let screen = await phone.render(<Learn />);
    expect(screen.has('Équations du premier degré')).toBe(true);
    expect(screen.has('0 sur 2 leçon(s) terminée(s)')).toBe(true);
    expect(screen.labels()).toContain('Leçon 1. Résoudre une équation simple. Étape suivante. Enregistrée sur ce téléphone');
    // The lesson that is not on the phone is offered in two explicit ways: read now (online) or download.
    expect(screen.has('Vérifier une solution')).toBe(true);
    expect(screen.has('Disponible en ligne')).toBe(true);
    expect(screen.labels()).toContain('Lire maintenant');
    expect(screen.labels()).toContain('Télécharger');
    navigation.calls.length = 0;
    await screen.press(/^Leçon 2\./);
    expect(navigation.calls).toEqual([`push /lesson/${OTHER_LESSON_ID}?mode=online`]);
    navigation.calls.length = 0;
    await screen.press(/^Leçon 1\./);
    expect(navigation.calls).toEqual([`push /lesson/${LESSON_ID}`]);

    // Completion is lesson-level and comes from the completion record only.
    await completeLesson(app.session.account, lesson, app.services.env);
    screen = await phone.render(<Learn />);
    expect(screen.labels()).toContain('Leçon 1. Résoudre une équation simple. Terminé. Enregistrée sur ce téléphone');
    expect(screen.has('1 sur 2 leçon(s) terminée(s)')).toBe(true);
    // A finished lesson can still be opened again.
    navigation.calls.length = 0;
    await screen.press(/^Leçon 1\./);
    expect(navigation.calls).toEqual([`push /lesson/${LESSON_ID}`]);
  });

  test('choosing a grade then a subject stores the selection for this account', async () => {
    const app = await phone.signIn('student.a');
    await phone.content.saveCatalog(catalog('fr'), SAVED_AT);
    const screen = await phone.render(<Learn />);
    expect(screen.has('Choisis d’abord ta classe et ta matière.')).toBe(true);
    await screen.press('9AF');
    await screen.press('Mathématiques');
    expect(await app.session.account.getPreference(PREF_GRADE)).toBe('9AF');
    expect(await app.session.account.getPreference(PREF_SUBJECT)).toBe('mathematiques');
    expect(screen.has('Équations du premier degré')).toBe(true);
  });

  test('no catalog on the phone yet: a clear message, and saved lessons stay reachable', async () => {
    await phone.signIn('student.a');
    await phone.content.replaceLesson(lessonSnapshot('fr'), SAVED_AT);
    const screen = await phone.render(<Learn />);
    expect(screen.has('Aucun cours disponible pour l’instant. Connecte-toi à Internet puis réessaie.')).toBe(true);
    expect(screen.labels()).toContain('Résoudre une équation simple. Disponible hors connexion');
  });
});

describe('Leçon', () => {
  test('shows only what the saved lesson contains, and remembers it as the last lesson', async () => {
    const app = await phone.signIn('student.a');
    await saveLesson();
    navigation.params = { id: LESSON_ID };
    const screen = await phone.render(<LessonReader />);
    const text = screen.text();
    for (const expected of [
      'Résoudre une équation simple',
      'Mathématiques · 9AF',
      'Équations du premier degré · Version 3',
      'Disponible hors connexion',
      'La règle de la balance',
      'Une équation est une égalité.',
      'Exemple guidé',
      'x + 5 = 12',
      'On retire 5',
      'Vérifie toujours ta réponse.',
      'Bloc d’un type inconnu.', // unknown block types fall back to their text
    ]) {
      expect(text).toContain(expected);
    }
    // Design-00 preview elements with no data behind them must not appear.
    for (const absent of ['Objectif', 'À retenir', 'Jude', 'indice', 'Comprendre', '1/4']) {
      expect(text).not.toContain(absent);
    }
    expect(await app.session.account.getPreference(PREF_LAST_LESSON)).toBe(LESSON_ID);

    await screen.press('J’ai terminé la leçon');
    expect((await app.session.account.lessonProgress(LESSON_ID))!.completed).toBe(true);
    expect(screen.labels()).toContain('Leçon terminée');
    expect(app.calls).toContain('syncNow');
    await screen.press('Faire les exercices');
    expect(navigation.calls).toContain(`push /quiz/${LESSON_ID}`);
  });

  test('a lesson that is not on the phone says so', async () => {
    await phone.signIn('student.a');
    navigation.params = { id: 'not-saved' };
    const screen = await phone.render(<LessonReader />);
    expect(screen.has('Cette leçon n’est pas enregistrée sur ce téléphone.')).toBe(true);
  });
});

describe('Exercices', () => {
  test('feedback and "saved on this phone" appear only after the answer is committed to SQLite', async () => {
    const app = await phone.signIn('student.a');
    await saveLesson();
    navigation.params = { id: LESSON_ID };
    const account = app.session.account;
    const original = account.recordAnswer.bind(account);
    let release: () => void = () => undefined;
    account.recordAnswer = async (answer) => {
      await new Promise<void>((resolve) => (release = resolve)); // hold the write
      return original(answer);
    };

    const screen = await phone.render(<Quiz />);
    expect(screen.has('Question 1 sur 2')).toBe(true);
    expect(screen.find('Valider').props.disabled).toBe(true); // nothing chosen yet
    await screen.press('x = 7');
    await screen.press('Valider');

    // The write has not finished: no verdict, no "saved", nothing counted.
    expect(screen.has('Réponse enregistrée sur ce téléphone')).toBe(false);
    expect(screen.has('Bonne réponse !')).toBe(false);
    expect(await account.attemptCount()).toBe(0);
    expect(app.calls).not.toContain('syncNow');

    release();
    await screen.settle();
    expect(await account.attemptCount()).toBe(1);
    expect((await account.syncSummary()).pending).toBe(1);
    expect(screen.has('Bonne réponse !')).toBe(true);
    expect(screen.has('Réponse enregistrée sur ce téléphone')).toBe(true);
    expect(screen.has('Explication 1')).toBe(true);
    expect(screen.labels()).toContain('x = 7. Bonne réponse !');
    expect(app.calls).toContain('syncNow'); // sync is attempted only after the local commit
    expect(screen.has('Synchronisé')).toBe(false);

    await screen.press('Question suivante');
    expect(screen.has('Question 2 sur 2')).toBe(true);
    account.recordAnswer = original;
    await screen.press('x = 7'); // wrong for question 2
    await screen.press('Valider');
    expect(screen.has('Ce n’est pas la bonne réponse.')).toBe(true);
    expect(screen.has('La bonne réponse : x = 2')).toBe(true);
    await screen.press('Voir mon résultat');
    expect(screen.has('Tu as 1 bonne(s) réponse(s) sur 2.')).toBe(true);
    expect(screen.has('Résultat provisoire : il sera confirmé à la synchronisation.')).toBe(true);
  });

  test('if the write fails, nothing is confirmed and the student is told to retry', async () => {
    const app = await phone.signIn('student.a');
    await saveLesson();
    navigation.params = { id: LESSON_ID };
    app.session.account.recordAnswer = async () => {
      throw new Error('disk full');
    };
    const screen = await phone.render(<Quiz />);
    await screen.press('x = 7');
    await screen.press('Valider');
    expect(screen.has('La réponse n’a pas pu être enregistrée. Réessaie.')).toBe(true);
    expect(screen.has('Réponse enregistrée sur ce téléphone')).toBe(false);
    expect(screen.has('Bonne réponse !')).toBe(false);
    expect(screen.find('Valider').props.disabled).toBe(false); // can try again
  });
});

describe('Réviser', () => {
  test('nothing saved: a path to the lessons, no review counts', async () => {
    await phone.signIn('student.a');
    const screen = await phone.render(<Review />);
    expect(screen.has('Rien à réviser pour l’instant')).toBe(true);
    expect(screen.text()).not.toMatch(/\d/);
  });

  test('real counts, and a "my mistakes" run limited to questions last answered wrongly', async () => {
    const app = await phone.signIn('student.a');
    const lesson = await saveLesson();
    let screen = await phone.render(<Review />);
    expect(screen.has('Exercices pas encore commencés')).toBe(true);
    expect(screen.labels().some((label) => label.startsWith('Revoir mes erreurs'))).toBe(false);

    await answerQuestion(app.session.account, lesson, lesson.questions[0], 'b', app.services.env); // right
    await answerQuestion(app.session.account, lesson, lesson.questions[1], 'b', app.services.env); // wrong
    screen = await phone.render(<Review />);
    expect(screen.has('2 sur 2 faits · 1 bonne(s) réponse(s)')).toBe(true);
    expect(screen.has('En attente de synchronisation')).toBe(true);
    await screen.press('Revoir mes erreurs (1)');
    expect(navigation.calls).toEqual([`push /quiz/${LESSON_ID}?only=missed`]);

    navigation.params = { id: LESSON_ID, only: 'missed' };
    const quiz = await phone.render(<Quiz />);
    expect(quiz.has('Question 1 sur 1')).toBe(true);
    expect(quiz.has('Résous : 5x = 10')).toBe(true);
    expect(quiz.has('Résous : x + 5 = 12')).toBe(false);
  });
});

describe('Profil', () => {
  test('work waiting for the server is never presented as synchronised', async () => {
    const app = await phone.signIn('student.a');
    const lesson = await saveLesson();
    await answerQuestion(app.session.account, lesson, lesson.questions[0], 'b', app.services.env);
    await answerQuestion(app.session.account, lesson, lesson.questions[1], 'b', app.services.env);
    await app.refreshSummary();

    for (const outcome of [null, 'offline', 'error', 'auth_required'] as const) {
      app.sync.lastReport = outcome === null ? null : { outcome, confirmed: 0, needsAttention: 0, pulled: 0, errorCode: 'x' };
      const screen = await phone.render(<Profile />);
      const text = screen.text();
      expect(text).toContain('2 action(s) en attente de synchronisation');
      expect(text).toContain('En attente de synchronisation (2)');
      expect(text).not.toContain('Tout est synchronisé');
      expect(screen.texts()).not.toContain('Synchronisé');
      if (outcome === 'offline') {
        expect(text).toContain('Envoi impossible pour le moment');
        expect(text).toContain('Serveur injoignable.');
        expect(text).toContain('Hors ligne');
      }
    }
  });

  test('"Serveur injoignable" only when the server could not be reached; a server that answered 503 is not that', async () => {
    const app = await phone.signIn('student.a');
    const base = { confirmed: 0, needsAttention: 0, pulled: 0 };
    app.sync.lastReport = { ...base, outcome: 'offline', errorCode: 'unreachable' };
    expect((await phone.render(<Profile />)).text()).toContain('Serveur injoignable.');
    app.sync.lastReport = { ...base, outcome: 'offline', errorCode: 'dependency_unavailable', serverAnswered: true };
    expect((await phone.render(<Profile />)).text()).not.toContain('Serveur injoignable.');
  });

  test('it is a profile, not only a progress page: account, progress, sync, language, sign-out', async () => {
    const app = await phone.signIn('student.a');
    const lesson = await saveLesson();
    await app.session.account.setPreference(PREF_GRADE, '9AF');
    await app.session.account.setPreference(PREF_SUBJECT, 'mathematiques');
    await answerQuestion(app.session.account, lesson, lesson.questions[0], 'b', app.services.env);
    await app.refreshSummary();
    const screen = await phone.render(<Profile />);
    const text = screen.text();
    for (const expected of [
      'Profil',
      'student.a@edupreneur.test',
      'Mathématiques · 9AF',
      'Ma progression',
      '0/1',
      'Leçons terminées',
      '1/1',
      'Réponses correctes',
      '1 question(s) répondue(s) sur 2',
      'Synchronisation',
      'Langue',
      'Mon compte',
    ]) {
      expect(text).toContain(expected);
    }
    expect(text).not.toMatch(/Objectif de la semaine|semaine/); // no invented weekly goal
    await screen.press('Kreyòl');
    expect(app.calls).toContain('setLocale ht');
    await screen.press('Synchroniser maintenant');
    expect(app.calls).toContain('syncNow');
  });

  test('sign-out with unsynchronised work warns first; "keep my work" signs out without deleting', async () => {
    const app = await phone.signIn('student.a');
    const lesson = await saveLesson();
    await answerQuestion(app.session.account, lesson, lesson.questions[0], 'b', app.services.env);
    await app.refreshSummary();
    const screen = await phone.render(<Profile />);
    await screen.press('Se déconnecter');
    expect(app.calls).not.toContain('signOut');
    expect(Alert.calls).toHaveLength(1);
    expect(Alert.calls[0].title).toBe('Travail non synchronisé');
    expect(Alert.calls[0].message).toContain('1 action(s) ne sont pas encore envoyées au serveur');
    expect(Alert.calls[0].buttons.map((button) => button.text)).toEqual([
      'Annuler',
      'Synchroniser d’abord',
      'Se déconnecter et garder mon travail',
    ]);
    Alert.calls[0].buttons[2].onPress!();
    await screen.settle();
    expect(app.calls).toContain('signOut');
    expect((await app.session.account.syncSummary()).pending).toBe(1); // the work is still in this account's database
  });

  test('sign-out with nothing pending needs no warning', async () => {
    const app = await phone.signIn('student.a');
    const screen = await phone.render(<Profile />);
    await screen.press('Se déconnecter');
    expect(Alert.calls).toHaveLength(0);
    expect(app.calls).toContain('signOut');
  });

  test('the next student on the same phone sees none of the first student’s progress', async () => {
    const a = await phone.signIn('student.a');
    const lesson = await saveLesson();
    await a.session.account.setPreference(PREF_LAST_LESSON, LESSON_ID);
    await answerQuestion(a.session.account, lesson, lesson.questions[0], 'b', a.services.env);
    await answerQuestion(a.session.account, lesson, lesson.questions[1], 'b', a.services.env);

    await phone.signIn('student.b');
    const profile = await phone.render(<Profile />);
    expect(profile.has('student.b@edupreneur.test')).toBe(true);
    expect(profile.has('student.a@edupreneur.test')).toBe(false);
    expect(profile.has('0 question(s) répondue(s) sur 2')).toBe(true);
    expect(profile.has('0/0')).toBe(true);
    expect(profile.has('en attente de synchronisation')).toBe(false);
    expect(profile.has('Tout est synchronisé')).toBe(true); // B truly has nothing waiting

    const home = await phone.render(<Home />);
    expect(home.has('Bonjour student.b')).toBe(true);
    expect(home.has('0 sur 2 exercices faits')).toBe(true);
    const review = await phone.render(<Review />);
    expect(review.has('Exercices pas encore commencés')).toBe(true);
    expect(review.labels().some((label) => label.startsWith('Revoir mes erreurs'))).toBe(false);
  });
});
