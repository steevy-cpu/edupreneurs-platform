/**
 * The only database surface the app's logic knows about.
 *
 * Two adapters implement it: `src/platform/expoSqlite.ts` (the phone) and
 * `tests/support/nodeSqlite.ts` (Node's built-in SQLite, for automated tests).
 * Both are real SQLite engines, so the SQL in this folder is the SQL that runs
 * on the device.
 */
export type SqlValue = string | number | null;

export interface SqlExecutor {
  run(sql: string, params?: SqlValue[]): Promise<void>;
  all<T>(sql: string, params?: SqlValue[]): Promise<T[]>;
  first<T>(sql: string, params?: SqlValue[]): Promise<T | null>;
}

export interface SqlDatabase extends SqlExecutor {
  /**
   * Runs `work` in one write transaction: everything in it is committed
   * together, or — if it throws — nothing is. Transactions never interleave.
   */
  transaction<T>(work: (tx: SqlExecutor) => Promise<T>): Promise<T>;
  close(): Promise<void>;
}

/** Opens (creating if needed) a database file by logical name, e.g. `content` or `account-<uuid>`. */
export type OpenDatabase = (name: string) => Promise<SqlDatabase>;

/**
 * Serialises async work: adapters use it so that a transaction and a
 * stand-alone write can never overlap on the same connection.
 */
export class Mutex {
  private tail: Promise<unknown> = Promise.resolve();

  run<T>(work: () => Promise<T>): Promise<T> {
    const result = this.tail.then(work, work);
    this.tail = result.catch(() => undefined);
    return result;
  }
}

export interface Migration {
  version: number;
  statements: string[];
}

/** Applies pending migrations using SQLite's `PRAGMA user_version`. */
export async function migrate(db: SqlDatabase, migrations: Migration[]): Promise<void> {
  const row = await db.first<{ user_version: number }>('PRAGMA user_version');
  const current = row?.user_version ?? 0;
  for (const migration of migrations) {
    if (migration.version <= current) continue;
    await db.transaction(async (tx) => {
      for (const statement of migration.statements) await tx.run(statement);
      // PRAGMA cannot take a bound parameter; the value is a constant from this file.
      await tx.run(`PRAGMA user_version = ${Math.trunc(migration.version)}`);
    });
  }
}
