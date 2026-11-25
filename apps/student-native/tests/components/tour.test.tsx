/**
 * The optional product tour, rendered for real over real SQLite files.
 * Behind the `tour` client flag, OFF by default.
 */
import React from 'react';

import { TOUR_VERSION } from '../../src/core/experience/tour';
import Home from '../../src/app/home';
import LessonReader from '../../src/app/lesson/[id]';
import Profile from '../../src/app/profile';
import Quiz from '../../src/app/quiz/[id]';
import Tour from '../../src/app/tour';
import { RestartablePhone } from '../support/experienceHarness';
import { navigation } from '../support/expoRouterMock';
import { resetFlags } from '../support/flagsMock';
import { catalog, LESSON_ID, lessonSnapshot } from '../support/screenHarness';

const mockHolder: { phone: RestartablePhone | null } = { phone: null };
jest.mock('../../src/ui/AppContext', () => ({ useApp: () => mockHolder.phone!.app }));
jest.mock('../../src/ui/remote', () => ({ useRemote: () => null }));
jest.mock('../../src/core/experience/flags', () => require('../support/flagsMock').flagsModule);

let phone: RestartablePhone;
const SAVED_AT = '2026-11-24T10:00:00.000Z';
const TOUR_WORDS = /Visite guidée|Découvre l’application|Vizit gide|Dekouvri aplikasyon an/;

beforeEach(async () => {
  phone = (await new RestartablePhone().start()) as RestartablePhone;
  mockHolder.phone = phone;
  navigation.calls.length = 0;
  navigation.params = {};
  navigation.canGoBack = false;
  resetFlags('tour');
});

afterEach(async () => {
  await phone.dispose();
});

async function saveLesson() {
  await phone.content.saveCatalog(catalog('fr'), SAVED_AT);
  await phone.content.replaceLesson(lessonSnapshot('fr'), SAVED_AT);
}

describe('flag off (the default)', () => {
  test('no offer on Accueil, no entry in Profil, the route goes home, nothing is written', async () => {
    resetFlags();
    const app = await phone.signIn('student.a');
    await saveLesson();
    expect((await phone.render(<Home />)).text()).not.toMatch(TOUR_WORDS);
    const profile = await phone.render(<Profile />);
    expect(profile.text()).not.toMatch(TOUR_WORDS);
    expect(profile.labels().some((label) => label.startsWith('Revoir la visite'))).toBe(false);
    const tour = await phone.render(<Tour />);
    expect(tour.redirect()).toBe('/home');
    expect(await app.session.account.experience.getTour()).toMatchObject({ versionSeen: 0, inProgress: false });
  });
});

describe('the offer on Accueil', () => {
  test('it is a card under the learning content, not in front of it', async () => {
    await phone.signIn('student.a');
    await saveLesson();
    const screen = await phone.render(<Home />);
    const texts = screen.texts();
    expect(texts).toContain('Découvre l’application');
    expect(screen.has('Une visite en 4 étapes. Elle fonctionne sans internet.')).toBe(true);
    // The Continue action and the downloaded lessons come first.
    expect(texts.indexOf('Découvre l’application')).toBeGreaterThan(texts.indexOf('Continuer ma leçon'));
    expect(texts.indexOf('Découvre l’application')).toBeGreaterThan(texts.indexOf('Mes leçons téléchargées'));
    // The primary action of the screen is still the lesson.
    await screen.press('Continuer ma leçon');
    expect(navigation.calls).toEqual([`push /lesson/${LESSON_ID}`]);
  });

  test('with nothing downloaded it comes after the invitation to choose a lesson', async () => {
    await phone.signIn('student.a');
    const texts = (await phone.render(<Home />)).texts();
    expect(texts.indexOf('Découvre l’application')).toBeGreaterThan(texts.indexOf('Choisis ta première leçon'));
  });

  test('"Commencer la visite" opens the tour route', async () => {
    const app = await phone.signIn('student.a');
    const screen = await phone.render(<Home />);
    await screen.press('Commencer la visite');
    expect(navigation.calls).toEqual(['push /tour']);
    expect(await app.session.account.experience.getTour()).toMatchObject({ inProgress: true, step: 0 });
  });

  test('"Non merci" removes the card at once and for good', async () => {
    const app = await phone.signIn('student.a');
    let screen = await phone.render(<Home />);
    await screen.press('Non merci');
    expect(screen.text()).not.toMatch(TOUR_WORDS);
    expect(navigation.calls).toEqual([]);
    expect(await app.session.account.experience.getTour()).toMatchObject({ dismissed: true, versionSeen: TOUR_VERSION });
    await phone.kill();
    await phone.signIn('student.a');
    screen = await phone.render(<Home />);
    expect(screen.text()).not.toMatch(TOUR_WORDS);
  });
});

describe('the tour itself', () => {
  test('French: four steps, then back to where the learner was; not offered again', async () => {
    const app = await phone.signIn('student.a');
    navigation.canGoBack = true;
    const screen = await phone.render(<Tour />);
    const pages: [string, string, string][] = [
      ['1/4 · Accueil', 'Reprends où tu t’es arrêté', 'Où : onglet Accueil'],
      ['2/4 · Apprendre', 'Choisis et télécharge tes leçons', 'Où : onglet Apprendre'],
      ['3/4 · Réviser', 'Refais tes exercices', 'Où : onglet Réviser'],
      ['4/4 · Profil', 'Ta progression et tes réglages', 'Où : onglet Profil'],
    ];
    for (const [index, [progress, title, where]] of pages.entries()) {
      expect(screen.has(progress)).toBe(true);
      expect(screen.has(title)).toBe(true);
      expect(screen.has(where)).toBe(true);
      expect(screen.has('Visite guidée')).toBe(true);
      if (index < pages.length - 1) {
        expect(screen.labels()).toEqual(expect.arrayContaining(['Suivant', 'Fermer la visite'])); // closable at every step
        await screen.press('Suivant');
      }
    }
    await screen.press('Terminer la visite');
    expect(navigation.calls).toEqual(['back']);
    expect(await app.session.account.experience.getTour()).toMatchObject({ versionSeen: TOUR_VERSION, dismissed: false, inProgress: false });
    expect((await phone.render(<Home />)).text()).not.toMatch(TOUR_WORDS);
  });

  test('Haitian Creole: offer, four steps and the Profil entry', async () => {
    await phone.signIn('student.a', 'ht');
    const home = await phone.render(<Home />);
    expect(home.has('Dekouvri aplikasyon an')).toBe(true);
    expect(home.has('Yon vizit an 4 etap. Li mache san entènèt.')).toBe(true);
    expect(home.labels()).toEqual(expect.arrayContaining(['Kòmanse vizit la', 'Non mèsi']));

    const screen = await phone.render(<Tour />);
    const pages: [string, string, string][] = [
      ['1/4 · Akèy', 'Kontinye kote ou te rete a', 'Ki kote: onglè Akèy'],
      ['2/4 · Aprann', 'Chwazi epi telechaje leson ou yo', 'Ki kote: onglè Aprann'],
      ['3/4 · Revize', 'Refè egzèsis ou yo', 'Ki kote: onglè Revize'],
      ['4/4 · Pwofil', 'Pwogrè ou ak reglaj ou yo', 'Ki kote: onglè Pwofil'],
    ];
    for (const [index, [progress, title, where]] of pages.entries()) {
      expect(screen.has(progress)).toBe(true);
      expect(screen.has(title)).toBe(true);
      expect(screen.has(where)).toBe(true);
      expect(screen.has('Vizit gide')).toBe(true);
      if (index < pages.length - 1) {
        expect(screen.labels()).toContain('Fèmen vizit la');
        await screen.press('Pwochen');
      }
    }
    await screen.press('Fini vizit la');
    expect(navigation.calls).toEqual(['replace /home']); // opened from a link: nothing to go back to

    const profile = await phone.render(<Profile />);
    expect(profile.labels()).toContain('Revwè vizit gide a. 4 etap · san entènèt');
  });

  test.each([0, 1, 2])('it can be closed at step %i; it is then not offered again', async (step) => {
    const app = await phone.signIn('student.a');
    const screen = await phone.render(<Tour />);
    for (let i = 0; i < step; i += 1) await screen.press('Suivant');
    await screen.press('Fermer la visite');
    expect(navigation.calls).toEqual(['replace /home']);
    expect(await app.session.account.experience.getTour()).toMatchObject({ dismissed: true, versionSeen: TOUR_VERSION, inProgress: false });
    expect((await phone.render(<Home />)).text()).not.toMatch(TOUR_WORDS);
  });

  test('the back button goes one step back, and closes the tour from the first step', async () => {
    const app = await phone.signIn('student.a');
    const screen = await phone.render(<Tour />);
    await screen.press('Suivant');
    expect(screen.has('2/4 · Apprendre')).toBe(true);
    await screen.press('Retour');
    expect(screen.has('1/4 · Accueil')).toBe(true);
    await screen.press('Retour');
    expect(navigation.calls).toEqual(['replace /home']);
    expect((await app.session.account.experience.getTour()).inProgress).toBe(false);
  });

  test('killed mid-tour: Accueil offers to continue, and the tour reopens on the same step', async () => {
    await phone.signIn('student.a');
    let screen = await phone.render(<Tour />);
    await screen.press('Suivant');
    await screen.press('Suivant');
    await phone.kill();
    await phone.signIn('student.a');
    const home = await phone.render(<Home />);
    expect(home.labels()).toContain('Continuer la visite');
    expect(home.labels()).not.toContain('Non merci');
    await home.press('Continuer la visite');
    expect(navigation.calls).toEqual(['push /tour']);
    screen = await phone.render(<Tour />);
    expect(screen.has('3/4 · Réviser')).toBe(true);
  });
});

describe('replay from Profil', () => {
  test('always available, starts from the first step, and closing a replay changes nothing', async () => {
    const app = await phone.signIn('student.a');
    let tour = await phone.render(<Tour />);
    await tour.press('Suivant');
    await tour.press('Fermer la visite'); // dismissed during the first run
    navigation.calls.length = 0;

    const profile = await phone.render(<Profile />);
    await profile.press('Revoir la visite guidée. 4 étapes · sans internet');
    expect(navigation.calls).toEqual(['push /tour']);
    tour = await phone.render(<Tour />);
    expect(tour.has('1/4 · Accueil')).toBe(true);
    await tour.press('Suivant');
    await tour.press('Fermer la visite');
    expect(await app.session.account.experience.getTour()).toMatchObject({ dismissed: true, versionSeen: TOUR_VERSION, inProgress: false });

    // Replay to the end: still fine, and Accueil still does not nag.
    await (await phone.render(<Profile />)).press('Revoir la visite guidée. 4 étapes · sans internet');
    expect((await app.session.account.experience.getTour()).inProgress).toBe(true);
    tour = await phone.render(<Tour />);
    for (let i = 0; i < 3; i += 1) await tour.press('Suivant');
    await tour.press('Terminer la visite');
    expect((await phone.render(<Home />)).text()).not.toMatch(TOUR_WORDS);
  });

  test('the Profil screen keeps everything it had before', async () => {
    await phone.signIn('student.a');
    const text = (await phone.render(<Profile />)).text();
    for (const expected of ['Profil', 'student.a@edupreneur.test', 'Ma progression', 'Synchronisation', 'Langue', 'Mon compte']) {
      expect(text).toContain(expected);
    }
  });
});

describe('boundaries', () => {
  test('never over a lesson or an exercise, even with a tour run in progress', async () => {
    await phone.signIn('student.a');
    await saveLesson();
    const tour = await phone.render(<Tour />);
    await tour.press('Suivant'); // a run is in progress
    navigation.params = { id: LESSON_ID };
    const lesson = await phone.render(<LessonReader />);
    expect(lesson.redirect()).toBeNull();
    expect(lesson.has('Résoudre une équation simple')).toBe(true);
    expect(lesson.text()).not.toMatch(TOUR_WORDS);
    expect(lesson.labels().join('|')).not.toMatch(/visite/i);
    const quiz = await phone.render(<Quiz />);
    expect(quiz.redirect()).toBeNull();
    expect(quiz.has('Question 1 sur 2')).toBe(true);
    expect(quiz.text()).not.toMatch(TOUR_WORDS);
  });

  test('each student on a shared phone has their own tour state', async () => {
    await phone.signIn('student.a');
    await (await phone.render(<Home />)).press('Non merci');
    await phone.signIn('student.b');
    const home = await phone.render(<Home />);
    expect(home.has('Découvre l’application')).toBe(true);
    expect(home.labels()).toContain('Commencer la visite');
    await phone.signIn('student.a');
    expect((await phone.render(<Home />)).text()).not.toMatch(TOUR_WORDS);
  });

  test('signed out: sign-in, not the tour', async () => {
    const app = await phone.signIn('student.a');
    (app as { session: unknown }).session = null;
    expect((await phone.render(<Tour />)).redirect()).toBe('/sign-in');
  });
});
