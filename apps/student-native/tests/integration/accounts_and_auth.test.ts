import fs from 'node:fs';

import { ApiError } from '../../src/core/api/errors';
import { AuthRefusedError, SupabaseAuthClient } from '../../src/core/auth/authClient';
import { WrongAccountError } from '../../src/core/auth/session';
import { AccountStore } from '../../src/core/db/accountStore';
import { answerQuestion, saveLessonOffline } from '../../src/core/learning/actions';
import {
  credentials, Device, PUBLISHABLE_KEY, resetServerLearningState, SEED, serverFeed, SUPABASE_URL,
} from '../support/device';
import { nodeDatabases } from '../support/nodeSqlite';

let device: Device;

beforeEach(() => {
  resetServerLearningState();
  device = new Device();
});

afterEach(async () => {
  await device.dispose();
});

async function signInAndSave(name: 'student_a' | 'student_b') {
  const app = await device.boot();
  const { email, password } = await credentials(name);
  const session = await app.sessions.signIn(email, password);
  await saveLessonOffline(device.api(app.sessions, session), app.content, SEED.lessonId, 'fr', device.env);
  const lesson = (await app.content.getLesson(SEED.lessonId, 'fr'))!;
  return { app, session, lesson };
}

describe('shared device: two accounts', () => {
  test('student B cannot see student A’s progress; A’s unsynced work survives and syncs at A’s next sign-in', async () => {
    const a = await signInAndSave('student_a');
    device.network.mode = 'offline';
    const aOps: string[] = [];
    for (const index of [0, 1, 2]) {
      aOps.push((await answerQuestion(a.session.account, a.lesson, a.lesson.questions[index], 'a', device.env)).opId);
    }
    expect((await a.session.account.syncSummary()).pending).toBe(3); // what the sign-out warning shows

    // A signs out WITHOUT syncing (chooses "keep my work on this phone").
    await a.app.sessions.signOut();
    expect(a.session.isActive()).toBe(false);
    expect(device.secure.value).toBeNull(); // credentials are gone
    await expect(a.session.account.syncSummary()).rejects.toThrow(); // A's database handle is closed
    await expect(a.app.sessions.accessToken(a.session)).rejects.toMatchObject({ kind: 'aborted' });

    // B signs in on the same phone.
    device.network.mode = 'online';
    const { email, password } = await credentials('student_b');
    const b = await a.app.sessions.signIn(email, password);
    expect(b.userId).toBe(SEED.accounts.student_b.id);
    expect(b.account.accountId).toBe(SEED.accounts.student_b.id);
    expect(await b.account.attemptCount()).toBe(0);
    expect((await b.account.questionProgress(SEED.lessonId)).size).toBe(0);
    expect(await b.account.syncSummary()).toEqual({ pending: 0, needsAttention: 0, lastSyncAt: null });
    // Public lesson content IS shared (saves B a download) — it holds nothing private.
    expect(await a.app.content.getLesson(SEED.lessonId, 'fr')).not.toBeNull();

    // B works and syncs: only B's operation is sent, with B's identity.
    const bOp = (await answerQuestion(b.account, a.lesson, a.lesson.questions[0], 'b', device.env)).opId;
    expect((await device.engine(a.app.sessions, b).run()).confirmed).toBe(1);
    expect((await serverFeed('student_b')).map((c) => c.op_id)).toEqual([bOp]);
    expect(await serverFeed('student_a')).toEqual([]); // A's pending work was NOT uploaded under B

    // Each account has its own file on disk.
    const files = fs.readdirSync(device.storageDir).filter((f) => f.endsWith('.db')).sort();
    expect(files).toEqual([
      `account-${SEED.accounts.student_a.id}.db`, `account-${SEED.accounts.student_b.id}.db`, 'content.db']);

    // A comes back (even after an app restart): the work is still there and now syncs.
    await a.app.sessions.signOut();
    await device.kill();
    const app = await device.boot();
    expect(app.session).toBeNull();
    const back = await app.sessions.signIn((await credentials('student_a')).email, (await credentials('student_a')).password);
    expect((await back.account.pendingOperations(50)).map((op) => op.opId)).toEqual(aOps);
    expect((await device.engine(app.sessions, back).run()).confirmed).toBe(3);
    expect((await serverFeed('student_a')).map((c) => c.op_id)).toEqual(aOps);
    expect(await serverFeed('student_b')).toHaveLength(1);
  });

  test('a response that arrives after the account switched is dropped, not stored', async () => {
    const a = await signInAndSave('student_a');
    const opId = (await answerQuestion(a.session.account, a.lesson, a.lesson.questions[0], 'b', device.env)).opId;

    // The push reaches the server; while its response is "in the air", A signs out and B signs in.
    let switched: Promise<unknown> | null = null;
    device.network.afterResponse = (url) => {
      if (url.includes('/v1/sync/push') && !switched) {
        switched = (async () => {
          await a.app.sessions.signOut();
          const { email, password } = await credentials('student_b');
          await a.app.sessions.signIn(email, password);
        })();
        return switched as Promise<void>;
      }
    };
    const run = await device.engine(a.app.sessions, a.session).run();
    expect(run).toMatchObject({ outcome: 'aborted', confirmed: 0 });
    device.network.afterResponse = null;

    const b = a.app.sessions.session!;
    expect(b.userId).toBe(SEED.accounts.student_b.id);
    expect(await b.account.attemptCount()).toBe(0); // nothing of A leaked into B's store
    expect(await b.account.syncSummary()).toMatchObject({ pending: 0 });
    expect((await device.engine(a.app.sessions, b).run()).outcome).toBe('ok');
    expect(await b.account.attemptCount()).toBe(0);
    expect(await serverFeed('student_b')).toEqual([]);

    // A's operation was committed by the server; A's phone state is intact and reconciles at next sign-in.
    await a.app.sessions.signOut();
    const again = await a.app.sessions.signIn((await credentials('student_a')).email, (await credentials('student_a')).password);
    expect((await again.account.pendingOperations(50)).map((op) => op.opId)).toEqual([opId]);
    expect(await device.engine(a.app.sessions, again).run()).toMatchObject({ outcome: 'ok', confirmed: 1 });
    expect((await serverFeed('student_a')).map((c) => c.op_id)).toEqual([opId]); // once
  });

  test('signing in as another account while one is active is refused', async () => {
    const a = await signInAndSave('student_a');
    const { email, password } = await credentials('student_b');
    await expect(a.app.sessions.signIn(email, password)).rejects.toBeInstanceOf(WrongAccountError);
    expect(a.app.sessions.session!.userId).toBe(SEED.accounts.student_a.id);
    expect(device.secure.value!.userId).toBe(SEED.accounts.student_a.id);
  });

  test('an account database cannot be opened for a different account id', async () => {
    const a = await signInAndSave('student_a');
    await a.app.sessions.signOut();
    const db = await nodeDatabases(device.storageDir)(`account-${SEED.accounts.student_a.id}`);
    await expect(AccountStore.open(db, SEED.accounts.student_b.id)).rejects.toThrow('another account');
  });
});

describe('sign-in', () => {
  test('wrong password is refused; nothing is stored', async () => {
    const app = await device.boot();
    const { email } = await credentials('student_a');
    await expect(app.sessions.signIn(email, 'definitely-not-the-password')).rejects.toBeInstanceOf(AuthRefusedError);
    expect(app.sessions.session).toBeNull();
    expect(device.secure.value).toBeNull();
  });

  test('unreachable Auth server is a transient error, not "wrong password"', async () => {
    const app = await device.boot();
    device.network.mode = 'offline';
    const { email, password } = await credentials('student_a');
    await expect(app.sessions.signIn(email, password)).rejects.toMatchObject({ kind: 'network' });
    expect(device.secure.value).toBeNull();
  });

  test('tokens live only in secure storage, never in SQLite files', async () => {
    const { session } = await signInAndSave('student_a');
    const stored = device.secure.value!;
    expect(stored.accessToken!.split('.')).toHaveLength(3);
    await session.account.setPreference('locale', 'ht');
    for (const file of fs.readdirSync(device.storageDir)) {
      const bytes = fs.readFileSync(`${device.storageDir}/${file}`).toString('latin1');
      expect(bytes.includes(stored.accessToken!)).toBe(false);
      expect(bytes.includes(stored.refreshToken!)).toBe(false);
      expect(bytes.includes(stored.accessToken!.split('.')[2])).toBe(false);
    }
  });
});

describe('expired and revoked sessions', () => {
  test('an expired access token is refreshed transparently and the rotated token is persisted', async () => {
    const { app, session, lesson } = await signInAndSave('student_a');
    await answerQuestion(session.account, lesson, lesson.questions[0], 'b', device.env);
    const before = { ...device.secure.value! };

    // Make the phone believe its token is still valid while the server rejects it (clock skew / early expiry).
    device.secure.value = { ...before, accessToken: `${before.accessToken}tampered` };
    await device.kill();
    const reopened = await device.boot();
    const run = await device.engine(reopened.sessions, reopened.session!).run();
    expect(run).toMatchObject({ outcome: 'ok', confirmed: 1 });
    expect(device.network.count('grant_type=refresh_token')).toBe(1);
    expect(device.secure.value!.refreshToken).not.toBe(before.refreshToken);
    expect(device.secure.value!.needsReauth).toBe(false);
    expect(app).toBeDefined();
  });

  test('a token past its expiry time is refreshed before the request is sent', async () => {
    const { session } = await signInAndSave('student_a');
    device.secure.value = { ...device.secure.value!, expiresAt: Math.floor(Date.now() / 1000) - 10 };
    await device.kill();
    const app = await device.boot();
    const callsBefore = device.network.calls.length;
    await device.api(app.sessions, app.session!).getMe();
    const calls = device.network.calls.slice(callsBefore).map((c) => c.url);
    expect(calls[0]).toContain('grant_type=refresh_token');
    expect(calls[1]).toContain('/v1/me');
    expect(session).toBeDefined();
  });

  test('concurrent requests share a single refresh', async () => {
    await signInAndSave('student_a');
    device.secure.value = { ...device.secure.value!, expiresAt: Math.floor(Date.now() / 1000) - 10 };
    await device.kill();
    const app = await device.boot();
    const api = device.api(app.sessions, app.session!);
    await Promise.all([api.getMe(), api.getCatalog('fr'), api.pull(null), api.getMe()]);
    expect(device.network.count('grant_type=refresh_token')).toBe(1);
  });

  test('revoked session: sync stops with auth_required, local work is kept, signing in again resumes', async () => {
    const { app, session, lesson } = await signInAndSave('student_a');
    device.network.mode = 'offline';
    const opIds: string[] = [];
    for (const index of [0, 1, 2, 3, 4]) {
      opIds.push((await answerQuestion(session.account, lesson, lesson.questions[index], 'b', device.env)).opId);
    }
    device.network.mode = 'online';

    // The session is revoked on the server (signed out elsewhere / admin action) and the token has expired.
    const auth = new SupabaseAuthClient({ supabaseUrl: SUPABASE_URL, publishableKey: PUBLISHABLE_KEY });
    await auth.signOut(device.secure.value!.accessToken!);
    device.secure.value = { ...device.secure.value!, expiresAt: Math.floor(Date.now() / 1000) - 10 };
    await device.kill();
    const reopened = await device.boot();
    const restored = reopened.session!;

    const run = await device.engine(reopened.sessions, restored).run();
    expect(run).toMatchObject({ outcome: 'auth_required', confirmed: 0 });
    expect(restored.needsReauth()).toBe(true);
    expect(restored.isActive()).toBe(true); // still this student's phone: offline study continues
    expect(device.secure.value).toMatchObject({ needsReauth: true, accessToken: null, refreshToken: null });
    expect((await restored.account.pendingOperations(50)).map((op) => op.opId)).toEqual(opIds); // nothing lost
    expect(await serverFeed('student_a')).toEqual([]);
    // More work can still be saved while signed out of the server:
    await answerQuestion(restored.account, lesson, lesson.questions[0], 'a', device.env);
    // ... and repeated sync attempts do not hammer the Auth server:
    const refreshCalls = device.network.count('grant_type=refresh_token');
    await device.engine(reopened.sessions, restored).run();
    expect(device.network.count('grant_type=refresh_token')).toBe(refreshCalls);

    // Survives a restart in that state, then the student signs in again.
    await device.kill();
    const third = await device.boot();
    expect(third.session!.needsReauth()).toBe(true);
    const { email, password } = await credentials('student_a');
    const again = await third.sessions.signIn(email, password);
    expect(again).toBe(third.session);
    expect(again.needsReauth()).toBe(false);
    const resumed = await device.engine(third.sessions, again).run();
    expect(resumed).toMatchObject({ outcome: 'ok', confirmed: 6 });
    expect((await serverFeed('student_a')).slice(0, 5).map((c) => c.op_id)).toEqual(opIds);
    expect(app).toBeDefined();
  });

  test('refresh that fails because the network is down keeps the session (transient, not expired)', async () => {
    await signInAndSave('student_a');
    device.secure.value = { ...device.secure.value!, expiresAt: Math.floor(Date.now() / 1000) - 10 };
    await device.kill();
    const app = await device.boot();
    device.network.mode = 'offline';
    const run = await device.engine(app.sessions, app.session!, { maxAttempts: 2 }).run();
    expect(run.outcome).toBe('offline');
    expect(app.session!.needsReauth()).toBe(false);
    expect(device.secure.value!.refreshToken).not.toBeNull();
    await expect(app.sessions.accessToken(app.session!)).rejects.toBeInstanceOf(ApiError);
  });
});
