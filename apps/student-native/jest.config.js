/**
 * Tests run the app's platform-free core (src/core) in Node:
 *  - against a REAL SQLite engine (Node's built-in one) through the same
 *    SqlDatabase interface the phone uses, and
 *  - against the REAL local API and Supabase Auth (started by tests/support/globalSetup).
 * They do not render React Native screens; see docs/MOBILE_01_REPORT.md.
 */
module.exports = {
  testEnvironment: 'node',
  roots: ['<rootDir>/tests'],
  testMatch: ['**/*.test.ts'],
  transform: {
    '^.+\\.ts$': [
      'babel-jest',
      {
        babelrc: false,
        configFile: false,
        presets: [require.resolve('@babel/preset-typescript')],
        plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
      },
    ],
  },
  globalSetup: '<rootDir>/tests/support/globalSetup.js',
  globalTeardown: '<rootDir>/tests/support/globalTeardown.js',
  testTimeout: 30000,
  // One worker: the integration tests share two synthetic accounts on one local server.
  maxWorkers: 1,
};
