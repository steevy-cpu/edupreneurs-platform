/**
 * Gold (confirmed versus pending) on Profil and Accueil, and the leaderboard
 * review screen. Rendered for real over real SQLite; flags are OFF by default.
 * Every number and pseudonym here is synthetic.
 */
import React from 'react';

import { answerQuestion } from '../../src/core/learning/actions';
import Home from '../../src/app/home';
import Leaderboard from '../../src/app/leaderboard';
import Profile from '../../src/app/profile';
import { translator } from '../../src/core/i18n/strings';
import { LEADERBOARD_FIXTURE } from '../../src/design/preview/leaderboardFixture';
import { LeaderboardReview } from '../../src/ui/experience/LeaderboardReview';
import { FakeRemote, RestartablePhone, sampleRewards } from '../support/experienceHarness';
import { navigation } from '../support/expoRouterMock';
import { resetFlags } from '../support/flagsMock';
import { testDevice } from '../support/reactNativeMock';
import { catalog, FakeApp, LESSON_ID, lessonSnapshot } from '../support/screenHarness';

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
  remote.rewards = sampleRewards(120);
  mockHolder.phone = phone;
  mockHolder.remote = remote;
  navigation.calls.length = 0;
  navigation.canGoBack = false;
  testDevice.fontScale = 1;
  delete (globalThis as { __DEV__?: boolean }).__DEV__;
  resetFlags('rewards');
});

afterEach(async () => {
  testDevice.fontScale = 1;
  await phone.dispose();
});

/** Two answers saved on the phone and not yet sent. */
async function twoPendingAnswers(app: FakeApp) {
  await phone.content.saveCatalog(catalog('fr'), SAVED_AT);
  await phone.content.replaceLesson(lessonSnapshot('fr'), SAVED_AT);
  const lesson = (await phone.content.getLesson(LESSON_ID, 'fr'))!;
  await answerQuestion(app.session.account, lesson, lesson.questions[0], 'b', app.services.env);
  await answerQuestion(app.session.account, lesson, lesson.questions[1], 'a', app.services.env);
  await app.refreshSummary();
}

/** Every number that appears in a line of text mentioning Gold. */
const goldNumbers = (texts: string[]) => texts.filter((text) => /gold/i.test(text)).flatMap((text) => text.match(/\d+/g) ?? []);

describe('flags off (the default)', () => {
  test('Profil and Accueil show nothing about Gold or a leaderboard, and no request is made', async () => {
    resetFlags();
    const app = await phone.signIn('student.a');
    await twoPendingAnswers(app);
    const profile = await phone.render(<Profile />);
    expect(profile.text()).not.toMatch(/Gold|Série|Classement/);
    const home = await phone.render(<Home />);
    expect(home.text()).not.toMatch(/Gold|Classement/);
    expect(remote.calls).toEqual([]);
    expect(await app.session.account.experience.getRewards()).toBeNull();
    expect((await phone.render(<Leaderboard />)).redirect()).toBe('/profile');
  });
});

describe('Gold on Profil', () => {
  test('confirmed Gold and streak come from the server; nothing is waiting', async () => {
    await phone.signIn('student.a');
    const screen = await phone.render(<Profile />);
    const texts = screen.texts();
    expect(texts).toEqual(expect.arrayContaining(['Gold et série', '120', 'Gold confirmé', 'Série en cours : 3 jour(s)', 'Meilleure série : 7 jour(s)', '2 réussite(s) obtenue(s)']));
    expect(texts.some((text) => text.startsWith('Confirmé par le serveur · '))).toBe(true);
    expect(screen.text()).not.toMatch(/En attente|sera calculé/);
    expect(remote.calls).toEqual(['GET /v1/rewards/summary']);
  });

  test('unsynced work is PENDING, counted in actions; the confirmed number does not move and no Gold is estimated', async () => {
    const app = await phone.signIn('student.a');
    await (await phone.render(<Profile />)).settle(); // the summary (120) is on the phone
    await twoPendingAnswers(app);

    const screen = await phone.render(<Profile />);
    const texts = screen.texts();
    expect(texts).toContain('120');
    expect(texts).toContain('Gold confirmé');
    expect(texts).toContain('En attente');
    expect(texts).toContain('2 action(s) en attente : leur Gold sera calculé par le serveur après la synchronisation.');
    // The only numbers on lines that mention Gold: the pending line counts ACTIONS (2). No amount anywhere.
    expect(goldNumbers(texts)).toEqual(['2']);
    // And the confirmed figure is the server's, alone on its line.
    expect(texts.filter((text) => /^\d+$/.test(text))).toEqual(['120']);
  });

  test('pending work with no summary yet: no number for Gold at all, not even zero', async () => {
    remote.mode = 'offline';
    const app = await phone.signIn('student.a');
    await twoPendingAnswers(app);
    const screen = await phone.render(<Profile />);
    await screen.settle();
    const texts = screen.texts();
    expect(texts).toContain('Ton Gold s’affichera ici après ta prochaine synchronisation.');
    expect(texts).toContain('2 action(s) en attente : leur Gold sera calculé par le serveur après la synchronisation.');
    expect(texts).not.toContain('Gold confirmé');
    expect(texts.filter((text) => /^\d+$/.test(text))).toEqual([]);
    expect(goldNumbers(texts)).toEqual(['2']);
  });

  test('after the server accepted the work, its new balance replaces the old one and "pending" disappears', async () => {
    const app = await phone.signIn('student.a');
    await (await phone.render(<Profile />)).settle();
    await twoPendingAnswers(app);

    // What a sync run does: the server acknowledges both answers, and its ledger now says 140.
    const sent = await app.session.account.pendingOperations(50);
    await app.session.account.applyPushResults(sent, sent.map((op) => ({ op_id: op.opId, status: 'accepted', result: { is_correct: true } })) as never);
    await app.session.account.markSynced('2099-01-01T00:00:00.000Z');
    await app.refreshSummary();
    remote.rewards = sampleRewards(140);

    const screen = await phone.render(<Profile />);
    await screen.settle();
    const texts = screen.texts();
    expect(texts.filter((text) => /^\d+$/.test(text))).toEqual(['140']);
    expect(screen.text()).not.toMatch(/En attente de|sera calculé/);
  });

  test('offline later: the last confirmed balance is still shown', async () => {
    await phone.signIn('student.a');
    await (await phone.render(<Profile />)).settle();
    await phone.kill();
    remote.mode = 'offline';
    await phone.signIn('student.a');
    const screen = await phone.render(<Profile />);
    await screen.settle();
    expect(screen.texts()).toEqual(expect.arrayContaining(['120', 'Gold confirmé']));
  });

  test('the server’s own caveats are passed on: provisional amounts, and a balance still being counted', async () => {
    remote.rewards = sampleRewards(120, { rules_status: 'provisional', up_to_date: false });
    await phone.signIn('student.a');
    let screen = await phone.render(<Profile />);
    expect(screen.texts()).toEqual(expect.arrayContaining(['Valeurs provisoires', 'Le serveur compte encore tes dernières actions.']));
    await phone.signIn('student.a', 'ht');
    screen = await phone.render(<Profile />);
    expect(screen.texts()).toEqual(expect.arrayContaining(['Valè pwovizwa', 'Sèvè a ap konte dènye aksyon ou yo toujou.']));
    // …and are absent when the server does not raise them
    remote.rewards = sampleRewards(120);
    await phone.signIn('student.b');
    expect((await phone.render(<Profile />)).text()).not.toMatch(/provisoires|compte encore/);
  });

  test('a streak of zero is not announced (no "you lost your streak")', async () => {
    remote.rewards = sampleRewards(30, { streak: { current: 0, longest: 5 }, achievements: 0 });
    await phone.signIn('student.a');
    const screen = await phone.render(<Profile />);
    expect(screen.texts()).toContain('Meilleure série : 5 jour(s)');
    expect(screen.text()).not.toMatch(/Série en cours|perdu|réussite/);
  });

  test('Haitian Creole', async () => {
    const app = await phone.signIn('student.a', 'ht');
    await (await phone.render(<Profile />)).settle();
    await phone.content.replaceLesson(lessonSnapshot('ht'), SAVED_AT);
    const lesson = (await phone.content.getLesson(LESSON_ID, 'ht'))!;
    await answerQuestion(app.session.account, lesson, lesson.questions[0], 'b', app.services.env);
    await app.refreshSummary();
    const texts = (await phone.render(<Profile />)).texts();
    expect(texts).toEqual(
      expect.arrayContaining([
        'Gold ak seri',
        '120',
        'Gold konfime',
        'Seri k ap kontinye: 3 jou',
        'Pi bon seri: 7 jou',
        '2 reyisit ou genyen',
        'Ap tann',
        '1 aksyon ap tann: sèvè a ap kalkile Gold yo apre senkronizasyon an.',
      ]),
    );
    expect(texts.some((text) => text.startsWith('Sèvè a konfime l · '))).toBe(true);
  });

  test('another student on the same phone sees none of it', async () => {
    await phone.signIn('student.a');
    await (await phone.render(<Profile />)).settle();
    remote.mode = 'offline';
    await phone.signIn('student.b');
    const screen = await phone.render(<Profile />);
    await screen.settle();
    expect(screen.texts()).not.toContain('120');
    expect(screen.has('Ton Gold s’affichera ici après ta prochaine synchronisation.')).toBe(true);
  });
});

describe('Gold on Accueil', () => {
  test('a single row with the confirmed balance, leading to Profil; nothing before the server has sent one', async () => {
    remote.mode = 'offline';
    const app = await phone.signIn('student.a');
    await twoPendingAnswers(app);
    let home = await phone.render(<Home />);
    await home.settle();
    expect(home.text()).not.toMatch(/Gold/);

    // The connection is back and a sync run reached the server (that is what makes a new download due
    // before the ten-minute spacing); the two answers of this test stay queued.
    remote.mode = 'online';
    await app.session.account.markSynced('2099-01-01T00:00:00.000Z');
    await app.refreshSummary();
    home = await phone.render(<Home />);
    await home.settle();
    expect(remote.calls.filter((call) => call.startsWith('GET /v1/rewards'))).toHaveLength(2); // one failed, one succeeded
    expect(home.labels()).toContain('Gold confirmé : 120. Le Gold du travail en attente n’est pas encore compté.');
    await home.press(/^Gold confirmé : 120/);
    expect(navigation.calls).toEqual(['replace /profile']);
  });
});

describe('leaderboard review screen (flag leaderboardReview, off by default)', () => {
  test('reachable from Profil without a fifth tab', async () => {
    resetFlags('leaderboardReview');
    await phone.signIn('student.a');
    const profile = await phone.render(<Profile />);
    const tabs = profile.pressables().filter((node) => node.props.accessibilityRole === 'tab');
    expect(tabs.map((tab) => tab.props.accessibilityLabel)).toEqual(['Accueil', 'Apprendre', 'Réviser', 'Profil']);
    await profile.press('Classement (aperçu). Écran en cours de revue, sans vrais élèves');
    expect(navigation.calls).toEqual(['push /leaderboard']);
  });

  test('in the production app it has nothing to rank: no names, no ranks, no Gold', async () => {
    resetFlags('leaderboardReview');
    await phone.signIn('student.a');
    const screen = await phone.render(<Leaderboard />);
    expect(screen.redirect()).toBeNull();
    expect(screen.texts()).toEqual(expect.arrayContaining(['Classement', 'Pas encore de classement', 'Cet écran est un aperçu. Aucun classement réel n’est calculé pour l’instant.']));
    expect(screen.text()).not.toMatch(/\d|Gold|TEST|Podium/);
    expect(screen.labels()).not.toContain('Voir l’aperçu avec des données fictives'); // no preview routes in a production build
    expect(remote.calls).toEqual([]);
  });

  test('in a build that contains the design previews, it links to the synthetic preview', async () => {
    resetFlags('leaderboardReview');
    (globalThis as { __DEV__?: boolean }).__DEV__ = true;
    await phone.signIn('student.a');
    const screen = await phone.render(<Leaderboard />);
    await screen.press('Voir l’aperçu avec des données fictives');
    expect(navigation.calls).toEqual(['push [object Object]']);
  });

  test('with the synthetic fixture: a notice first, a podium of three, then the list in rank order', async () => {
    await phone.signIn('student.a');
    const screen = await phone.render(<LeaderboardReview entries={LEADERBOARD_FIXTURE} synthetic t={translator('fr')} />);
    const texts = screen.texts();
    expect(texts[0]).toBe('Données fictives pour la démonstration. Ce ne sont pas de vrais élèves.');
    expect(texts).toEqual(expect.arrayContaining(['Podium', 'Suite du classement', 'Colibri-TEST', '900 Gold', 'Toi']));
    // Drawn 2nd · 1st · 3rd, like a podium…
    const podiumNames = texts.slice(texts.indexOf('Podium') + 1, texts.indexOf('Suite du classement')).filter((text) => text.endsWith('-TEST'));
    expect(podiumNames).toEqual(['Flamboyant-TEST', 'Colibri-TEST', 'Lambi-TEST']);
    // …and the rest strictly by rank.
    const listNames = texts.slice(texts.indexOf('Suite du classement') + 1).filter((text) => text.endsWith('-TEST'));
    expect(listNames).toEqual(['Mapou-TEST', 'Zandolit-TEST', 'Kayiman-TEST', 'Palmis-TEST', 'Tako-TEST']);
    // Nothing on this screen can be pressed: it is a picture to review, not a feature.
    expect(screen.pressables()).toEqual([]);
  });

  test('large text or a narrow layout: the podium becomes three full-width rows in reading order', async () => {
    testDevice.fontScale = 1.5;
    await phone.signIn('student.a');
    const screen = await phone.render(<LeaderboardReview entries={LEADERBOARD_FIXTURE.slice(0, 3)} synthetic t={translator('fr')} />);
    expect(screen.texts().filter((text) => text.endsWith('-TEST'))).toEqual(['Colibri-TEST', 'Flamboyant-TEST', 'Lambi-TEST']);
    expect(screen.has('Suite du classement')).toBe(false);
  });

  test('Haitian Creole', async () => {
    await phone.signIn('student.a', 'ht');
    const screen = await phone.render(<LeaderboardReview entries={LEADERBOARD_FIXTURE} synthetic t={translator('ht')} />);
    expect(screen.texts()).toEqual(
      expect.arrayContaining(['Done sa yo pa reyèl, se pou demonstrasyon. Se pa vrè elèv.', 'Podyòm', 'Rès klasman an', 'Ou menm', '500 Gold']),
    );
    const empty = await phone.render(<LeaderboardReview entries={[]} synthetic={false} t={translator('ht')} />);
    expect(empty.texts()).toEqual(expect.arrayContaining(['Poko gen klasman', 'Ekran sa a se yon apèsi. Poko gen okenn klasman reyèl ki kalkile.']));
  });

  test('the design preview route draws the fixture (development / preview builds only)', async () => {
    (globalThis as { __DEV__?: boolean }).__DEV__ = true;
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Preview = (require('../../src/app/design/leaderboard') as { default: React.ComponentType }).default;
    await phone.signIn('student.a');
    navigation.params = { locale: 'fr', state: 'default' };
    const screen = await phone.render(<Preview />);
    expect(screen.has('Données fictives pour la démonstration. Ce ne sont pas de vrais élèves.')).toBe(true);
    expect(screen.has('Colibri-TEST')).toBe(true);
    navigation.params = { locale: 'ht', state: 'empty' };
    expect((await phone.render(<Preview />)).has('Poko gen klasman')).toBe(true);
    navigation.params = {};
  });
});
