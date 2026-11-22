const fs = require('node:fs');
const { PID_FILE } = require('./localStack');

module.exports = async function globalTeardown() {
  try {
    const pid = Number(fs.readFileSync(PID_FILE, 'utf8'));
    if (pid > 0) process.kill(-pid, 'SIGTERM'); // the whole process group started by globalSetup
  } catch {
    // already gone
  }
  fs.rmSync(PID_FILE, { force: true });
};
