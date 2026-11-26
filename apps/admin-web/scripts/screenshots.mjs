// Captures REAL browser screenshots of the production build (vite preview) with headless Chrome driven over the
// DevTools protocol using only Node built-ins (no extra dependency). Output: ../../docs/admin-01/screenshots/.
// Usage: npm run build && npm run screenshots   (CHROME_PATH overrides the browser location)
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

const CHROME = process.env.CHROME_PATH ?? ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/chromium'].find(existsSync);
if (!CHROME) { console.error('No Chrome/Chromium found; set CHROME_PATH.'); process.exit(1); }
const OUT = new URL('../../../docs/admin-01/screenshots/', import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });
const BASE = 'http://127.0.0.1:4174/';

const procs = [];
const cleanup = () => procs.forEach((p) => { try { p.kill(); } catch { /* already gone */ } });
process.on('exit', cleanup);

async function waitHttp(url, tries = 60) {
  for (let i = 0; i < tries; i++) { try { if ((await fetch(url)).ok) return; } catch { /* not yet */ } await sleep(250); }
  throw new Error(`timeout waiting for ${url}`);
}

const preview = spawn('npx', ['vite', 'preview'], { cwd: new URL('..', import.meta.url).pathname, stdio: 'ignore' });
procs.push(preview);
await waitHttp(BASE);

const profile = mkdtempSync(join(tmpdir(), 'admin01-chrome-'));
const chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-port=9333', `--user-data-dir=${profile}`, '--hide-scrollbars', '--no-first-run', '--disable-gpu', 'about:blank'], { stdio: 'ignore' });
procs.push(chrome);
await waitHttp('http://127.0.0.1:9333/json/version');
const targets = await (await fetch('http://127.0.0.1:9333/json')).json();
const ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r));
let id = 0; const pending = new Map();
ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } });
const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, (d) => (d.error ? rej(new Error(JSON.stringify(d.error))) : res(d.result))); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = (expression) => send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });

await send('Page.enable');

async function shot(name, { path, persona = 'p-gaelle', width = 1440, height = 900, full = true, steps = [] }) {
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 600 });
  await send('Page.navigate', { url: `${BASE}?persona=${persona}#${path}` });
  await sleep(1200);
  await evaluate('location.reload()');
  await sleep(1200);
  for (const s of steps) { await evaluate(s); await sleep(500); }
  let clip;
  if (full) {
    const m = await send('Page.getLayoutMetrics');
    clip = { x: 0, y: 0, width, height: Math.min(Math.ceil(m.cssContentSize.height), 6000), scale: 1 };
  }
  const r = await send('Page.captureScreenshot', { format: 'png', ...(clip ? { clip, captureBeyondViewport: true } : {}) });
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(r.data, 'base64'));
  const overflow = await evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth');
  console.log(`${name}.png ${width}px  horizontal overflow: ${overflow.result.value}px`);
}

const clickText = (text) => `[...document.querySelectorAll('button,a')].find((b) => b.textContent.trim() === ${JSON.stringify(text)})?.click()`;

await shot('01-dashboard-desktop', { path: '/' });
await shot('02-dashboard-tablet', { path: '/', width: 820, height: 1100 });
await shot('03-dashboard-narrow', { path: '/', width: 390, height: 844 });
await shot('04-content-catalogue', { path: '/contenu', persona: 'p-anne' });
await shot('05-revision-editor-validation', { path: '/contenu/revision/rev-l-ax-b-1', persona: 'p-anne' });
await shot('06-review-with-diff', { path: '/contenu/revision/rev-l-comparer-2', persona: 'p-chloe' });
await shot('07-publish-confirmation', { path: '/contenu/revision/rev-l-additionner-1', persona: 'p-david', full: false, steps: [clickText('Publier')] });
await shot('08-author-cannot-publish', { path: '/contenu/revision/rev-l-equivalentes-1', persona: 'p-helene' });
await shot('09-roles-matrix', { path: '/roles', persona: 'p-gaelle' });
await shot('10-support-access-refused', { path: '/contenu', persona: 'p-farid', height: 700, full: false });
await shot('11-placeholder-jude', { path: '/jude-ia' });
await shot('12-editor-narrow', { path: '/contenu/revision/rev-l-ax-b-1', persona: 'p-anne', width: 390, height: 844 });
await shot('13-narrow-menu-open', { path: '/roles', persona: 'p-eva', width: 390, height: 844, full: false, steps: [clickText('Menu')] });
await shot('15-roles-narrow', { path: '/roles', persona: 'p-eva', width: 390, height: 844 });
await shot('14-analyst-dashboard', { path: '/', persona: 'p-eva' });

ws.close();
cleanup();
process.exit(0);
