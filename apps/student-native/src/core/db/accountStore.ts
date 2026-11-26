import type { ChangeItem, OperationResult, SyncOperation } from '../api/types';
import { EXPERIENCE_MIGRATIONS } from '../experience/schema';
import { ExperienceStore } from '../experience/store';
import { migrate, Migration, SqlDatabase, SqlExecutor } from './driver';

/**
 * PRIVATE data of ONE account, in its own database file (`account-<user id>`).
 *
 * A signed-in session only ever opens its own file, so one student's session
 * has no way to query another student's rows. No token or password is stored here.
 *
 * Tables
 *   attempts           every practice answer known on this phone (made here, or pulled from another device)
 *   question_progress  projection: latest answer per question (kept in step with `attempts` inside the same transaction)
 *   lesson_progress    lesson completion (local intent + server confirmation)
 *   outbox             operations not yet confirmed by the server, in the order they happened
 *   meta               account id, pull cursor, last sync time, preferences
 *
 * Versions 2+ add the learner-experience tables (onboarding, tour, …). They are
 * defined in ../experience/schema.ts, are additive only, and never touch the
 * tables above.
 */
const MIGRATIONS: Migration[] = [
  {
    version: 1,
    statements: [
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
    ],
  },
  ...EXPERIENCE_MIGRATIONS,
  {
    // Online-only continuity (Content-Delivery). A minimal reference to each lesson this student opened or
    // answered, so Home and Review can show activity for a lesson that is not downloaded. It holds the
    // lesson's PUBLIC title and revision only: never lesson content, answers or questions. Additive only.
    version: 5,
    statements: [
      `CREATE TABLE IF NOT EXISTS lesson_refs (
         lesson_id      TEXT NOT NULL,
         locale         TEXT NOT NULL CHECK (locale IN ('fr','ht')),
         title          TEXT NOT NULL,
         revision_id    TEXT NOT NULL,
         revision       INTEGER NOT NULL,
         last_opened_at TEXT NOT NULL,
         PRIMARY KEY (lesson_id, locale)
       )`,
    ],
  },
];

/** What is remembered about a lesson this student has opened: public metadata only. */
export interface LessonRef {
  lessonId: string;
  locale: 'fr' | 'ht';
  title: string;
  revisionId: string;
  revision: number;
  /** ISO time of the most recent open, answer or completion. */
  at: string;
}

async function upsertLessonRef(tx: SqlExecutor, ref: LessonRef): Promise<void> {
  await tx.run(
    `INSERT INTO lesson_refs (lesson_id, locale, title, revision_id, revision, last_opened_at)
     VALUES (?, ?, ?, ?, ?, ?)
     ON CONFLICT (lesson_id, locale) DO UPDATE SET title = excluded.title, revision_id = excluded.revision_id,
       revision = excluded.revision, last_opened_at = excluded.last_opened_at`,
    [ref.lessonId, ref.locale, ref.title, ref.revisionId, ref.revision, ref.at],
  );
}

export type SyncState = 'pending' | 'synced' | 'needs_attention';

export interface PendingOperation {
  opId: string;
  kind: string;
  payload: Record<string, unknown>;
  clientRecordedAt: string;
}

export interface AttentionItem {
  opId: string;
  kind: string;
  problemCode: string;
  recordedAt: string;
}

export interface QuestionProgress {
  questionRevisionId: string;
  attemptsCount: number;
  lastChoiceId: string;
  /** Server verdict when known, otherwise the provisional local one; null if neither exists. */
  lastIsCorrect: boolean | null;
  lastSyncState: SyncState;
}

export interface LessonProgress {
  lessonId: string;
  completed: boolean;
  completedRevisionId: string | null;
  completedAt: string | null;
  syncState: SyncState;
}

export interface SyncSummary {
  pending: number;
  needsAttention: number;
  lastSyncAt: string | null;
}

export interface NewAnswer {
  opId: string;
  questionRevisionId: string;
  lessonRevisionId: string;
  lessonId: string;
  choiceId: string;
  localIsCorrect: boolean;
  recordedAt: string;
  /** Written in the same transaction as the answer, so an answered lesson is never unreferenced. */
  ref?: LessonRef;
}

export interface NewCompletion {
  opId: string;
  lessonId: string;
  lessonRevisionId: string;
  recordedAt: string;
  ref?: LessonRef;
}

export interface PushApplyOutcome {
  confirmed: number;
  needsAttention: number;
  unresolved: number;
}

const META_ACCOUNT = 'account_id';
const META_CURSOR = 'pull_cursor';
const META_RESET = 'pull_reset_pending';
const META_LAST_SYNC = 'last_sync_at';

function asBool(value: number | null): boolean | null {
  return value === null || value === undefined ? null : value !== 0;
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

export class AccountStore {
  /** This account's onboarding / tour / cached extras. Same file, same isolation as the learning data. */
  readonly experience: ExperienceStore;

  private constructor(
    private readonly db: SqlDatabase,
    readonly accountId: string,
  ) {
    this.experience = new ExperienceStore(db);
  }

  /**
   * Opens the store and binds it to `accountId`. If the file already belongs
   * to a different account it refuses to open (defence against a mixed-up file name).
   */
  static async open(db: SqlDatabase, accountId: string): Promise<AccountStore> {
    await migrate(db, MIGRATIONS);
    const owner = await db.first<{ value: string }>('SELECT value FROM meta WHERE key = ?', [
      META_ACCOUNT,
    ]);
    if (owner === null) {
      await db.run('INSERT INTO meta (key, value) VALUES (?, ?)', [META_ACCOUNT, accountId]);
    } else if (owner.value !== accountId) {
      await db.close();
      throw new Error('account database belongs to another account');
    }
    return new AccountStore(db, accountId);
  }

  close(): Promise<void> {
    return this.db.close();
  }

  // ------------------------------------------------------------------ preferences
  async getPreference(name: string): Promise<string | null> {
    const row = await this.db.first<{ value: string }>('SELECT value FROM meta WHERE key = ?', [
      `pref.${name}`,
    ]);
    return row?.value ?? null;
  }

  async setPreference(name: string, value: string): Promise<void> {
    await setMeta(this.db, `pref.${name}`, value);
  }

  // ---------------------------------------------------------------- local actions
  /**
   * Save an answer. ONE transaction writes the attempt, the progress projection
   * and the pending operation; the UI may only confirm after this resolves.
   */
  async recordAnswer(answer: NewAnswer): Promise<void> {
    await this.db.transaction(async (tx) => {
      if (answer.ref) await upsertLessonRef(tx, answer.ref);
      await tx.run(
        `INSERT INTO attempts (op_id, question_revision_id, lesson_revision_id, lesson_id, choice_id,
           local_is_correct, recorded_at, origin, sync_state)
         VALUES (?, ?, ?, ?, ?, ?, ?, 'local', 'pending')`,
        [
          answer.opId,
          answer.questionRevisionId,
          answer.lessonRevisionId,
          answer.lessonId,
          answer.choiceId,
          answer.localIsCorrect ? 1 : 0,
          answer.recordedAt,
        ],
      );
      await refreshQuestionProgress(tx, answer.questionRevisionId);
      await tx.run(
        `INSERT INTO outbox (op_id, kind, payload_json, client_recorded_at, state)
         VALUES (?, 'practice_answer', ?, ?, 'pending')`,
        [
          answer.opId,
          JSON.stringify({
            question_revision_id: answer.questionRevisionId,
            response: { choice_id: answer.choiceId },
          }),
          answer.recordedAt,
        ],
      );
    });
  }

  /**
   * Mark a lesson as finished. Returns false (and writes nothing) if this
   * account already has a completion for the lesson, local or from the server.
   */
  async recordLessonCompleted(completion: NewCompletion): Promise<boolean> {
    return this.db.transaction(async (tx) => {
      if (completion.ref) await upsertLessonRef(tx, completion.ref);
      const existing = await tx.first<{ local_completed_at: string | null; server_completed_at: string | null }>(
        'SELECT local_completed_at, server_completed_at FROM lesson_progress WHERE lesson_id = ?',
        [completion.lessonId],
      );
      if (existing && (existing.local_completed_at || existing.server_completed_at)) return false;
      await tx.run(
        `INSERT INTO lesson_progress (lesson_id, local_revision_id, local_completed_at, local_op_id, sync_state)
         VALUES (?, ?, ?, ?, 'pending')
         ON CONFLICT (lesson_id) DO UPDATE SET local_revision_id = excluded.local_revision_id,
           local_completed_at = excluded.local_completed_at, local_op_id = excluded.local_op_id,
           sync_state = 'pending'`,
        [completion.lessonId, completion.lessonRevisionId, completion.recordedAt, completion.opId],
      );
      await tx.run(
        `INSERT INTO outbox (op_id, kind, payload_json, client_recorded_at, state)
         VALUES (?, 'lesson_completed', ?, ?, 'pending')`,
        [
          completion.opId,
          JSON.stringify({ lesson_revision_id: completion.lessonRevisionId }),
          completion.recordedAt,
        ],
      );
      return true;
    });
  }

  // ------------------------------------------------------------------ lesson references
  /** Remember that this student opened a lesson (any source). Public metadata only. */
  async touchLessonRef(ref: LessonRef): Promise<void> {
    await this.db.transaction((tx) => upsertLessonRef(tx, ref));
  }

  /** Lessons this student has opened or answered, most recent first. */
  async listLessonRefs(locale: 'fr' | 'ht'): Promise<LessonRef[]> {
    const rows = await this.db.all<{
      lesson_id: string;
      locale: 'fr' | 'ht';
      title: string;
      revision_id: string;
      revision: number;
      last_opened_at: string;
    }>('SELECT * FROM lesson_refs WHERE locale = ? ORDER BY last_opened_at DESC, lesson_id', [locale]);
    return rows.map((row) => ({
      lessonId: row.lesson_id,
      locale: row.locale,
      title: row.title,
      revisionId: row.revision_id,
      revision: row.revision,
      at: row.last_opened_at,
    }));
  }

  // ------------------------------------------------------------------------ push
  async pendingOperations(limit: number): Promise<PendingOperation[]> {
    const rows = await this.db.all<{
      op_id: string;
      kind: string;
      payload_json: string;
      client_recorded_at: string;
    }>(
      `SELECT op_id, kind, payload_json, client_recorded_at FROM outbox
       WHERE state = 'pending' ORDER BY seq LIMIT ?`,
      [limit],
    );
    return rows.map((row) => ({
      opId: row.op_id,
      kind: row.kind,
      payload: JSON.parse(row.payload_json) as Record<string, unknown>,
      clientRecordedAt: row.client_recorded_at,
    }));
  }

  static toWire(operation: PendingOperation): SyncOperation {
    return {
      op_id: operation.opId,
      kind: operation.kind,
      client_recorded_at: operation.clientRecordedAt,
      payload: operation.payload,
    };
  }

  /**
   * Record the server's answer for a pushed batch. In ONE transaction, for each
   * operation: the acknowledgement is written onto the attempt / progress row
   * and only then the outbox row is removed. `rejected` and `conflict` are kept
   * as "needs attention" and are never sent again.
   */
  async applyPushResults(sent: PendingOperation[], results: OperationResult[]): Promise<PushApplyOutcome> {
    const byId = new Map(results.map((result) => [result.op_id.toLowerCase(), result]));
    const outcome: PushApplyOutcome = { confirmed: 0, needsAttention: 0, unresolved: 0 };
    await this.db.transaction(async (tx) => {
      for (const operation of sent) {
        const result = byId.get(operation.opId.toLowerCase());
        if (!result) {
          outcome.unresolved += 1;
          continue;
        }
        if (result.status === 'accepted') {
          await confirmOperation(tx, operation.opId, operation.kind, result.result ?? {});
          outcome.confirmed += 1;
        } else {
          const code =
            result.code ?? (result.status === 'conflict' ? 'op_id_conflict' : 'rejected');
          await flagOperation(tx, operation.opId, operation.kind, code);
          outcome.needsAttention += 1;
        }
      }
    });
    return outcome;
  }

  /** A single operation the server refused at the request level (HTTP 4xx when sent alone). */
  async flagOperation(operation: PendingOperation, problemCode: string): Promise<void> {
    await this.db.transaction((tx) => flagOperation(tx, operation.opId, operation.kind, problemCode));
  }

  async noteSendFailure(opIds: string[], error: string): Promise<void> {
    if (opIds.length === 0) return;
    await this.db.transaction(async (tx) => {
      for (const opId of opIds) {
        await tx.run(
          'UPDATE outbox SET send_attempts = send_attempts + 1, last_error = ? WHERE op_id = ?',
          [error, opId],
        );
      }
    });
  }

  // ------------------------------------------------------------------------ pull
  async getCursor(): Promise<string | null> {
    const row = await this.db.first<{ value: string }>('SELECT value FROM meta WHERE key = ?', [
      META_CURSOR,
    ]);
    return row?.value ?? null;
  }

  /**
   * The server said the cursor is unusable (HTTP 410). Forget it; the next
   * applied page will first clear server-derived rows. The outbox is NOT touched.
   */
  async beginCursorReset(): Promise<void> {
    await this.db.transaction(async (tx) => {
      await tx.run('DELETE FROM meta WHERE key = ?', [META_CURSOR]);
      await setMeta(tx, META_RESET, '1');
    });
  }

  /**
   * Apply one page of server changes AND advance the cursor in ONE transaction.
   * If the app dies in the middle, neither happened and the page is pulled again;
   * applying a change twice gives the same rows (upserts keyed by op id / lesson id).
   */
  async applyPulledPage(changes: ChangeItem[], nextCursor: string): Promise<number> {
    return this.db.transaction(async (tx) => {
      const reset = await tx.first<{ value: string }>('SELECT value FROM meta WHERE key = ?', [
        META_RESET,
      ]);
      if (reset) {
        const touched = await tx.all<{ question_revision_id: string }>(
          `SELECT DISTINCT question_revision_id FROM attempts WHERE origin = 'remote'`,
        );
        await tx.run(`DELETE FROM attempts WHERE origin = 'remote'`);
        for (const row of touched) await refreshQuestionProgress(tx, row.question_revision_id);
        await tx.run(
          `DELETE FROM lesson_progress WHERE local_completed_at IS NULL`,
        );
        await tx.run('DELETE FROM meta WHERE key = ?', [META_RESET]);
      }
      let applied = 0;
      for (const change of changes) {
        if (await applyChange(tx, change)) applied += 1;
      }
      await setMeta(tx, META_CURSOR, nextCursor);
      return applied;
    });
  }

  async markSynced(at: string): Promise<void> {
    await setMeta(this.db, META_LAST_SYNC, at);
  }

  // --------------------------------------------------------------------- queries
  async syncSummary(): Promise<SyncSummary> {
    const counts = await this.db.first<{ pending: number | null; attention: number | null }>(
      `SELECT SUM(state = 'pending') AS pending, SUM(state = 'needs_attention') AS attention FROM outbox`,
    );
    const last = await this.db.first<{ value: string }>('SELECT value FROM meta WHERE key = ?', [
      META_LAST_SYNC,
    ]);
    return {
      pending: counts?.pending ?? 0,
      needsAttention: counts?.attention ?? 0,
      lastSyncAt: last?.value ?? null,
    };
  }

  async attentionItems(): Promise<AttentionItem[]> {
    const rows = await this.db.all<{
      op_id: string;
      kind: string;
      problem_code: string | null;
      client_recorded_at: string;
    }>(
      `SELECT op_id, kind, problem_code, client_recorded_at FROM outbox
       WHERE state = 'needs_attention' ORDER BY seq`,
    );
    return rows.map((row) => ({
      opId: row.op_id,
      kind: row.kind,
      problemCode: row.problem_code ?? 'unknown',
      recordedAt: row.client_recorded_at,
    }));
  }

  async questionProgress(lessonId: string): Promise<Map<string, QuestionProgress>> {
    const rows = await this.db.all<{
      question_revision_id: string;
      attempts_count: number;
      last_choice_id: string;
      last_is_correct: number | null;
      last_sync_state: SyncState;
    }>('SELECT * FROM question_progress WHERE lesson_id = ?', [lessonId]);
    return new Map(
      rows.map((row) => [
        row.question_revision_id,
        {
          questionRevisionId: row.question_revision_id,
          attemptsCount: row.attempts_count,
          lastChoiceId: row.last_choice_id,
          lastIsCorrect: asBool(row.last_is_correct),
          lastSyncState: row.last_sync_state,
        },
      ]),
    );
  }

  async lessonProgress(lessonId: string): Promise<LessonProgress | null> {
    const row = await this.db.first<{
      lesson_id: string;
      local_revision_id: string | null;
      local_completed_at: string | null;
      server_revision_id: string | null;
      server_completed_at: string | null;
      sync_state: SyncState;
    }>('SELECT * FROM lesson_progress WHERE lesson_id = ?', [lessonId]);
    if (!row) return null;
    return {
      lessonId: row.lesson_id,
      completed: Boolean(row.server_completed_at ?? row.local_completed_at),
      // The server's record wins: it is the completion every device agrees on.
      completedRevisionId: row.server_revision_id ?? row.local_revision_id,
      completedAt: row.server_completed_at ?? row.local_completed_at,
      syncState: row.sync_state,
    };
  }

  async attemptCount(): Promise<number> {
    const row = await this.db.first<{ n: number }>('SELECT COUNT(*) AS n FROM attempts');
    return row?.n ?? 0;
  }
}

// ---------------------------------------------------------------------- helpers
async function setMeta(db: SqlExecutor, key: string, value: string): Promise<void> {
  await db.run(
    `INSERT INTO meta (key, value) VALUES (?, ?)
     ON CONFLICT (key) DO UPDATE SET value = excluded.value`,
    [key, value],
  );
}

/** Rebuild the projection row for one question from `attempts` (the source of truth). */
async function refreshQuestionProgress(tx: SqlExecutor, questionRevisionId: string): Promise<void> {
  const latest = await tx.first<{
    op_id: string;
    lesson_id: string;
    lesson_revision_id: string;
    choice_id: string;
    is_correct: number | null;
    sync_state: SyncState;
    recorded_at: string;
  }>(
    `SELECT op_id, lesson_id, lesson_revision_id, choice_id,
            COALESCE(server_is_correct, local_is_correct) AS is_correct, sync_state, recorded_at
     FROM attempts WHERE question_revision_id = ?
     -- "Latest" must mean the same thing on every device of the account, so it
     -- follows the SERVER's order (change version), never the phones' clocks.
     -- Answers not yet confirmed have no version: they are this phone's newest work.
     ORDER BY (server_version IS NULL) DESC, server_version DESC, recorded_at DESC, rowid DESC
     LIMIT 1`,
    [questionRevisionId],
  );
  if (!latest) {
    await tx.run('DELETE FROM question_progress WHERE question_revision_id = ?', [questionRevisionId]);
    return;
  }
  const count = await tx.first<{ n: number }>(
    'SELECT COUNT(*) AS n FROM attempts WHERE question_revision_id = ?',
    [questionRevisionId],
  );
  await tx.run(
    `INSERT INTO question_progress (question_revision_id, lesson_id, lesson_revision_id, attempts_count,
       last_op_id, last_choice_id, last_is_correct, last_sync_state, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT (question_revision_id) DO UPDATE SET
       lesson_id = excluded.lesson_id, lesson_revision_id = excluded.lesson_revision_id,
       attempts_count = excluded.attempts_count, last_op_id = excluded.last_op_id,
       last_choice_id = excluded.last_choice_id, last_is_correct = excluded.last_is_correct,
       last_sync_state = excluded.last_sync_state, updated_at = excluded.updated_at`,
    [
      questionRevisionId,
      latest.lesson_id,
      latest.lesson_revision_id,
      count?.n ?? 0,
      latest.op_id,
      latest.choice_id,
      latest.is_correct,
      latest.sync_state,
      latest.recorded_at,
    ],
  );
}

/** The server accepted this operation (now or earlier). Persist that, then drop the outbox row. */
async function confirmOperation(
  tx: SqlExecutor,
  opId: string,
  kind: string,
  result: Record<string, unknown>,
): Promise<void> {
  if (kind === 'practice_answer') {
    const isCorrect = typeof result.is_correct === 'boolean' ? (result.is_correct ? 1 : 0) : null;
    await tx.run(
      `UPDATE attempts SET sync_state = 'synced', problem_code = NULL,
         server_attempt_id = COALESCE(?, server_attempt_id),
         server_is_correct = COALESCE(?, server_is_correct),
         server_score = COALESCE(?, server_score),
         server_version = COALESCE(?, server_version)
       WHERE op_id = ?`,
      [
        str(result.attempt_id),
        isCorrect,
        typeof result.score === 'number' ? result.score : null,
        typeof result.change_version === 'number' ? result.change_version : null,
        opId,
      ],
    );
    const row = await tx.first<{ question_revision_id: string }>(
      'SELECT question_revision_id FROM attempts WHERE op_id = ?',
      [opId],
    );
    if (row) await refreshQuestionProgress(tx, row.question_revision_id);
  } else if (kind === 'lesson_completed') {
    const lessonId = str(result.lesson_id);
    if (lessonId) {
      await upsertServerCompletion(tx, lessonId, {
        revisionId: str(result.lesson_revision_id),
        completedAt: str(result.completed_at),
        version: typeof result.change_version === 'number' ? result.change_version : null,
      });
    } else {
      await tx.run(`UPDATE lesson_progress SET sync_state = 'synced' WHERE local_op_id = ?`, [opId]);
    }
  }
  await tx.run('DELETE FROM outbox WHERE op_id = ?', [opId]);
}

async function flagOperation(
  tx: SqlExecutor,
  opId: string,
  kind: string,
  problemCode: string,
): Promise<void> {
  await tx.run(
    `UPDATE outbox SET state = 'needs_attention', problem_code = ? WHERE op_id = ?`,
    [problemCode, opId],
  );
  if (kind === 'practice_answer') {
    await tx.run(
      `UPDATE attempts SET sync_state = 'needs_attention', problem_code = ? WHERE op_id = ?`,
      [problemCode, opId],
    );
    const row = await tx.first<{ question_revision_id: string }>(
      'SELECT question_revision_id FROM attempts WHERE op_id = ?',
      [opId],
    );
    if (row) await refreshQuestionProgress(tx, row.question_revision_id);
  } else if (kind === 'lesson_completed') {
    await tx.run(
      `UPDATE lesson_progress SET sync_state = 'needs_attention'
       WHERE local_op_id = ? AND server_completed_at IS NULL`,
      [opId],
    );
  }
}

async function upsertServerCompletion(
  tx: SqlExecutor,
  lessonId: string,
  server: { revisionId: string | null; completedAt: string | null; version: number | null },
): Promise<void> {
  await tx.run(
    `INSERT INTO lesson_progress (lesson_id, server_revision_id, server_completed_at, server_version, sync_state)
     VALUES (?, ?, ?, ?, 'synced')
     ON CONFLICT (lesson_id) DO UPDATE SET
       server_revision_id = COALESCE(excluded.server_revision_id, server_revision_id),
       server_completed_at = COALESCE(excluded.server_completed_at, server_completed_at),
       server_version = COALESCE(excluded.server_version, server_version),
       sync_state = 'synced'`,
    [lessonId, server.revisionId, server.completedAt, server.version],
  );
}

/**
 * Apply one change from the server's feed. Returns false for changes this app
 * version does not understand (they are skipped, not fatal, so a newer server
 * cannot block sync on an older app).
 */
async function applyChange(tx: SqlExecutor, change: ChangeItem): Promise<boolean> {
  const data = (change.data ?? {}) as Record<string, unknown>;
  const opId = str(data.op_id)?.toLowerCase() ?? null;

  if (change.entity_type === 'practice_attempt') {
    if (change.is_tombstone) {
      const rows = await tx.all<{ question_revision_id: string }>(
        'SELECT question_revision_id FROM attempts WHERE server_attempt_id = ?',
        [change.entity_id],
      );
      await tx.run('DELETE FROM attempts WHERE server_attempt_id = ?', [change.entity_id]);
      for (const row of rows) await refreshQuestionProgress(tx, row.question_revision_id);
      return true;
    }
    const questionId = str(data.question_revision_id);
    const lessonRevisionId = str(data.lesson_revision_id);
    const lessonId = str(data.lesson_id);
    const choiceId = str(data.choice_id);
    if (!opId || !questionId || !lessonRevisionId || !lessonId || !choiceId) return false;
    const isCorrect = typeof data.is_correct === 'boolean' ? (data.is_correct ? 1 : 0) : null;
    const score = typeof data.score === 'number' ? data.score : null;
    await tx.run(
      `INSERT INTO attempts (op_id, question_revision_id, lesson_revision_id, lesson_id, choice_id,
         local_is_correct, recorded_at, origin, sync_state, server_attempt_id, server_is_correct,
         server_score, server_version)
       VALUES (?, ?, ?, ?, ?, NULL, ?, 'remote', 'synced', ?, ?, ?, ?)
       ON CONFLICT (op_id) DO UPDATE SET sync_state = 'synced', problem_code = NULL,
         server_attempt_id = excluded.server_attempt_id, server_is_correct = excluded.server_is_correct,
         server_score = excluded.server_score, server_version = excluded.server_version`,
      [
        opId,
        questionId,
        lessonRevisionId,
        lessonId,
        choiceId,
        change.created_at,
        change.entity_id,
        isCorrect,
        score,
        change.version,
      ],
    );
    // The feed proves the server holds this operation (e.g. our push response was lost).
    await tx.run('DELETE FROM outbox WHERE op_id = ?', [opId]);
    await refreshQuestionProgress(tx, questionId);
    return true;
  }

  if (change.entity_type === 'lesson_progress') {
    const lessonId = str(data.lesson_id) ?? change.entity_id;
    if (change.is_tombstone) {
      await tx.run(
        `UPDATE lesson_progress SET server_revision_id = NULL, server_completed_at = NULL,
           server_version = NULL WHERE lesson_id = ?`,
        [lessonId],
      );
      await tx.run(
        'DELETE FROM lesson_progress WHERE lesson_id = ? AND local_completed_at IS NULL',
        [lessonId],
      );
      return true;
    }
    await upsertServerCompletion(tx, lessonId, {
      revisionId: str(data.lesson_revision_id),
      completedAt: str(data.completed_at),
      version: change.version,
    });
    if (opId) await tx.run('DELETE FROM outbox WHERE op_id = ?', [opId]);
    return true;
  }

  return false;
}
