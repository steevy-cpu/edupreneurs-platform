/* Starts the local FastAPI service for the integration tests (LOCAL stack only). */
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { readRootEnv, REPO_ROOT, API_PORT, PID_FILE, LOG_FILE, deriveRepoTarget,
  assertPortFree, awaitOwnApi } = require('./localStack');

module.exports = async function globalSetup() {
  const env = readRootEnv();
  for (const name of ['LOCAL_SUPABASE_URL', 'LOCAL_SUPABASE_PUBLISHABLE_KEY', 'LOCAL_SUPABASE_SECRET_KEY']) {
    if (!env[name]) {
      throw new Error(
        `${name} is missing from ${path.join(REPO_ROOT, '.env')}. Start the backend first: ` +
          '`make start && make db-reset` in the repository root. Integration tests are never skipped silently.',
      );
    }
  }
  const host = new URL(env.LOCAL_SUPABASE_URL).hostname;
  if (!['127.0.0.1', 'localhost'].includes(host)) {
    throw new Error('LOCAL_SUPABASE_URL is not this machine. Tests only run against the local stack.');
  }

  // Refuses (throws) unless the database stack is this checkout's own and the .env matches it.
  const target = deriveRepoTarget();
  console.error(
    `[mobile-test-harness] stack ${target.projectId}: db container ${target.dbContainer}, db port ${target.dbPort}, ` +
      `Supabase ${env.LOCAL_SUPABASE_URL}, test API port ${API_PORT}, pid file ${PID_FILE}`,
  );

  await assertPortFree(API_PORT); // refuse before spawning: never share a port with another checkout

  const log = fs.openSync(LOG_FILE, 'w');
  const child = spawn(
    'uv',
    ['run', 'uvicorn', 'edu_api.main:create_app', '--factory', '--host', '127.0.0.1', '--port', String(API_PORT)],
    { cwd: REPO_ROOT, detached: true, stdio: ['ignore', log, log] },
  );
  child.unref();
  fs.writeFileSync(PID_FILE, String(child.pid));

  await awaitOwnApi({
    port: API_PORT,
    readLog: () => fs.readFileSync(LOG_FILE, 'utf8'),
    isAlive: () => child.exitCode === null && child.signalCode === null,
    kill: () => {
      try {
        process.kill(-child.pid, 'SIGTERM'); // do not leave a half-started server behind
      } catch {
        // already gone
      }
    },
  });
};
