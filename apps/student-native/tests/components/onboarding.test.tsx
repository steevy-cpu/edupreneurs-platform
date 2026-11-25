/**
 * First-run onboarding, rendered for real over real SQLite files
 * (see tests/support/screenHarness.tsx for what is real and what is a stand-in).
 *
 * The flow is behind the `onboarding` client flag, which is OFF by default;
 * each test switches on what it needs.
 */
import React from 'react';

import { answerQuestion } from '../../src/core/learning/actions';
import { PREF_GRADE, PREF_SUBJECT } from '../../src/core/learning/overview';
import Home from '../../src/app/home';
import LessonReader from '../../src/app/lesson/[id]';
import Onboarding from '../../src/app/onboarding';
import { FakeRemote, RestartablePhone } from '../support/experienceHarness';
import { navigation } from '../support/expoRouterMock';
import { resetFlags } from '../support/flagsMock';
import { catalog, LESSON_ID, lessonSnapshot } from '../support/screenHarness';

const mockHolder: { phone: RestartablePhone | null; remote: FakeRemote | null } = { phone: null, remote: null };
jest.mock('../../src/ui/AppContext', () => ({ useApp: () => mockHolder.phone!.app }));
jest.mock('../../src/ui/remote', () => ({ useRemote: () => mockHolder.remote }));
jest.mock('../../src/core/experience/flags', () => require('../support/flagsMock').flagsModule);

let phone: RestartablePhone;
const SAVED_AT = '2026-11-24T10:00:00.000Z';

beforeEach(async () => {
  phone = (await new RestartablePhone().start()) as RestartablePhone;
  mockHolder.phone = phone;
  mockHolder.remote = null;
  navigation.calls.length = 0;
  navigation.params = {};
  resetFlags('onboarding');
});

afterEach(async () => {
  await phone.dispose();
});

const selected = (screen: Awaited<ReturnType<RestartablePhone['render']>>) =>
  screen
    .pressables()
    .filter((node) => node.props.accessibilityRole === 'radio' && node.props.accessibilityState.selected)
    .map((node) => String(node.props.accessibilityLabel));

describe('flag off (the default)', () => {
  test('Accueil is exactly as before for a brand-new account, and nothing is written', async () => {
    resetFlags();
    const app = await phone.signIn('student.a');
    const screen = await phone.render(<Home />);
    expect(screen.redirect()).toBeNull();
    expect(screen.has('Choisis ta première leçon')).toBe(true);
    expect(await app.session.account.experience.getOnboarding()).toBeNull();
  });

  test('the onboarding route sends the learner home without showing or storing anything', async () => {
    resetFlags();
    const app = await phone.signIn('student.a');
    const screen = await phone.render(<Onboarding />);
    expect(screen.redirect()).toBe('/home');
    expect(screen.texts()).toEqual([]);
    expect(await app.session.account.experience.getOnboarding()).toBeNull();
  });
});

describe('who sees the flow', () => {
  test('a new account is sent from Accueil to onboarding', async () => {
    await phone.signIn('student.a');
    const screen = await phone.render(<Home />);
    expect(screen.redirect()).toBe('/onboarding');
    expect(screen.has('Bonjour')).toBe(false);
  });

  test('an account that already chose its class on this phone is not: Accueil opens as usual', async () => {
    const app = await phone.signIn('student.a');
    await app.session.account.setPreference(PREF_GRADE, '9AF');
    const home = await phone.render(<Home />);
    expect(home.redirect()).toBeNull();
    expect(home.has('Bonjour student.a')).toBe(true);
    const flow = await phone.render(<Onboarding />);
    expect(flow.redirect()).toBe('/home');
  });

  test('review L3: opening the onboarding route directly does not start the flow for such an account either', async () => {
    const app = await phone.signIn('student.a');
    await app.session.account.setPreference(PREF_GRADE, '9AF');
    const flow = await phone.render(<Onboarding />); // Accueil was never shown
    expect(flow.redirect()).toBe('/home');
    expect(await app.session.account.experience.getOnboarding()).toMatchObject({ status: 'returning' });
    expect((await phone.render(<Home />)).redirect()).toBeNull();
  });

  test('signed out: sign-in, not onboarding', async () => {
    const app = await phone.signIn('student.a');
    (app as { session: unknown }).session = null;
    expect((await phone.render(<Onboarding />)).redirect()).toBe('/sign-in');
  });

  test('a saved lesson opens directly even while onboarding is unfinished', async () => {
    await phone.signIn('student.a');
    await phone.content.replaceLesson(lessonSnapshot('fr'), SAVED_AT);
    navigation.params = { id: LESSON_ID };
    const lesson = await phone.render(<LessonReader />);
    expect(lesson.redirect()).toBeNull();
    expect(lesson.has('Résoudre une équation simple')).toBe(true);
    expect(lesson.has('Bienvenue sur Edupreneurs')).toBe(false);
  });
});

describe('the five steps', () => {
  test('French, start to finish, with no network and no catalogue on the phone', async () => {
    const app = await phone.signInLive('student.a');
    const screen = await phone.render(<Onboarding />);

    // 1. welcome
    expect(screen.has('Bienvenue sur Edupreneurs')).toBe(true);
    expect(screen.has('1/5 · Bienvenue')).toBe(true);
    expect(screen.labels()).toEqual(expect.arrayContaining(['Commencer', 'Passer l’introduction']));
    expect(screen.labels()).not.toContain('Retour'); // nothing to go back to
    await screen.press('Commencer');

    // 2. language
    expect(screen.has('Choisis ta langue')).toBe(true);
    expect(screen.has('2/5 · Langue')).toBe(true);
    expect(selected(screen)).toEqual(['Français']);
    await screen.press('Continuer');

    // 3. class: the built-in list, clearly presented as such
    expect(screen.has('En quelle classe es-tu ?')).toBe(true);
    expect(screen.has('Pas encore de connexion : voici la liste des classes.')).toBe(true);
    const grades = screen.labels().filter((label) => /^(\dAF|NS\d) · /.test(label));
    expect(grades).toEqual([
      '7AF · 7e année fondamentale',
      '8AF · 8e année fondamentale',
      '9AF · 9e année fondamentale',
      'NS1 · Nouveau Secondaire 1',
      'NS2 · Nouveau Secondaire 2',
      'NS3 · Nouveau Secondaire 3',
      'NS4 · Nouveau Secondaire 4',
    ]);
    expect(screen.find('Continuer').props.disabled).toBe(true); // nothing chosen yet
    await screen.press('NS2 · Nouveau Secondaire 2');
    expect(selected(screen)).toEqual(['NS2 · Nouveau Secondaire 2']);
    await screen.press('Continuer');
    expect(await app.session.account.getPreference(PREF_GRADE)).toBe('NS2');

    // 4. how offline works: downloads, offline status, answers saved here, sync later
    expect(screen.has('Comment ça marche sans internet')).toBe(true);
    for (const title of ['Télécharge tes leçons', 'Étudie sans internet', 'Tes réponses sont enregistrées ici', 'Synchronisation plus tard']) {
      expect(screen.has(title)).toBe(true);
    }
    expect(screen.has('« Hors ligne » s’affiche quand le serveur est injoignable.')).toBe(true);
    await screen.press('J’ai compris');

    // 5. ready
    expect(screen.has('Tout est prêt')).toBe(true);
    expect(screen.has('5/5 · Prêt')).toBe(true);
    expect(screen.has('Langue : Français')).toBe(true);
    expect(screen.has('Classe : NS2 · Nouveau Secondaire 2')).toBe(true);
    await screen.press('Choisir ma première leçon');
    expect(navigation.calls).toEqual(['replace /learn']);
    expect(await app.session.account.experience.getOnboarding()).toMatchObject({ status: 'completed', gradeCode: 'NS2' });

    // Accueil no longer redirects.
    const home = await phone.render(<Home />);
    expect(home.redirect()).toBeNull();
    expect(home.has('Bonjour student.a')).toBe(true);
  });

  test('Haitian Creole: choosing Kreyòl switches the flow at once and every step is in Creole', async () => {
    const app = await phone.signInLive('student.a');
    await phone.content.saveCatalog(catalog('ht'), SAVED_AT);
    const screen = await phone.render(<Onboarding />);
    await screen.press('Commencer');
    await screen.press('Kreyòl');
    expect(app.calls).toContain('setLocale ht');
    expect(await app.session.account.getPreference('locale')).toBe('ht');
    expect(screen.has('Chwazi lang ou')).toBe(true);
    expect(screen.has('2/5 · Lang')).toBe(true);
    expect(selected(screen)).toEqual(['Kreyòl']);
    await screen.press('Kontinye');

    expect(screen.has('Nan ki klas ou ye?')).toBe(true);
    // The catalogue is on the phone: its classes are offered, with no "no connection" notice.
    expect(screen.has('Poko gen koneksyon')).toBe(false);
    expect(screen.labels().filter((label) => label.includes(' · '))).toEqual(['9AF · 9e année fondamentale']);
    await screen.press('M ap chwazi pita');

    expect(screen.has('Kijan sa mache san entènèt')).toBe(true);
    for (const title of ['Telechaje leson ou yo', 'Etidye san entènèt', 'Repons ou yo anrejistre isit la', 'Senkronizasyon pita']) {
      expect(screen.has(title)).toBe(true);
    }
    await screen.press('Mwen konprann');

    expect(screen.has('Tout bagay pare')).toBe(true);
    expect(screen.has('Lang: Kreyòl')).toBe(true);
    expect(screen.has('Klas: pou chwazi nan Aprann')).toBe(true);
    expect(screen.labels()).toEqual(expect.arrayContaining(['Chwazi premye leson mwen', 'Ale nan akèy']));
    await screen.press('Ale nan akèy');
    expect(navigation.calls).toEqual(['replace /home']);
    expect(await app.session.account.getPreference(PREF_GRADE)).toBeNull(); // "later" stored no class
    expect(await app.session.account.experience.getOnboarding()).toMatchObject({ status: 'completed', gradeCode: null });
  });

  test('the welcome step in Creole', async () => {
    await phone.signInLive('student.a', 'ht');
    const screen = await phone.render(<Onboarding />);
    expect(screen.has('Byenveni sou Edupreneurs')).toBe(true);
    expect(screen.has('1/5 · Byenveni')).toBe(true);
    expect(screen.labels()).toEqual(expect.arrayContaining(['Kòmanse', 'Sote entwodiksyon an']));
  });

  test('skipping the introduction goes straight to Accueil and is remembered', async () => {
    const app = await phone.signInLive('student.a');
    const screen = await phone.render(<Onboarding />);
    await screen.press('Passer l’introduction');
    expect(navigation.calls).toEqual(['replace /home']);
    expect(await app.session.account.experience.getOnboarding()).toMatchObject({ status: 'skipped' });
    expect(await app.session.account.getPreference(PREF_GRADE)).toBeNull();
    expect((await phone.render(<Home />)).redirect()).toBeNull();
    expect((await phone.render(<Onboarding />)).redirect()).toBe('/home');
  });

  test('the back button returns to the previous step and keeps the choices made', async () => {
    await phone.signInLive('student.a');
    const screen = await phone.render(<Onboarding />);
    await screen.press('Commencer');
    await screen.press('Continuer');
    await screen.press('9AF · 9e année fondamentale');
    await screen.press('Retour');
    expect(screen.has('Choisis ta langue')).toBe(true);
    await screen.press('Continuer');
    expect(selected(screen)).toEqual(['9AF · 9e année fondamentale']);
  });

  test('if a choice cannot be written, the learner is told and the step does not move', async () => {
    const app = await phone.signInLive('student.a');
    const screen = await phone.render(<Onboarding />);
    const store = app.session.account.experience;
    const write = jest.spyOn(store, 'updateOnboarding').mockRejectedValueOnce(new Error('SQLITE_FULL: simulated storage failure'));
    await screen.press('Commencer');
    expect(screen.has('Ce choix n’a pas pu être enregistré. Réessaie.')).toBe(true);
    expect(screen.has('Bienvenue sur Edupreneurs')).toBe(true);
    write.mockRestore();
    await screen.press('Commencer');
    expect(screen.has('Choisis ta langue')).toBe(true);
    expect(screen.has('Ce choix n’a pas pu être enregistré.')).toBe(false);
  });
});

describe('interruptions', () => {
  test('killing the app mid-flow reopens the same step, language and selection', async () => {
    await phone.signInLive('student.a');
    let screen = await phone.render(<Onboarding />);
    await screen.press('Commencer');
    await screen.press('Kreyòl');
    await screen.press('Kontinye');
    await screen.press('NS3 · Nouvo Segondè 3');

    await phone.kill(); // force-quit: nothing is flushed on exit
    await phone.signInLive('student.a'); // cold start restores the session and the saved language
    expect((await phone.render(<Home />)).redirect()).toBe('/onboarding');
    screen = await phone.render(<Onboarding />);
    expect(screen.has('Nan ki klas ou ye?')).toBe(true);
    expect(screen.has('3/5 · Klas')).toBe(true);
    expect(selected(screen)).toEqual(['NS3 · Nouvo Segondè 3']);
  });

  test('two students on one phone each have their own place in the flow', async () => {
    await phone.signInLive('student.a');
    let screen = await phone.render(<Onboarding />);
    await screen.press('Commencer');
    await screen.press('Continuer');
    await screen.press('8AF · 8e année fondamentale');
    await screen.press('Continuer');
    expect(screen.has('Comment ça marche sans internet')).toBe(true);

    const b = await phone.signInLive('student.b');
    screen = await phone.render(<Onboarding />);
    expect(screen.has('Bienvenue sur Edupreneurs')).toBe(true);
    expect(await b.session.account.getPreference(PREF_GRADE)).toBeNull();
    await screen.press('Passer l’introduction');

    const a = await phone.signInLive('student.a');
    screen = await phone.render(<Onboarding />);
    expect(screen.has('Comment ça marche sans internet')).toBe(true);
    expect(await a.session.account.getPreference(PREF_GRADE)).toBe('8AF');
    expect((await a.session.account.experience.getOnboarding())?.status).toBe('in_progress');
    expect((await b.session.account.experience.getOnboarding())?.status).toBe('skipped');
  });

  test('going through the flow never removes or resets saved learning work', async () => {
    const app = await phone.signInLive('student.a');
    await phone.content.saveCatalog(catalog('fr'), SAVED_AT);
    await phone.content.replaceLesson(lessonSnapshot('fr'), SAVED_AT);
    const lesson = (await phone.content.getLesson(LESSON_ID, 'fr'))!;
    const account = app.session.account;
    await answerQuestion(account, lesson, lesson.questions[0], 'b', app.services.env);
    await answerQuestion(account, lesson, lesson.questions[1], 'b', app.services.env);
    await account.setPreference(PREF_SUBJECT, 'mathematiques');
    const before = {
      attempts: await account.attemptCount(),
      pending: await account.pendingOperations(50),
      progress: [...(await account.questionProgress(LESSON_ID)).values()],
    };

    const screen = await phone.render(<Onboarding />);
    await screen.press('Commencer');
    await screen.press('Continuer');
    await screen.press('9AF · 9e année fondamentale');
    await screen.press('Continuer');
    await screen.press('J’ai compris');
    await screen.press('Aller à l’accueil');

    expect(await account.attemptCount()).toBe(before.attempts);
    expect(await account.pendingOperations(50)).toEqual(before.pending);
    expect([...(await account.questionProgress(LESSON_ID)).values()]).toEqual(before.progress);
    expect((await phone.content.listSavedLessons('fr')).map((saved) => saved.lessonId)).toEqual([LESSON_ID]);
    const home = await phone.render(<Home />);
    expect(home.has('2 sur 2 exercices faits')).toBe(true);
  });
});

describe('server sync (flag onboardingSync, off by default)', () => {
  test('without the flag no request is made, even when a server adapter exists', async () => {
    mockHolder.remote = new FakeRemote();
    await phone.signInLive('student.a');
    const screen = await phone.render(<Onboarding />);
    await screen.press('Passer l’introduction');
    await phone.render(<Home />);
    expect(mockHolder.remote.calls).toEqual([]);
  });

  test('finishing tells the server in the background; the flow does not wait for it', async () => {
    resetFlags('onboarding', 'onboardingSync');
    const remote = (mockHolder.remote = new FakeRemote());
    const app = await phone.signInLive('student.a');
    const screen = await phone.render(<Onboarding />);
    await screen.press('Commencer');
    await screen.press('Kreyòl');
    await screen.press('Kontinye');
    await screen.press('9AF · 9èm ane fondamantal');
    await screen.press('Kontinye');
    await screen.press('Mwen konprann');
    await screen.press('Ale nan akèy');
    await screen.settle();
    expect(remote.onboarding.state).toBe('ready');
    expect(remote.profile).toEqual({ grade_code: '9AF', preferred_locale: 'ht' });
    expect(await app.session.account.experience.getOnboarding()).toMatchObject({ needsPush: false, profileNeedsPush: false });
  });

  test('server unreachable: the flow still completes, and Accueil retries later', async () => {
    resetFlags('onboarding', 'onboardingSync');
    const remote = (mockHolder.remote = new FakeRemote());
    remote.mode = 'offline';
    const app = await phone.signInLive('student.a');
    const screen = await phone.render(<Onboarding />);
    await screen.press('Passer l’introduction');
    await screen.settle();
    expect(navigation.calls).toEqual(['replace /home']);
    expect(await app.session.account.experience.getOnboarding()).toMatchObject({ status: 'skipped', needsPush: true });

    remote.mode = 'online';
    let home = await phone.render(<Home />);
    await home.settle();
    expect(remote.onboarding.state).toBe('new'); // too soon after the failed attempt: Accueil does not hammer the server
    app.services.env.now = () => new Date('2026-11-24T13:00:00.000Z'); // later
    home = await phone.render(<Home />);
    await home.settle();
    expect(remote.onboarding.state).toBe('ready');
    expect((await app.session.account.experience.getOnboarding())?.needsPush).toBe(false);
  });

  test('a learner who finished on another phone is taken home instead of through the flow again', async () => {
    resetFlags('onboarding', 'onboardingSync');
    const remote = (mockHolder.remote = new FakeRemote());
    remote.onboarding.state = 'ready';
    await phone.signInLive('student.a');
    const screen = await phone.render(<Onboarding />);
    await screen.settle();
    expect(screen.redirect()).toBe('/home');
  });
});
