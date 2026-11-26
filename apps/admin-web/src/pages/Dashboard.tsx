import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { BarChart, dayPoints, LineChart, SegmentBar } from '../components/charts';
import { Heatmap } from '../components/Heatmap';
import { MetricTile } from '../components/MetricTile';
import { Badge, Notice, PageHeader, TableWrap } from '../components/ui';
import type { DashboardData } from '../domain/dashboard';
import { pipelineCounts, STATUS_LABEL, type RevStatus } from '../domain/editorial';
import { METRICS, type MetricId } from '../domain/metrics';
import { sectionLevel } from '../domain/roles';
import { fmtDay, fmtNumber, fmtPercent } from '../i18n/format';
import { useRolePreview } from '../state/RolePreview';
import { useEditorial, useServices } from '../state/Services';

/** Indicators a role with limited analytics access sees in this demo (the server filters in production). */
const LIMITED_VIEW: ReadonlySet<MetricId> = new Set<MetricId>(['M5', 'M7', 'M8', 'M16']);

const STATUS_ORDER: RevStatus[] = ['draft', 'changes_requested', 'in_review', 'approved', 'published', 'withdrawn', 'superseded'];

function Section({ id, title, hint, children }: { id: string; title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="section" aria-labelledby={`sec-${id}`}>
      <h2 id={`sec-${id}`}>{title}{hint && <small>{hint}</small>}</h2>
      {children}
    </section>
  );
}

export function Dashboard() {
  const services = useServices();
  const { persona } = useRolePreview();
  const { state: editorial } = useEditorial();
  const [data, setData] = useState<DashboardData | null>(null);

  useEffect(() => {
    let live = true;
    void services.getDashboard().then((d) => { if (live) setData(d); });
    return () => { live = false; };
  }, [services]);

  const level = sectionLevel(persona.roles, 'dashboard');
  if (!data) return <p role="status">Chargement des données synthétiques…</p>;

  const now = new Date(data.now);
  const show = (id: MetricId) => level === 'full' || LIMITED_VIEW.has(id);
  const asOf = (id: MetricId) => data.asOf[id];
  const counts = pipelineCounts(editorial);
  const waiting = counts.in_review;

  const withValue = METRICS.filter((m) => m.refreshHours !== null && !m.adminOnly).length;
  const without = METRICS.length - withValue;

  return (
    <>
      <PageHeader title="Tableau de bord" actions={<Link className="btn" to="/indicateurs">Catalogue des 21 indicateurs</Link>}>
        Aperçu du centre de contrôle sur des <strong>données synthétiques</strong>. Chaque indicateur porte sa définition, sa période et sa date d’actualisation ; un indicateur sans source est déclaré indisponible, jamais deviné.
      </PageHeader>

      <Notice tone="warn" title="Rien ici n’est réel.">
        Valeurs fabriquées pour la démonstration, date de référence fixe : {fmtDay(data.now.slice(0, 10))} 2026 (Haïti). {withValue} indicateurs ont un aperçu synthétique,
        {' '}{without} sont indisponibles faute de source dans le backend. Aucun enregistrement individuel d’élève n’est affiché ; les groupes de moins de K = {data.m8.k} sont masqués (valeur provisoire, décision du propriétaire).
      </Notice>
      {level === 'limited' && (
        <Notice tone="violet" title="Accès limité (◐).">
          Le rôle de {persona.name} voit des statistiques limitées. Ici : M5, M7, M8, M16. La limite réelle (par exemple « son contenu ») sera appliquée par le serveur.
        </Notice>
      )}

      {show('M1') && (
        <Section id="apprenants" title="Apprenants" hint="inscriptions et activité d’apprentissage">
          <div className="grid">
            <MetricTile id="M1" now={now} asOf={asOf('M1')}>
              <div className="tile-value">{fmtNumber(data.m1.total)}<small>apprenants</small></div>
              <p className="delta">▲ +{fmtNumber(data.m1.delta7d)} <span className="muted">sur 7 jours</span></p>
            </MetricTile>
            <MetricTile id="M3" now={now} asOf={asOf('M3')}>
              <div className="tile-value">{fmtNumber(data.m3.daily)} <small>/ jour</small></div>
              <p className="muted">{fmtNumber(data.m3.monthly)} sur 28 jours glissants</p>
              <BarChart title="Actifs en apprentissage par jour" unit="Apprenants" points={dayPoints(data.m3.dailySeries)} tone="alt" />
            </MetricTile>
            <MetricTile id="M2" now={now} asOf={asOf('M2')} className="span-2">
              <LineChart title="Inscriptions par semaine" unit="Nouveaux profils" points={data.m2.map((w) => ({ label: fmtDay(w.weekStart), value: w.count }))} />
            </MetricTile>
            <MetricTile id="M4" now={now} />
          </div>
        </Section>
      )}

      <Section id="apprentissage" title="Apprentissage" hint="leçons, exercices, précision">
        <div className="grid">
          {show('M5') && (
            <MetricTile id="M5" now={now} asOf={asOf('M5')}>
              <div className="tile-value">{fmtNumber(data.m5.total7d)}<small>leçons terminées</small></div>
              <BarChart title="Leçons terminées par jour" unit="Leçons" points={dayPoints(data.m5.byDay)} />
            </MetricTile>
          )}
          {show('M6') && (
            <MetricTile id="M6" now={now} asOf={asOf('M6')}>
              <div className="tile-value">{fmtNumber(data.m6.reduce((a, d) => a + d.count, 0))}<small>réponses (14 j)</small></div>
              <BarChart title="Réponses d’exercice par jour" unit="Réponses" points={dayPoints(data.m6)} tone="alt" />
            </MetricTile>
          )}
          {show('M7') && (
            <MetricTile id="M7" now={now} asOf={asOf('M7')}>
              <div className="tile-value">{fmtPercent(data.m7.percent)}<small>correctes (notes serveur)</small></div>
              <p className="muted">Sur {fmtNumber(data.m7.sample)} réponses. Jamais affiché par apprenant.</p>
            </MetricTile>
          )}
        </div>
      </Section>

      {show('M8') && (
        <Section id="engagement" title="Engagement par classe et matière">
          <MetricTile id="M8" now={now} asOf={asOf('M8')}>
            <Heatmap grades={data.m8.grades} subjects={data.m8.subjects} cells={data.m8.cells} k={data.m8.k} />
          </MetricTile>
        </Section>
      )}

      {level === 'full' && (
        <Section id="sync" title="Santé de la synchronisation">
          <div className="grid">
            <MetricTile id="M12" now={now} asOf={asOf('M12')}>
              {(() => {
                const t = data.m12.days.reduce((a, d) => a + d.accepted + d.duplicate + d.rejected + d.conflict, 0);
                const rej = data.m12.days.reduce((a, d) => a + d.rejected, 0);
                return <div className="tile-value">{fmtPercent((rej / t) * 100)}<small>opérations rejetées</small></div>;
              })()}
              <BarChart title="Opérations rejetées par jour" unit="Rejetées" points={data.m12.days.map((d) => ({ label: fmtDay(d.date), value: d.rejected }))} tone="warn" />
              <TableWrap label="Codes de rejet">
                <table className="data">
                  <caption>Codes de rejet (7 jours)</caption>
                  <thead><tr><th scope="col">Code</th><th scope="col" className="num">Nombre</th></tr></thead>
                  <tbody>{data.m12.rejectionCodes.map((c) => <tr key={c.code}><th scope="row"><code>{c.code}</code></th><td className="num">{c.count}</td></tr>)}</tbody>
                </table>
              </TableWrap>
            </MetricTile>
            <MetricTile id="M13" now={now} />
          </div>
        </Section>
      )}

      <Section id="contenu" title="Contenu et Mot du jour">
        <div className="grid">
          {show('M16') && (
            <MetricTile id="M16" now={now} asOf={asOf('M16')}>
              <div className="tile-value">{waiting}<small>en attente de relecture</small></div>
              <SegmentBar label="Révisions par statut" segments={STATUS_ORDER.map((s) => ({ key: s, label: STATUS_LABEL[s], value: counts[s] }))} />
              <p className="muted small">Calculé en direct sur l’aperçu éditorial : une action dans <Link to="/contenu">Contenu</Link> change ce graphique. Durée médiane brouillon → publié : {data.m16.medianDaysToPublish} j (fixture).</p>
            </MetricTile>
          )}
          {level === 'full' && (
            <MetricTile id="M15" now={now} asOf={asOf('M15')}>
              {(() => {
                const n = data.m15.filter((d) => d.covered).length;
                return (
                  <>
                    <div className="tile-value">{n} / 14<small>jours couverts</small></div>
                    <ol className="coverage" aria-label="Couverture des 14 prochains jours">
                      {data.m15.map((d) => (
                        <li key={d.date} className={d.covered ? 'yes' : 'no'}>
                          <strong>{fmtDay(d.date).split(' ')[0]}</strong>
                          <span>{d.covered ? 'mot publié' : 'aucun mot'}</span>
                        </li>
                      ))}
                    </ol>
                  </>
                );
              })()}
            </MetricTile>
          )}
        </div>
      </Section>

      {level === 'full' && (
        <>
          <Section id="exploitation" title="Exploitation">
            <div className="grid">
              <MetricTile id="M18" now={now} asOf={asOf('M18')}>
                <ul className="checks">
                  {data.m18.map((c) => (
                    <li key={c.id}><Badge tone={c.state === 'ok' ? 'ok' : 'outline'}>{c.state === 'ok' ? 'OK' : 'Inconnu'}</Badge><span><strong>{c.label}</strong><br /><span className="muted small">{c.note}</span></span></li>
                  ))}
                </ul>
              </MetricTile>
              <MetricTile id="M17" now={now} asOf={asOf('M17')}>
                <div className="tile-value">{data.m17.delivered} / {data.m17.failed}<small>livrées / en échec</small></div>
              </MetricTile>
            </div>
          </Section>

          <Section id="autres" title="Autres indicateurs du catalogue" hint="sans source aujourd’hui, sauf M9">
            <div className="grid">
              <MetricTile id="M9" now={now} asOf={asOf('M9')}>
                <div className="tile-value">{fmtNumber(data.m9.gold7d)}<small>pièces d’or (7 j)</small></div>
                <p className="muted">{fmtNumber(data.m9.achievements7d)} succès attribués</p>
              </MetricTile>
              {(['M10', 'M11', 'M14', 'M19', 'M20', 'M21'] as MetricId[]).map((id) => <MetricTile key={id} id={id} now={now} />)}
            </div>
          </Section>
        </>
      )}
    </>
  );
}
