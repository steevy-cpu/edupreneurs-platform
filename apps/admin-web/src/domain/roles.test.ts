import { describe, expect, it } from 'vitest';
import { repoFile } from '../test/repo';
import { CAPABILITIES, PERSONAS, ROLES, ROLE_INFO, SECTION_ACCESS, SEPARATION_RULES, can, levelFor, sectionLevel, type Level, type Role } from './roles';

const doc2 = repoFile('docs/architecture/admin-00/02-roles-and-permissions.md');

describe('role matrix (Admin-00 doc 2)', () => {
  it('reproduces every cell of the specification table', () => {
    const rows = doc2.split('\n').filter((l) => /^\| .*\|/.test(l)).filter((l) => /(✔|◐|—)/.test(l) && !l.includes('---'));
    // Keep only the capability matrix rows (7 cells), not the roles table or others.
    const matrix = rows.map((r) => r.split('|').slice(1, -1).map((c) => c.trim())).filter((c) => c.length === 7);
    expect(matrix).toHaveLength(CAPABILITIES.length);
    const order: Role[] = ['editor', 'reviewer', 'publisher', 'analyst', 'support', 'admin'];
    matrix.forEach((cells, i) => {
      order.forEach((role, j) => {
        const sym = cells[j + 1]!;
        const expected: Level = sym.startsWith('✔') ? 'yes' : sym.startsWith('◐') || sym.startsWith('own') ? 'limited' : 'no';
        expect(CAPABILITIES[i]!.cells[role], `${CAPABILITIES[i]!.id} / ${role}`).toBe(expected);
      });
    });
  });

  it('marks analyst and support as proposed and the other four as existing', () => {
    expect(ROLES.filter((r) => ROLE_INFO[r].state === 'proposed')).toEqual(['analyst', 'support']);
    expect(ROLES.filter((r) => ROLE_INFO[r].state === 'exists')).toEqual(['editor', 'reviewer', 'publisher', 'admin']);
  });

  it('keeps the admin out of draft authoring and review (no back door to unreviewed content)', () => {
    for (const c of ['draft.own', 'sources.manage', 'revision.submit', 'revision.review']) expect(can(['admin'], c)).toBe(false);
  });

  it('computes effective permission as the union of roles', () => {
    expect(levelFor(['editor', 'publisher'], 'pack.release')).toBe('yes');
    expect(levelFor(['editor', 'publisher'], 'draft.own')).toBe('yes');
    expect(levelFor(['reviewer'], 'analytics.read')).toBe('limited');
    expect(levelFor(['analyst'], 'learner.lookup')).toBe('no');
  });

  it('shows analytics to the analyst only as a full section, and nothing at all to support', () => {
    expect(sectionLevel(['analyst'], 'dashboard')).toBe('full');
    expect(sectionLevel(['support'], 'dashboard')).toBe('none');
    expect(sectionLevel(['editor'], 'dashboard')).toBe('limited');
  });

  it('defaults sections the spec is silent about to admin only (deny by default)', () => {
    for (const s of ['exams', 'moderation', 'jude', 'gold', 'leaderboard'] as const) expect(Object.keys(SECTION_ACCESS[s].access)).toEqual(['admin']);
  });

  it('lists the separation-of-duties rules with their true status', () => {
    expect(SEPARATION_RULES).toHaveLength(6);
    expect(SEPARATION_RULES.find((r) => r.id === 'sod-1')!.status).toBe('exists');
    expect(SEPARATION_RULES.find((r) => r.id === 'sod-3')!.status).toBe('to-add');
    expect(SEPARATION_RULES.find((r) => r.id === 'sod-4')!.status).toBe('open');
  });

  it('uses only clearly synthetic personas', () => {
    for (const p of PERSONAS) expect(p.name).toContain('synthétique');
    expect(PERSONAS.some((p) => p.roles.length > 1)).toBe(true);
  });
});
