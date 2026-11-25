/**
 * Local tables added for the learner experience (onboarding, tour, …).
 *
 * They live in the PRIVATE per-account database (`account-<user id>`), next to
 * the learning tables, so each account on a shared phone has its own state and
 * signing in as another account can never read it.
 *
 * Rules these migrations follow:
 *  - ADDITIVE ONLY: `CREATE TABLE` / `INSERT` into the new tables. No statement
 *    alters, drops, rewrites or deletes from an existing table, so every saved
 *    answer, completion and queued operation survives the upgrade untouched.
 *  - Each migration runs in one transaction together with its version bump
 *    (see `migrate` in db/driver.ts): a phone that dies half-way keeps the old
 *    schema and simply tries again at the next start.
 */
import type { Migration } from '../db/driver';

export const ONBOARDING_STEPS = ['welcome', 'language', 'grade', 'downloads', 'ready'] as const;

const STEP_LIST = ONBOARDING_STEPS.map((step) => `'${step}'`).join(',');

/** SQLite's own clock, formatted like `Date.prototype.toISOString()`. Only used for the one-off upgrade row. */
const NOW_ISO = `strftime('%Y-%m-%dT%H:%M:%fZ','now')`;

export const EXPERIENCE_MIGRATION_V2: Migration = {
  version: 2,
  statements: [
    `CREATE TABLE onboarding_state (
       id                  INTEGER PRIMARY KEY CHECK (id = 1),
       flow_version        INTEGER NOT NULL,
       status              TEXT NOT NULL CHECK (status IN ('in_progress','completed','skipped','returning')),
       step                TEXT NOT NULL CHECK (step IN (${STEP_LIST})),
       furthest_step       TEXT NOT NULL CHECK (furthest_step IN (${STEP_LIST})),
       grade_code          TEXT,
       started_at          TEXT NOT NULL,
       updated_at          TEXT NOT NULL,
       completed_at        TEXT,
       server_state        TEXT,
       server_synced_at    TEXT,
       needs_push          INTEGER NOT NULL DEFAULT 1,
       profile_needs_push  INTEGER NOT NULL DEFAULT 0
     )`,
    `CREATE TABLE tour_state (
       id            INTEGER PRIMARY KEY CHECK (id = 1),
       version_seen  INTEGER NOT NULL DEFAULT 0,
       dismissed     INTEGER NOT NULL DEFAULT 0,
       in_progress   INTEGER NOT NULL DEFAULT 0,
       step          INTEGER NOT NULL DEFAULT 0,
       updated_at    TEXT NOT NULL,
       needs_push    INTEGER NOT NULL DEFAULT 0
     )`,
    // Upgrade rule: a database that already belongs to an account (it has an
    // `account_id` row) was used with an app version that had no onboarding.
    // That learner is a RETURNING user and is never sent through the first-run
    // flow. A brand-new database has an empty `meta` table at this point (the
    // owner row is written after the migrations), so nothing is inserted.
    `INSERT INTO onboarding_state
       (id, flow_version, status, step, furthest_step, started_at, updated_at, completed_at, needs_push)
     SELECT 1, 0, 'returning', 'ready', 'ready', ${NOW_ISO}, ${NOW_ISO}, ${NOW_ISO}, 1
     WHERE EXISTS (SELECT 1 FROM meta WHERE key = 'account_id')`,
  ],
};

/**
 * Word of the Day: the last word downloaded for each interface language, so it
 * can be re-read with no network. One row per language. A row may exist with no
 * word in it (only `last_attempt_at`): that is how a failed first download is
 * remembered so the app does not retry on every screen.
 */
export const EXPERIENCE_MIGRATION_V3: Migration = {
  version: 3,
  statements: [
    `CREATE TABLE daily_word_cache (
       locale           TEXT PRIMARY KEY NOT NULL CHECK (locale IN ('fr','ht')),
       haiti_date       TEXT,
       valid_until      TEXT,
       etag             TEXT,
       body_json        TEXT,
       fetched_at       TEXT,
       last_attempt_at  TEXT,
       last_outcome     TEXT
     )`,
  ],
};

export const EXPERIENCE_MIGRATIONS: Migration[] = [EXPERIENCE_MIGRATION_V2, EXPERIENCE_MIGRATION_V3];
