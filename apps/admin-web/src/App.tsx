import type { ReactElement } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import { Shell } from './components/Shell';
import { PageHeader } from './components/ui';
import { sectionLevel, type SectionId } from './domain/roles';
import { ContentCatalog } from './pages/ContentCatalog';
import { ContentLayout } from './pages/ContentLayout';
import { Dashboard } from './pages/Dashboard';
import { MetricCatalog } from './pages/MetricCatalog';
import { ModulePage } from './pages/ModulePage';
import { NoAccess } from './pages/NoAccess';
import { PublicationPage } from './pages/PublicationPage';
import { ReviewQueue } from './pages/ReviewQueue';
import { RevisionPage } from './pages/RevisionPage';
import { RolesPage } from './pages/RolesPage';
import { useRolePreview } from './state/RolePreview';

/** Demonstration guard: a hidden section also refuses its URL. Real enforcement is server-side (403). */
function Guard({ section, children }: { section: SectionId; children: ReactElement }) {
  const { persona } = useRolePreview();
  return sectionLevel(persona.roles, section) === 'none' ? <NoAccess section={section} /> : children;
}

function NotFound() {
  return (
    <>
      <PageHeader title="Page introuvable" />
      <p><Link to="/">Retour au tableau de bord</Link></p>
    </>
  );
}

const PLACEHOLDER_ROUTES: { path: string; section: SectionId }[] = [
  { path: 'mot-du-jour', section: 'wotd' },
  { path: 'examens-bibliotheque', section: 'exams' },
  { path: 'or-succes', section: 'gold' },
  { path: 'classement', section: 'leaderboard' },
  { path: 'jude-ia', section: 'jude' },
  { path: 'notifications', section: 'notifications' },
  { path: 'moderation', section: 'moderation' },
  { path: 'paiements', section: 'payments' },
  { path: 'infrastructure-audit', section: 'infra' },
];

/** Routes only; the router (hash in the browser, memory in tests) is supplied by the caller. */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Guard section="dashboard"><Dashboard /></Guard>} />
        <Route path="indicateurs" element={<Guard section="dashboard"><MetricCatalog /></Guard>} />
        <Route path="contenu" element={<Guard section="content"><ContentLayout /></Guard>}>
          <Route index element={<ContentCatalog />} />
          <Route path="relecture" element={<ReviewQueue />} />
          <Route path="publication" element={<PublicationPage />} />
          <Route path="revision/:id" element={<RevisionPage />} />
        </Route>
        <Route path="roles" element={<Guard section="roles"><RolesPage /></Guard>} />
        {PLACEHOLDER_ROUTES.map((r) => (
          <Route key={r.path} path={r.path} element={<Guard section={r.section}><ModulePage section={r.section} /></Guard>} />
        ))}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
