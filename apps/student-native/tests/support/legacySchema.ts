/**
 * The account database exactly as Mobile-02 shipped it (schema version 1),
 * FROZEN here on purpose: upgrade tests build a version-1 file from this copy,
 * fill it with work, and then open it with today's code. Do not "keep it in
 * step" with src/core/db/accountStore.ts — being the old schema is its job.
 */
import type { SqlDatabase } from '../../src/core/db/driver';

export const V1_ACCOUNT_SCHEMA: string[] = [
  `CREATE TABLE meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)`,
  `CREATE TABLE attempts (
     op_id                TEXT PRIMARY KEY NOT NULL,
     question_revision_id TEXT NOT NULL,
     lesson_revision_id   TEXT NOT NULL,
     lesson_id            TEXT NOT NULL,
     choice_id            TEXT NOT NULL,
     local_is_correct     INTEGER,
     recorded_at          TEXT NOT NULL,
     origin               TEXT NOT NULL CHECK (origin IN ('local','remote')),
     sync_state           TEXT NOT NULL CHECK (sync_state IN ('pending','synced','needs_attention')),
     server_attempt_id    TEXT,
     server_is_correct    INTEGER,
     server_score         REAL,
     server_version       INTEGER,
     problem_code         TEXT
   )`,
  `CREATE INDEX attempts_by_question ON attempts (question_revision_id, recorded_at)`,
  `CREATE INDEX attempts_by_server_id ON attempts (server_attempt_id)`,
  `CREATE TABLE question_progress (
     question_revision_id TEXT PRIMARY KEY NOT NULL,
     lesson_id            TEXT NOT NULL,
     lesson_revision_id   TEXT NOT NULL,
     attempts_count       INTEGER NOT NULL,
     last_op_id           TEXT NOT NULL,
     last_choice_id       TEXT NOT NULL,
     last_is_correct      INTEGER,
     last_sync_state      TEXT NOT NULL,
     updated_at           TEXT NOT NULL
   )`,
  `CREATE INDEX question_progress_by_lesson ON question_progress (lesson_id)`,
  `CREATE TABLE lesson_progress (
     lesson_id           TEXT PRIMARY KEY NOT NULL,
     local_revision_id   TEXT,
     local_completed_at  TEXT,
     local_op_id         TEXT,
     server_revision_id  TEXT,
     server_completed_at TEXT,
     server_version      INTEGER,
     sync_state          TEXT NOT NULL CHECK (sync_state IN ('pending','synced','needs_attention'))
   )`,
  `CREATE TABLE outbox (
     seq                INTEGER PRIMARY KEY AUTOINCREMENT,
     op_id              TEXT NOT NULL UNIQUE,
     kind               TEXT NOT NULL,
     payload_json       TEXT NOT NULL,
     client_recorded_at TEXT NOT NULL,
     state              TEXT NOT NULL CHECK (state IN ('pending','needs_attention')),
     problem_code       TEXT,
     send_attempts      INTEGER NOT NULL DEFAULT 0,
     last_error         TEXT
   )`,
  `CREATE INDEX outbox_by_state ON outbox (state, seq)`,
];

export const V1_TABLES = ['meta', 'attempts', 'question_progress', 'lesson_progress', 'outbox'] as const;

/** Saved work of a learner who used the Mobile-02 app: synced and unsynced answers, a completion, preferences. */
const V1_ROWS: string[] = [
  `INSERT INTO meta (key, value) VALUES
     ('account_id', 'ACCOUNT'), ('pull_cursor', 'cursor-41'), ('last_sync_at', '2026-11-20T09:00:00.000Z'),
     ('pref.locale', 'ht'), ('pref.grade_code', '9AF'), ('pref.subject_slug', 'mathematiques'), ('pref.last_lesson_id', 'lesson-1')`,
  `INSERT INTO attempts (op_id, question_revision_id, lesson_revision_id, lesson_id, choice_id, local_is_correct, recorded_at,
     origin, sync_state, server_attempt_id, server_is_correct, server_score, server_version, problem_code) VALUES
     ('op-1', 'q1', 'rev-1', 'lesson-1', 'b', 1, '2026-11-19T10:00:00.000Z', 'local', 'synced', 'srv-1', 1, 1.0, 12, NULL),
     ('op-2', 'q2', 'rev-1', 'lesson-1', 'a', 0, '2026-11-21T10:00:00.000Z', 'local', 'pending', NULL, NULL, NULL, NULL, NULL),
     ('op-3', 'q3', 'rev-1', 'lesson-1', 'c', NULL, '2026-11-18T10:00:00.000Z', 'remote', 'synced', 'srv-3', 0, 0.0, 9, NULL),
     ('op-4', 'q4', 'rev-1', 'lesson-1', 'd', 1, '2026-11-21T11:00:00.000Z', 'local', 'needs_attention', NULL, NULL, NULL, NULL, 'unknown_question')`,
  `INSERT INTO question_progress (question_revision_id, lesson_id, lesson_revision_id, attempts_count, last_op_id,
     last_choice_id, last_is_correct, last_sync_state, updated_at) VALUES
     ('q1', 'lesson-1', 'rev-1', 1, 'op-1', 'b', 1, 'synced', '2026-11-19T10:00:00.000Z'),
     ('q2', 'lesson-1', 'rev-1', 1, 'op-2', 'a', 0, 'pending', '2026-11-21T10:00:00.000Z'),
     ('q3', 'lesson-1', 'rev-1', 1, 'op-3', 'c', 0, 'synced', '2026-11-18T10:00:00.000Z'),
     ('q4', 'lesson-1', 'rev-1', 1, 'op-4', 'd', 1, 'needs_attention', '2026-11-21T11:00:00.000Z')`,
  `INSERT INTO lesson_progress (lesson_id, local_revision_id, local_completed_at, local_op_id, server_revision_id,
     server_completed_at, server_version, sync_state) VALUES
     ('lesson-1', 'rev-1', '2026-11-21T12:00:00.000Z', 'op-5', NULL, NULL, NULL, 'pending'),
     ('lesson-0', NULL, NULL, NULL, 'rev-0', '2026-11-10T08:00:00.000Z', 3, 'synced')`,
  `INSERT INTO outbox (op_id, kind, payload_json, client_recorded_at, state, problem_code, send_attempts, last_error) VALUES
     ('op-2', 'practice_answer', '{"question_revision_id":"q2","response":{"choice_id":"a"}}', '2026-11-21T10:00:00.000Z', 'pending', NULL, 2, 'unreachable'),
     ('op-4', 'practice_answer', '{"question_revision_id":"q4","response":{"choice_id":"d"}}', '2026-11-21T11:00:00.000Z', 'needs_attention', 'unknown_question', 1, NULL),
     ('op-5', 'lesson_completed', '{"lesson_revision_id":"rev-1"}', '2026-11-21T12:00:00.000Z', 'pending', NULL, 0, NULL)`,
];

/** Writes a version-1 account database with saved work in it. The caller closes `db`. */
export async function buildV1AccountDatabase(db: SqlDatabase, accountId: string): Promise<void> {
  await db.transaction(async (tx) => {
    for (const statement of V1_ACCOUNT_SCHEMA) await tx.run(statement);
    for (const statement of V1_ROWS) await tx.run(statement.replace('ACCOUNT', accountId));
    await tx.run('PRAGMA user_version = 1');
  });
}

/** Every row of the version-1 tables, in a stable order, for before/after comparison. */
export async function dumpV1Tables(db: SqlDatabase): Promise<Record<string, unknown[]>> {
  const out: Record<string, unknown[]> = {};
  for (const table of V1_TABLES) out[table] = await db.all(`SELECT * FROM ${table} ORDER BY 1`);
  return out;
}
