import { useState } from 'react';
import { NavLink, Outlet, useMatch } from 'react-router-dom';
import { Notice, PageHeader } from '../components/ui';
import { pipelineCounts } from '../domain/editorial';
import { useEditorial } from '../state/Services';

export function ContentLayout() {
  const revision = useMatch('/contenu/revision/:id');
  const { state, store } = useEditorial();
  const [resetCount, setResetCount] = useState(0);
  const reset = <button type="button" className="btn" onClick={() => {
    store.reset();
    setResetCount(n => n + 1);
  }}>Réinitialiser les données synthétiques</button>;
  const counts = pipelineCounts(state);
  return (
    <>
      {revision ? <div className="row">{reset}</div> : <PageHeader
        title="Contenu éducatif"
        actions={reset}
      >
        Aperçu du flux éditorial sur des leçons <strong>synthétiques</strong> au format de blocs v1 (titre, paragraphe, exemple, encadré).
      </PageHeader>}
      <Notice tone="warn" title="Aucune publication réelle.">
        Approuver, publier ou retirer ne change que la mémoire de cette page ; le rechargement restaure les fixtures. Les règles de rôle sont
        reproduites pour la démonstration : <strong>FastAPI décidera réellement</strong>. Les formats de blocs v2 (images, formules, audio) ne sont
        pas pris en charge : leur contrat n’est pas approuvé.
      </Notice>
      <nav className="tabs" aria-label="Sections du contenu">
        <NavLink to="/contenu" end>Catalogue</NavLink>
        <NavLink to="/contenu/relecture">File de relecture ({counts.in_review})</NavLink>
        <NavLink to="/contenu/publication">Publication ({counts.approved} prête{counts.approved > 1 ? 's' : ''})</NavLink>
      </nav>
      <Outlet key={resetCount} />
    </>
  );
}
