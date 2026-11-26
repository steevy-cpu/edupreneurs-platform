import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { MODULES, MODULE_STATE_LABEL } from '../domain/modules';
import { PERSONAS, ROLE_INFO, sectionLevel } from '../domain/roles';
import { useRolePreview } from '../state/RolePreview';
import { Icon } from './Icon';
import { Badge } from './ui';

export const ENVIRONMENT = 'LOCAL' as const;

function EnvironmentBanner() {
  return (
    <div className="env-banner" role="status" aria-label="Environnement">
      <span className="pill">{ENVIRONMENT}</span>
      <span>DONNÉES SYNTHÉTIQUES</span>
      <span>Aucun serveur : rien n’est lu, écrit, publié ni envoyé.</span>
    </div>
  );
}

/** Synthetic role preview: visibly NOT a login. */
function RolePreviewSelector() {
  const { persona, setPersonaId } = useRolePreview();
  return (
    <div className="role-preview" role="group" aria-labelledby="rp-title">
      <span id="rp-title" className="sr-only">Aperçu de rôle synthétique</span>
      <label htmlFor="rp-select">Aperçu de rôle (synthétique, pas une connexion)</label>
      <select id="rp-select" value={persona.id} onChange={(e) => setPersonaId(e.target.value)}>
        {PERSONAS.map((p) => (
          <option key={p.id} value={p.id}>{p.name} — {p.roles.map((r) => ROLE_INFO[r].label + (ROLE_INFO[r].state === 'proposed' ? ' (proposé)' : '')).join(' + ')}</option>
        ))}
      </select>
      <span className="roles">
        {persona.roles.map((r) => <Badge key={r} tone={ROLE_INFO[r].state === 'proposed' ? 'outline' : 'violet'}>{ROLE_INFO[r].label}{ROLE_INFO[r].state === 'proposed' ? ' (proposé)' : ''}</Badge>)}
      </span>
    </div>
  );
}

export function Shell() {
  const { persona } = useRolePreview();
  const loc = useLocation();
  // The drawer is open only for the path it was opened on, so any navigation closes it without an effect.
  const [openPath, setOpenPath] = useState<string | null>(null);
  const open = openPath === loc.pathname;
  const first = useRef(true);
  const menu = useRef<HTMLButtonElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  useEffect(() => {
    if (open) sidebar.current?.querySelector<HTMLElement>('nav a')?.focus();
  }, [open]);

  // Move focus to the page title on every navigation (keyboard and screen-reader users).
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    (document.getElementById('page-title') ?? document.getElementById('main'))?.focus();
  }, [loc.pathname]);

  const visible = MODULES.filter((m) => sectionLevel(persona.roles, m.id) !== 'none');
  const hidden = MODULES.length - visible.length;

  return (
    <div className="shell">
      <a className="skip-link" href="#main" onClick={event => { event.preventDefault(); document.getElementById('main')?.focus(); }}>Aller au contenu</a>
      <aside className="sidebar" data-open={open} id="sidebar" ref={sidebar}
        onBlur={event => {
          if (open && !event.currentTarget.contains(event.relatedTarget) && event.relatedTarget !== menu.current) setOpenPath(null);
        }}
        onKeyDown={event => {
          if (open && event.key === 'Escape') { setOpenPath(null); menu.current?.focus(); }
        }}>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">E</span>
          <span>Edupreneurs Admin<small>Prototype AD-1 · synthétique</small></span>
        </div>
        <nav aria-label="Navigation principale">
          <ul className="nav">
            {visible.map((m) => (
              <li key={m.id}>
                <NavLink onClick={() => setOpenPath(null)} to={m.path} end={m.path === '/'}>
                  <Icon name={m.id} />
                  <span>{m.label}</span>
                  {m.state !== 'fixture' && <span className="state">{m.state === 'partial' ? 'partiel' : m.state === 'unavailable' ? 'indispo.' : 'à venir'}</span>}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <p className="nav-hidden-note">
          {hidden > 0 ? `${hidden} section${hidden > 1 ? 's' : ''} masquée${hidden > 1 ? 's' : ''} pour ce rôle (démonstration).` : 'Toutes les sections sont visibles pour ce rôle.'}{' '}
          Masquer n’est pas protéger : le serveur décidera.
        </p>
      </aside>

      <div className="main-col">
        <EnvironmentBanner />
        <div className="topbar">
          <button type="button" className="btn menu-toggle" ref={menu} aria-expanded={open} aria-controls="sidebar" onClick={() => setOpenPath(open ? null : loc.pathname)}>
            {open ? 'Fermer le menu' : 'Menu'}
          </button>
          <RolePreviewSelector />
        </div>
        <main id="main" className="page" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export { MODULE_STATE_LABEL };
