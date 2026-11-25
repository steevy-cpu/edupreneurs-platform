/**
 * The Word of the Day card on Accueil, rendered for real over real SQLite.
 * Behind the `dailyWord` client flag, OFF by default. Synthetic words only.
 */
import React from 'react';

import Home from '../../src/app/home';
import { FakeRemote, RestartablePhone, sampleWord } from '../support/experienceHarness';
import { navigation } from '../support/expoRouterMock';
import { resetFlags } from '../support/flagsMock';
import { catalog, FakeApp, lessonSnapshot } from '../support/screenHarness';

const mockHolder: { phone: RestartablePhone | null; remote: FakeRemote | null } = { phone: null, remote: null };
jest.mock('../../src/ui/AppContext', () => ({ useApp: () => mockHolder.phone!.app }));
jest.mock('../../src/ui/remote', () => ({ useRemote: () => mockHolder.remote }));
jest.mock('../../src/core/experience/flags', () => require('../support/flagsMock').flagsModule);

let phone: RestartablePhone;
let remote: FakeRemote;
const SAVED_AT = '2026-11-24T10:00:00.000Z';
const MORNING = '2026-11-24T15:00:00.000Z'; //  10:00 in Haiti on the 24th
const AFTERNOON = '2026-11-24T18:00:00.000Z'; //       13:00 in Haiti on the 24th
const BEFORE_MIDNIGHT = '2026-11-25T04:59:59.000Z'; // 23:59:59 in Haiti on the 24th
const AFTER_MIDNIGHT = '2026-11-25T05:00:00.000Z'; //  00:00:00 in Haiti on the 25th

beforeEach(async () => {
  phone = (await new RestartablePhone().start()) as RestartablePhone;
  remote = new FakeRemote();
  remote.dailyWords.fr = sampleWord('2026-11-24', 'fr');
  remote.dailyWords.ht = sampleWord('2026-11-24', 'ht');
  mockHolder.phone = phone;
  mockHolder.remote = remote;
  navigation.calls.length = 0;
  resetFlags('dailyWord');
});

afterEach(async () => {
  await phone.dispose();
});

/** Sign in with the phone's clock set to `at`. */
async function signInAt(at: string, name: 'student.a' | 'student.b' = 'student.a', locale: 'fr' | 'ht' = 'fr'): Promise<FakeApp> {
  const app = await phone.signIn(name, locale);
  app.services.env.now = () => new Date(at);
  return app;
}

describe('flag off (the default)', () => {
  test('no card and no request, even with a word in the cache', async () => {
    await signInAt(MORNING);
    await (await phone.render(<Home />)).settle(); // flag on: the word is downloaded and cached
    expect(remote.calls).toHaveLength(1);

    resetFlags();
    remote.calls.length = 0;
    const screen = await phone.render(<Home />);
    expect(screen.has('Mot du jour')).toBe(false);
    expect(screen.has('persévérance')).toBe(false);
    expect(screen.has('Choisis ta première leçon')).toBe(true);
    expect(remote.calls).toEqual([]);
  });
});

describe('today’s word', () => {
  test('French: term, pronunciation, definition, example and gloss, labelled "Mot du jour" with its date', async () => {
    await signInAt(MORNING);
    const screen = await phone.render(<Home />);
    const texts = screen.texts();
    for (const expected of [
      'Mot du jour',
      '24 novembre 2026',
      'persévérance',
      'nom · Prononciation : pèr-sé-vé-rans',
      'Qualité d’une personne qui continue ses efforts malgré les difficultés.',
      'Exemple',
      'Avec de la persévérance, elle a terminé tous ses exercices.',
      'En créole : pèseverans',
    ]) {
      expect(texts).toContain(expected);
    }
    expect(screen.text()).not.toMatch(/Dernier mot téléchargé|Audio|pas encore disponible en créole/);
    expect(remote.calls).toEqual(['GET /v1/daily-word?locale=fr']);
  });

  test('Haitian Creole', async () => {
    await signInAt(MORNING, 'student.a', 'ht');
    const texts = (await phone.render(<Home />)).texts();
    for (const expected of [
      'Mo jodi a',
      '24 novanm 2026',
      'pèseverans',
      'non · Pwononsyasyon: pè-se-ve-rans',
      'Kalite yon moun ki kontinye fè efò menm lè sa difisil.',
      'Egzanp',
      'Ak pèseverans, li fini tout egzèsis li yo.',
      'An fransè: persévérance',
    ]) {
      expect(texts).toContain(expected);
    }
  });

  test('Creole interface, word only available in French: shown in French and said so, in Creole', async () => {
    remote.dailyWords.ht = { ...sampleWord('2026-11-24', 'fr'), requested_locale: 'ht', is_fallback_locale: true };
    await signInAt(MORNING, 'student.a', 'ht');
    const screen = await phone.render(<Home />);
    expect(screen.has('Mo jodi a')).toBe(true);
    expect(screen.has('persévérance')).toBe(true);
    expect(screen.has('Mo sa a poko disponib an kreyòl. Nou montre l an fransè.')).toBe(true);
    expect(screen.has('An kreyòl: pèseverans')).toBe(true);
  });

  test('it sits under the learning content and adds nothing to press: no audio control, nothing that plays', async () => {
    remote.dailyWords.fr = sampleWord('2026-11-24', 'fr', { audio: { mime: 'audio/mpeg', bytes: 20480, duration_ms: 1800 } });
    const app = await signInAt(MORNING);
    await phone.content.saveCatalog(catalog('fr'), SAVED_AT);
    await phone.content.replaceLesson(lessonSnapshot('fr'), SAVED_AT);

    resetFlags();
    const without = (await phone.render(<Home />)).labels();
    resetFlags('dailyWord');
    app.services.env.now = () => new Date(MORNING);
    const screen = await phone.render(<Home />);
    expect(screen.labels()).toEqual(without); // exactly the same controls as with the flag off
    const texts = screen.texts();
    expect(texts.indexOf('Mot du jour')).toBeGreaterThan(texts.indexOf('Continuer ma leçon'));
    // Audio metadata exists: it is only mentioned, as text.
    expect(texts).toContain('Audio : bientôt disponible');
  });

  test('re-opening Accueil the same day reads the cache and makes no request', async () => {
    const app = await signInAt(MORNING);
    await phone.render(<Home />);
    remote.calls.length = 0;
    remote.mode = 'offline';
    app.services.env.now = () => new Date(AFTERNOON);
    const screen = await phone.render(<Home />);
    expect(screen.has('Mot du jour')).toBe(true);
    expect(screen.has('persévérance')).toBe(true);
    expect(remote.calls).toEqual([]);
  });
});

describe('never yesterday’s word as today’s', () => {
  test('one second before Haiti midnight it is "Mot du jour"; at midnight, offline, it is "Dernier mot téléchargé · 24 novembre 2026"', async () => {
    const app = await signInAt(MORNING);
    await phone.render(<Home />);
    remote.mode = 'offline';

    app.services.env.now = () => new Date(BEFORE_MIDNIGHT);
    let screen = await phone.render(<Home />);
    expect(screen.texts()).toContain('Mot du jour');
    expect(screen.text()).not.toContain('Dernier mot téléchargé');

    app.services.env.now = () => new Date(AFTER_MIDNIGHT);
    screen = await phone.render(<Home />);
    expect(screen.texts()).toContain('Dernier mot téléchargé · 24 novembre 2026');
    expect(screen.texts()).not.toContain('Mot du jour');
    expect(screen.text()).not.toMatch(/Mot du jour/);
    expect(screen.has('persévérance')).toBe(true); // still readable
    expect(screen.has('Le mot d’aujourd’hui se chargera à la prochaine connexion.')).toBe(true);
  });

  test('the same in Creole', async () => {
    const app = await signInAt(MORNING, 'student.a', 'ht');
    await phone.render(<Home />);
    remote.mode = 'offline';
    app.services.env.now = () => new Date(AFTER_MIDNIGHT);
    const screen = await phone.render(<Home />);
    expect(screen.texts()).toContain('Dènye mo ki telechaje · 24 novanm 2026');
    expect(screen.text()).not.toMatch(/Mo jodi a(?! ap)/);
    expect(screen.has('Mo jodi a ap chaje lè ou gen koneksyon ankò.')).toBe(true);
  });

  test('after a restart with no network the cached word is still there, still honestly labelled', async () => {
    await signInAt(MORNING);
    await phone.render(<Home />);
    await phone.kill();
    remote.mode = 'offline';
    await signInAt('2026-11-26T15:00:00.000Z'); // two days later
    const screen = await phone.render(<Home />);
    expect(screen.texts()).toContain('Dernier mot téléchargé · 24 novembre 2026');
    expect(screen.text()).not.toMatch(/Mot du jour/);
  });

  test('when the connection is back the new day’s word replaces it', async () => {
    const app = await signInAt(MORNING);
    await phone.render(<Home />);
    remote.dailyWords.fr = sampleWord('2026-11-25', 'fr');
    app.services.env.now = () => new Date('2026-11-25T15:00:00.000Z');
    const screen = await phone.render(<Home />);
    await screen.settle();
    expect(screen.texts()).toEqual(expect.arrayContaining(['Mot du jour', '25 novembre 2026', 'hypothèse']));
    expect(screen.has('persévérance')).toBe(false);
  });

  test('no word assigned today: the old one is shown as old, with "Pas de nouveau mot pour aujourd’hui."', async () => {
    const app = await signInAt(MORNING);
    await phone.render(<Home />);
    delete remote.dailyWords.fr;
    app.services.env.now = () => new Date('2026-11-25T15:00:00.000Z');
    const screen = await phone.render(<Home />);
    await screen.settle();
    expect(screen.texts()).toContain('Dernier mot téléchargé · 24 novembre 2026');
    expect(screen.has('Pas de nouveau mot pour aujourd’hui.')).toBe(true);
    expect(screen.text()).not.toMatch(/Mot du jour/);
  });
});

describe('withdrawn during the day', () => {
  test('the card disappears instead of keeping withdrawn content on screen', async () => {
    const app = await signInAt(MORNING);
    await phone.render(<Home />);
    delete remote.dailyWords.fr;
    app.services.env.now = () => new Date(BEFORE_MIDNIGHT); // many hours later, still the 24th in Haiti
    const screen = await phone.render(<Home />);
    await screen.settle();
    expect(screen.text()).not.toMatch(/Mot du jour|Dernier mot|persévérance/);
  });

  test('a part of speech this app version does not know is left out rather than shown as a code', async () => {
    const word = sampleWord('2026-11-24', 'fr');
    word.word.part_of_speech = 'gerund';
    remote.dailyWords.fr = word;
    await signInAt(MORNING);
    const texts = (await phone.render(<Home />)).texts();
    expect(texts).toContain('Prononciation : pèr-sé-vé-rans');
    expect(texts.join('\n')).not.toContain('gerund');
  });
});

describe('nothing to show', () => {
  test('first start with no network: no card, no invented word, and Accueil works as usual', async () => {
    remote.mode = 'offline';
    await signInAt(MORNING);
    const screen = await phone.render(<Home />);
    await screen.settle();
    expect(screen.text()).not.toMatch(/Mot du jour|Dernier mot/);
    expect(screen.has('Choisis ta première leçon')).toBe(true);
    await screen.press('Voir les matières');
    expect(navigation.calls).toEqual(['replace /learn']);
  });

  test('another student on the same phone does not see the first student’s cached word', async () => {
    await signInAt(MORNING, 'student.a');
    await phone.render(<Home />);
    remote.mode = 'offline';
    await signInAt(MORNING, 'student.b');
    const screen = await phone.render(<Home />);
    await screen.settle();
    expect(screen.has('persévérance')).toBe(false);
    expect(screen.has('Bonjour student.b')).toBe(true);
  });
});
