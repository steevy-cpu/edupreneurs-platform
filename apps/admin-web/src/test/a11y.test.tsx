import axe from 'axe-core';
import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { contrast, TEXT_PAIRS } from '../styles/tokens';
import { renderApp } from './render';

async function violations() {
  // jsdom has no layout engine: colour contrast cannot be computed here, so it is covered by the token test below
  // and by real-browser screenshots. Everything else axe checks runs.
  const r = await axe.run(document.body, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
  return r.violations.map((v) => `${v.id}: ${v.nodes.slice(0, 2).map((n) => n.target.join(' ')).join(' | ')}`);
}

describe('accessibility (axe-core on rendered pages)', () => {
  const pages: [string, string, string][] = [
    ['dashboard', '/', 'Tableau de bord'],
    ['metric catalog', '/indicateurs', 'Catalogue des 21 indicateurs'],
    ['content catalogue', '/contenu', 'Contenu éducatif'],
    ['revision editor', '/contenu/revision/rev-l-ax-b-1', 'Résoudre ax + b = c · v1'],
    ['review queue', '/contenu/relecture', 'File de relecture'],
    ['publication', '/contenu/publication', 'Publication'],
    ['roles matrix', '/roles', 'Rôles et permissions'],
    ['placeholder', '/jude-ia', 'Jude IA'],
  ];
  it.each(pages)('%s has no axe violations', async (_n, path, heading) => {
    renderApp(path, path.startsWith('/contenu/revision') ? 'p-anne' : 'p-gaelle');
    await screen.findByRole('heading', { level: 1, name: heading });
    expect(await violations()).toEqual([]);
  });

  it('has an open dialog free of axe violations', async () => {
    renderApp('/contenu/revision/rev-l-comparer-2', 'p-chloe');
    await screen.findByRole('heading', { level: 1, name: 'Comparer des fractions · v2' });
    screen.getByRole('button', { name: 'Approuver' }).click();
    await screen.findByRole('dialog');
    expect(await violations()).toEqual([]);
  });

  it('exposes one h1 per page, labelled landmarks and a labelled data table for each chart', async () => {
    renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Tableau de bord' });
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Navigation principale' })).toBeInTheDocument();
    expect(document.querySelectorAll('svg.chart[role="img"][aria-label]').length).toBeGreaterThanOrEqual(5);
    expect(document.querySelectorAll('details.chart-data table').length).toBeGreaterThanOrEqual(5);
  });
});

describe('colour contrast of the design tokens (WCAG AA, computed)', () => {
  it.each(TEXT_PAIRS.map((p) => [p.name, p.fg, p.bg, p.min] as const))('%s', (_n, fg, bg, min) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(min);
  });
});
