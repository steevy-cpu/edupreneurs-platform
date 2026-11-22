import fs from 'node:fs';
import path from 'node:path';

import { Mutex, OpenDatabase, SqlDatabase, SqlExecutor, SqlValue } from '../../src/core/db/driver';

// `node:sqlite` is loaded this way because Jest's module resolver does not know the built-in yet.
type NodeSqliteModule = typeof import('node:sqlite');
const { DatabaseSync } = (
  process as unknown as { getBuiltinModule(name: string): NodeSqliteModule }
).getBuiltinModule('node:sqlite');

/** Lets a test make chosen statements fail, to simulate storage errors (disk full, I/O error). */
export interface FaultPlan {
  /** Throw when a statement matches. Called with the SQL text. */
  shouldFail: (sql: string) => boolean;
}

class NodeSqliteDatabase implements SqlDatabase {
  private readonly db: InstanceType<typeof DatabaseSync>;
  private readonly mutex = new Mutex();
  private closed = false;

  constructor(file: string, private readonly faults: FaultPlan | null) {
    this.db = new DatabaseSync(file);
    this.db.exec('PRAGMA journal_mode = WAL; PRAGMA synchronous = FULL; PRAGMA foreign_keys = ON;');
  }

  private check(sql: string): void {
    if (this.closed) throw new Error('database is closed');
    if (this.faults?.shouldFail(sql)) throw new Error('SQLITE_FULL: simulated storage failure');
  }

  private raw: SqlExecutor = {
    run: async (sql, params = []) => {
      this.check(sql);
      this.db.prepare(sql).run(...params);
    },
    all: async <T>(sql: string, params: SqlValue[] = []) => {
      this.check(sql);
      return this.db.prepare(sql).all(...params).map((row) => ({ ...row })) as T[];
    },
    first: async <T>(sql: string, params: SqlValue[] = []) => {
      this.check(sql);
      const row = this.db.prepare(sql).get(...params);
      return row ? ({ ...row } as T) : null;
    },
  };

  run(sql: string, params?: SqlValue[]): Promise<void> {
    return this.mutex.run(() => this.raw.run(sql, params));
  }

  all<T>(sql: string, params?: SqlValue[]): Promise<T[]> {
    return this.raw.all<T>(sql, params);
  }

  first<T>(sql: string, params?: SqlValue[]): Promise<T | null> {
    return this.raw.first<T>(sql, params);
  }

  transaction<T>(work: (tx: SqlExecutor) => Promise<T>): Promise<T> {
    return this.mutex.run(async () => {
      if (this.closed) throw new Error('database is closed');
      this.db.exec('BEGIN IMMEDIATE');
      try {
        const result = await work(this.raw);
        this.check('COMMIT');
        this.db.exec('COMMIT');
        return result;
      } catch (error) {
        this.db.exec('ROLLBACK');
        throw error;
      }
    });
  }

  async close(): Promise<void> {
    await this.mutex.run(async () => {
      if (!this.closed) {
        this.closed = true;
        this.db.close();
      }
    });
  }
}

/** Database files in `directory`: this is the "phone storage" of one simulated device. */
export function nodeDatabases(directory: string, faults: FaultPlan | null = null): OpenDatabase {
  fs.mkdirSync(directory, { recursive: true });
  return async (name) => new NodeSqliteDatabase(path.join(directory, `${name}.db`), faults);
}
