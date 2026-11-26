import type { ReactNode } from 'react';

export type Tone = 'neutral' | 'ok' | 'info' | 'warn' | 'danger' | 'violet' | 'outline';

export function Badge({ tone = 'neutral', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span className={`badge ${tone}`} title={title}>{children}</span>;
}

/** Appears on every value that comes from a fixture, so a screenshot can never be mistaken for real data. */
export function SyntheticBadge() {
  return <span className="badge synthetic" title="Valeur issue de données de démonstration, pas de la production">Synthétique</span>;
}

export function Notice({ tone, title, children }: { tone?: 'warn' | 'danger' | 'violet'; title?: string; children: ReactNode }) {
  return (
    <div className={`notice ${tone ?? ''}`} role={tone === 'danger' ? 'alert' : undefined}>
      {title && <strong>{title}</strong>}
      {children}
    </div>
  );
}

export function PageHeader({ title, children, actions, crumbs }: { title: string; children?: ReactNode; actions?: ReactNode; crumbs?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        {crumbs && <nav className="crumbs" aria-label="Fil d’Ariane">{crumbs}</nav>}
        <h1 id="page-title" tabIndex={-1}>{title}</h1>
        {children && <p>{children}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

/** Horizontally scrollable table region that is reachable and operable by keyboard. */
export function TableWrap({ label, children }: { label: string; children: ReactNode }) {
  return <div className="table-wrap" role="region" aria-label={`Tableau : ${label}`} tabIndex={0}>{children}</div>;
}
