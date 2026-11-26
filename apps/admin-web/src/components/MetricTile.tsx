import type { ReactNode } from 'react';
import { fmtAge, fmtDateTime } from '../i18n/format';
import { isStale, METRIC_BY_ID, READINESS_GLYPH, READINESS_LABEL, type MetricId } from '../domain/metrics';
import { useRolePreview } from '../state/RolePreview';
import { Badge, SyntheticBadge } from './ui';

interface Props {
  id: MetricId;
  scopeUnavailable?: boolean;
  /** The demo's fixed "now" (Haiti), used for freshness. */
  now: Date;
  /** Refresh instant of the aggregate behind this value (ISO). Absent for unavailable metrics. */
  asOf?: string;
  /** The fixture rendering. Omitted → the tile shows its honest unavailable state. */
  children?: ReactNode;
  className?: string;
}

/**
 * One metric, always with: definition, period, freshness and availability (Admin-00 doc 1 §A, doc 3).
 * `unavailable` is a first-class state — never a zero and never a guess.
 */
export function MetricTile({ id, now, asOf, children, scopeUnavailable, className = '' }: Props) {
  const def = METRIC_BY_ID[id];
  const { persona } = useRolePreview();
  const restricted = def.adminOnly === true && !persona.roles.includes('admin');
  const available = def.refreshHours !== null && children !== undefined && !restricted && !scopeUnavailable;
  const stale = available && asOf !== undefined && isStale(new Date(asOf), def.refreshHours, now);
  const state = restricted ? 'restricted' : !available ? 'unavailable' : stale ? 'stale' : 'fixture';

  return (
    <article className={`card tile ${state === 'unavailable' || state === 'restricted' ? 'unavailable' : ''} ${stale ? 'stale' : ''} ${className}`} aria-labelledby={`t-${id}`} data-metric={id} data-state={state}>
      <div className="tile-head">
        <h3 id={`t-${id}`}><span className="muted">{id}</span> · {def.label}</h3>
        <div className="tile-tags">
          {(state === 'fixture' || state === 'stale') && <SyntheticBadge />}
          {state === 'stale' && <Badge tone="warn">Obsolète</Badge>}
          {state === 'unavailable' && <Badge tone="outline">Indisponible</Badge>}
          {state === 'restricted' && <Badge tone="violet">Réservé admin</Badge>}
          <Badge tone="outline" title="Niveau de confidentialité : T0 agrégat plateforme, T1 par classe/matière (petits groupes masqués), T2 individuel">{def.tier}</Badge>
        </div>
      </div>

      {available ? (
        <>
          {children}
          {def.caveat && <p className="small muted">{def.caveat}</p>}
        </>
      ) : (
        <>
          <div className="tile-value dash" aria-label="Valeur indisponible">—</div>
          <p className="tile-reason">
            {restricted ? 'Vue individuelle (T2) réservée au rôle administrateur, avec motif et audit. Aucune donnée individuelle n’est affichée dans ce prototype.' : scopeUnavailable ? 'Aucune donnée synthétique attribuable à votre contenu pour cet indicateur.' : def.unavailableReason ?? 'Aucune donnée.'}
          </p>
        </>
      )}

      <dl className="tile-meta">
        <dt>Période</dt><dd>{def.period}</dd>
        <dt>Données au</dt>
        <dd>
          {available && asOf ? (<>{fmtDateTime(asOf)} <span className="muted">({fmtAge(asOf, now)})</span>{stale && <span className="stale-note"> · plus de 2× l’intervalle de {def.refreshHours} h</span>}</>) : 'Aucune valeur disponible'}
        </dd>
        <dt>Source</dt><dd>{READINESS_GLYPH[def.readiness]} {READINESS_LABEL[def.readiness]}</dd>
      </dl>

      <details>
        <summary>Définition et calcul</summary>
        <dl>
          <dt>Définition</dt><dd>{def.definition}</dd>
          <dt>Source de données</dt><dd>{def.source}</dd>
          <dt>Calcul</dt><dd>{def.calculation}</dd>
        </dl>
      </details>
    </article>
  );
}
