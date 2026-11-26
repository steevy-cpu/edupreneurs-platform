import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { renderApp } from './render';

const nav = () => within(screen.getByRole('navigation', { name: 'Navigation principale' }));
const tile = (id: string) => document.querySelector<HTMLElement>(`[data-metric="${id}"]`)!;

describe('boot and navigation', () => {
  it('boots on the dashboard with the LOCAL / synthetic banner and a skip link', async () => {
    renderApp('/');
    expect(await screen.findByRole('heading', { level: 1, name: 'Tableau de bord' })).toBeInTheDocument();
    const banner = screen.getByRole('status', { name: 'Environnement' });
    expect(banner).toHaveTextContent('LOCAL');
    expect(banner).toHaveTextContent('DONNÉES SYNTHÉTIQUES');
    expect(screen.getByRole('link', { name: 'Aller au contenu' })).toHaveAttribute('href', '#main');
    expect(document.documentElement.lang || 'fr').toBe('fr');
  });

  it('navigates between the main areas', async () => {
    const user = userEvent.setup();
    renderApp('/');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    await user.click(nav().getByRole('link', { name: /Contenu éducatif/ }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Contenu éducatif' })).toBeInTheDocument();
    await user.click(nav().getByRole('link', { name: /Rôles et permissions/ }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Rôles et permissions' })).toBeInTheDocument();
    await user.click(nav().getByRole('link', { name: /Jude IA/ }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Jude IA' })).toBeInTheDocument();
  });

  it('shows a not-found page for unknown routes', () => {
    renderApp('/nimporte-quoi');
    expect(screen.getByRole('heading', { name: 'Page introuvable' })).toBeInTheDocument();
  });

  it('has a role-preview selector that is clearly not a login and no credential field anywhere', async () => {
    renderApp('/');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    expect(screen.getByRole('combobox', { name: /Aperçu de rôle \(synthétique, pas une connexion\)/ })).toBeInTheDocument();
    expect(document.querySelector('input[type="password"], input[type="email"], input[autocomplete*="password"]')).toBeNull();
    expect(screen.queryByText(/mot de passe|se connecter|connexion réussie/i)).toBeNull();
  });

  it('toggles the mobile menu with aria-expanded', async () => {
    const user = userEvent.setup();
    renderApp('/');
    const toggle = screen.getByRole('button', { name: 'Menu' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(screen.getByRole('button', { name: 'Fermer le menu' })).toHaveAttribute('aria-expanded', 'true');
  });
});

describe('dashboard metrics', () => {
  it('renders all 21 catalog metrics for an admin', async () => {
    renderApp('/');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    const ids = [...document.querySelectorAll('[data-metric]')].map((e) => e.getAttribute('data-metric'));
    expect(new Set(ids).size).toBe(21);
    expect(ids).toHaveLength(21);
  });

  it('gives every tile a definition, a period, a freshness line and an availability badge', async () => {
    renderApp('/');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    for (const el of document.querySelectorAll<HTMLElement>('[data-metric]')) {
      const w = within(el);
      expect(w.getByText('Définition et calcul'), el.dataset.metric).toBeInTheDocument();
      expect(w.getAllByText('Période').length).toBeGreaterThan(0);
      expect(w.getByText('Données au')).toBeInTheDocument();
      expect(el.dataset.state).toMatch(/fixture|stale|unavailable|restricted/);
    }
  });

  it('labels every fixture value as synthetic', async () => {
    renderApp('/');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    for (const el of document.querySelectorAll<HTMLElement>('[data-state="fixture"],[data-state="stale"]')) {
      expect(within(el).getByText('Synthétique'), el.dataset.metric).toBeInTheDocument();
    }
  });

  it('shows an honest unavailable state, with the reason, for metrics with no source', async () => {
    renderApp('/');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    for (const id of ['M4', 'M10', 'M11', 'M13', 'M14', 'M19', 'M20']) {
      const t = tile(id);
      expect(t.dataset.state, id).toBe('unavailable');
      expect(within(t).getByText('Indisponible')).toBeInTheDocument();
      expect(within(t).getByLabelText('Valeur indisponible')).toHaveTextContent('—');
    }
    expect(tile('M4')).toHaveTextContent(/Aucun événement d’ouverture/);
    expect(tile('M10')).toHaveTextContent(/Aucune source/);
    expect(tile('M19')).toHaveTextContent(/aucun jeton, coût ou erreur n’est mesuré/);
    expect(tile('M20')).toHaveTextContent(/Aucune tuile de revenus/);
  });

  it('marks the stale M12 tile amber and explains why', async () => {
    renderApp('/');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    expect(tile('M12').dataset.state).toBe('stale');
    expect(within(tile('M12')).getByText('Obsolète')).toBeInTheDocument();
    expect(tile('M1').dataset.state).toBe('fixture');
  });

  it('hides small groups in the engagement heat-map', async () => {
    renderApp('/');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    expect(within(tile('M8')).getAllByText('Masqué').length).toBeGreaterThan(0);
  });

  it('reserves M21 to admins and shows no individual record to anyone', async () => {
    const { unmount } = renderApp('/', 'p-eva');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    expect(tile('M21').dataset.state).toBe('restricted');
    unmount();
    renderApp('/', 'p-gaelle');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    expect(tile('M21').dataset.state).toBe('unavailable');
    expect(document.body.textContent).not.toMatch(/@[a-z]+\.[a-z]{2,}/i);
  });

  it('gives limited roles only the limited indicator set', async () => {
    renderApp('/', 'p-anne');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    const ids = [...document.querySelectorAll('[data-metric]')].map((e) => e.getAttribute('data-metric'));
    expect(ids.sort()).toEqual(['M16', 'M5', 'M7', 'M8']);
    expect(screen.getByText(/Accès limité/)).toBeInTheDocument();
  });

  it('exposes the full catalog as a table with definitions', async () => {
    renderApp('/indicateurs');
    const rows = document.querySelectorAll('[data-metric-row]');
    expect(rows).toHaveLength(21);
    expect(screen.getByRole('table', { name: 'Indicateurs M1 à M21' })).toBeInTheDocument();
  });
});

describe('role-based visibility (demonstration only)', () => {
  const links = () => within(screen.getByRole('navigation', { name: 'Navigation principale' })).getAllByRole('link').map((a) => a.textContent ?? '');

  it('shows every section to the admin', async () => {
    renderApp('/');
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    expect(links()).toHaveLength(12);
  });

  it('hides content and dashboard from the support role and keeps its URL refused', async () => {
    renderApp('/', 'p-farid');
    expect(await screen.findByRole('heading', { name: 'Accès refusé (aperçu)' })).toBeInTheDocument();
    expect(links().join('|')).not.toMatch(/Contenu éducatif|Tableau de bord/);
    expect(screen.getByText(/le serveur répond 403/)).toBeInTheDocument();
  });

  it('keeps the analyst out of the content area', async () => {
    renderApp('/contenu', 'p-eva');
    expect(await screen.findByRole('heading', { name: 'Accès refusé (aperçu)' })).toBeInTheDocument();
  });

  it('switches the menu live when the previewed role changes', async () => {
    const user = userEvent.setup();
    renderApp('/roles');
    await screen.findByRole('heading', { name: 'Rôles et permissions' });
    await user.selectOptions(screen.getByRole('combobox', { name: /Aperçu de rôle/ }), 'p-farid');
    expect(links().join('|')).not.toMatch(/Contenu éducatif/);
    expect(screen.getByText(/sections masquées pour ce rôle/)).toBeInTheDocument();
  });
});

describe('role matrix viewer', () => {
  it('is read-only, labels proposed roles and states that hiding is not security', async () => {
    renderApp('/roles');
    expect(await screen.findByText(/Masquer un bouton n’est pas une sécurité/)).toBeInTheDocument();
    expect(screen.getByText(/L’autorisation réelle est faite par FastAPI/)).toBeInTheDocument();
    const matrix = screen.getByRole('table', { name: 'Capacités par rôle' });
    expect(within(matrix).getAllByText(/\(proposé\)/)).toHaveLength(2);
    expect(within(matrix).queryAllByRole('button')).toHaveLength(0);
    expect(document.querySelectorAll('[data-rule]')).toHaveLength(6);
  });
});

describe('placeholder modules', () => {
  it.each([
    ['/mot-du-jour', 'Mot du jour'], ['/examens-bibliotheque', 'Examens et bibliothèque'], ['/or-succes', 'Or et succès'],
    ['/classement', 'Politique du classement'], ['/jude-ia', 'Jude IA'], ['/notifications', 'Notifications'],
    ['/moderation', 'Modération communautaire'], ['/paiements', 'Paiements et droits d’accès'], ['/infrastructure-audit', 'Infrastructure et audit'],
  ])('%s is a truthful placeholder, not a fake screen', (path, title) => {
    renderApp(path);
    expect(screen.getByRole('heading', { level: 1, name: title })).toBeInTheDocument();
    expect(screen.getByText(/Livraison prévue/)).toBeInTheDocument();
    expect(document.querySelectorAll('form, input, textarea').length).toBe(1 /* role preview select is not an input */ - 1);
  });

  it('states Jude AI and moderation are unavailable and payments await the backend', () => {
    const { unmount } = renderApp('/jude-ia');
    expect(screen.getByText('Indisponible.')).toBeInTheDocument();
    unmount();
    renderApp('/paiements');
    expect(screen.getByText('Pas encore construit.')).toBeInTheDocument();
    expect(screen.getByText(/Aucune tuile de revenus tant que la réconciliation n’existe pas/)).toBeInTheDocument();
  });
});
