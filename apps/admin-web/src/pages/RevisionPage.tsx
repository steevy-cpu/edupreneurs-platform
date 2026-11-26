import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { BlockEditor } from '../components/BlockEditor';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { PhonePreview } from '../components/PhonePreview';
import { RightsBadge, StatusBadge } from '../components/StatusBadge';
import { Badge, Notice, PageHeader } from '../components/ui';
import { diffBlocks, validateBlocks, type Block } from '../domain/blocks';
import {
  canEditDraft, canPublish, canReview, canSubmit, canWithdraw, findRevision, lessonTitle, revisionsOfLesson,
  sourcesReady, type Affordance, type Locale, type Result, type Revision, type RightsStatus, type SourceRef,
} from '../domain/editorial';
import { fmtDateTime } from '../i18n/format';
import { useRolePreview } from '../state/RolePreview';
import { useEditorial } from '../state/Services';

type Action = 'submit' | 'approve' | 'changes' | 'publish' | 'withdraw' | 'rollback';

export function RevisionPage() {
  const { id = '' } = useParams();
  const { state } = useEditorial();
  const rev = findRevision(state, id);
  if (!rev) {
    return (
      <div className="card"><p className="empty">Révision introuvable. <Link to="/contenu">Retour au catalogue</Link></p></div>
    );
  }
  return <RevisionView key={rev.id} rev={rev} />;
}

function RevisionView({ rev }: { rev: Revision }) {
  const { state, store } = useEditorial();
  const { persona } = useRolePreview();
  const [locale, setLocale] = useState<Locale>('fr');
  const [drafts, setDrafts] = useState<Partial<Record<Locale, Block[]>>>(() => structuredClone(rev.blocks));
  const [action, setAction] = useState<Action | null>(null);

  const title = lessonTitle(state, rev.lessonId);
  const editable = canEditDraft(persona, rev);
  const saved = rev.blocks[locale];
  const working = useMemo<Block[]>(() => (editable.allowed ? drafts[locale] : saved) ?? [], [editable.allowed, drafts, locale, saved]);
  const issues = useMemo(() => (working.length || saved ? validateBlocks(working) : []), [working, saved]);
  const dirty = editable.allowed && JSON.stringify(drafts) !== JSON.stringify(rev.blocks);

  const lessonRevs = revisionsOfLesson(state, rev.lessonId);
  const previous = lessonRevs.find((r) => r.number < rev.number);
  const diff = previous && rev.blocks.fr && previous.blocks.fr ? diffBlocks(previous.blocks.fr, rev.blocks.fr) : null;
  const hasRollback = rev.status === 'published' && lessonRevs.some((r) => r.status === 'superseded');

  const aff: Record<Action, Affordance> = {
    submit: dirty ? { allowed: false, reason: 'Enregistrer d’abord les modifications.' } : canSubmit(persona, rev),
    approve: canReview(persona, rev),
    changes: canReview(persona, rev),
    publish: canPublish(persona, rev),
    withdraw: canWithdraw(persona, rev),
    rollback: hasRollback ? canWithdraw(persona, { ...rev, status: 'published' }) : { allowed: false, reason: 'Aucune version antérieure à rétablir.' },
  };

  const run = (a: Action, reason: string): Result => {
    switch (a) {
      case 'submit': return store.dispatch({ type: 'submit', revisionId: rev.id }, persona);
      case 'approve': return store.dispatch({ type: 'review', revisionId: rev.id, decision: 'approve', comment: reason }, persona);
      case 'changes': return store.dispatch({ type: 'review', revisionId: rev.id, decision: 'changes', comment: reason }, persona);
      case 'publish': return store.dispatch({ type: 'publish', revisionId: rev.id, reason }, persona);
      case 'withdraw': return store.dispatch({ type: 'withdraw', revisionId: rev.id, reason }, persona);
      case 'rollback': return store.dispatch({ type: 'rollback', lessonId: rev.lessonId, reason }, persona);
    }
  };

  const DIALOG: Record<Action, { title: string; label: string; required: boolean; confirm: string; danger?: boolean; stepUp?: boolean }> = {
    submit: { title: 'Soumettre à la relecture', label: 'Note pour le relecteur', required: false, confirm: 'Soumettre' },
    approve: { title: 'Approuver la révision', label: 'Commentaire', required: false, confirm: 'Approuver' },
    changes: { title: 'Demander des changements', label: 'Ce qui doit changer', required: true, confirm: 'Demander des changements' },
    publish: { title: 'Publier la révision', label: 'Motif de publication', required: true, confirm: 'Publier (synthétique)', stepUp: true },
    withdraw: { title: 'Retirer la révision (retrait / takedown)', label: 'Motif du retrait', required: true, confirm: 'Retirer (synthétique)', danger: true, stepUp: true },
    rollback: { title: 'Revenir à la version précédente', label: 'Motif du retour arrière', required: true, confirm: 'Revenir en arrière (synthétique)', danger: true, stepUp: true },
  };

  const btn = (a: Action, text: string, primary = false) => (
    <li key={a}>
      <button type="button" className={`btn ${primary ? 'primary' : ''}`} disabled={!aff[a].allowed} onClick={() => setAction(a)}>{text}</button>
      {!aff[a].allowed && aff[a].reason && <p className="why">{aff[a].reason}</p>}
    </li>
  );

  const setBlocks = (next: Block[]) => setDrafts((d) => ({ ...d, [locale]: next }));
  const sourceCmd = (cmd: Parameters<typeof store.dispatch>[0]) => store.dispatch(cmd, persona);

  return (
    <>
      <PageHeader
        title={`${title} · v${rev.number}`}
        crumbs={<><Link to="/contenu">Catalogue</Link> › {title}</>}
        actions={<><StatusBadge status={rev.status} />{rev.aiAssisted && <Badge tone="violet" title="Une révision assistée par IA ne peut jamais être approuvée par son auteur">Assisté par IA</Badge>}</>}
      >
        Auteur : {rev.authorName}. {rev.aiAssisted && 'Brouillon assisté par IA (synthétique) : un relecteur autre que l’auteur doit tout vérifier. '}
        Aperçu synthétique du format de blocs v1.
      </PageHeader>

      {!editable.allowed && <Notice title="Lecture seule.">{editable.reason}</Notice>}

      <div className="editor-grid">
        <div className="stack">
          <section className="card" aria-labelledby="blocks-h">
            <div className="row">
              <h2 id="blocks-h">Blocs</h2>
              <div className="chips" role="group" aria-label="Langue">
                {(['fr', 'ht'] as Locale[]).map((l) => <button key={l} type="button" className="chip" aria-pressed={locale === l} onClick={() => setLocale(l)}>{l === 'fr' ? 'Français' : 'Kreyòl'}</button>)}
              </div>
            </div>
            {locale === 'ht' && <p className="small muted">Version créole : brouillon synthétique, non relu par un éducateur.</p>}
            {working.length === 0 && saved === undefined ? (
              <p className="empty">Aucune version dans cette langue pour cette révision.</p>
            ) : (
              <BlockEditor blocks={working} onChange={setBlocks} issues={issues} disabled={!editable.allowed} />
            )}
            {editable.allowed && (
              <div className="row">
                <button type="button" className="btn primary" disabled={!dirty} onClick={() => store.dispatch({ type: 'update_blocks', revisionId: rev.id, locale, blocks: drafts[locale] ?? [] }, persona)}>Enregistrer le brouillon (synthétique)</button>
                {dirty ? <Badge tone="warn">Modifications non enregistrées</Badge> : <Badge tone="outline">Enregistré</Badge>}
                {issues.length > 0 && <Badge tone="danger">{issues.length} erreur{issues.length > 1 ? 's' : ''} de validation</Badge>}
              </div>
            )}
          </section>

          {diff && (
            <section className="card" aria-labelledby="diff-h">
              <h2 id="diff-h">Différences avec la v{previous!.number}</h2>
              <ul className="diff">
                {diff.map((d) => (
                  <li key={d.key} className={d.kind}>
                    <Badge tone={d.kind === 'added' ? 'ok' : d.kind === 'removed' ? 'danger' : d.kind === 'changed' ? 'warn' : 'outline'}>{{ added: 'Ajouté', removed: 'Supprimé', changed: 'Modifié', unchanged: 'Inchangé' }[d.kind]}</Badge>{' '}
                    <code>{d.key}</code>
                    {d.before && d.kind !== 'unchanged' && <span className="before">{d.before}</span>}
                    {d.after && <span>{d.after}</span>}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <div className="stack">
          <section className="card" aria-labelledby="prev-h">
            <h2 id="prev-h">Aperçu téléphone (320 dp)</h2>
            <PhonePreview blocks={working} locale={locale} />
            <p className="small muted">Texte brut uniquement, comme sur le téléphone.</p>
          </section>

          <section className="card" aria-labelledby="flow-h">
            <h2 id="flow-h">Flux éditorial</h2>
            <p className="small muted">Aperçu de rôle : {persona.name}. Les raisons de blocage sont affichées, mais c’est le serveur qui décidera.</p>
            <ul className="plain stack">
              {btn('submit', 'Soumettre à la relecture', true)}
              {btn('approve', 'Approuver', true)}
              {btn('changes', 'Demander des changements')}
              {btn('publish', 'Publier', true)}
              {btn('rollback', 'Retour arrière')}
              {btn('withdraw', 'Retirer (takedown)')}
            </ul>
            <p className="small muted">Le retrait n’a pas encore de route serveur (constat L-B2-3).</p>
          </section>

          <SourcesCard rev={rev} editable={editable} sourceCmd={sourceCmd} />

          <section className="card" aria-labelledby="hist-h">
            <h2 id="hist-h">Historique et relectures</h2>
            {rev.reviews.length > 0 && (
              <ul className="plain stack">
                {rev.reviews.map((r, i) => <li key={i}><Badge tone={r.decision === 'approve' ? 'ok' : 'warn'}>{r.decision === 'approve' ? 'Approuvée' : 'Changements demandés'}</Badge> par {r.reviewerName}{r.comment && <> : « {r.comment} »</>}</li>)}
              </ul>
            )}
            {rev.history.length === 0 ? <p className="muted small">Aucun événement enregistré (fixture).</p> : (
              <ul className="history">{rev.history.map((h, i) => <li key={i}>{fmtDateTime(h.at)} · {h.actor} · {h.action}{h.reason ? ` (${h.reason})` : ''}</li>)}</ul>
            )}
          </section>
        </div>
      </div>

      {action && (
        <ConfirmDialog
          title={DIALOG[action].title}
          object={`${title}, version ${rev.number} (${rev.id})`}
          reasonLabel={DIALOG[action].label}
          reasonRequired={DIALOG[action].required}
          confirmLabel={DIALOG[action].confirm}
          danger={DIALOG[action].danger}
          stepUp={DIALOG[action].stepUp}
          onConfirm={(reason) => run(action, reason)}
          onClose={() => setAction(null)}
        />
      )}
    </>
  );
}

function SourcesCard({ rev, editable, sourceCmd }: { rev: Revision; editable: Affordance; sourceCmd: (c: Parameters<ReturnType<typeof useEditorial>['store']['dispatch']>[0]) => Result }) {
  const [title, setTitle] = useState('');
  const [rights, setRights] = useState<RightsStatus>('pending');
  return (
    <section className="card" aria-labelledby="src-h">
      <h2 id="src-h">Sources et droits {sourcesReady(rev) ? <Badge tone="ok">✔ prêtes</Badge> : <Badge tone="warn">Incomplètes</Badge>}</h2>
      <p className="small muted">Au moins une source, toutes avec droits confirmés, avant de soumettre.</p>
      {rev.sources.length === 0 && <p className="empty">Aucune source jointe.</p>}
      <ul className="plain stack">
        {rev.sources.map((s: SourceRef) => (
          <li key={s.id}>
            <strong>{s.title}</strong><br />
            <span className="small muted">{s.kind} · {s.licence}</span> <RightsBadge rights={s.rights} />
            {editable.allowed && (
              <div className="row">
                <label className="sr-only" htmlFor={`r-${s.id}`}>Droits de {s.title}</label>
                <select id={`r-${s.id}`} value={s.rights} onChange={(e) => sourceCmd({ type: 'set_rights', revisionId: rev.id, sourceId: s.id, rights: e.target.value as RightsStatus })}>
                  <option value="cleared">Droits confirmés</option><option value="pending">Droits en attente</option><option value="unknown">Droits inconnus</option><option value="restricted">Droits restreints</option>
                </select>
                <button type="button" className="btn small" onClick={() => sourceCmd({ type: 'remove_source', revisionId: rev.id, sourceId: s.id })}>Retirer la source</button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {editable.allowed && (
        <form className="row" onSubmit={(e) => { e.preventDefault(); if (!title.trim()) return; sourceCmd({ type: 'add_source', revisionId: rev.id, source: { title: title.trim(), kind: 'textbook', licence: 'À préciser', rights } }); setTitle(''); }}>
          <label className="sr-only" htmlFor="new-src">Titre de la nouvelle source</label>
          <input id="new-src" type="text" placeholder="Titre de la source" value={title} onChange={(e) => setTitle(e.target.value)} />
          <label className="sr-only" htmlFor="new-src-r">Droits de la nouvelle source</label>
          <select id="new-src-r" value={rights} onChange={(e) => setRights(e.target.value as RightsStatus)}>
            <option value="pending">Droits en attente</option><option value="cleared">Droits confirmés</option>
          </select>
          <button type="submit" className="btn">Joindre</button>
        </form>
      )}
    </section>
  );
}
