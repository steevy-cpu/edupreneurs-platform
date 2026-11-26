import type { ReactNode } from 'react';
import { fmtDay, fmtNumber } from '../i18n/format';

/**
 * Small, dependency-free SVG charts. Chosen over a charting library on purpose (Admin-00: "fewer
 * dependencies for a staff tool handling minors' data"): ~150 lines, no third-party runtime, strict CSP
 * friendly (no inline styles). Each chart is an image with a text alternative and a real data table.
 */

export interface Point { label: string; value: number }

const W = 640;
const H = 220;
const PAD = { l: 44, r: 12, t: 14, b: 28 };

function scale(points: readonly Point[]) {
  const max = Math.max(1, ...points.map((p) => p.value));
  const nice = Math.pow(10, Math.floor(Math.log10(max)));
  const top = Math.ceil(max / nice) * nice;
  return { top, y: (v: number) => PAD.t + (H - PAD.t - PAD.b) * (1 - v / top) };
}

function Frame({ title, summary, children, table }: { title: string; summary: string; children: ReactNode; table: ReactNode }) {
  return (
    <figure className="stack">
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. ${summary}`}>{children}</svg>
      <details className="chart-data">
        <summary>Voir les données ({title})</summary>
        {table}
      </details>
    </figure>
  );
}

function Grid({ top, y }: { top: number; y: (v: number) => number }) {
  return (
    <>
      {[0, 0.25, 0.5, 0.75, 1].map((f) => (
        <g key={f}>
          <line className="grid-line" x1={PAD.l} x2={W - PAD.r} y1={y(top * f)} y2={y(top * f)} />
          <text className="axis-text" x={PAD.l - 6} y={y(top * f) + 4} textAnchor="end">{fmtNumber(Math.round(top * f))}</text>
        </g>
      ))}
    </>
  );
}

function DataTable({ points, unit }: { points: readonly Point[]; unit: string }) {
  return (
    <table className="data">
      <thead><tr><th scope="col">Période</th><th scope="col" className="num">{unit}</th></tr></thead>
      <tbody>{points.map((p) => <tr key={p.label}><th scope="row">{p.label}</th><td className="num">{fmtNumber(p.value)}</td></tr>)}</tbody>
    </table>
  );
}

export function LineChart({ title, points, unit }: { title: string; points: readonly Point[]; unit: string }) {
  const { top, y } = scale(points);
  const x = (i: number) => PAD.l + ((W - PAD.l - PAD.r) * i) / Math.max(1, points.length - 1);
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
  const first = points[0];
  const last = points[points.length - 1];
  const step = Math.ceil(points.length / 6);
  return (
    <Frame title={title} summary={first && last ? `De ${fmtNumber(first.value)} (${first.label}) à ${fmtNumber(last.value)} (${last.label}).` : 'Aucune donnée.'} table={<DataTable points={points} unit={unit} />}>
      <Grid top={top} y={y} />
      <path className="area" d={`${d} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`} />
      <path className="line" d={d} />
      {points.map((p, i) => <circle key={p.label} className="dot" cx={x(i)} cy={y(p.value)} r={3.5}><title>{`${p.label} : ${fmtNumber(p.value)}`}</title></circle>)}
      {points.map((p, i) => (i % step === 0 ? <text key={p.label} className="axis-text" x={x(i)} y={H - 8} textAnchor="middle">{p.label}</text> : null))}
    </Frame>
  );
}

export function BarChart({ title, points, unit, tone = 'teal' }: { title: string; points: readonly Point[]; unit: string; tone?: 'teal' | 'alt' | 'warn' }) {
  const { top, y } = scale(points);
  const slot = (W - PAD.l - PAD.r) / Math.max(1, points.length);
  const bw = Math.max(6, slot * 0.64);
  const step = Math.ceil(points.length / 7);
  const total = points.reduce((a, p) => a + p.value, 0);
  return (
    <Frame title={title} summary={`${points.length} valeurs, total ${fmtNumber(total)}.`} table={<DataTable points={points} unit={unit} />}>
      <Grid top={top} y={y} />
      {points.map((p, i) => {
        const cx = PAD.l + slot * i + slot / 2;
        return (
          <g key={p.label}>
            <rect className={`bar ${tone === 'teal' ? '' : tone}`} x={cx - bw / 2} y={y(p.value)} width={bw} height={Math.max(0, y(0) - y(p.value))} rx={2}><title>{`${p.label} : ${fmtNumber(p.value)}`}</title></rect>
            {i % step === 0 && <text className="axis-text" x={cx} y={H - 8} textAnchor="middle">{p.label}</text>}
          </g>
        );
      })}
    </Frame>
  );
}

export const dayPoints = (rows: readonly { date: string; count: number }[]): Point[] => rows.map((r) => ({ label: fmtDay(r.date), value: r.count }));

/** Proportional segments with a text legend (counts are always readable, not only colours). */
export function SegmentBar({ segments, label }: { segments: readonly { key: string; label: string; value: number }[]; label: string }) {
  const total = Math.max(1, segments.reduce((a, s) => a + s.value, 0));
  const W2 = 600;
  const shown = segments.filter((s) => s.value > 0);
  const rects = shown.map((s, i) => ({ s, x: (shown.slice(0, i).reduce((a, t) => a + t.value, 0) / total) * W2, w: (s.value / total) * W2 }));
  return (
    <div>
      <svg className="chart" viewBox={`0 0 ${W2} 18`} role="img" aria-label={`${label} : ${segments.map((s) => `${s.label} ${s.value}`).join(', ')}.`}>
        {rects.map(({ s, x, w }) => <rect key={s.key} className={`s-${s.key}`} x={x} y={0} width={w} height={18}><title>{`${s.label} : ${s.value}`}</title></rect>)}
      </svg>
      <ul className="legend">
        {segments.map((s) => <li key={s.key}><span className={`swatch s-${s.key}`} aria-hidden="true" />{s.label} : <strong>{s.value}</strong></li>)}
      </ul>
    </div>
  );
}
