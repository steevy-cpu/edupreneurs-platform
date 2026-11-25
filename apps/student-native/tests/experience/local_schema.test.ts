/**
 * The account database after this change: the upgrade from the Mobile-02
 * schema keeps every saved row, the new tables are per account, and a failed
 * upgrade leaves the old database usable.
 *
 * Real SQLite files; the version-1 database is built from a frozen copy of the
 * Mobile-02 schema (tests/support/legacySchema.ts), not from today's code.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { AccountStore } from '../../src/core/db/accountStore';
import { EXPERIENCE_MIGRATIONS } from '../../src/core/experience/schema';
import { beginOrResumeOnboarding, goToOnboardingStep, onboardingGate } from '../../src/core/experience/onboarding';
import { buildV1AccountDatabase, dumpV1Tables } from '../support/legacySchema';
import { FaultPlan, nodeDatabases } from '../support/nodeSqlite';

const A = 'a0000000-0000-4000-8000-00000000000a';
const B = 'a0000000-0000-4000-8000-00000000000b';
const NOW = new Date('2026-11-24T12:00:00.000Z');

let dir: string;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'edu-schema-'));
});
afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

async function v1File(accountId: string) {
  const open = nodeDatabases(dir);
  const db = await open(`account-${accountId}`);
  await buildV1AccountDatabase(db, accountId);
  const before = await dumpV1Tables(db);
  await db.close();
  return before;
}

async function userVersion(accountId: string): Promise<number> {
  const db = await nodeDatabases(dir)(`account-${accountId}`);
  const row = await db.first<{ user_version: number }>('PRAGMA user_version');
  await db.close();
  return row!.user_version;
}

async function tableNames(accountId: string): Promise<string[]> {
  const db = await nodeDatabases(dir)(`account-${accountId}`);
  const rows = await db.all<{ name: string }>(`SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name`);
  await db.close();
  return rows.map((row) => row.name);
}

describe('upgrade from the Mobile-02 local schema (version 1)', () => {
  test('every saved row is still there, byte for byte, and the work is still usable', async () => {
    const before = await v1File(A);
    expect(await userVersion(A)).toBe(1);

    const store = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
    // through the app's own interface
    expect(await store.attemptCount()).toBe(4);
    expect((await store.pendingOperations(50)).map((op) => [op.opId, op.kind, op.payload])).toEqual([
      ['op-2', 'practice_answer', { question_revision_id: 'q2', response: { choice_id: 'a' } }],
      ['op-5', 'lesson_completed', { lesson_revision_id: 'rev-1' }],
    ]);
    expect(await store.syncSummary()).toEqual({ pending: 2, needsAttention: 1, lastSyncAt: '2026-11-20T09:00:00.000Z' });
    expect(await store.getCursor()).toBe('cursor-41');
    expect(await store.getPreference('locale')).toBe('ht');
    expect(await store.getPreference('grade_code')).toBe('9AF');
    expect(await store.getPreference('last_lesson_id')).toBe('lesson-1');
    expect((await store.lessonProgress('lesson-1'))?.completed).toBe(true);
    expect((await store.questionProgress('lesson-1')).size).toBe(4);
    await store.close();

    // row by row
    const raw = await nodeDatabases(dir)(`account-${A}`);
    expect(await dumpV1Tables(raw)).toEqual(before);
    await raw.close();
    expect(await userVersion(A)).toBeGreaterThanOrEqual(2);
    expect(await tableNames(A)).toEqual(expect.arrayContaining(['attempts', 'lesson_progress', 'meta', 'onboarding_state', 'outbox', 'question_progress', 'tour_state', 'daily_word_cache', 'rewards_summary_cache']));
  });

  test('a learner who used the app before the upgrade is a returning learner: never sent through onboarding', async () => {
    await v1File(A);
    const store = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
    const record = await store.experience.getOnboarding();
    expect(record).toMatchObject({ status: 'returning', step: 'ready', furthestStep: 'ready', flowVersion: 0, needsPush: true });
    expect(record!.completedAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    expect(await onboardingGate(store, NOW)).toBe('done');
    // Opening the flow anyway changes nothing for them.
    expect((await beginOrResumeOnboarding(store, NOW)).status).toBe('returning');
    await store.close();
  });

  test('opening an upgraded database again changes nothing (the upgrade runs once)', async () => {
    const before = await v1File(A);
    let store = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
    const first = await store.experience.getOnboarding();
    await store.close();
    store = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
    expect(await store.experience.getOnboarding()).toEqual(first);
    await store.close();
    const raw = await nodeDatabases(dir)(`account-${A}`);
    expect(await dumpV1Tables(raw)).toEqual(before);
    await raw.close();
  });

  test('an upgrade that fails half-way leaves the old database intact; the next start finishes it', async () => {
    const before = await v1File(A);
    const faults: FaultPlan = { shouldFail: (sql) => sql.includes('CREATE TABLE IF NOT EXISTS tour_state') };
    await expect(AccountStore.open(await nodeDatabases(dir, faults)(`account-${A}`), A)).rejects.toThrow('SQLITE_FULL');

    expect(await userVersion(A)).toBe(1);
    expect(await tableNames(A)).not.toContain('onboarding_state'); // the half-made table was rolled back
    const raw = await nodeDatabases(dir)(`account-${A}`);
    expect(await dumpV1Tables(raw)).toEqual(before);
    await raw.close();

    const store = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
    expect(await store.attemptCount()).toBe(4);
    expect((await store.experience.getOnboarding())?.status).toBe('returning');
    await store.close();
  });
});

test('review L2: every experience migration statement can be run a second time without error or change', async () => {
  await v1File(A);
  const store = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
  const before = await store.experience.getOnboarding();
  await store.close();
  const raw = await nodeDatabases(dir)(`account-${A}`);
  for (const migration of EXPERIENCE_MIGRATIONS) for (const statement of migration.statements) await raw.run(statement);
  await raw.close();
  const again = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
  expect(await again.experience.getOnboarding()).toEqual(before);
  expect(await again.attemptCount()).toBe(4);
  await again.close();
});

describe('a new account database', () => {
  test('starts with no onboarding row: the first-run flow is due', async () => {
    const store = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
    expect(await store.experience.getOnboarding()).toBeNull();
    expect(await store.experience.getTour()).toMatchObject({ versionSeen: 0, dismissed: false, inProgress: false });
    expect(await onboardingGate(store, NOW)).toBe('required');
    expect(await store.experience.getOnboarding()).toBeNull(); // asking does not start the flow
    await store.close();
  });

  test('an account that already chose its class while the flow was switched off is not asked again', async () => {
    const store = await AccountStore.open(await nodeDatabases(dir)(`account-${A}`), A);
    await store.setPreference('grade_code', 'NS1');
    expect(await onboardingGate(store, NOW)).toBe('done');
    expect(await store.experience.getOnboarding()).toMatchObject({ status: 'returning', gradeCode: 'NS1' });
    await store.close();
  });
});

describe('two accounts on one phone', () => {
  test('each has its own onboarding and tour state, in its own file', async () => {
    const open = nodeDatabases(dir);
    const a = await AccountStore.open(await open(`account-${A}`), A);
    await beginOrResumeOnboarding(a, NOW);
    await goToOnboardingStep(a, 'grade', NOW);
    await a.experience.updateTour((tour) => ({ ...tour, versionSeen: 1, dismissed: true, updatedAt: NOW.toISOString() }));
    await a.close();

    const b = await AccountStore.open(await open(`account-${B}`), B);
    expect(await b.experience.getOnboarding()).toBeNull();
    expect((await b.experience.getTour()).dismissed).toBe(false);
    await b.close();

    const again = await AccountStore.open(await open(`account-${A}`), A);
    expect(await again.experience.getOnboarding()).toMatchObject({ status: 'in_progress', step: 'grade' });
    expect(await again.experience.getTour()).toMatchObject({ versionSeen: 1, dismissed: true });
    await again.close();

    // The file name guard still holds: A's file cannot be opened as B.
    await expect(AccountStore.open(await open(`account-${A}`), B)).rejects.toThrow('belongs to another account');
  });
});
