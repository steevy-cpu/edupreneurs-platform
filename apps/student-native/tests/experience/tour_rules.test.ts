/** Product tour rules over real SQLite: offer, resume, dismiss, replay, and sync of the flags. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { AccountStore } from '../../src/core/db/accountStore';
import { onboardingSyncDue, syncOnboarding } from '../../src/core/experience/onboardingSync';
import { EMPTY_TOUR } from '../../src/core/experience/store';
import { dismissTour, finishTour, setTourStep, startTour, TOUR_STEPS, TOUR_VERSION, tourOffer } from '../../src/core/experience/tour';
import { FakeRemote } from '../support/experienceHarness';
import { nodeDatabases } from '../support/nodeSqlite';

const A = 'a0000000-0000-4000-8000-00000000000a';
let clock = Date.UTC(2026, 10, 24, 12, 0, 0);
const now = () => new Date((clock += 1000));
let dir: string;
let account: AccountStore;

beforeEach(async () => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'edu-tour-'));
  account = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
});
afterEach(async () => {
  await account.close().catch(() => undefined);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('the tour is short: three to five steps, one per tab', () => {
  expect(TOUR_STEPS.length).toBeGreaterThanOrEqual(3);
  expect(TOUR_STEPS.length).toBeLessThanOrEqual(5);
  expect(TOUR_STEPS.map((step) => step.tab)).toEqual(['tabHome', 'tabLearn', 'tabReview', 'tabProfile']);
});

test('offer rule: new account yes; finished or declined no; a newer tour version is offered only to those who did not decline', () => {
  expect(tourOffer(EMPTY_TOUR)).toBe('start');
  expect(tourOffer({ ...EMPTY_TOUR, versionSeen: TOUR_VERSION })).toBe('none');
  expect(tourOffer({ ...EMPTY_TOUR, versionSeen: TOUR_VERSION, dismissed: true })).toBe('none');
  // what an account that finished / declined an OLDER version looks like to this version
  expect(tourOffer({ ...EMPTY_TOUR, versionSeen: TOUR_VERSION - 1 })).toBe('start');
  expect(tourOffer({ ...EMPTY_TOUR, versionSeen: TOUR_VERSION - 1, dismissed: true })).toBe('none');
  expect(tourOffer({ ...EMPTY_TOUR, versionSeen: TOUR_VERSION, dismissed: true, inProgress: true })).toBe('resume');
});

test('an interrupted run continues at the same step after the app is killed; replay starts over', async () => {
  await startTour(account, now());
  await setTourStep(account, 2, now());
  await account.close(); // force-quit
  account = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
  expect(await account.experience.getTour()).toMatchObject({ inProgress: true, step: 2 });
  expect(await startTour(account, now())).toMatchObject({ inProgress: true, step: 2 });
  expect(await startTour(account, now(), { replay: true })).toMatchObject({ inProgress: true, step: 0 });
});

test('steps stay inside the tour', async () => {
  await startTour(account, now());
  expect((await setTourStep(account, 99, now())).step).toBe(TOUR_STEPS.length - 1);
  expect((await setTourStep(account, -3, now())).step).toBe(0);
});

test('finishing marks the version as seen without "dismissed"; closing early marks both', async () => {
  await startTour(account, now());
  expect(await finishTour(account, now())).toMatchObject({ versionSeen: TOUR_VERSION, dismissed: false, inProgress: false, needsPush: true });

  const other = await AccountStore.open(await nodeDatabases(dir)('account-other'), 'other');
  await startTour(other, now());
  await setTourStep(other, 1, now());
  expect(await dismissTour(other, now())).toMatchObject({ versionSeen: TOUR_VERSION, dismissed: true, inProgress: false, step: 0 });
  await other.close();
});

test('closing a replay changes no flag', async () => {
  await startTour(account, now());
  await finishTour(account, now());
  await startTour(account, now(), { replay: true });
  await setTourStep(account, 1, now());
  expect(await dismissTour(account, now())).toMatchObject({ versionSeen: TOUR_VERSION, dismissed: false, inProgress: false });
  // and with nothing running, "dismiss" is a no-op
  const before = await account.experience.getTour();
  expect(await dismissTour(account, now())).toEqual(before);
});

test('the flags reach the server with the onboarding sync and only ever grow', async () => {
  const remote = new FakeRemote();
  await startTour(account, now());
  await dismissTour(account, now());
  expect(await onboardingSyncDue(account)).toBe(true);
  expect(await syncOnboarding(account, remote, { now })).toBe('synced');
  expect(remote.onboarding).toMatchObject({ tour_version_seen: TOUR_VERSION, tour_dismissed: true, state: 'new' }); // the onboarding state is not invented
  // Exactly the fields the strict endpoint accepts: no `state` when only the tour is reported, a flow version of at least 1.
  expect(remote.calls.filter((call) => call.startsWith('PUT'))).toEqual([
    `PUT /v1/me/onboarding {"onboarding_version":1,"tour_version_seen":${TOUR_VERSION},"tour_dismissed":true}`,
  ]);
  expect(await onboardingSyncDue(account)).toBe(false);

  // Another phone already saw a NEWER tour: this phone adopts it and sends nothing back.
  remote.onboarding.tour_version_seen = TOUR_VERSION + 1;
  remote.calls.length = 0;
  await syncOnboarding(account, remote, { now });
  expect((await account.experience.getTour()).versionSeen).toBe(TOUR_VERSION + 1);
  expect(remote.calls.filter((call) => call.startsWith('PUT'))).toEqual([]);
});
