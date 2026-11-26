import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { Heatmap } from '../components/Heatmap';
import { buildDashboardFixture } from '../data/dashboardFixtures';
import { buildEditorialFixture } from '../data/editorialFixtures';
import { apply, type Command } from '../domain/editorial';
import { personaById } from '../domain/roles';
import { createMockServices } from '../state/Services';
import { renderApp } from './render';

const anne = personaById('p-anne');
const david = personaById('p-david');
const clock = new Date('2026-11-26T14:00:00Z');
const rollback: Command = { type: 'rollback', lessonId: 'l-etats', reason: 'Révision du texte' };

it('keeps a supplied invalid translation in draft, while allowing an absent translation', () => {
  const s = buildEditorialFixture();
  const r = s.revisions.find(r => r.id === 'rev-l-comparer-2')!;
  r.status = 'draft';
  const submit: Command = { type: 'submit', revisionId: r.id };
  const submitted = apply(s, { ...submit, note: 'Vérifier le titre.' }, anne, clock);
  expect(submitted.result).toMatchObject({ ok: true, receipt: { reason: 'Vérifier le titre.' } });
  expect(submitted.state.revisions.find(v => v.id === r.id)?.history.at(-1)?.reason).toBe('Vérifier le titre.');
  r.blocks.ht = [];
  expect(apply(s, submit, anne, clock).result).toMatchObject({ok:false, code:'validation_failed'});
});
it('does not roll forward into a superseded higher revision', () => {
  const first = apply(buildEditorialFixture(), rollback, david, clock);
  expect(first.result.ok).toBe(true);
  expect(apply(first.state, rollback, david, clock).result).toMatchObject({ok:false,code:'nothing_to_rollback'});
});
it('checks authorship of the revision being republished by rollback', () => {
  expect(apply(buildEditorialFixture(), rollback, {...david,id:anne.id}, clock).result).toMatchObject({ok:false,code:'own_revision'});
});
it('retains the returned text when starting the next revision', () => {
  const s = buildEditorialFixture();
  const returned = s.revisions.find(r => r.id === 'rev-l-comparer-2')!;
  returned.status = 'changes_requested';
  const next = apply(s,{type:'create_revision',lessonId:returned.lessonId},anne,clock);
  expect(next.state.revisions.at(-1)?.blocks).toEqual(returned.blocks);
});
it('limits an editor to their own audit receipts', () => {
  const services = createMockServices();
  services.editorial.dispatch(rollback,david);
  renderApp('/contenu/publication', anne.id,services);
  expect(screen.queryByText('SYN-0001')).not.toBeInTheDocument();
});
it('does not show platform aggregates as an editor’s own analytics', async () => {
  const { container } = renderApp('/',anne.id);
  await screen.findByText('Rien ici n’est réel.');
  expect(container.querySelector('[data-metric="M5"] .tile-value:not(.dash)')).toBeNull();
});
it('distinguishes an absent cell and an unknown answer count from suppression and zero', () => {
  render(<Heatmap grades={['NS1']} subjects={['Français','Créole']} k={5}
    cells={[{grade:'NS1',subject:'Créole',learners:7,answers:null}]} />);
  expect(screen.getByText('Donnée indisponible')).toBeInTheDocument();
  expect(screen.getByText('Réponses inconnues')).toBeInTheDocument();
});
it('reports the same current daily population in the chart and its headline', () => {
  const {m3} = buildDashboardFixture();
  expect(m3.daily).toBe(m3.dailySeries.at(-1)?.count);
});

it('rejects a missing lesson or source without generating an audit receipt', () => {
  const state = buildEditorialFixture();
  const commands: Command[] = [
    { type: 'create_revision', lessonId: 'missing' },
    { type: 'set_rights', revisionId: 'rev-l-ax-b-1', sourceId: 'missing', rights: 'cleared' },
  ];
  for (const command of commands) {
    const next = apply(state, command, anne, clock);
    expect(next.state).toBe(state);
    expect(next.result).toMatchObject({ ok: false, code: 'not_found' });
  }
});
it('keeps rights records distinct after removing and re-adding a source', () => {
  let state = buildEditorialFixture();
  const revisionId = 'rev-l-ax-b-1';
  const sources = () => state.revisions.find(r => r.id === revisionId)!.sources;
  const add: Command = { type: 'add_source', revisionId, source: { ...sources()[0]!, title: 'Autre source' } };
  state = apply(state, add, anne, clock).state;
  state = apply(state, { type: 'remove_source', revisionId, sourceId: sources()[0]!.id }, anne, clock).state;
  state = apply(state, add, anne, clock).state;
  expect(new Set(sources().map(s => s.id)).size).toBe(sources().length);
});

it('saves only a changed language and resets the visible draft buffer', async () => {
  const user = userEvent.setup();
  renderApp('/contenu/revision/rev-l-ax-b-1', anne.id);
  const first = () => screen.getByRole('textbox', { name: 'Texte du bloc 1' });
  const original = (first() as HTMLInputElement).value;
  await user.clear(first());
  await user.type(first(), 'Nouveau titre');
  await user.click(screen.getByRole('button', { name: 'Kreyòl' }));
  expect(screen.getByRole('button', { name: /Enregistrer le brouillon/ })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Français' }));
  expect(first()).toHaveValue('Nouveau titre');
  await user.click(screen.getByRole('button', { name: /Réinitialiser les données/ }));
  expect(first()).toHaveValue(original);
});
