import type { DashboardData, DayCount, HeatCell } from '../domain/dashboard';
import { K_FLOOR } from '../domain/metrics';

/** The demo's "now": Haiti time (UTC−5, no DST in November). Fixed so screenshots and tests are deterministic. */
export const FIXTURE_NOW = '2026-11-26T09:00:00-05:00';

const DAY = 86_400_000;
const nowMs = new Date(FIXTURE_NOW).getTime();

/** Haiti local calendar date `back` days before the fixture "now". */
function haitiDate(back: number): string {
  const d = new Date(nowMs - back * DAY - 5 * 3_600_000);
  return d.toISOString().slice(0, 10);
}

/** Small deterministic pseudo-random in [0,1) — no Math.random, so the fixtures never change. */
function rnd(seed: number): number {
  const x = Math.sin(seed * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

const series = (n: number, base: number, amp: number, seed: number): DayCount[] =>
  Array.from({ length: n }, (_, i) => {
    const date = haitiDate(n - 1 - i);
    const weekend = [0, 6].includes(new Date(`${date}T12:00:00Z`).getUTCDay());
    const v = Math.round((base + amp * rnd(seed + i)) * (weekend ? 0.72 : 1));
    return { date, count: v };
  });

const GRADES = ['7AF', '8AF', '9AF', 'NS1', 'NS2', 'NS3', 'NS4'];
const SUBJECTS = ['Mathématiques', 'Français', 'Sciences expérimentales', 'Sciences sociales', 'Anglais', 'Créole'];

function heat(): HeatCell[] {
  const cells: HeatCell[] = [];
  GRADES.forEach((g, gi) => {
    SUBJECTS.forEach((s, si) => {
      const learners = Math.round(8 + rnd(gi * 31 + si * 7 + 3) * 420 * (si === 0 ? 1.4 : 1) * (gi > 4 ? 0.5 : 1));
      // Server-side K-suppression, imitated: a group smaller than K is never sent to the browser.
      const hidden = learners < K_FLOOR + 12 && rnd(gi * 17 + si) > 0.45;
      cells.push(hidden ? { grade: g, subject: s, learners: null, answers: null } : { grade: g, subject: s, learners, answers: learners * Math.round(9 + rnd(si + gi) * 9) });
    });
  });
  return cells;
}

const iso = (hoursBefore: number) => new Date(nowMs - hoursBefore * 3_600_000).toISOString();

export function buildDashboardFixture(): DashboardData {
  const syncDays = series(7, 4200, 900, 40).map((d, i) => {
    const total = d.count;
    const rejected = Math.round(total * (0.002 + 0.004 * rnd(60 + i)));
    const duplicate = Math.round(total * 0.03);
    const conflict = Math.round(total * 0.0015);
    return { date: d.date, accepted: total - rejected - duplicate - conflict, duplicate, rejected, conflict };
  });
  const coverageDays = Array.from({ length: 14 }, (_, i) => ({ date: haitiDate(-i), covered: i < 9 || i === 11 }));

  return {
    now: FIXTURE_NOW,
    asOf: {
      M1: iso(5), M2: iso(5), M3: iso(5), M5: iso(5), M6: iso(5), M7: iso(5), M8: iso(5), M9: iso(5),
      // Deliberately stale (> 2× the 1 h schedule) so the amber state is visible and tested.
      M12: iso(3.5),
      M15: iso(5), M16: iso(5), M17: iso(5), M18: iso(0.4),
    },
    m1: { total: 12480, delta7d: 312 },
    m2: Array.from({ length: 12 }, (_, i) => ({
      weekStart: haitiDate((11 - i) * 7 + 3),
      count: Math.round(180 + i * 9 + rnd(i + 5) * 70),
    })),
    m3: { daily: 1905, monthly: 6220, dailySeries: series(14, 1500, 520, 11) },
    m5: (() => {
      const byDay = series(7, 1180, 420, 21);
      return { byDay, total7d: byDay.reduce((a, d) => a + d.count, 0) };
    })(),
    m6: series(14, 15500, 5200, 31),
    m7: { percent: 71, sample: 184_250 },
    m8: { grades: GRADES, subjects: SUBJECTS, k: K_FLOOR, cells: heat() },
    m9: { gold7d: 48_200, achievements7d: 1_136 },
    m12: {
      days: syncDays,
      rejectionCodes: [
        { code: 'question_unknown', count: 61 },
        { code: 'stale_revision', count: 38 },
        { code: 'invalid_payload', count: 12 },
      ],
    },
    m15: coverageDays,
    m16: { medianDaysToPublish: 6.5 },
    m17: { delivered: 0, failed: 0 },
    m18: [
      { id: 'api', label: 'API', state: 'ok', note: 'Réponse /health à l’instant (fixture).' },
      { id: 'db', label: 'Base de données', state: 'ok', note: 'Joignable (fixture).' },
      { id: 'worker', label: 'Worker d’agrégation', state: 'unknown', note: 'Aucun déploiement de worker n’existe encore.' },
      { id: 'x1', label: 'Contrôles de disponibilité X-1', state: 'unknown', note: 'Script X-1 non construit : TEMP et extensions non vérifiés.' },
    ],
  };
}
