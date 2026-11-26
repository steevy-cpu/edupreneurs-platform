/**
 * Every experience flag ON at once: the additions sit together without
 * displacing the learning content, and none of them stands between a learner
 * and a saved lesson — including when the server cannot be reached.
 */
import React from 'react';

import { answerQuestion } from '../../src/core/learning/actions';
import { PREF_GRADE } from '../../src/core/learning/overview';
import Home from '../../src/app/home';
import LessonReader from '../../src/app/lesson/[id]';
import Onboarding from '../../src/app/onboarding';
import Profile from '../../src/app/profile';
import Quiz from '../../src/app/quiz/[id]';
import { FakeRemote, RestartablePhone, sampleRewards, sampleWord } from '../support/experienceHarness';
import { navigation } from '../support/expoRouterMock';
import { resetFlags } from '../support/flagsMock';
import { catalog, LESSON_ID, lessonSnapshot } from '../support/screenHarness';

const mockHolder: { phone: RestartablePhone | null; remote: FakeRemote | null } = { phone: null, remote: null };
jest.mock('../../src/ui/AppContext', () => ({ useApp: () => mockHolder.phone!.app }));
jest.mock('../../src/ui/remote', () => ({ useRemote: () => mockHolder.remote }));
jest.mock('../../src/core/experience/flags', () => require('../support/flagsMock').flagsModule);

let phone: RestartablePhone;
let remote: FakeRemote;
const SAVED_AT = '2026-11-24T10:00:00.000Z';

beforeEach(async () => {
  phone = (await new RestartablePhone().start()) as RestartablePhone;
  remote = new FakeRemote();
  remote.dailyWords.fr = sampleWord('2026-11-24', 'fr');
  remote.rewards = sampleRewards(120);
  mockHolder.phone = phone;
  mockHolder.remote = remote;
  navigation.calls.length = 0;
  navigation.params = {};
  resetFlags('onboarding', 'tour', 'onboardingSync', 'dailyWord', 'rewards', 'leaderboardReview');
});

afterEach(async () => {
  await phone.dispose();
});

async function returningLearnerWithWork() {
  const app = await phone.signIn('student.a');
  app.services.env.now = () => new Date('2026-11-24T15:00:00.000Z');
  await app.session.account.setPreference(PREF_GRADE, '9AF'); // used the app before: no onboarding
  await phone.content.saveCatalog(catalog('fr'), SAVED_AT);
  await phone.content.replaceLesson(lessonSnapshot('fr'), SAVED_AT);
  const lesson = (await phone.content.getLesson(LESSON_ID, 'fr'))!;
  await answerQuestion(app.session.account, lesson, lesson.questions[0], 'b', { ...app.services.env, now: () => new Date('2026-11-24T14:00:00.000Z') });
  await app.refreshSummary();
  return app;
}

test('Accueil: lesson first, then pending work, Gold, the word, review, downloads, and the tour offer last', async () => {
  await returningLearnerWithWork();
  const screen = await phone.render(<Home />);
  await screen.settle();
  const texts = screen.texts();
  const order = [
    'Continuer ma leçon',
    '1 action(s) en attente de synchronisation',
    'Gold confirmé : 120',
    'Mot du jour',
    'Refaire les exercices',
    'Mes leçons téléchargées',
    'Découvre l’application',
  ].map((marker) => texts.findIndex((text) => text.includes(marker)));
  expect(order.every((index) => index >= 0)).toBe(true);
  expect(order).toEqual([...order].sort((a, b) => a - b));
  const tabs = screen.pressables().filter((node) => node.props.accessibilityRole === 'tab');
  expect(tabs).toHaveLength(4);
});

test('Profil: still four tabs; Gold, tour replay and the leaderboard review are entries inside the screen', async () => {
  await returningLearnerWithWork();
  const screen = await phone.render(<Profile />);
  await screen.settle();
  expect(screen.pressables().filter((node) => node.props.accessibilityRole === 'tab')).toHaveLength(4);
  expect(screen.texts()).toEqual(expect.arrayContaining(['Gold et série', '120', 'Synchronisation', 'Langue', 'Mon compte']));
  expect(screen.labels()).toEqual(
    expect.arrayContaining(['Revoir la visite guidée. 4 étapes · sans internet', 'Classement (aperçu). Écran en cours de revue, sans vrais élèves', 'Se déconnecter']),
  );
});

test('server unreachable, everything on: Accueil, a saved lesson and its exercises open and an answer is saved', async () => {
  remote.mode = 'offline';
  const app = await returningLearnerWithWork();
  const home = await phone.render(<Home />);
  await home.settle();
  expect(home.redirect()).toBeNull();
  expect(home.has('Résoudre une équation simple')).toBe(true);
  await home.press('Continuer ma leçon');
  expect(navigation.calls).toEqual([`push /lesson/${LESSON_ID}`]);

  navigation.params = { id: LESSON_ID };
  const lesson = await phone.render(<LessonReader />);
  expect(lesson.has('Une équation est une égalité.')).toBe(true);

  const quiz = await phone.render(<Quiz />);
  await quiz.press(/x = 7/);
  await quiz.press('Valider');
  expect(quiz.has('Réponse enregistrée sur ce téléphone')).toBe(true);
  expect((await app.session.account.syncSummary()).pending).toBe(2);
});

test('a brand-new account with everything on and no network: onboarding can be skipped in one tap and nothing else is in the way', async () => {
  remote.mode = 'offline';
  await phone.signIn('student.a');
  expect((await phone.render(<Home />)).redirect()).toBe('/onboarding');
  const flow = await phone.render(<Onboarding />);
  await flow.settle();
  await flow.press('Passer l’introduction');
  expect(navigation.calls).toEqual(['replace /home']);
  const home = await phone.render(<Home />);
  await home.settle();
  expect(home.redirect()).toBeNull();
  expect(home.has('Choisis ta première leçon')).toBe(true);
});
