import { Link } from 'react-router-dom';
import { Badge, Notice, PageHeader, TableWrap } from '../components/ui';
import { METRICS, READINESS_GLYPH, READINESS_LABEL } from '../domain/metrics';

/** The full catalog of Admin-00 doc 3, as data: the single source of truth the dashboard tiles read from. */
export function MetricCatalog() {
  return (
    <>
      <PageHeader title="Catalogue des 21 indicateurs" crumbs={<Link to="/">Tableau de bord</Link>}>
        Aucun indicateur sans définition, source et calcul. Sans source, l’indicateur est « indisponible » et dit pourquoi.
      </PageHeader>
      <Notice title="Heure d’Haïti.">Toutes les « journées » sont des dates locales d’Haïti. Les petits groupes (&lt; K) sont masqués côté serveur.</Notice>
      <TableWrap label="Catalogue des indicateurs">
        <table className="data">
          <caption>Indicateurs M1 à M21</caption>
          <thead>
            <tr><th scope="col">#</th><th scope="col">Indicateur</th><th scope="col">Définition</th><th scope="col">Source</th><th scope="col">Niveau</th><th scope="col">Disponibilité</th></tr>
          </thead>
          <tbody>
            {METRICS.map((m) => (
              <tr key={m.id} data-metric-row={m.id}>
                <th scope="row">{m.id}</th>
                <td><strong>{m.label}</strong></td>
                <td>{m.definition}{m.unavailableReason && <><br /><span className="muted small">{m.unavailableReason}</span></>}</td>
                <td>{m.source}</td>
                <td><Badge tone="outline">{m.tier}</Badge></td>
                <td>{READINESS_GLYPH[m.readiness]} {READINESS_LABEL[m.readiness]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </>
  );
}
