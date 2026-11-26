import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { checkCsp, scanSecrets, scanSource, scanUrls } from '../../scripts/lib/scan.mjs';
import { renderApp } from './render';

describe('scanners catch what they must', () => {
  it('flags secrets and private endpoints', () => {
    const cases = [
      'const k = "service_role"', 'https://abcdwxyz.supabase.co/rest/v1', 'postgres://user:pw@db:5432/x', 'OPENROUTER_API_KEY',
      'sk-' + 'a'.repeat(30), 'http://127.0.0.1:8000/v1', 'eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.abcdefgh12345678', '-----BEGIN PRIVATE KEY-----',
    ];
    for (const c of cases) expect(scanSecrets(c, 'x').length, c).toBeGreaterThan(0);
  });
  it('flags unexpected URLs but accepts the namespaces React ships', () => {
    expect(scanUrls('fetch("https://api.example.com/x")', 'x')).toHaveLength(1);
    expect(scanUrls('xmlns="http://www.w3.org/2000/svg" http://localhost', 'x')).toHaveLength(0);
  });
  it('flags raw HTML, network and storage in source', () => {
    for (const bad of ['<div dangerouslySetInnerHTML={{__html:x}} />', 'el.innerHTML = x', 'fetch("/a")', 'localStorage.setItem("t", t)', 'eval("1")', 'import.meta.env.VITE_URL']) {
      expect(scanSource(bad, 'x').length, bad).toBeGreaterThan(0);
    }
  });
  it('validates the CSP of a built page', () => {
    const good = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'">`;
    expect(checkCsp(good)).toEqual([]);
    expect(checkCsp('<html></html>')).toHaveLength(1);
    expect(checkCsp(good.replace("connect-src 'none'", "connect-src *"))).not.toEqual([]);
    expect(checkCsp(good + '<script>alert(1)</script>')).toContain('inline <script> in built html');
  });
});

describe('the real source tree', () => {
  const root = join(process.cwd(), 'src');
  const files: string[] = [];
  (function walk(d: string) {
    for (const n of readdirSync(d)) {
      const p = join(d, n);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.(ts|tsx|css)$/.test(n) && !/\.test\.tsx?$/.test(n) && !p.includes('/test/')) files.push(p);
    }
  })(root);

  it('has no raw HTML, network call, browser storage, dynamic code, env read, secret or URL', () => {
    const findings = files.flatMap((f) => scanSource(readFileSync(f, 'utf8'), f));
    expect(findings).toEqual([]);
    expect(files.length).toBeGreaterThan(30);
  });

  it('keeps package dependencies modest and free of data/network clients', () => {
    const pkg = JSON.parse(readFileSync(join(process.cwd(), 'package.json'), 'utf8')) as { dependencies: Record<string, string> };
    expect(Object.keys(pkg.dependencies).sort()).toEqual(['react', 'react-dom', 'react-router-dom']);
    for (const v of Object.values(pkg.dependencies)) expect(v).toMatch(/^\d/); // exact versions
  });
});

describe('runtime: the app works with the network unavailable', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('renders the dashboard and the editor without ever calling fetch or XHR', async () => {
    const fetchSpy = vi.fn(() => { throw new Error('network is forbidden'); });
    vi.stubGlobal('fetch', fetchSpy);
    vi.stubGlobal('XMLHttpRequest', fetchSpy);
    const { unmount } = renderApp('/');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    unmount();
    renderApp('/contenu/revision/rev-l-comparer-2', 'p-chloe');
    await screen.findByRole('heading', { name: 'Comparer des fractions · v2' });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('keeps no state in browser storage', async () => {
    const before = [localStorage.length, sessionStorage.length];
    renderApp('/contenu/revision/rev-l-comparer-2', 'p-chloe');
    await screen.findByRole('heading', { name: 'Comparer des fractions · v2' });
    expect([localStorage.length, sessionStorage.length]).toEqual(before);
    expect(document.cookie).toBe('');
  });
});
