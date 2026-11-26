/**
 * Tests run the app's platform-free core (src/core) in Node:
 *  - against a REAL SQLite engine (Node's built-in one) through the same
 *    SqlDatabase interface the phone uses, and
 *  - against the REAL local API and Supabase Auth (started by tests/support/globalSetup).
 *
 * Component tests (tests/components, *.test.tsx) render the app's real screens
 * with react-test-renderer over the same real SQLite engine. `react-native`,
 * `expo-router` and the safe-area library are replaced by small stand-ins
 * (tests/support/*Mock*), so those tests check words, states and ordering —
 * not pixels. Layout is checked on the emulators (see docs/MOBILE_02_REPORT.md).
 */
module.exports = {
  testEnvironment: 'node',
  roots: ['<rootDir>/tests'],
  testMatch: ['**/*.test.ts', '**/*.test.tsx'],
  moduleNameMapper: {
    '^react-native$': '<rootDir>/tests/support/reactNativeMock.tsx',
    '^expo-router$': '<rootDir>/tests/support/expoRouterMock.tsx',
    '^react-native-safe-area-context$': '<rootDir>/tests/support/safeAreaMock.ts',
  },
  transform: {
    '^.+\\.tsx?$': [
      'babel-jest',
      {
        babelrc: false,
        configFile: false,
        presets: [require.resolve('@babel/preset-typescript')],
        plugins: [
          [require.resolve('@babel/plugin-transform-react-jsx'), { runtime: 'automatic' }],
          require.resolve('@babel/plugin-transform-modules-commonjs'),
        ],
      },
    ],
  },
  globalSetup: '<rootDir>/tests/support/globalSetup.js',
  globalTeardown: '<rootDir>/tests/support/globalTeardown.js',
  testTimeout: 30000,
  // One worker: the integration tests share two synthetic accounts on one local server.
  maxWorkers: 1,
};
