// Pure scanners used by check-source.mjs, check-dist.mjs and the unit tests.
// They enforce Admin-00 doc 5: no secret, no private endpoint, no raw HTML, no network in this prototype.

/** Text that must never appear in a browser bundle. Each entry: [rule id, pattern]. */
export const SECRET_PATTERNS = [
  ['supabase-service-role', /service[_-]?role/i],
  ['supabase-host', /supabase\.(co|in)\b/i],
  ['jwt', /\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/],
  ['postgres-url', /postgres(ql)?:\/\//i],
  ['openrouter', /openrouter/i],
  ['openai-style-key', /\bsk-[A-Za-z0-9_-]{20,}/],
  ['private-key', /BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY/],
  ['payment-secret', /\b(sk|rk)_(live|test)_[A-Za-z0-9]{8,}/],
  ['aws-key', /\bAKIA[0-9A-Z]{16}\b/],
  ['local-api', /(localhost|127\.0\.0\.1|0\.0\.0\.0):(8000|8011|5432|54321|55\d{3})\b/],
  ['bearer-literal', /Bearer\s+[A-Za-z0-9._-]{20,}/],
];

/** URL hosts that legitimately appear inside the bundled React/router code as strings, never fetched. */
export const ALLOWED_URL_PREFIXES = [
  'http://www.w3.org/', // SVG / MathML / XML namespaces
  'https://www.w3.org/',
  'https://react.dev/', // React error decoder links in messages
  'https://reactrouter.com/', // router documentation links in warnings
  'https://reactjs.org/',
  'https://github.com/remix-run/', // router issue links in warnings
  'https://github.com/facebook/react',
];

/** Exact URL strings allowed: react-router uses a dummy base to parse relative paths; it is never requested. */
export const ALLOWED_URL_EXACT = ['http://localhost'];

/** @param {string} text @param {string} file */
export function scanSecrets(text, file) {
  const out = [];
  for (const [rule, re] of SECRET_PATTERNS) {
    const m = text.match(re);
    if (m) out.push({ file, rule, sample: '[redacted]' });
  }
  return out;
}

/** Absolute http(s) URLs that are not on the allow-list. */
export function scanUrls(text, file, allowed = ALLOWED_URL_PREFIXES) {
  const out = [];
  for (const m of text.matchAll(/https?:\/\/[^\s"'`)<>\\]+/g)) {
    if (!ALLOWED_URL_EXACT.includes(m[0]) && !allowed.some((p) => m[0].startsWith(p))) out.push({ file, rule: 'unexpected-url', sample: '[redacted URL]' });
  }
  return out;
}

/** Source-level rules: things the lint rules also forbid, double-checked textually so a lint-disable cannot hide them. */
export const SOURCE_FORBIDDEN = [
  ['raw-html', /dangerouslySetInnerHTML|\.innerHTML\b|\.outerHTML\b|insertAdjacentHTML|document\.write/],
  ['network', /\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon|navigator\.serviceWorker/],
  ['browser-storage', /\blocalStorage\b|\bsessionStorage\b|indexedDB|document\.cookie/],
  ['dynamic-code', /\beval\s*\(|new Function\s*\(/],
  ['env-read', /import\.meta\.env|process\.env/],
];

/** @param {string} text @param {string} file */
export function scanSource(text, file) {
  const out = [];
  for (const [rule, re] of SOURCE_FORBIDDEN) {
    const m = text.match(re);
    if (m) out.push({ file, rule, sample: m[0] });
  }
  return [...out, ...scanSecrets(text, file), ...scanUrls(text, file, [])];
}

/** @param {string} html */
export function checkCsp(html) {
  const problems = [];
  const decoded = html.replace(/&#39;/g, "'").replace(/&quot;/g, '"');
  const m = decoded.match(/http-equiv="Content-Security-Policy"\s+content="([^"]*)"/);
  if (!m) return ['Content-Security-Policy meta missing'];
  const csp = m[1];
  const expected = new Set(["default-src 'none'", "script-src 'self'", "style-src 'self'", "img-src 'self' data:", "font-src 'self'", "connect-src 'none'", "base-uri 'none'", "form-action 'none'"]);
  for (const directive of csp.split(';').map(s => s.trim().replace(/\s+/g, ' ')).filter(Boolean)) {
    if (!expected.delete(directive)) problems.push('Unexpected or repeated CSP directive');
  }
  for (const missing of expected) problems.push(`CSP lacks ${missing}`);
  if (/unsafe-inline|unsafe-eval|\*/.test(csp)) problems.push('CSP allows unsafe-inline/unsafe-eval/wildcard');
  if (/<script(?![^>]*\bsrc=)[^>]*>/i.test(decoded)) problems.push('inline <script> in built html');
  return problems;
}
