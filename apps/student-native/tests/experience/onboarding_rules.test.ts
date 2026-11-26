/**
 * Onboarding rules and server sync, over real SQLite with an in-memory stand-in
 * for the server (the identity lane's endpoints are not on this branch).
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { ApiError } from '../../src/core/api/errors';
import { AccountStore } from '../../src/core/db/accountStore';
import {
  beginOrResumeOnboarding,
  confirmOnboardingGrade,
  finishOnboarding,
  goToOnboardingStep,
  mergeServerOnboarding,
  ONBOARDING_FLOW_VERSION,
  onboardingGate,
  selectOnboardingGrade,
  serverStateOf,
  skipOnboardingGrade,
} from '../../src/core/experience/onboarding';
import { ONBOARDING_SYNC_SPACING_MS, onboardingSyncDue, syncOnboarding } from '../../src/core/experience/onboardingSync';
import { ExperienceApi, parseRemoteOnboarding } from '../../src/core/experience/remote';
import type { OnboardingRecord } from '../../src/core/experience/store';
import { FakeRemote } from '../support/experienceHarness';
import { nodeDatabases } from '../support/nodeSqlite';

const A = 'a0000000-0000-4000-8000-00000000000a';
let clock = Date.UTC(2026, 10, 24, 12, 0, 0);
const now = () => new Date((clock += 1000));

let dir: string;
let account: AccountStore;

beforeEach(async () => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'edu-onb-'));
  account = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
});
afterEach(async () => {
  await account.close().catch(() => undefined);
  fs.rmSync(dir, { recursive: true, force: true });
});

async function reopen(): Promise<void> {
  await account.close();
  account = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
}

describe('the flow', () => {
  test('starts on the first step and resumes on the same step after the app is killed', async () => {
    expect(await beginOrResumeOnboarding(account, now())).toMatchObject({
      status: 'in_progress',
      step: 'welcome',
      flowVersion: ONBOARDING_FLOW_VERSION,
    });
    await goToOnboardingStep(account, 'language', now());
    await goToOnboardingStep(account, 'grade', now());
    await selectOnboardingGrade(account, 'NS2', now());
    await reopen(); // force-quit
    expect(await onboardingGate(account, now())).toBe('required');
    expect(await beginOrResumeOnboarding(account, now())).toMatchObject({ step: 'grade', gradeCode: 'NS2', status: 'in_progress' });
  });

  test('going back does not lose how far the learner got; the server state never moves backwards', async () => {
    await beginOrResumeOnboarding(account, now());
    for (const step of ['language', 'grade', 'downloads'] as const) await goToOnboardingStep(account, step, now());
    expect(serverStateOf((await account.experience.getOnboarding())!)).toBe('profile_selected');
    const back = await goToOnboardingStep(account, 'language', now());
    expect(back).toMatchObject({ step: 'language', furthestStep: 'downloads' });
    expect(serverStateOf(back!)).toBe('profile_selected');
  });

  test('confirming a class writes the same preferences Apprendre writes, and is safe to repeat', async () => {
    await account.setPreference('grade_code', '9AF');
    await account.setPreference('subject_slug', 'mathematiques');
    // an account with a class would normally be "returning"; here the flow is opened on purpose (e.g. replay)
    await account.experience.updateOnboarding(() => null);
    await beginOrResumeOnboarding(account, now());
    await goToOnboardingStep(account, 'grade', now());

    await confirmOnboardingGrade(account, now()); // same class as before: the subject is kept
    expect(await account.getPreference('subject_slug')).toBe('mathematiques');

    await goToOnboardingStep(account, 'grade', now());
    await selectOnboardingGrade(account, 'NS1', now());
    const moved = await confirmOnboardingGrade(account, now());
    expect(moved).toMatchObject({ step: 'downloads', gradeCode: 'NS1', profileNeedsPush: true });
    expect(await account.getPreference('grade_code')).toBe('NS1');
    expect(await account.getPreference('subject_slug')).toBe(''); // a subject belongs to a class
    await confirmOnboardingGrade(account, now());
    expect(await account.getPreference('grade_code')).toBe('NS1');
  });

  test('"I will choose later" stores no class', async () => {
    await beginOrResumeOnboarding(account, now());
    await goToOnboardingStep(account, 'grade', now());
    await selectOnboardingGrade(account, 'NS3', now());
    expect(await skipOnboardingGrade(account, now())).toMatchObject({ step: 'downloads', gradeCode: null });
    expect(await account.getPreference('grade_code')).toBeNull();
  });

  test('finished is final: completed or skipped, later calls and later app versions change nothing', async () => {
    await beginOrResumeOnboarding(account, now());
    const done = await finishOnboarding(account, 'skipped', now());
    expect(done).toMatchObject({ status: 'skipped' });
    expect(await onboardingGate(account, now())).toBe('done');
    expect(await finishOnboarding(account, 'completed', now())).toMatchObject({ status: 'skipped' });
    expect(await goToOnboardingStep(account, 'grade', now())).toMatchObject({ status: 'skipped', step: done!.step });
    // A row written by an OLDER flow version is just as final.
    await account.experience.updateOnboarding((current) => ({ ...current!, flowVersion: 0 }));
    await reopen();
    expect(await onboardingGate(account, now())).toBe('done');
    expect(await beginOrResumeOnboarding(account, now())).toMatchObject({ status: 'skipped', flowVersion: 0 });
  });

  test('an unfinished flow from an older version resumes where it was instead of starting over', async () => {
    await beginOrResumeOnboarding(account, now());
    await goToOnboardingStep(account, 'downloads', now());
    await account.experience.updateOnboarding((current) => ({ ...current!, flowVersion: 0 }));
    await reopen();
    expect(await beginOrResumeOnboarding(account, now())).toMatchObject({ step: 'downloads', status: 'in_progress' });
  });
});

describe('forward-only merge with the server', () => {
  const at = new Date('2026-11-24T12:00:00.000Z');
  const local = (over: Partial<OnboardingRecord>): OnboardingRecord => ({
    flowVersion: 1,
    status: 'in_progress',
    step: 'grade',
    furthestStep: 'grade',
    gradeCode: null,
    startedAt: 't0',
    updatedAt: 't0',
    completedAt: null,
    serverState: null,
    serverSyncedAt: null,
    needsPush: true,
    profileNeedsPush: false,
    ...over,
  });

  test('server "ready" ends the flow here: finished on another phone means not asked again', () => {
    expect(mergeServerOnboarding(local({}), 'ready', at)).toMatchObject({ status: 'returning', serverState: 'ready', needsPush: false });
    expect(mergeServerOnboarding(null, 'ready', at)).toMatchObject({ status: 'returning', needsPush: false });
  });

  test('server ahead: resume further on; server behind: nothing goes backwards and a push is owed', () => {
    // what another phone reached is remembered, but the step on screen is not moved under the learner (review M4)
    expect(mergeServerOnboarding(local({}), 'downloads_informed', at)).toMatchObject({ status: 'in_progress', step: 'grade', furthestStep: 'ready' });
    // flow not opened here yet: start further on only when this phone already has a grade
    expect(mergeServerOnboarding(null, 'profile_selected', at, true)).toMatchObject({ step: 'downloads', furthestStep: 'downloads' });
    expect(mergeServerOnboarding(null, 'profile_selected', at, false)).toMatchObject({ step: 'welcome', furthestStep: 'downloads' });
    const ahead = local({ step: 'ready', furthestStep: 'ready' });
    expect(mergeServerOnboarding(ahead, 'new', at)).toMatchObject({ step: 'ready', furthestStep: 'ready', serverState: 'new', needsPush: true });
    const finished = local({ status: 'completed', step: 'ready', furthestStep: 'ready' });
    expect(mergeServerOnboarding(finished, 'profile_selected', at)).toMatchObject({ status: 'completed', needsPush: true });
  });

  test('server "new" and nothing local: nothing is written', () => {
    expect(mergeServerOnboarding(null, 'new', at)).toBeNull();
  });
});

describe('server sync (flag onboardingSync)', () => {
  test('finishing pushes state, tour flags and the chosen class/language once; a second run asks for nothing', async () => {
    const remote = new FakeRemote();
    await account.setPreference('locale', 'ht');
    await beginOrResumeOnboarding(account, now());
    await goToOnboardingStep(account, 'grade', now());
    await selectOnboardingGrade(account, '9AF', now());
    await confirmOnboardingGrade(account, now());
    await finishOnboarding(account, 'completed', now());
    expect(await onboardingSyncDue(account)).toBe(true);

    expect(await syncOnboarding(account, remote, { now })).toBe('synced');
    expect(remote.onboarding).toMatchObject({ state: 'ready', onboarding_version: ONBOARDING_FLOW_VERSION });
    expect(remote.profile).toEqual({ grade_code: '9AF', preferred_locale: 'ht' });
    expect(await account.experience.getOnboarding()).toMatchObject({ serverState: 'ready', needsPush: false, profileNeedsPush: false });
    expect(await onboardingSyncDue(account)).toBe(false);

    remote.calls.length = 0;
    expect(await syncOnboarding(account, remote, { now })).toBe('spaced'); // too soon: no request at all
    expect(remote.calls).toEqual([]);
    clock += ONBOARDING_SYNC_SPACING_MS;
    expect(await syncOnboarding(account, remote, { now })).toBe('nothing_to_do');
    expect(remote.calls).toEqual(['GET /v1/me/onboarding']);
  });

  test('offline: nothing is lost, nothing is marked sent, and the next attempt succeeds', async () => {
    const remote = new FakeRemote();
    remote.mode = 'offline';
    await beginOrResumeOnboarding(account, now());
    await finishOnboarding(account, 'skipped', now());
    expect(await syncOnboarding(account, remote, { now })).toBe('failed');
    expect(await account.experience.getOnboarding()).toMatchObject({ status: 'skipped', needsPush: true, serverState: null });
    remote.mode = 'online';
    clock += ONBOARDING_SYNC_SPACING_MS;
    expect(await syncOnboarding(account, remote, { now })).toBe('synced');
    expect(remote.onboarding.state).toBe('ready');
  });

  test('review M3: a PATCH the server refuses (404 profile editing off, 422 grade not offered) is final — no endless retry', async () => {
    for (const status of [404, 422]) {
      const remote = new FakeRemote();
      remote.patchRefusal = status;
      await account.experience.updateOnboarding((current) => (current ? { ...current, profileNeedsPush: true, updatedAt: `t-${status}` } : null));
      if (!(await account.experience.getOnboarding())) {
        await beginOrResumeOnboarding(account, now());
        await goToOnboardingStep(account, 'grade', now());
        await selectOnboardingGrade(account, 'NS4', now());
        await confirmOnboardingGrade(account, now());
        await finishOnboarding(account, 'completed', now());
      }
      clock += ONBOARDING_SYNC_SPACING_MS;
      await syncOnboarding(account, remote, { now });
      expect(await account.experience.getOnboarding()).toMatchObject({ profileNeedsPush: false, needsPush: false });
      expect(await onboardingSyncDue(account)).toBe(false); // Accueil will not ask again
      expect(remote.calls.filter((call) => call.startsWith('PATCH'))).toHaveLength(1);
    }
  });

  test('review M3: a server error on PATCH is NOT final (retried later), and visits in between make no request', async () => {
    const remote = new FakeRemote();
    await beginOrResumeOnboarding(account, now());
    await goToOnboardingStep(account, 'grade', now());
    await selectOnboardingGrade(account, '9AF', now());
    await confirmOnboardingGrade(account, now());
    const patch = jest.spyOn(remote, 'patchProfile').mockRejectedValueOnce(new ApiError('server', 'server_error', 503));
    clock += ONBOARDING_SYNC_SPACING_MS;
    expect(await syncOnboarding(account, remote, { now })).toBe('failed');
    expect((await account.experience.getOnboarding())?.profileNeedsPush).toBe(true);
    remote.calls.length = 0;
    for (let visit = 0; visit < 5; visit += 1) expect(await syncOnboarding(account, remote, { now })).toBe('spaced');
    expect(remote.calls).toEqual([]);
    patch.mockRestore();
    clock += ONBOARDING_SYNC_SPACING_MS;
    expect(await syncOnboarding(account, remote, { now })).toBe('synced');
    expect(remote.profile).toMatchObject({ grade_code: '9AF' });
  });

  test('review M3: overlapping calls share one run', async () => {
    const remote = new FakeRemote();
    await beginOrResumeOnboarding(account, now());
    await finishOnboarding(account, 'skipped', now());
    clock += ONBOARDING_SYNC_SPACING_MS;
    const outcomes = await Promise.all([syncOnboarding(account, remote, { now }), syncOnboarding(account, remote, { now }), syncOnboarding(account, remote, { now })]);
    expect(outcomes).toEqual(['synced', 'synced', 'synced']);
    expect(remote.calls.filter((call) => call.startsWith('GET /v1/me/onboarding'))).toHaveLength(1);
    expect(remote.calls.filter((call) => call.startsWith('PUT'))).toHaveLength(1);
  });

  test('review L4: a choice made while the request is in flight keeps its "to send" flag', async () => {
    const remote = new FakeRemote();
    await beginOrResumeOnboarding(account, now());
    await goToOnboardingStep(account, 'grade', now());
    await selectOnboardingGrade(account, '9AF', now());
    await confirmOnboardingGrade(account, now());
    const original = remote.patchProfile.bind(remote);
    jest.spyOn(remote, 'patchProfile').mockImplementationOnce(async (body) => {
      await account.experience.updateOnboarding((current) => ({ ...current!, updatedAt: 'changed-during-request', profileNeedsPush: true }));
      return original(body);
    });
    clock += ONBOARDING_SYNC_SPACING_MS;
    await syncOnboarding(account, remote, { now });
    expect((await account.experience.getOnboarding())?.profileNeedsPush).toBe(true);
  });

  test('review M4: new phone, the server knows the grade (profile_selected): no jump past the grade step, and the grade is prefilled', async () => {
    const remote = new FakeRemote();
    remote.onboarding.state = 'profile_selected';
    remote.serverProfile = { grade_code: 'NS2', preferred_locale: 'fr' };
    await beginOrResumeOnboarding(account, now()); // the learner is on the welcome step
    clock += ONBOARDING_SYNC_SPACING_MS;
    await syncOnboarding(account, remote, { now });
    expect(await account.experience.getOnboarding()).toMatchObject({ step: 'welcome', furthestStep: 'downloads', gradeCode: 'NS2', status: 'in_progress' });
    expect(await account.getPreference('grade_code')).toBeNull(); // confirmed by the learner on the grade step, not behind their back
    await goToOnboardingStep(account, 'grade', now());
    await confirmOnboardingGrade(account, now());
    expect(await account.getPreference('grade_code')).toBe('NS2');
  });

  test('review M4: finished elsewhere (ready) — the server’s grade becomes the phone’s grade, so Apprendre has courses', async () => {
    const remote = new FakeRemote();
    remote.onboarding.state = 'ready';
    remote.serverProfile = { grade_code: '9AF', preferred_locale: 'ht' };
    clock += ONBOARDING_SYNC_SPACING_MS;
    await syncOnboarding(account, remote, { now });
    expect(await onboardingGate(account, now())).toBe('done');
    expect(await account.getPreference('grade_code')).toBe('9AF');
    // a phone that already has a grade does not ask for the profile at all
    const again = new FakeRemote();
    again.onboarding.state = 'ready';
    clock += ONBOARDING_SYNC_SPACING_MS;
    await syncOnboarding(account, again, { now });
    expect(again.calls).not.toContain('GET /v1/me');
  });

  test('a new phone for a learner the server already knows: onboarding is not required after the first sync', async () => {
    const remote = new FakeRemote();
    remote.onboarding = { state: 'ready', onboarding_version: 1, tour_version_seen: 1, tour_dismissed: true };
    expect(await onboardingGate(account, now())).toBe('required');
    await syncOnboarding(account, remote, { now });
    expect(await onboardingGate(account, now())).toBe('done');
    expect(await account.experience.getTour()).toMatchObject({ versionSeen: 1, dismissed: true, needsPush: false });
    expect(remote.calls.filter((call) => call.startsWith('PUT'))).toEqual([]); // nothing to tell the server
  });

  test('a stale replay cannot move the server backwards', async () => {
    const remote = new FakeRemote();
    remote.onboarding = { state: 'downloads_informed', onboarding_version: 1, tour_version_seen: 2, tour_dismissed: true };
    await beginOrResumeOnboarding(account, now());
    await goToOnboardingStep(account, 'language', now());
    await syncOnboarding(account, remote, { now });
    expect(remote.onboarding).toEqual({ state: 'downloads_informed', onboarding_version: 1, tour_version_seen: 2, tour_dismissed: true });
    expect(await account.experience.getOnboarding()).toMatchObject({ step: 'language', furthestStep: 'ready', status: 'in_progress' });
  });

  test('a session that ended while the request was in flight writes nothing', async () => {
    const remote = new FakeRemote();
    remote.onboarding.state = 'ready';
    await beginOrResumeOnboarding(account, now());
    expect(await syncOnboarding(account, remote, { now, isActive: () => false })).toBe('failed');
    expect(await account.experience.getOnboarding()).toMatchObject({ status: 'in_progress', serverState: null });
  });
});

describe('the HTTP adapter (assumed contract, briefs/identity.md)', () => {
  function api(handler: (url: string, init: RequestInit) => Response | Promise<Response>, tokens = ['token-1', 'token-2']) {
    const seen: { url: string; method: string; headers: Record<string, string>; body: unknown; refreshed: boolean }[] = [];
    let asked = 0;
    const client = new ExperienceApi({
      baseUrl: 'http://127.0.0.1:9/',
      timeoutMs: 1000,
      getAccessToken: async (options) => {
        asked += 1;
        return options?.forceRefresh ? tokens[1] : tokens[0];
      },
      fetchImpl: async (url, init) => {
        seen.push({
          url,
          method: init?.method ?? 'GET',
          headers: init?.headers as Record<string, string>,
          body: typeof init?.body === 'string' ? JSON.parse(init.body) : null,
          refreshed: asked > 1,
        });
        return handler(url, init ?? {});
      },
    });
    return { client, seen };
  }
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

  test('reads and writes the onboarding state on the documented paths, with the bearer token', async () => {
    const state = { state: 'profile_selected', onboarding_version: 1, tour_version_seen: 0, tour_dismissed: false };
    const { client, seen } = api(() => json(200, state));
    expect(await client.getOnboarding()).toEqual(state);
    await client.putOnboarding({ state: 'ready', onboarding_version: 1, tour_version_seen: 1, tour_dismissed: true });
    await client.patchProfile({ grade_code: '9AF', preferred_locale: 'ht' });
    expect(seen.map((call) => `${call.method} ${call.url}`)).toEqual([
      'GET http://127.0.0.1:9/v1/me/onboarding',
      'PUT http://127.0.0.1:9/v1/me/onboarding',
      'PATCH http://127.0.0.1:9/v1/me',
    ]);
    expect(seen[0].headers.Authorization).toBe('Bearer token-1');
    expect(seen[1].body).toEqual({ state: 'ready', onboarding_version: 1, tour_version_seen: 1, tour_dismissed: true });
    expect(seen[2].body).toEqual({ grade_code: '9AF', preferred_locale: 'ht' }); // never a user id, never anything else
  });

  test('a 401 is retried once with a refreshed token; a second 401 asks for sign-in', async () => {
    let calls = 0;
    const { client, seen } = api(() => (++calls === 1 ? json(401, { error: { code: 'token_expired' } }) : json(200, { state: 'new' })));
    expect((await client.getOnboarding()).state).toBe('new');
    expect(seen.map((call) => call.headers.Authorization)).toEqual(['Bearer token-1', 'Bearer token-2']);

    const refused = api(() => json(401, { error: { code: 'token_expired' } }));
    await expect(refused.client.getOnboarding()).rejects.toMatchObject({ kind: 'auth_required' });
  });

  test('flag off on the server (404), server errors and nonsense bodies are errors, never data', async () => {
    await expect(api(() => json(404, { error: { code: 'not_found' } })).client.getOnboarding()).rejects.toMatchObject({ kind: 'client', code: 'not_found' });
    await expect(api(() => json(503, { error: { code: 'dependency_unavailable' } })).client.getOnboarding()).rejects.toMatchObject({ kind: 'server' });
    await expect(api(() => json(200, { state: 'finished' })).client.getOnboarding()).rejects.toMatchObject({ code: 'invalid_response' });
    await expect(api(() => new Response('<html>captive portal</html>', { status: 200 })).client.getOnboarding()).rejects.toBeInstanceOf(ApiError);
    await expect(
      api(() => {
        throw new TypeError('Network request failed');
      }).client.getOnboarding(),
    ).rejects.toMatchObject({ kind: 'network' });
  });

  test('validation: unknown states and negative versions are refused; missing optional numbers default to 0', () => {
    expect(parseRemoteOnboarding({ state: 'ready' })).toEqual({ state: 'ready', onboarding_version: 0, tour_version_seen: 0, tour_dismissed: false });
    expect(() => parseRemoteOnboarding({ state: 'ready', tour_version_seen: -1 })).toThrow(ApiError);
    expect(() => parseRemoteOnboarding(null)).toThrow(ApiError);
    expect(() => parseRemoteOnboarding([])).toThrow(ApiError);
  });
});
