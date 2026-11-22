/* Shared constants for the test harness. Reads the git-ignored root .env written by `make db-reset`. */
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..', '..');
const API_PORT = 8011;
const PID_FILE = path.join(os.tmpdir(), 'edu-mobile-test-api.pid');

function readRootEnv() {
  const file = path.join(REPO_ROOT, '.env');
  const values = {};
  if (!fs.existsSync(file)) return values;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim() || line.trim().startsWith('#') || !line.includes('=')) continue;
    const index = line.indexOf('=');
    values[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return values;
}

module.exports = { REPO_ROOT, API_PORT, PID_FILE, readRootEnv };
