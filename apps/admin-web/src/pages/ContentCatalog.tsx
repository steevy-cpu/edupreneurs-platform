import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { StatusBadge } from '../components/StatusBadge';
import { Badge, TableWrap } from '../components/ui';
import { canCreateRevision, headlineRevision, revisionsOfLesson, sourcesReady, type Lesson } from '../domain/editorial';
import { useRolePreview } from '../state/RolePreview';
import { useEditorial } from '../state/Services';

export function ContentCatalog() {
  const { state, store } = useEditorial();
  const { persona } = useRolePreview();
  const nav = useNavigate();
  const [grade, setGrade] = useState<string>('all');
  const [subject, setSubject] = useState<string>('all');
  const [lessonId, setLessonId] = useState<string | null>('l-comparer');

  const grades = useMemo(() => [...new Set(state.courses.map((c) => c.grade))], [state.courses]);
  const subjects = useMemo(() => [...new Set(state.courses.map((c) => c.subject))], [state.courses]);
  const courses = state.courses.filter((c) => (grade === 'all' || c.grade === grade) && (subject === 'all' || c.subject === subject));

  const selected: (Lesson & { course: string; unit: string }) | undefined = (() => {
    for (const c of state.courses) for (const u of c.units) for (const l of u.lessons) if (l.id === lessonId) return { ...l, course: c.title, unit: u.title };
    return undefined;
  })();
  const revs = selected ? revisionsOfLesson(state, selected.id) : [];
  const create = selected ? canCreateRevision(persona, state, selected.id) : { allowed: false };

  return (
    <div className="two-col">
      <section className="card" aria-labelledby="cat-title">
        <h2 id="cat-title">Classes et matières</h2>
        <div className="stack">
          <div>
            <p className="small muted" id="grade-label">Classe</p>
            <div className="chips" role="group" aria-labelledby="grade-label">
              {['all', ...grades].map((g) => <button key={g} type="button" className="chip" aria-pressed={grade === g} onClick={() => setGrade(g)}>{g === 'all' ? 'Toutes' : g}</button>)}
            </div>
          </div>
          <label className="field">Matière
            <select value={subject} onChange={(e) => setSubject(e.target.value)}>
              <option value="all">Toutes les matières</option>
              {subjects.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
        </div>
        {courses.length === 0 && <p className="empty">Aucun cours pour ce filtre.</p>}
        <ul className="tree" aria-label="Arborescence du catalogue">
          {courses.map((c) => (
            <li key={c.id}>
              <p className="node-title">{c.title}</p>
              <ul>
                {c.units.map((u) => (
                  <li key={u.id}>
                    <p className="muted small">{u.title}</p>
                    <ul>
                      {u.lessons.map((l) => {
                        const head = headlineRevision(state, l.id);
                        return (
                          <li key={l.id}>
                            <button type="button" className="lesson-link" aria-current={lessonId === l.id ? 'true' : undefined} onClick={() => setLessonId(l.id)}>
                              <span>{l.title}</span>
                              {head ? <StatusBadge status={head.status} /> : <Badge tone="outline">Aucune révision</Badge>}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </section>

      <section className="card" aria-labelledby="lesson-title" aria-live="polite">
        {!selected ? (
          <p className="empty">Choisir une leçon dans l’arborescence.</p>
        ) : (
          <>
            <p className="muted small">{selected.course} › {selected.unit}</p>
            <h2 id="lesson-title">{selected.title}</h2>
            {revs.length === 0 ? (
              <p className="empty">Aucune révision pour cette leçon.</p>
            ) : (
              <TableWrap label={`Révisions de ${selected.title}`}>
                <table className="data">
                  <caption>Révisions</caption>
                  <thead><tr><th scope="col">N°</th><th scope="col">Statut</th><th scope="col">Auteur</th><th scope="col">Sources et droits</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
                  <tbody>
                    {revs.map((r) => (
                      <tr key={r.id}>
                        <th scope="row">v{r.number}</th>
                        <td><StatusBadge status={r.status} />{r.aiAssisted && <> <Badge tone="violet">Assisté par IA</Badge></>}</td>
                        <td>{r.authorName}</td>
                        <td>{r.sources.length === 0 ? <Badge tone="warn">Aucune source</Badge> : sourcesReady(r) ? <Badge tone="ok">✔ {r.sources.length} source{r.sources.length > 1 ? 's' : ''}, droits confirmés</Badge> : <Badge tone="warn">! Droits à confirmer</Badge>}</td>
                        <td><Link className="btn small" to={`/contenu/revision/${r.id}`} aria-label={`Ouvrir ${selected.title} version ${r.number}`}>Ouvrir</Link></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            )}
            <div className="row">
              <button type="button" className="btn primary" disabled={!create.allowed} onClick={() => {
                const res = store.dispatch({ type: 'create_revision', lessonId: selected.id }, persona);
                if (res.ok && res.revisionId) nav(`/contenu/revision/${res.revisionId}`);
              }}>Nouvelle révision (brouillon)</button>
            </div>
            {!create.allowed && 'reason' in create && <p className="why">{create.reason}</p>}
          </>
        )}
      </section>
    </div>
  );
}
