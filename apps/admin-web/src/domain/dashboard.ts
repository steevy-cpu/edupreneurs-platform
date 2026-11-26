import type { MetricId } from './metrics';

/** Shapes the dashboard consumes. A future FastAPI client (`GET /v1/staff/metrics/{metric_id}`) must return the same shapes. */

export interface DayCount { date: string; count: number }
export interface WeekCount { weekStart: string; count: number }
export interface SyncDay { date: string; accepted: number; duplicate: number; rejected: number; conflict: number }
export interface HeatCell { grade: string; subject: string; learners: number | null; answers: number | null }
export interface CoverageDay { date: string; covered: boolean }
export interface HealthCheck { id: string; label: string; state: 'ok' | 'unknown'; note: string }

export interface DashboardData {
  /** Fixed reference instant of the fixtures ("now" of the demo). Never the real clock. */
  now: string;
  /** Per-metric refresh instant, ISO. */
  asOf: Partial<Record<MetricId, string>>;
  m1: { total: number; delta7d: number };
  m2: WeekCount[];
  m3: { daily: number; monthly: number; dailySeries: DayCount[] };
  m5: { total7d: number; byDay: DayCount[] };
  m6: DayCount[];
  m7: { percent: number; sample: number };
  m8: { grades: string[]; subjects: string[]; k: number; cells: HeatCell[] };
  m9: { goldByDay: DayCount[]; achievements7d: number };
  m12: { days: SyncDay[]; rejectionCodes: { code: string; count: number }[] };
  m15: CoverageDay[];
  m16: { medianDaysToPublish: number };
  m17: { kind: string; delivered: number; failed: number }[];
  m18: HealthCheck[];
}
