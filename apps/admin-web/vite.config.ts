import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

/**
 * Strict Content-Security-Policy, added to the BUILT html only (the dev server needs inline HMR code).
 * `connect-src 'none'` makes the "no network" property enforceable by the browser: this prototype
 * cannot call any API, even by mistake. A real deployment must also send the same policy as an HTTP
 * header, together with `frame-ancestors 'none'` and `Referrer-Policy: no-referrer` (meta cannot carry them).
 */
const CSP = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join('; ');

function cspForBuild(): Plugin {
  return {
    name: 'admin-csp',
    apply: 'build',
    transformIndexHtml: () => [
      { tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP }, injectTo: 'head-prepend' },
      { tag: 'meta', attrs: { name: 'referrer', content: 'no-referrer' }, injectTo: 'head-prepend' },
    ],
  };
}

export default defineConfig({
  plugins: [react(), cspForBuild()],
  base: './', // relative asset paths: the build works from any static path (module scripts do not load from file://)
  server: { host: '127.0.0.1', port: 5174, strictPort: true },
  preview: { host: '127.0.0.1', port: 4174, strictPort: true },
  build: { sourcemap: false, target: 'es2022', cssCodeSplit: false },
});
