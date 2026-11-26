// Scans the PRODUCTION BUILD: no secret, no private endpoint, no unexpected URL, strict CSP present, no source maps.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { checkCsp, scanSecrets, scanUrls } from './lib/scan.mjs';

const dist = new URL('../dist', import.meta.url).pathname;
if (!existsSync(dist)) { console.error('check:dist FAILED: dist/ missing, run the build first'); process.exit(1); }

const files = [];
(function walk(dir) {
  for (const n of readdirSync(dir)) {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) walk(p); else files.push(p);
  }
})(dist);

const problems = [];
for (const f of files) {
  const rel = relative(dist, f);
  if (rel.endsWith('.map')) problems.push(`source map shipped: ${rel}`);
  if (!/\.(js|css|html|svg|json|txt)$/.test(rel)) continue;
  const text = readFileSync(f, 'utf8');
  for (const x of [...scanSecrets(text, rel), ...scanUrls(text, rel)]) problems.push(`${x.file}: ${x.rule} -> ${x.sample}`);
  if (rel === 'index.html') for (const p of checkCsp(text)) problems.push(`index.html: ${p}`);
}
if (problems.length) { console.error('check:dist FAILED'); problems.forEach((p) => console.error('  ' + p)); process.exit(1); }
console.log(`check:dist OK (${files.length} files: no secret, no private endpoint, no unexpected URL, strict CSP with connect-src 'none', no source maps)`);
