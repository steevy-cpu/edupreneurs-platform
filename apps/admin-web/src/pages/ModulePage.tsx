import { Link } from 'react-router-dom';
import { Badge, Notice, PageHeader } from '../components/ui';
import { MODULE_BY_ID, MODULE_STATE_LABEL, PLACEHOLDERS } from '../domain/modules';
import { SECTION_ACCESS, ROLE_INFO, type SectionId } from '../domain/roles';
import { useRolePreview } from '../state/RolePreview';

/** Truthful placeholder: says what the area is for, why it shows nothing, and what blocks it. Never a fake screen. */
export function ModulePage({ section }: { section: SectionId }) {
  const meta = MODULE_BY_ID[section];
  const spec = PLACEHOLDERS[section];
  const { persona } = useRolePreview();
  const roles = (Object.keys(SECTION_ACCESS[section].access) as (keyof typeof ROLE_INFO)[]).map((r) => ROLE_INFO[r].label).join(', ');
  const tone = meta.state === 'unavailable' ? 'danger' : 'warn';

  return (
    <>
      <PageHeader title={meta.label} actions={<Badge tone={meta.state === 'unavailable' ? 'danger' : 'warn'}>{MODULE_STATE_LABEL[meta.state]}</Badge>}>{meta.summary}</PageHeader>
      <Notice tone={tone} title={meta.state === 'unavailable' ? 'Indisponible.' : 'Pas encore construit.'}>
        {meta.state === 'unavailable'
          ? 'Aucune source de données ni module backend n’existe pour cette zone : rien n’est affiché plutôt que de simuler.'
          : 'Cette zone attend un jalon backend. Aucun écran fonctionnel n’est simulé : un faux formulaire laisserait croire à une action réelle.'}
        {' '}Livraison prévue : <strong>{meta.milestone}</strong>.
      </Notice>

      {spec && (
        <div className="grid wide">
          <section className="card" aria-labelledby="m-planned"><h2 id="m-planned">Ce que cette zone fera</h2><ul className="bullets">{spec.planned.map((x) => <li key={x}>{x}</li>)}</ul></section>
          <section className="card" aria-labelledby="m-backend"><h2 id="m-backend">Backend encore nécessaire</h2><ul className="bullets">{spec.backend.map((x) => <li key={x}>{x}</li>)}</ul></section>
          <section className="card" aria-labelledby="m-dec"><h2 id="m-dec">Décisions du propriétaire</h2><ul className="bullets">{spec.decisions.map((x) => <li key={x}>{x}</li>)}</ul></section>
        </div>
      )}
      <p className="muted small">Rôles prévus : {roles}. Aperçu actuel : {persona.name}. L’autorisation réelle sera faite par le serveur. · <Link to="/roles">Matrice des rôles</Link></p>
      {section === 'wotd' && <p><Link to="/">Voir la couverture du calendrier (indicateur M15, synthétique) sur le tableau de bord</Link>.</p>}
    </>
  );
}
