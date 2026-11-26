import { describe, expect, it } from 'vitest';
import { repoFile } from '../test/repo';
import { buildDashboardFixture, FIXTURE_NOW } from '../data/dashboardFixtures';
import { isStale, K_FLOOR, METRIC_BY_ID, METRICS, type MetricId } from './metrics';

const doc = (name: string) => repoFile(`docs/architecture/admin-00/${name}`);

describe('metric catalog (Admin-00 doc 3 is the source of truth)', () => {
  it('has exactly the 21 metrics M1…M21, once each', () => {
    expect(METRICS.map((m) => m.id)).toEqual(Array.from({ length: 21 }, (_, i) => `M${i + 1}`));
  });

  it('matches the tier and availability column of the specification table', () => {
    const rows = doc('03-metric-catalog.md').split('\n').filter((l) => /^\| M\d+ /.test(l));
    expect(rows).toHaveLength(21);
    for (const row of rows) {
      const cells = row.split('|').map((c) => c.trim());
      const id = cells[1] as MetricId;
      const def = METRIC_BY_ID[id];
      const tier = cells[cells.length - 3]!; // … | Tier | Avail. |
      const avail = cells[cells.length - 2]!;
      if (tier.startsWith('T')) expect(tier, `${id} tier`).toContain(def.tier);
      const glyph = avail.startsWith('✅') ? 'existing' : avail.startsWith('🔧') ? 'queries' : 'new-event';
      expect(def.readiness, `${id} availability`).toBe(glyph);
    }
  });

  it('gives every metric a definition, a source, a calculation and a period', () => {
    for (const m of METRICS) {
      expect(m.label.length).toBeGreaterThan(3);
      expect(m.definition.length, m.id).toBeGreaterThan(3);
      expect(m.source.length, m.id).toBeGreaterThan(3);
      expect(m.calculation.length, m.id).toBeGreaterThan(0);
      expect(m.period.length, m.id).toBeGreaterThan(0);
    }
  });

  it('declares exactly the source-less metrics as unavailable, each with a reason', () => {
    const unavailable = METRICS.filter((m) => m.refreshHours === null).map((m) => m.id);
    expect(unavailable).toEqual(['M4', 'M10', 'M11', 'M13', 'M14', 'M19', 'M20', 'M21']);
    for (const id of unavailable) expect(METRIC_BY_ID[id].unavailableReason, id).toBeTruthy();
  });

  it('never invents app opens, download counts, AI spend or revenue', () => {
    const f = buildDashboardFixture() as unknown as Record<string, unknown>;
    for (const key of ['m4', 'm10', 'm11', 'm13', 'm14', 'm19', 'm20', 'm21']) expect(f[key], key).toBeUndefined();
    expect(Object.keys(f.asOf as object)).not.toEqual(expect.arrayContaining(['M4', 'M10', 'M11', 'M13', 'M14', 'M19', 'M20', 'M21']));
  });

  it('keeps M21 (fraud signals) admin-only and individual-level', () => {
    expect(METRIC_BY_ID.M21.adminOnly).toBe(true);
    expect(METRIC_BY_ID.M21.tier).toBe('T2');
  });
});

describe('freshness and privacy fixtures', () => {
  const now = new Date(FIXTURE_NOW);
  it('turns amber after twice the refresh interval, not before', () => {
    expect(isStale(new Date(now.getTime() - 1.9 * 3_600_000), 1, now)).toBe(false);
    expect(isStale(new Date(now.getTime() - 2.1 * 3_600_000), 1, now)).toBe(true);
    expect(isStale(new Date(0), null, now)).toBe(false);
  });
  it('is deterministic and ships a deliberately stale M12 so the state is visible', () => {
    expect(JSON.stringify(buildDashboardFixture())).toBe(JSON.stringify(buildDashboardFixture()));
    const d = buildDashboardFixture();
    expect(isStale(new Date(d.asOf.M12!), 1, now)).toBe(true);
    expect(isStale(new Date(d.asOf.M1!), 24, now)).toBe(false);
  });
  it('suppresses groups below K before they reach the browser', () => {
    const d = buildDashboardFixture();
    expect(d.m8.k).toBe(K_FLOOR);
    expect(d.m8.cells.some((c) => c.learners === null)).toBe(true);
    for (const c of d.m8.cells) if (c.learners !== null) expect(c.learners).toBeGreaterThanOrEqual(K_FLOOR);
  });
  it('contains no individual learner record', () => {
    const json = JSON.stringify(buildDashboardFixture());
    for (const word of ['email', 'learner_id', 'user_id', 'first_name', 'last_name', 'phone']) expect(json).not.toContain(word);
  });
});
