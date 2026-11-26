import { Link } from 'react-router-dom';
import { ROLE_INFO, SECTION_ACCESS, type SectionId } from '../domain/roles';
import { MODULE_BY_ID } from '../domain/modules';
import { useRolePreview } from '../state/RolePreview';
import { Notice, PageHeader } from '../components/ui';

/** Shown when a persona opens a URL for a section its role does not include. Demonstration of deny-by-default. */
export function NoAccess({ section }: { section: SectionId }) {
  const { persona } = useRolePreview();
  const allowed = Object.keys(SECTION_ACCESS[section].access) as (keyof typeof ROLE_INFO)[];
  return (
    <>
      <PageHeader title="Accès refusé (aperçu)">{MODULE_BY_ID[section].label}</PageHeader>
      <Notice tone="warn" title="Démonstration.">
        Avec le rôle de {persona.name}, cette section est masquée. Dans la version réelle, <strong>le serveur répond 403</strong> à toute requête
        de ce rôle ; masquer l’écran n’est qu’un confort.
      </Notice>
      <p>Rôles prévus pour cette section : {allowed.map((r) => ROLE_INFO[r].label).join(', ')}.</p>
      <p><Link to="/roles">Voir la matrice des rôles</Link></p>
    </>
  );
}
