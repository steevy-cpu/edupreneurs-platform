import { Link } from 'react-router-dom';
import { Badge, Notice, TableWrap } from '../components/ui';
import { StatusBadge } from '../components/StatusBadge';
import { canReview, lessonTitle, sourcesReady } from '../domain/editorial';
import { useRolePreview } from '../state/RolePreview';
import { useEditorial } from '../state/Services';

export function ReviewQueue() {
  const { state } = useEditorial();
  const { persona } = useRolePreview();
  const queue = state.revisions.filter((r) => r.status === 'in_review');
  const changes = state.revisions.filter((r) => r.status === 'changes_requested');
  return (
    <div className="stack">
      <Notice title="Séparation des tâches.">Un relecteur ne relit jamais sa propre révision ; une demande de changements exige un commentaire. Ces règles sont reproduites ici, appliquées par le serveur en réalité.</Notice>
      <section className="card" aria-labelledby="q-h">
        <h2 id="q-h">En attente de relecture ({queue.length})</h2>
        {queue.length === 0 ? <p className="empty">Rien à relire.</p> : (
          <TableWrap label="File de relecture">
            <table className="data">
              <caption>Révisions soumises</caption>
              <thead><tr><th scope="col">Leçon</th><th scope="col">Version</th><th scope="col">Auteur</th><th scope="col">Sources</th><th scope="col">Pour {persona.name.split(' ')[0]}</th></tr></thead>
              <tbody>
                {queue.map((r) => {
                  const a = canReview(persona, r);
                  return (
                    <tr key={r.id}>
                      <th scope="row"><Link to={`/contenu/revision/${r.id}`}>{lessonTitle(state, r.lessonId)}</Link></th>
                      <td>v{r.number} {r.aiAssisted && <Badge tone="violet">IA</Badge>}</td>
                      <td>{r.authorName}</td>
                      <td>{sourcesReady(r) ? <Badge tone="ok">✔ Droits confirmés</Badge> : <Badge tone="warn">! À vérifier</Badge>}</td>
                      <td>{a.allowed ? <Badge tone="info">Peut relire</Badge> : <span className="small muted">{a.reason}</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
        )}
      </section>
      <section className="card" aria-labelledby="c-h">
        <h2 id="c-h">Changements demandés ({changes.length})</h2>
        {changes.length === 0 ? <p className="empty">Aucune.</p> : (
          <ul className="plain stack">
            {changes.map((r) => (
              <li key={r.id}><Link to={`/contenu/revision/${r.id}`}>{lessonTitle(state, r.lessonId)} v{r.number}</Link> <StatusBadge status={r.status} /> — {r.authorName}<br /><span className="small muted">« {r.reviews[r.reviews.length - 1]?.comment} »</span></li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
