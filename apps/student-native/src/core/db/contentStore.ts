import type { CatalogResponse, LessonResponse, Locale, PracticeQuestion } from '../api/types';
import { migrate, Migration, SqlDatabase } from './driver';

/**
 * PUBLIC lesson content saved for offline study. Shared by every account on
 * the phone (it is the same published content for everyone) — nothing private
 * is ever stored in this database.
 */
const MIGRATIONS: Migration[] = [
  {
    version: 1,
    statements: [
      `CREATE TABLE saved_lessons (
         lesson_id   TEXT NOT NULL,
         locale      TEXT NOT NULL CHECK (locale IN ('fr','ht')),
         revision_id TEXT NOT NULL,
         revision    INTEGER NOT NULL,
         title       TEXT NOT NULL,
         blocks_json TEXT NOT NULL,
         saved_at    TEXT NOT NULL,
         PRIMARY KEY (lesson_id, locale)
       )`,
      `CREATE TABLE saved_questions (
         question_id        TEXT PRIMARY KEY NOT NULL,
         lesson_id          TEXT NOT NULL,
         locale             TEXT NOT NULL,
         lesson_revision_id TEXT NOT NULL,
         question_key       TEXT NOT NULL,
         position           INTEGER NOT NULL,
         kind               TEXT NOT NULL,
         prompt_json        TEXT NOT NULL,
         response_spec_json TEXT NOT NULL,
         answer_key_json    TEXT NOT NULL,
         explanation_json   TEXT NOT NULL,
         FOREIGN KEY (lesson_id, locale) REFERENCES saved_lessons (lesson_id, locale) ON DELETE CASCADE
       )`,
      `CREATE INDEX saved_questions_by_lesson ON saved_questions (lesson_id, locale, position)`,
      `CREATE TABLE catalog_cache (
         locale     TEXT PRIMARY KEY NOT NULL,
         body_json  TEXT NOT NULL,
         fetched_at TEXT NOT NULL
       )`,
    ],
  },
  {
    // The moment the server answered "no such published lesson" for a lesson saved on this phone.
    // Cleared by the next successful download. Additive: one nullable column, no existing row changes.
    version: 2,
    statements: [`ALTER TABLE saved_lessons ADD COLUMN server_gone_at TEXT`],
  },
  {
    version: 3,
    statements: [`CREATE TABLE download_requests (
      lesson_id TEXT NOT NULL, locale TEXT NOT NULL, token TEXT NOT NULL,
      PRIMARY KEY (lesson_id, locale)
    )`],
  },
];

export interface SavedLessonInfo {
  lessonId: string;
  locale: Locale;
  revisionId: string;
  revision: number;
  title: string;
  savedAt: string;
  /** When the server last said this lesson is no longer published; null if it never did. */
  serverGoneAt: string | null;
}

export interface SavedLesson extends SavedLessonInfo {
  blocks: LessonResponse['blocks'];
  questions: PracticeQuestion[];
}

interface LessonRow {
  lesson_id: string;
  locale: Locale;
  revision_id: string;
  revision: number;
  title: string;
  blocks_json: string;
  saved_at: string;
  server_gone_at: string | null;
}

interface QuestionRow {
  question_id: string;
  question_key: string;
  position: number;
  kind: string;
  prompt_json: string;
  response_spec_json: string;
  answer_key_json: string;
  explanation_json: string;
}

function toInfo(row: LessonRow): SavedLessonInfo {
  return {
    lessonId: row.lesson_id,
    locale: row.locale,
    revisionId: row.revision_id,
    revision: row.revision,
    title: row.title,
    savedAt: row.saved_at,
    serverGoneAt: row.server_gone_at ?? null,
  };
}

export type DownloadOutcome = 'new' | 'updated' | 'unchanged' | 'superseded';

export class ContentStore {
  private constructor(private readonly db: SqlDatabase) {}

  static async open(db: SqlDatabase): Promise<ContentStore> {
    await migrate(db, MIGRATIONS);
    return new ContentStore(db);
  }

  close(): Promise<void> {
    return this.db.close();
  }

  /** Reserve the next explicit selection before fetching. Different handles share the same order. */
  beginDownload(lessonId: string, locale: Locale): Promise<string> {
    return this.db.transaction(async (tx) => {
      const row = await tx.first<{ token: string }>('SELECT hex(randomblob(16)) AS token');
      const token = row!.token;
      await tx.run('INSERT OR REPLACE INTO download_requests VALUES (?, ?, ?)', [lessonId, locale, token]);
      return token;
    });
  }

  async finishFailedDownload(lessonId: string, locale: Locale, token: string, goneAt: string | null): Promise<void> {
    await this.db.transaction(async (tx) => {
      const args = [lessonId, locale, token];
      if (goneAt) {
        await tx.run(`UPDATE saved_lessons SET server_gone_at = ? WHERE lesson_id = ? AND locale = ?
          AND EXISTS (SELECT 1 FROM download_requests WHERE lesson_id = ? AND locale = ? AND token = ?)`,
          [goneAt, lessonId, locale, ...args]);
      }
      await tx.run('DELETE FROM download_requests WHERE lesson_id = ? AND locale = ? AND token = ?', args);
    });
  }

  /**
   * Replace the saved copy of a lesson with a new, already validated snapshot.
   * One transaction: a reader sees either the complete old copy or the complete
   * new one, and a failure part-way leaves the old copy in place.
   */
  async replaceLesson(snapshot: LessonResponse, savedAt: string, token?: string): Promise<DownloadOutcome> {
    return this.db.transaction(async (tx) => {
      const key = [snapshot.lesson_id, snapshot.locale];
      if (token) {
        const current = await tx.first<{ token: string }>(
          'SELECT token FROM download_requests WHERE lesson_id = ? AND locale = ?', key);
        if (current?.token !== token) return 'superseded';
      }
      await tx.run('DELETE FROM download_requests WHERE lesson_id = ? AND locale = ?', key);
      const previous = await tx.first<{ revision_id: string }>(
        'SELECT revision_id FROM saved_lessons WHERE lesson_id = ? AND locale = ?', key);
      if (token && previous?.revision_id === snapshot.revision_id) {
        await tx.run('UPDATE saved_lessons SET server_gone_at = NULL WHERE lesson_id = ? AND locale = ?', key);
        return 'unchanged';
      }
      await tx.run('DELETE FROM saved_lessons WHERE lesson_id = ? AND locale = ?', [
        snapshot.lesson_id,
        snapshot.locale,
      ]);
      await tx.run('DELETE FROM saved_questions WHERE lesson_id = ? AND locale = ?', [
        snapshot.lesson_id,
        snapshot.locale,
      ]);
      await tx.run(
        `INSERT INTO saved_lessons (lesson_id, locale, revision_id, revision, title, blocks_json, saved_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
        [
          snapshot.lesson_id,
          snapshot.locale,
          snapshot.revision_id,
          snapshot.revision,
          snapshot.title,
          JSON.stringify(snapshot.blocks),
          savedAt,
        ],
      );
      for (const question of snapshot.questions) {
        await tx.run(
          `INSERT INTO saved_questions (question_id, lesson_id, locale, lesson_revision_id, question_key,
             position, kind, prompt_json, response_spec_json, answer_key_json, explanation_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            question.id,
            snapshot.lesson_id,
            snapshot.locale,
            snapshot.revision_id,
            question.question_key,
            question.position,
            question.kind,
            JSON.stringify(question.prompt),
            JSON.stringify(question.response_spec),
            JSON.stringify(question.answer_key),
            JSON.stringify(question.explanation),
          ],
        );
      }
      return previous ? 'updated' : 'new';
    });
  }

  /**
   * Remove a downloaded lesson and its saved questions. Returns false if nothing was saved.
   * Public content only: student records are in the account database and are not touched.
   */
  async deleteLesson(lessonId: string, locale: Locale): Promise<boolean> {
    return this.db.transaction(async (tx) => {
      const existing = await tx.first<{ lesson_id: string }>(
        'SELECT lesson_id FROM saved_lessons WHERE lesson_id = ? AND locale = ?',
        [lessonId, locale],
      );
      await tx.run('DELETE FROM download_requests WHERE lesson_id = ? AND locale = ?', [lessonId, locale]);
      if (!existing) return false;
      await tx.run('DELETE FROM saved_questions WHERE lesson_id = ? AND locale = ?', [lessonId, locale]);
      await tx.run('DELETE FROM saved_lessons WHERE lesson_id = ? AND locale = ?', [lessonId, locale]);
      return true;
    });
  }

  /** Record that the server said this saved lesson is no longer published. The copy and the student's work are kept. */
  async markServerGone(lessonId: string, locale: Locale, at: string): Promise<void> {
    await this.db.run('UPDATE saved_lessons SET server_gone_at = ? WHERE lesson_id = ? AND locale = ?', [
      at,
      lessonId,
      locale,
    ]);
  }

  async getLessonInfo(lessonId: string, locale: Locale): Promise<SavedLessonInfo | null> {
    const row = await this.db.first<LessonRow>(
      'SELECT * FROM saved_lessons WHERE lesson_id = ? AND locale = ?',
      [lessonId, locale],
    );
    return row ? toInfo(row) : null;
  }

  async listSavedLessons(locale: Locale): Promise<SavedLessonInfo[]> {
    const rows = await this.db.all<LessonRow>(
      'SELECT * FROM saved_lessons WHERE locale = ? ORDER BY title',
      [locale],
    );
    return rows.map(toInfo);
  }

  async getLesson(lessonId: string, locale: Locale): Promise<SavedLesson | null> {
    const row = await this.db.first<LessonRow>(
      'SELECT * FROM saved_lessons WHERE lesson_id = ? AND locale = ?',
      [lessonId, locale],
    );
    if (!row) return null;
    const questions = await this.db.all<QuestionRow>(
      'SELECT * FROM saved_questions WHERE lesson_id = ? AND locale = ? ORDER BY position',
      [lessonId, locale],
    );
    return {
      ...toInfo(row),
      blocks: JSON.parse(row.blocks_json) as LessonResponse['blocks'],
      questions: questions.map((q) => ({
        id: q.question_id,
        question_key: q.question_key,
        position: q.position,
        kind: q.kind,
        prompt: JSON.parse(q.prompt_json),
        response_spec: JSON.parse(q.response_spec_json),
        answer_key: JSON.parse(q.answer_key_json),
        explanation: JSON.parse(q.explanation_json),
      })),
    };
  }

  async saveCatalog(catalog: CatalogResponse, fetchedAt: string): Promise<void> {
    await this.db.run(
      `INSERT INTO catalog_cache (locale, body_json, fetched_at) VALUES (?, ?, ?)
       ON CONFLICT (locale) DO UPDATE SET body_json = excluded.body_json, fetched_at = excluded.fetched_at`,
      [catalog.locale, JSON.stringify(catalog), fetchedAt],
    );
  }

  async getCatalog(locale: Locale): Promise<{ catalog: CatalogResponse; fetchedAt: string } | null> {
    const row = await this.db.first<{ body_json: string; fetched_at: string }>(
      'SELECT body_json, fetched_at FROM catalog_cache WHERE locale = ?',
      [locale],
    );
    if (!row) return null;
    return { catalog: JSON.parse(row.body_json) as CatalogResponse, fetchedAt: row.fetched_at };
  }
}
