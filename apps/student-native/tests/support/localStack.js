/*
 * Shared constants and the database-target derivation for the test harness.
 *
 * The harness may only ever touch the stack that belongs to THIS repository checkout:
 * container names, ports and the API pid file are all derived from `supabase/config.toml`
 * and the git-ignored root `.env`; nothing is hard-coded. It refuses to run otherwise.
 */
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..', '..');
const SHARED_PROJECT_ID = 'mon-edupreneur';
const DEFAULT_API_PORT = 8011;

function parsePort(value, name) {
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be a port number, got "${value}".`);
  }
  return port;
}

const API_PORT = process.env.EDU_MOBILE_TEST_API_PORT
  ? parsePort(process.env.EDU_MOBILE_TEST_API_PORT, 'EDU_MOBILE_TEST_API_PORT')
  : DEFAULT_API_PORT;

/** One pid/log file per checkout, so two worktrees never signal each other's server. */
function repoTag(root = REPO_ROOT) {
  return crypto.createHash('sha256').update(path.resolve(root)).digest('hex').slice(0, 12);
}
const PID_FILE = path.join(os.tmpdir(), `edu-mobile-test-api-${repoTag()}.pid`);
const LOG_FILE = path.join(os.tmpdir(), `edu-mobile-test-api-${repoTag()}.log`);

function readEnvFile(file) {
  const values = {};
  if (!fs.existsSync(file)) return values;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim() || line.trim().startsWith('#') || !line.includes('=')) continue;
    const index = line.indexOf('=');
    values[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return values;
}

function readRootEnv() {
  return readEnvFile(path.join(REPO_ROOT, '.env'));
}

/** project_id and the [api] / [db] ports from a supabase/config.toml text. */
function parseSupabaseConfig(text) {
  let section = '';
  const out = { projectId: null, apiPort: null, dbPort: null };
  for (const raw of text.split('\n')) {
    const line = raw.replace(/#.*$/, '').trim();
    const header = line.match(/^\[([^\]]+)\]$/);
    if (header) {
      section = header[1];
      continue;
    }
    const pair = line.match(/^([A-Za-z_]+)\s*=\s*(.+)$/);
    if (!pair) continue;
    const [, key, value] = pair;
    if (section === '' && key === 'project_id') out.projectId = value.replace(/^"|"$/g, '');
    if (section === 'api' && key === 'port') out.apiPort = Number(value);
    if (section === 'db' && key === 'port') out.dbPort = Number(value);
  }
  return out;
}

function dockerContainerRunning(name) {
  try {
    const out = execFileSync('docker', ['ps', '--filter', `name=^${name}$`, '--format', '{{.Names}}'], {
      encoding: 'utf8',
    });
    return out.split('\n').map((s) => s.trim()).includes(name);
  } catch {
    return false;
  }
}

/**
 * Work out which stack the harness may touch, or throw. Pure apart from `isRunning`
 * (injectable so the logic is testable without Docker).
 *
 *   configText  contents of this repository's supabase/config.toml
 *   env         parsed root .env
 *   processEnv  environment variables (EDU_TEST_ALLOW_SHARED_STACK)
 *   isRunning   (containerName) => boolean
 */
function deriveTarget({ configText, env, processEnv = process.env, isRunning = dockerContainerRunning }) {
  const config = parseSupabaseConfig(configText);
  if (!config.projectId) throw new Error('supabase/config.toml has no project_id; refusing to run the test harness.');
  if (!config.dbPort || !config.apiPort) {
    throw new Error('supabase/config.toml has no [api] / [db] port; refusing to run the test harness.');
  }
  if (config.projectId === SHARED_PROJECT_ID && processEnv.EDU_TEST_ALLOW_SHARED_STACK !== '1') {
    throw new Error(
      `supabase/config.toml project_id is the shared stack "${SHARED_PROJECT_ID}". The test harness TRUNCATEs ` +
        'learning tables, so it refuses to run there. Use your own stack, or set EDU_TEST_ALLOW_SHARED_STACK=1 ' +
        'if you really mean it.',
    );
  }

  const adminUrl = env.LOCAL_ADMIN_DATABASE_URL;
  if (!adminUrl) throw new Error('LOCAL_ADMIN_DATABASE_URL is missing from the root .env; refusing to run.');
  let admin;
  try {
    admin = new URL(adminUrl);
  } catch {
    throw new Error('LOCAL_ADMIN_DATABASE_URL in the root .env is not a valid URL; refusing to run.');
  }
  if (!['127.0.0.1', 'localhost'].includes(admin.hostname)) {
    throw new Error('LOCAL_ADMIN_DATABASE_URL is not this machine; refusing to run.');
  }
  if (Number(admin.port) !== config.dbPort) {
    throw new Error(
      `Root .env database port ${admin.port || '(none)'} does not match supabase/config.toml [db] port ` +
        `${config.dbPort}. The .env belongs to another stack; run \`make db-reset\` in this checkout. Refusing to run.`,
    );
  }
  if (env.LOCAL_SUPABASE_URL) {
    const api = new URL(env.LOCAL_SUPABASE_URL);
    if (Number(api.port) !== config.apiPort) {
      throw new Error(
        `LOCAL_SUPABASE_URL port ${api.port || '(none)'} does not match supabase/config.toml [api] port ` +
          `${config.apiPort}. Refusing to run.`,
      );
    }
  }

  const dbContainer = `supabase_db_${config.projectId}`;
  const kongContainer = `supabase_kong_${config.projectId}`;
  if (!isRunning(dbContainer)) {
    throw new Error(`Database container ${dbContainer} is not running. Start this checkout's stack: \`make start\`.`);
  }
  return { projectId: config.projectId, dbContainer, kongContainer, dbPort: config.dbPort, apiPort: config.apiPort };
}

function deriveRepoTarget() {
  const configText = fs.readFileSync(path.join(REPO_ROOT, 'supabase', 'config.toml'), 'utf8');
  return deriveTarget({ configText, env: readRootEnv() });
}

const TRUNCATE_SQL =
  'TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed, app.lesson_progress, app.account_sync_state';

/** Empty the learning tables in this checkout's own database. Throws instead of touching anything else. */
function resetLearningState() {
  const target = deriveRepoTarget();
  if (process.env.EDU_TEST_DEBUG) {
    console.error(`[mobile-test-harness] reset via container ${target.dbContainer} (db port ${target.dbPort})`);
  }
  execFileSync('docker', ['exec', target.dbContainer, 'psql', '-U', 'postgres', '-q', '-c', TRUNCATE_SQL]);
  return target;
}

module.exports = {
  REPO_ROOT, API_PORT, PID_FILE, LOG_FILE, SHARED_PROJECT_ID, readRootEnv,
  parseSupabaseConfig, deriveTarget, deriveRepoTarget, resetLearningState, repoTag, TRUNCATE_SQL,
};
