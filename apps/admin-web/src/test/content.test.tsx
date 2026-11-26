import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { renderApp } from './render';

describe('content catalogue', () => {
  it('filters by grade and subject and lists lessons with status badges', async () => {
    const user = userEvent.setup();
    renderApp('/contenu');
    const tree = await screen.findByRole('list', { name: 'Arborescence du catalogue' });
    expect(within(tree).getByText('Comparer des fractions')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'NS2' }));
    expect(within(tree).queryByText('Comparer des fractions')).toBeNull();
    expect(within(tree).getByText('Present perfect')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Toutes' }));
    await user.selectOptions(screen.getByLabelText('Matière'), 'Français');
    expect(within(tree).getByText('Le schéma narratif')).toBeInTheDocument();
    expect(within(tree).queryByText('Present perfect')).toBeNull();
  });

  it('shows revisions for the selected lesson and an empty state when there is none', async () => {
    const user = userEvent.setup();
    renderApp('/contenu', 'p-anne');
    await screen.findByRole('list', { name: 'Arborescence du catalogue' });
    expect(screen.getByRole('region', { name: 'Tableau : Révisions de Comparer des fractions' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Nombres relatifs/ }));
    expect(screen.getByText('Aucune révision pour cette leçon.')).toBeInTheDocument();
  });

  it('explains, in words, why an admin cannot create a draft', async () => {
    renderApp('/contenu', 'p-gaelle');
    await screen.findByRole('list', { name: 'Arborescence du catalogue' });
    expect(screen.getByRole('button', { name: 'Nouvelle révision (brouillon)' })).toBeDisabled();
    expect(screen.getByText('Réservé au rôle éditeur.')).toBeInTheDocument();
  });
});

describe('revision editor', () => {
  it('lets the author edit, flags markup inline by rule code, and previews it as literal text', async () => {
    const user = userEvent.setup();
    renderApp('/contenu/revision/rev-l-ax-b-1', 'p-anne');
    expect(await screen.findByRole('heading', { name: 'Résoudre ax + b = c · v1' })).toBeInTheDocument();
    const alerts = screen.getAllByRole('alert');
    expect(alerts.some((a) => a.textContent?.includes('markup'))).toBe(true);
    // The phone preview shows the tags literally: it never interprets markup.
    const phone = screen.getByRole('group', { name: /Aperçu téléphone 320 dp/ });
    expect(phone).toHaveTextContent('<b>Attention</b>');
    expect(phone.querySelector('b')).toBeNull();
    // Submit is blocked, with the reason in words.
    expect(screen.getByRole('button', { name: 'Soumettre à la relecture' })).toBeDisabled();
    // Editing clears the issue and enables saving.
    const text = screen.getByLabelText('Texte du bloc 2');
    await user.clear(text);
    await user.type(text, 'On isole x en deux temps.');
    expect(screen.queryAllByRole('alert').some((a) => a.textContent?.includes('markup'))).toBe(false);
    expect(screen.getByText('Modifications non enregistrées')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Enregistrer le brouillon (synthétique)' }));
    expect(screen.getByText('Enregistré')).toBeInTheDocument();
  });

  it('reorders and removes blocks with keyboard-operable buttons', async () => {
    const user = userEvent.setup();
    renderApp('/contenu/revision/rev-l-ax-b-1', 'p-anne');
    await screen.findByRole('heading', { name: 'Résoudre ax + b = c · v1' });
    await user.click(screen.getByRole('button', { name: 'Descendre le bloc 1' }));
    expect(screen.getByLabelText('Identifiant du bloc 1')).toHaveValue('methode');
    await user.click(screen.getByRole('button', { name: 'Supprimer le bloc 1' }));
    expect(screen.getByLabelText('Identifiant du bloc 1')).toHaveValue('titre');
    await user.selectOptions(screen.getByLabelText('Type du nouveau bloc'), 'callout');
    await user.click(screen.getByRole('button', { name: 'Ajouter un bloc' }));
    expect(screen.getByRole('region', { name: /Bloc 3, Encadré/ })).toBeInTheDocument();
  });

  it('is read-only for another editor, for the admin, and for a frozen revision', async () => {
    for (const persona of ['p-bruno', 'p-gaelle']) {
      const { unmount } = renderApp('/contenu/revision/rev-l-ax-b-1', persona);
      await screen.findByRole('heading', { name: 'Résoudre ax + b = c · v1' });
      expect(screen.getByText('Lecture seule.')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Enregistrer le brouillon (synthétique)' })).toBeNull();
      expect(screen.getByLabelText('Texte du bloc 2')).toBeDisabled();
      unmount();
    }
    renderApp('/contenu/revision/rev-l-comparer-2', 'p-anne');
    await screen.findByRole('heading', { name: 'Comparer des fractions · v2' });
    expect(screen.getAllByText(/Une révision soumise est figée/).length).toBeGreaterThan(0);
  });

  it('shows a block diff against the previous revision for the reviewer', async () => {
    renderApp('/contenu/revision/rev-l-comparer-2', 'p-chloe');
    expect(await screen.findByRole('heading', { name: 'Différences avec la v1' })).toBeInTheDocument();
    expect(screen.getAllByText('Ajouté').length).toBeGreaterThan(0);
  });

  it('displays the creole tab as an unreviewed draft', async () => {
    const user = userEvent.setup();
    renderApp('/contenu/revision/rev-l-comparer-1', 'p-chloe');
    await screen.findByRole('heading', { name: 'Comparer des fractions · v1' });
    await user.click(screen.getByRole('button', { name: 'Kreyòl' }));
    expect(screen.getByText(/brouillon synthétique, non relu/)).toBeInTheDocument();
    expect(screen.getByRole('group', { name: /Aperçu téléphone 320 dp, ht/ })).toHaveTextContent('Konpare fraksyon');
  });
});

describe('Editor → Reviewer → Publisher interaction (synthetic, in memory)', () => {
  it('runs a revision from review to publication with confirmations, reasons and synthetic receipts', async () => {
    const user = userEvent.setup();
    const { services, unmount } = renderApp('/contenu/revision/rev-l-comparer-2', 'p-chloe');
    await screen.findByRole('heading', { name: 'Comparer des fractions · v2' });

    // The author cannot review (explained), the reviewer can.
    await user.click(screen.getByRole('button', { name: 'Demander des changements' }));
    const dlg = screen.getByRole('dialog', { name: 'Demander des changements' });
    expect(within(dlg).getByRole('button', { name: 'Demander des changements' })).toBeDisabled(); // comment mandatory
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Approuver' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Approuver' }));
    expect(screen.getByText(/Reçu d’audit synthétique SYN-0001/)).toBeInTheDocument();
    expect(screen.getByText(/Aucune donnée n’a été écrite/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Fermer' }));
    expect(services.editorial.getSnapshot().revisions.find((r) => r.id === 'rev-l-comparer-2')!.status).toBe('approved');
    unmount();

    // Hélène (editor+publisher) cannot publish her own approved revision; David can publish Bruno's.
    const h = renderApp('/contenu/revision/rev-l-equivalentes-1', 'p-helene', services);
    await screen.findByRole('heading', { name: 'Fractions équivalentes · v1' });
    expect(screen.getByRole('button', { name: 'Publier' })).toBeDisabled();
    expect(screen.getByText(/l’auteur ne publie pas sa propre révision/)).toBeInTheDocument();
    h.unmount();

    renderApp('/contenu/revision/rev-l-comparer-2', 'p-david', services);
    await screen.findByRole('heading', { name: 'Comparer des fractions · v2' });
    await user.click(screen.getByRole('button', { name: 'Publier' }));
    const pub = screen.getByRole('dialog', { name: 'Publier la révision' });
    expect(within(pub).getByText(/Step-up MFA non implémenté/)).toBeInTheDocument();
    expect(within(pub).getByRole('button', { name: 'Publier (synthétique)' })).toBeDisabled(); // reason mandatory
    await user.type(within(pub).getByRole('textbox'), 'Nouvel exemple validé');
    await user.click(within(pub).getByRole('button', { name: 'Publier (synthétique)' }));
    expect(within(pub).getByText(/SYN-0002/)).toBeInTheDocument();
    const rev = services.editorial.getSnapshot().revisions;
    expect(rev.find((r) => r.id === 'rev-l-comparer-2')!.status).toBe('published');
    expect(rev.find((r) => r.id === 'rev-l-comparer-1')!.status).toBe('superseded');
  });

  it('returns keyboard focus to the opening button when a dialog is closed', async () => {
    const user = userEvent.setup();
    renderApp('/contenu/revision/rev-l-comparer-2', 'p-chloe');
    await screen.findByRole('heading', { name: 'Comparer des fractions · v2' });
    const opener = screen.getByRole('button', { name: 'Approuver' });
    opener.focus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(opener).toHaveFocus();
  });

  it('keeps focus inside an open dialog when tabbing', async () => {
    const user = userEvent.setup();
    renderApp('/contenu/revision/rev-l-comparer-2', 'p-chloe');
    await screen.findByRole('heading', { name: 'Comparer des fractions · v2' });
    await user.click(screen.getByRole('button', { name: 'Approuver' }));
    const dlg = screen.getByRole('dialog');
    for (let i = 0; i < 6; i++) { await user.tab(); expect(dlg.contains(document.activeElement), `tab ${i}`).toBe(true); }
  });

  it('feeds the dashboard pipeline tile from the same in-memory state', async () => {
    const { services, unmount } = renderApp('/contenu/revision/rev-l-comparer-2', 'p-chloe');
    await screen.findByRole('heading', { name: 'Comparer des fractions · v2' });
    services.editorial.dispatch({ type: 'review', revisionId: 'rev-l-comparer-2', decision: 'approve', comment: '' }, { id: 'p-chloe', name: 'Chloé (synthétique)', roles: ['reviewer'], hint: '' });
    unmount();
    renderApp('/', 'p-gaelle', services);
    await screen.findByRole('heading', { name: 'Tableau de bord' });
    expect(document.querySelector('[data-metric="M16"]')).toHaveTextContent(/Approuvée : 3/);
  });

  it('lists the review queue and the publication queue with per-persona explanations', async () => {
    const { unmount } = renderApp('/contenu/relecture', 'p-anne');
    await screen.findByRole('heading', { name: /En attente de relecture/ });
    expect(screen.getAllByText('Réservé au rôle relecteur.').length).toBeGreaterThan(0);
    unmount();
    renderApp('/contenu/publication', 'p-helene');
    await screen.findByRole('heading', { name: /Prêtes à publier/ });
    expect(screen.getByText(/Séparation des tâches \(à ajouter côté serveur\)/)).toBeInTheDocument();
    expect(screen.getByText(/Retrait \(takedown\) : pas de route serveur/)).toBeInTheDocument();
  });
});
