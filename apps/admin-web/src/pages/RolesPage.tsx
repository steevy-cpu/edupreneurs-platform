import { Badge, Notice, PageHeader, TableWrap } from '../components/ui';
import { MODULES } from '../domain/modules';
import { ADMIN_NOT_AUTHOR_NOTE, CAPABILITIES, ROLES, ROLE_INFO, SECTION_ACCESS, SEPARATION_RULES, levelFor, type Level } from '../domain/roles';
import { useRolePreview } from '../state/RolePreview';

const SYMBOL: Record<Level, { sym: string; text: string }> = {
  yes: { sym: '✔', text: 'Autorisé' },
  limited: { sym: '◐', text: 'Limité' },
  no: { sym: '—', text: 'Refusé' },
};
const RULE_TONE = { exists: 'ok', 'to-add': 'warn', open: 'danger' } as const;
const RULE_LABEL = { exists: 'Existe', 'to-add': 'À ajouter', open: 'Constat ouvert' } as const;

/** Read-only viewer of Admin-00 doc 2. Nothing on this page grants or changes any role. */
export function RolesPage() {
  const { persona } = useRolePreview();
  const mine = persona.roles;
  const focus = (r: (typeof ROLES)[number]) => (mine.includes(r) ? 'focus-role' : '');

  return (
    <>
      <PageHeader title="Rôles et permissions">Lecture seule, transcrite de la spécification Admin-00 (doc 2). Aucune attribution de rôle n’est possible ici.</PageHeader>

      <Notice tone="danger" title="Masquer un bouton n’est pas une sécurité.">
        Cette interface cache ce qu’un rôle ne peut pas faire pour le confort. <strong>L’autorisation réelle est faite par FastAPI</strong> (et, en dessous,
        par les fonctions SQL <code>staff.*</code>). Le sélecteur de rôle en haut de page est un <strong>aperçu synthétique</strong> : ce n’est pas une
        connexion, il n’y a ni compte, ni mot de passe, ni MFA dans ce prototype.
      </Notice>

      <section className="section" aria-labelledby="r-roles">
        <h2 id="r-roles">Les six rôles</h2>
        <div className="grid">
          {ROLES.map((r) => (
            <article key={r} className="card" aria-labelledby={`role-${r}`}>
              <h3 id={`role-${r}`}>{ROLE_INFO[r].label} {ROLE_INFO[r].state === 'proposed' ? <Badge tone="warn">Proposé</Badge> : <Badge tone="ok">Existe</Badge>}</h3>
              <p className="muted">{ROLE_INFO[r].purpose}</p>
              {ROLE_INFO[r].state === 'proposed' && <p className="small">Ajouter ce rôle modifie la contrainte de base de données figée : accord explicite du propriétaire et migration relue requis (non fait ici).</p>}
            </article>
          ))}
        </div>
        <p className="muted small">Une personne peut cumuler plusieurs rôles : la permission effective est l’union, <strong>moins</strong> les règles de séparation des tâches ci-dessous.</p>
      </section>

      <section className="section" aria-labelledby="r-matrix">
        <h2 id="r-matrix">Matrice des capacités</h2>
        <p className="muted small">✔ autorisé · ◐ limité · — refusé. Colonnes hachurées : rôles proposés. Colonnes encadrées : rôles de l’aperçu actuel ({persona.name}).</p>
        <TableWrap label="Matrice des rôles et capacités">
          <table className="data matrix">
            <caption>Capacités par rôle</caption>
            <thead>
              <tr>
                <th scope="col">Capacité</th>
                {ROLES.map((r) => <th key={r} scope="col" className={`${ROLE_INFO[r].state === 'proposed' ? 'col-proposed' : ''} ${focus(r)}`}>{ROLE_INFO[r].label}{ROLE_INFO[r].state === 'proposed' && <><br /><small>(proposé)</small></>}</th>)}
                <th scope="col">Effectif (aperçu)</th>
              </tr>
            </thead>
            <tbody>
              {CAPABILITIES.map((c) => {
                const eff = levelFor(mine, c.id);
                return (
                  <tr key={c.id} data-capability={c.id}>
                    <th scope="row">{c.label}{c.footnote && <sup> 1</sup>}</th>
                    {ROLES.map((r) => (
                      <td key={r} className={`cell ${focus(r)}`}>
                        <span className={`sym ${c.cells[r]}`} aria-hidden="true">{SYMBOL[c.cells[r]].sym}</span>
                        <span className="sr-only">{SYMBOL[c.cells[r]].text}</span>
                        {c.notes?.[r] && <span className="small muted">{c.notes[r]}</span>}
                      </td>
                    ))}
                    <td className="cell"><span className={`sym ${eff}`} aria-hidden="true">{SYMBOL[eff].sym}</span><span className="sr-only">{SYMBOL[eff].text}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
        <p className="small muted"><sup>1</sup> {ADMIN_NOT_AUTHOR_NOTE}</p>
      </section>

      <section className="section" aria-labelledby="r-sections">
        <h2 id="r-sections">Sections visibles par rôle</h2>
        <p className="muted small">Dérivé de la matrice (qui est par action, pas par écran). Là où Admin-00 est muet, accès administrateur seul par défaut. C’est ce que fait le menu de gauche.</p>
        <TableWrap label="Sections visibles par rôle">
          <table className="data matrix">
            <caption>Section × rôle</caption>
            <thead><tr><th scope="col">Section</th>{ROLES.map((r) => <th key={r} scope="col" className={focus(r)}>{ROLE_INFO[r].label}</th>)}<th scope="col">Base de la dérivation</th></tr></thead>
            <tbody>
              {MODULES.map((m) => (
                <tr key={m.id}>
                  <th scope="row">{m.label}</th>
                  {ROLES.map((r) => {
                    const a = SECTION_ACCESS[m.id].access[r];
                    const l: Level = a === 'full' ? 'yes' : a === 'limited' ? 'limited' : 'no';
                    return <td key={r} className={`cell ${focus(r)}`}><span className={`sym ${l}`} aria-hidden="true">{SYMBOL[l].sym}</span><span className="sr-only">{SYMBOL[l].text}</span></td>;
                  })}
                  <td className="small muted">{SECTION_ACCESS[m.id].basis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </section>

      <section className="section" aria-labelledby="r-sod">
        <h2 id="r-sod">Séparation des tâches</h2>
        <ul className="plain stack">
          {SEPARATION_RULES.map((s) => (
            <li key={s.id} className="card" data-rule={s.id}>
              <div className="row"><Badge tone={RULE_TONE[s.status]}>{RULE_LABEL[s.status]}</Badge>{s.demonstrated && <Badge tone="violet">Démontré dans l’éditeur synthétique</Badge>}</div>
              <p><strong>{s.text}</strong></p>
              <p className="muted small">{s.statusNote}</p>
            </li>
          ))}
        </ul>
        <p className="muted small">Ces règles sont appliquées <strong>côté serveur, en SQL</strong>, pas dans l’interface. Ce prototype les reproduit seulement pour les montrer.</p>
      </section>
    </>
  );
}
