import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'screenshots'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { globals: globals.browser },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Security rules of Admin-00 doc 5 §4: no raw HTML, no network, no browser storage in this prototype.
      'no-restricted-syntax': [
        'error',
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: 'Raw HTML is forbidden: render text only.' },
        { selector: "Identifier[name='innerHTML']", message: 'Raw HTML is forbidden: render text only.' },
        { selector: "Identifier[name='outerHTML']", message: 'Raw HTML is forbidden: render text only.' },
      ],
      'no-restricted-globals': ['error', 'fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'localStorage', 'sessionStorage'],
      'no-restricted-properties': [
        'error',
        { object: 'window', property: 'fetch', message: 'No network in Admin-01.' },
        { object: 'navigator', property: 'sendBeacon', message: 'No network in Admin-01.' },
      ],
      'no-eval': 'error',
      'no-new-func': 'error',
    },
  },
  {
    // Tests may ASSERT the absence of storage; the rules protect application code.
    files: ['src/**/*.test.{ts,tsx}', 'src/test/**'],
    rules: { 'no-restricted-globals': 'off' },
  },
  {
    files: ['scripts/**/*.mjs', '*.config.{js,ts}'],
    languageOptions: { globals: globals.node },
  },
);
