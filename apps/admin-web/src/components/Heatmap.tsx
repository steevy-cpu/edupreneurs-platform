import type { HeatCell } from '../domain/dashboard';
import { fmtNumber } from '../i18n/format';
import { TableWrap } from './ui';

/** Grade × subject table. Cells of groups smaller than K arrive as `null` (suppressed server-side) and are shown as « < K ». */
export function Heatmap({ grades, subjects, cells, k }: { grades: string[]; subjects: string[]; cells: HeatCell[]; k: number }) {
  const max = Math.max(1, ...cells.map((c) => c.learners ?? 0));
  const bucket = (v: number) => Math.min(4, Math.floor((v / max) * 5));
  const at = (g: string, s: string) => cells.find((c) => c.grade === g && c.subject === s);
  return (
    <TableWrap label="Engagement par classe et matière">
      <table className="data heat">
        <caption>Apprenants actifs distincts (28 jours), par classe et matière</caption>
        <thead>
          <tr><th scope="col">Classe</th>{subjects.map((s) => <th scope="col" key={s}>{s}</th>)}</tr>
        </thead>
        <tbody>
          {grades.map((g) => (
            <tr key={g}>
              <th scope="row">{g}</th>
              {subjects.map((s) => {
                const c = at(g, s);
                if (!c || c.learners === null) return <td key={s} className="suppressed">Masqué <small>groupe &lt; {k}</small></td>;
                return <td key={s} className={`h${bucket(c.learners)}`}>{fmtNumber(c.learners)}<small>{fmtNumber(c.answers ?? 0)} réponses</small></td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}
