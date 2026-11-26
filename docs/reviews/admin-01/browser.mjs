// Run from apps/admin-web against vite preview of a verified production build.
import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const out = path.resolve(process.env.ADMIN_EVIDENCE || 'browser-evidence');
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome' });
const base = 'http://127.0.0.1:4174';
const page = await browser.newPage();
const results = [], failures = [], traffic = new Set(), runtimeErrors = [];
page.on('pageerror', e => runtimeErrors.push(e.message));
page.on('request', req => traffic.add(req.url().split('#')[0]));
const axe = await readFile('node_modules/axe-core/axe.min.js', 'utf8');
function check(name, ok) { results.push({ name, ok }); if (!ok) failures.push(name); }
async function visit(route, persona) {
  await page.goto('about:blank');
  await page.goto(base + '/?persona=' + persona + '#' + route);
  await page.locator('main h1').first().waitFor();
}
try {
  for (const [width, height] of [[1440, 900], [820, 1100], [320, 740]]) {
    await page.setViewportSize({ width, height });
    for (const [name, route, persona, anchor] of [
      ['dashboard', '/', 'p-gaelle', '[data-metric="M1"]'],
      ['editor', '/contenu/revision/rev-l-ax-b-1', 'p-anne', '.block-edit'],
      ['queue', '/contenu/relecture', 'p-chloe', '#q-h'],
      ['roles', '/roles', 'p-gaelle', '#r-matrix'],
    ]) {
      await visit(route, persona);
      const target = page.locator(anchor).first();
      await target.waitFor();
      check(name + '-' + width + ' page width', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      check(name + '-' + width + ' primary heading', await page.locator('h1').count() === 1);
      await target.scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(out, name + '-' + width + '.jpg'), type: 'jpeg', quality: 70 });
      await page.evaluate(axe);
      const issues = await page.evaluate(async () => (await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa'] } })).violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.map(n => n.target).slice(0,6) })));
      results.push({ name, width, issues });
      check(name + '-' + width + ' browser axe', issues.length === 0);
    }
  }
  await visit('/roles', 'p-gaelle');
  const skip = page.getByRole('link', { name: 'Aller au contenu' });
  await skip.focus(); await page.keyboard.press('Enter');
  check('skip retains hash route and focuses main', await page.evaluate(() => location.hash === '#/roles' && document.activeElement === document.querySelector('main')));
  await visit('/roles', 'p-gaelle');
  await page.keyboard.press('Tab'); await page.keyboard.press('Tab');
  check('closed drawer is skipped by Tab', await page.locator('#sidebar :focus').count() === 0);
  const toggle = page.getByRole('button', { name: 'Menu', exact: true });
  await toggle.focus(); await page.keyboard.press('Enter');
  check('opening drawer focuses its navigation', await page.locator('#sidebar a:focus').count() === 1);
  await page.keyboard.press('Escape');
  check('Escape returns focus to menu control', await page.locator('.menu-toggle').evaluate(el => el === document.activeElement && el.getAttribute('aria-expanded') === 'false').catch(() => false));
  await visit('/contenu/revision/rev-l-ax-b-1', 'p-anne');
  const marker = '<strong>Exemple de texte</strong>';
  await page.getByRole('textbox', { name: 'Texte du bloc 1', exact: true }).fill(marker);
  check('editor displays markup literally', await page.locator('.phone-screen').innerText().then(t => t.includes(marker)) && await page.locator('.phone-screen strong').filter({hasText:'Exemple de texte'}).count() === 0);
  await page.getByRole('button', { name: 'Enregistrer le brouillon (synthétique)' }).click();
  await page.reload();
  check('reloading discards edit', await page.locator('.phone-screen').innerText().then(t => !t.includes(marker)));
  await visit('/contenu/revision/rev-l-comparer-2', 'p-chloe');
  const approve = page.getByRole('button', { name: 'Approuver', exact: true });
  await approve.click();
  const dialog = page.getByRole('dialog');
  await page.keyboard.press('Shift+Tab');
  check('reverse Tab stays in confirmation', await dialog.locator(':focus').count() === 1);
  await page.keyboard.press('Escape');
  check('Escape restores opener', await approve.evaluate(el => el === document.activeElement));
  await approve.click();
  await dialog.getByRole('button', {name:'Approuver', exact:true}).click();
  check('receipt retains keyboard focus', await dialog.locator(':focus').count() === 1);
  await dialog.getByRole('button', {name:'Fermer'}).click();
  check('completed action leaves useful focus', await page.evaluate(() => document.activeElement !== document.body));
  check('no unexpected application requests', [...traffic].every(url => {
    if (url === 'about:blank') return true;
    const u = new URL(url);
    return u.origin === base && (['/', '/favicon.svg'].includes(u.pathname) || /^\/assets\/[^/]+\.(js|css)$/.test(u.pathname));
  }));
  const blocked = await page.evaluate(async () => {
    const violation = new Promise(resolve => document.addEventListener('securitypolicyviolation', e => resolve(e.effectiveDirective), {once:true}));
    try { await fetch('/qa-connectivity-probe'); return false; } catch { return await Promise.race([violation, new Promise(r => setTimeout(() => r('timeout'), 2000))]) === 'connect-src'; }
  });
  check('production CSP blocks same-origin fetch', blocked);
  check('no uncaught application exceptions', runtimeErrors.length === 0);
} finally {
  await writeFile(path.join(out, 'results.json'), JSON.stringify({ browser: browser.version(), results, failures, runtimeErrors }, null, 2));
  console.log(JSON.stringify({ results, failures, runtimeErrors }));
  await browser.close();
}
if (failures.length) process.exitCode = 1;
