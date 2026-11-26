// Fails when source code contains raw HTML, network calls, browser storage, dynamic code, env reads, secrets or URLs.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { scanSource } from './lib/scan.mjs';

const root = new URL('../src', import.meta.url).pathname;
const files = [];
(function walk(dir) {
  for (const n of readdirSync(dir)) {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) walk(p);
    else if (/\.(ts|tsx|css|html)$/.test(n) && !/\.test\.(ts|tsx)$/.test(n) && !p.includes('/test/')) files.push(p);
  }
})(root);

const findings = files.flatMap((f) => scanSource(readFileSync(f, 'utf8'), relative(root, f)));
if (findings.length) {
  console.error('check:src FAILED');
  for (const f of findings) console.error(`  ${f.file}: ${f.rule} -> ${f.sample}`);
  process.exit(1);
}
console.log(`check:src OK (${files.length} files scanned: no raw HTML, network, storage, eval, env reads, secrets or URLs)`);
