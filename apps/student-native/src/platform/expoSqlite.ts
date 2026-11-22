import * as SQLite from 'expo-sqlite';

import { Mutex, OpenDatabase, SqlDatabase, SqlExecutor, SqlValue } from '../core/db/driver';

type Queryable = Pick<SQLite.SQLiteDatabase, 'runAsync' | 'getAllAsync' | 'getFirstAsync'>;

function executor(target: Queryable): SqlExecutor {
  return {
    run: async (sql, params: SqlValue[] = []) => {
      await target.runAsync(sql, params);
    },
    all: <T>(sql: string, params: SqlValue[] = []) => target.getAllAsync<T>(sql, params),
    first: <T>(sql: string, params: SqlValue[] = []) => target.getFirstAsync<T>(sql, params),
  };
}

/**
 * expo-sqlite behind the app's SqlDatabase interface.
 *
 * - WAL journal + `synchronous = FULL`: once a transaction resolves, the data
 *   has been handed to durable storage. Writes here are tiny (one answer), so the
 *   extra fsync is cheap and is what lets the UI say "saved" truthfully.
 * - A mutex serialises every write so a stand-alone write can never collide
 *   with an open exclusive transaction ("database is locked").
 */
class ExpoDatabase implements SqlDatabase {
  private readonly mutex = new Mutex();
  private readonly direct: SqlExecutor;

  constructor(private readonly db: SQLite.SQLiteDatabase) {
    this.direct = executor(db);
  }

  run(sql: string, params?: SqlValue[]): Promise<void> {
    return this.mutex.run(() => this.direct.run(sql, params));
  }

  all<T>(sql: string, params?: SqlValue[]): Promise<T[]> {
    return this.direct.all<T>(sql, params);
  }

  first<T>(sql: string, params?: SqlValue[]): Promise<T | null> {
    return this.direct.first<T>(sql, params);
  }

  transaction<T>(work: (tx: SqlExecutor) => Promise<T>): Promise<T> {
    return this.mutex.run(async () => {
      let result: T | undefined;
      await this.db.withExclusiveTransactionAsync(async (txn) => {
        result = await work(executor(txn));
      });
      return result as T;
    });
  }

  close(): Promise<void> {
    return this.mutex.run(() => this.db.closeAsync());
  }
}

export const openExpoDatabase: OpenDatabase = async (name) => {
  const db = await SQLite.openDatabaseAsync(`${name}.db`);
  await db.execAsync('PRAGMA journal_mode = WAL; PRAGMA synchronous = FULL; PRAGMA foreign_keys = ON;');
  return new ExpoDatabase(db);
};
