/**
 * Content-delivery tests: the app's core against a REAL SQLite engine (Node's built-in one) and a
 * FAKE API. They need no local stack, no Docker, no Supabase and no network, so they cannot touch
 * the owner's shared database (see docs/architecture/content-delivery-00/08-testing.md).
 * Run:  npx jest -c jest.delivery.config.js
 */
const base = require('./jest.config.js');

module.exports = {
  ...base,
  // delivery tests + the existing network-free suites (components, unit); the integration suites need the local stack.
  roots: ['<rootDir>/tests/delivery', '<rootDir>/tests/components', '<rootDir>/tests/unit'],
  globalSetup: undefined,
  globalTeardown: undefined,
};
