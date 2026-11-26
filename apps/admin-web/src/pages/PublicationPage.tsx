import { Link } from 'react-router-dom';
import { StatusBadge } from '../components/StatusBadge';
import { Badge, Notice, TableWrap } from '../components/ui';
import { canPublish, lessonTitle, type Revision } from '../domain/editorial';
import { levelFor } from '../domain/roles';
import { fmtDateTime, fmtNumber } from '../i18n/format';
import { useRolePreview } from '../state/RolePreview';
import { useEditorial } from '../state/Services';

/** Synthetic estimate of a pack manifest: bytes of the French blocks as JSON. Not a real pack, no assets (format v2 unsupported). */
function estimateBytes(revs: Revision[]): number {
  return revs.reduce((n, r) => n + new TextEncoder().encode(JSON.stringify(r.blocks.fr ?? [])).length, 0);
}

export function PublicationPage() {
  const { state } = useEditorial();
  const { persona } = useRolePreview();
  const audit = levelFor(persona.roles, 'audit.read');
  const receipts = state.receipts.filter(r => audit === 'yes' || (audit === 'limited' && r.actorId === persona.id));
  const ready = state.revisions.filter((r) => r.status === 'approved');
  const live = state.revisions.filter((r) => r.status === 'published');
  const withdrawn = state.revisions.filter((r) => r.status === 'withdrawn');
  const row = (r: Revision) => (
    <tr key={r.id}>
      <th scope="row"><Link to={`/contenu/revision/${r.id}`}>{lessonTitle(state, r.lessonId)}</Link></th>
      <td>v{r.number}</td><td>{r.authorName}</td><td><StatusBadge status={r.status} /></td>
    </tr>
  );
  return (
    <div className="stack">
      <Notice tone="warn" title="Retrait (takedown) : pas de route serveur.">La spécification recense l’absence de route de retrait (constat L-B2-3). Ici le retrait est simulé ; une vraie publication exigerait le step-up MFA (AD-2).</Notice>
      <section className="card" aria-labelledby="p-ready">
        <h2 id="p-ready">Prêtes à publier ({ready.length})</h2>
        {ready.length === 0 ? <p className="empty">Aucune révision approuvée en attente.</p> : (
          <TableWrap label="Révisions prêtes à publier">
            <table className="data">
              <caption>Approuvées</caption>
              <thead><tr><th scope="col">Leçon</th><th scope="col">Version</th><th scope="col">Auteur</th><th scope="col">Statut</th><th scope="col">Pour {persona.name.split(' ')[0]}</th></tr></thead>
              <tbody>
                {ready.map((r) => {
                  const a = canPublish(persona, r);
                  return <tr key={r.id}><th scope="row"><Link to={`/contenu/revision/${r.id}`}>{lessonTitle(state, r.lessonId)}</Link></th><td>v{r.number}</td><td>{r.authorName}</td><td><StatusBadge status={r.status} /></td><td>{a.allowed ? <Badge tone="info">Peut publier</Badge> : <span className="small muted">{a.reason}</span>}</td></tr>;
                })}
              </tbody>
            </table>
          </TableWrap>
        )}
        <p className="small muted">Aperçu du manifeste (estimation synthétique) : {ready.length} leçon{ready.length > 1 ? 's' : ''}, environ {fmtNumber(estimateBytes(ready))} octets de texte, 0 média (les médias exigent le format v2, non approuvé).</p>
      </section>
      <section className="card" aria-labelledby="p-live">
        <h2 id="p-live">Publiées ({live.length})</h2>
        <TableWrap label="Révisions publiées"><table className="data"><caption>Publiées</caption><thead><tr><th scope="col">Leçon</th><th scope="col">Version</th><th scope="col">Auteur</th><th scope="col">Statut</th></tr></thead><tbody>{live.map(row)}</tbody></table></TableWrap>
      </section>
      <section className="card" aria-labelledby="p-wd">
        <h2 id="p-wd">Retirées ({withdrawn.length})</h2>
        {withdrawn.length === 0 ? <p className="empty">Aucune.</p> : <TableWrap label="Révisions retirées"><table className="data"><caption>Retirées</caption><thead><tr><th scope="col">Leçon</th><th scope="col">Version</th><th scope="col">Auteur</th><th scope="col">Statut</th></tr></thead><tbody>{withdrawn.map(row)}</tbody></table></TableWrap>}
      </section>
      <section className="card" aria-labelledby="p-log">
        <h2 id="p-log">Reçus d’audit de cette session (synthétiques)</h2>
        {receipts.length === 0 ? <p className="empty">Aucune action pour l’instant.</p> : (
          <ol className="history">{receipts.map((r) => <li key={r.id}><code>{r.id}</code> {fmtDateTime(r.at)} · {r.actor} · {r.action} · {r.target}{r.reason ? ` — ${r.reason}` : ''}</li>)}</ol>
        )}
        <p className="small muted">Un vrai journal d’audit est écrit par le serveur, jamais par le navigateur.</p>
      </section>
    </div>
  );
}
