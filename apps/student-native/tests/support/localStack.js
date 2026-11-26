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
const API_PORT_BASE = 20000;
const API_PORT_SPAN = 10000; // 20000-29999: clear of Supabase lanes (54xxx-58xxx), 8000 and 8081
const net = require('node:net');

function parsePort(value, name) {
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be a port number, got "${value}".`);
  }
  return port;
}

/** One pid/log file per checkout, so two worktrees never signal each other's server. */
function repoTag(root = REPO_ROOT) {
  return crypto.createHash('sha256').update(path.resolve(root)).digest('hex').slice(0, 12);
}

/** Default test-API port: a stable function of the checkout root, in 20000-29999. */
function defaultApiPort(root = REPO_ROOT) {
  return API_PORT_BASE + (parseInt(repoTag(root).slice(0, 8), 16) % API_PORT_SPAN);
}

/** EDU_MOBILE_TEST_API_PORT (validated) wins; otherwise the per-checkout default. */
function resolveApiPort(processEnv = process.env, root = REPO_ROOT) {
  return processEnv.EDU_MOBILE_TEST_API_PORT
    ? parsePort(processEnv.EDU_MOBILE_TEST_API_PORT, 'EDU_MOBILE_TEST_API_PORT')
    : defaultApiPort(root);
}

const API_PORT = resolveApiPort();
const API_URL = `http://127.0.0.1:${API_PORT}`;
const PID_FILE = path.join(os.tmpdir(), `edu-mobile-test-api-${repoTag()}.pid`);
const LOG_FILE = path.join(os.tmpdir(), `edu-mobile-test-api-${repoTag()}.log`);

function readEnvFile(file) {
  const values = Object.create(null);
  if (!fs.existsSync(file)) return values;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim() || line.trim().startsWith('#') || !line.includes('=')) continue;
    const index = line.indexOf('=');
    const name = line.slice(0, index).trim();
    if (name in values || !/^[a-z_][a-z0-9_]*$/i.test(name)) throw new Error('Ambiguous environment file');
    values[name] = line.slice(index + 1).trim();
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

function publishedPorts(container, internal) {
  const format = `{{json (index .NetworkSettings.Ports "${internal}/tcp")}}`;
  const bindings = JSON.parse(execFileSync('docker', ['inspect', '--format', format, container], { encoding: 'utf8' }));
  return (bindings ?? []).filter((binding) => ['0.0.0.0', '127.0.0.1', '::'].includes(binding.HostIp))
    .map((binding) => Number(binding.HostPort));
}

const ENDPOINTS = {
  LOCAL_ADMIN_DATABASE_URL: ['postgresql:', 'dbPort', '/postgres'],
  EDU_DATABASE_URL: ['postgresql+asyncpg:', 'dbPort', '/postgres'],
  LOCAL_SUPABASE_URL: ['http:', 'apiPort', '/'],
  EDU_AUTH_ISSUER: ['http:', 'apiPort', '/auth/v1'],
  EDU_AUTH_JWKS_URL: ['http:', 'apiPort', '/auth/v1/.well-known/jwks.json'],
};

function validateEndpoint(name, value, protocol, port, pathname, hosts = ['127.0.0.1', 'localhost']) {
  let url;
  try { url = new URL(value); } catch { throw new Error(`${name} is missing or invalid`); }
  if (!hosts.includes(url.hostname)) throw new Error(`${name} is not this machine`);
  if (url.protocol !== protocol || Number(url.port) !== port || url.pathname !== pathname ||
      url.search || url.hash || (protocol === 'http:' && (url.username || url.password))) {
    throw new Error(`${name} does not match the verified endpoint on port ${port}`);
  }
}

function deriveTarget({ configText, env, processEnv = process.env, getPorts = publishedPorts }) {
  const config = parseSupabaseConfig(configText);
  if (!config.projectId) throw new Error('supabase/config.toml has no project_id');
  if (config.projectId === SHARED_PROJECT_ID || !/^[a-zA-Z0-9_-]+$/.test(config.projectId)) {
    throw new Error('Refusing shared stack or invalid project_id. Use a separate worktree with its own project_id.');
  }
  const fastApiPort = resolveApiPort(processEnv);
  if (new Set([fastApiPort, config.apiPort, config.dbPort]).size !== 3) throw new Error('Conflicting stack ports');
  for (const [name, [protocol, portKey, pathname]] of Object.entries(ENDPOINTS)) {
    // Pydantic settings are case insensitive. Validate all spellings before a child can inherit them.
    for (const source of [env, processEnv]) {
      for (const key of Object.keys(source)) {
        if (key.toUpperCase() === name && (key !== name || source[key] !== env[name])) {
          throw new Error(`Conflicting environment override for ${name}`);
        }
      }
    }
    validateEndpoint(name, env[name], protocol, parsePort(config[portKey], name), pathname);
  }
  const dbContainer = `supabase_db_${config.projectId}`;
  const kongContainer = `supabase_kong_${config.projectId}`;
  for (const [container, internal, expected] of [[dbContainer, 5432, config.dbPort], [kongContainer, 8000, config.apiPort]]) {
    const ports = getPorts(container, internal);
    if (!ports.length || ports.some((port) => port !== expected)) {
      throw new Error(`${container} does not publish the verified port ${expected}`);
    }
  }
  return { projectId: config.projectId, dbContainer, kongContainer, dbPort: config.dbPort, apiPort: config.apiPort, fastApiPort };
}

function deriveRepoTarget(env = readRootEnv()) {
  const configText = fs.readFileSync(path.join(REPO_ROOT, 'supabase', 'config.toml'), 'utf8');
  return deriveTarget({ configText, env });
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

/** Rejects if anything already accepts a TCP connection on 127.0.0.1:<port>. */
function assertPortFree(port) {
  return new Promise((resolve, reject) => {
    const taken = () =>
      reject(
        new Error(
          `Port ${port} on 127.0.0.1 is already in use, so the mobile test API cannot start. Another process (likely ` +
            'another checkout\'s test API, or a stale one) is listening there; the tests would run against it. ' +
            'Stop it, or choose a free port with EDU_MOBILE_TEST_API_PORT.',
        ),
      );
    // Bind locally instead of opening a connection to an unknown listener.
    const probe = net.createServer();
    probe.once('error', (error) => error.code === 'EADDRINUSE' ? taken() : reject(error));
    probe.listen(port, '127.0.0.1', () => probe.close((error) => error ? reject(error) : resolve()));
  });
}

/**
 * Wait until OUR spawned server is ready. A foreign server answering /ready is never enough: our own
 * log must show uvicorn bound this port and our child must still be alive. Kills the group and throws
 * on any failure.
 *
 *   port, fetchFn, readLog() => string, isAlive() => boolean, kill() => void, sleep(ms), timeoutMs, pollMs
 */
async function awaitOwnApi({
  port, fetchFn = fetch, readLog, isAlive, kill, timeoutMs = 30_000, pollMs = 300,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
}) {
  const fail = (message) => {
    kill();
    throw new Error(message);
  };
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const log = readLog();
    if (!isAlive()) {
      fail(
        `The test API process exited before becoming ready (port ${port} taken? set EDU_MOBILE_TEST_API_PORT). ` +
          `Log tail: ${log.slice(-400)}`,
      );
    }
    if (/address already in use|errno 98|errno 48/i.test(log)) {
      fail(`The test API could not bind port ${port} (already in use). Set EDU_MOBILE_TEST_API_PORT to a free port.`);
    }
    if (log.includes(`Uvicorn running on http://127.0.0.1:${port} `)) {
      try {
        const response = await fetchFn(`http://127.0.0.1:${port}/ready`);
        if (response.ok) return;
      } catch {
        // not answering yet
      }
    }
    if (Date.now() > deadline) {
      fail('The local API did not become ready (its own log never showed it bound the port). Is the database running? (`make start`)');
    }
    await sleep(pollMs);
  }
}

module.exports = {
  assertPortFree, awaitOwnApi, defaultApiPort, resolveApiPort, API_URL,
  REPO_ROOT, API_PORT, PID_FILE, LOG_FILE, SHARED_PROJECT_ID, readRootEnv,
  validateEndpoint, readEnvFile, parseSupabaseConfig, deriveTarget, deriveRepoTarget, resetLearningState, repoTag, TRUNCATE_SQL,
};
