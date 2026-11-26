import { describe, expect, it } from 'vitest';
import { buildEditorialFixture } from '../data/editorialFixtures';
import { EditorialStore } from '../data/editorialStore';
import { personaById } from './roles';
import { findRevision, pipelineCounts, type Command } from './editorial';

const anne = personaById('p-anne');
const bruno = personaById('p-bruno');
const chloe = personaById('p-chloe');
const david = personaById('p-david');
const helene = personaById('p-helene');
const gaelle = personaById('p-gaelle');
const eva = personaById('p-eva');
const farid = personaById('p-farid');
const fixedClock = () => new Date('2026-11-26T14:00:00Z');
const store = () => new EditorialStore(fixedClock);

function run(s: EditorialStore, cmd: Command, who: typeof anne) {
  return s.dispatch(cmd, who);
}

describe('editorial workflow (demonstration rules)', () => {
  it('lets the reviewer approve a submitted revision written by someone else', () => {
    const s = store();
    const r = run(s, { type: 'review', revisionId: 'rev-l-comparer-2', decision: 'approve', comment: '' }, chloe);
    expect(r.ok).toBe(true);
    expect(findRevision(s.getSnapshot(), 'rev-l-comparer-2')!.status).toBe('approved');
  });

  it('requires a comment to request changes', () => {
    const s = store();
    const r = run(s, { type: 'review', revisionId: 'rev-l-comparer-2', decision: 'changes', comment: '   ' }, chloe);
    expect(r).toMatchObject({ ok: false, code: 'comment_required' });
    expect(findRevision(s.getSnapshot(), 'rev-l-comparer-2')!.status).toBe('in_review');
  });

  it('forbids reviewing your own revision even when you hold the reviewer role (separation of duties)', () => {
    const s = store();
    const dual = { ...chloe, id: 'p-anne', name: 'Anne bis', roles: ['editor', 'reviewer'] as ('editor' | 'reviewer')[] };
    expect(run(s, { type: 'review', revisionId: 'rev-l-comparer-2', decision: 'approve', comment: '' }, dual)).toMatchObject({ ok: false, code: 'own_revision' });
  });

  it('forbids non-reviewers from reviewing', () => {
    for (const who of [anne, david, gaelle, eva, farid]) {
      expect(run(store(), { type: 'review', revisionId: 'rev-l-comparer-2', decision: 'approve', comment: '' }, who)).toMatchObject({ ok: false, code: 'forbidden_role' });
    }
  });

  it('forbids an author-publisher from publishing their own revision, but not someone else’s', () => {
    const s = store();
    expect(run(s, { type: 'publish', revisionId: 'rev-l-equivalentes-1', reason: 'go' }, helene)).toMatchObject({ ok: false, code: 'own_revision' });
    expect(run(s, { type: 'publish', revisionId: 'rev-l-additionner-1', reason: 'go' }, helene).ok).toBe(true);
  });

  it('requires a reason to publish, and publishing supersedes the previously published revision', () => {
    const s = store();
    expect(run(s, { type: 'publish', revisionId: 'rev-l-additionner-1', reason: '' }, david)).toMatchObject({ ok: false, code: 'reason_required' });
    run(s, { type: 'review', revisionId: 'rev-l-comparer-2', decision: 'approve', comment: '' }, chloe);
    expect(run(s, { type: 'publish', revisionId: 'rev-l-comparer-2', reason: 'Nouvel exemple' }, david).ok).toBe(true);
    const st = s.getSnapshot();
    expect(findRevision(st, 'rev-l-comparer-2')!.status).toBe('published');
    expect(findRevision(st, 'rev-l-comparer-1')!.status).toBe('superseded');
    expect(st.revisions.filter((r) => r.lessonId === 'l-comparer' && r.status === 'published')).toHaveLength(1);
  });

  it('refuses to publish anything that is not approved', () => {
    for (const id of ['rev-l-comparer-2', 'rev-l-ax-b-1', 'rev-l-comparer-1']) {
      expect(run(store(), { type: 'publish', revisionId: id, reason: 'x' }, david)).toMatchObject({ ok: false, code: 'wrong_status' });
    }
  });

  it('keeps an admin out of other people’s drafts', () => {
    const r = run(store(), { type: 'update_blocks', revisionId: 'rev-l-ax-b-1', locale: 'fr', blocks: [{ key: 'a', type: 'heading', text: 'x' }] }, gaelle);
    expect(r).toMatchObject({ ok: false, code: 'forbidden_role' });
  });

  it('keeps one editor out of another editor’s draft', () => {
    const r = run(store(), { type: 'update_blocks', revisionId: 'rev-l-ax-b-1', locale: 'fr', blocks: [{ key: 'a', type: 'heading', text: 'x' }] }, bruno);
    expect(r).toMatchObject({ ok: false, code: 'not_author' });
  });

  it('freezes a submitted revision', () => {
    const r = run(store(), { type: 'update_blocks', revisionId: 'rev-l-comparer-2', locale: 'fr', blocks: [{ key: 'a', type: 'heading', text: 'x' }] }, anne);
    expect(r).toMatchObject({ ok: false, code: 'wrong_status' });
  });

  it('blocks submission while a source has unconfirmed rights or the text is invalid', () => {
    const s = store();
    expect(run(s, { type: 'submit', revisionId: 'rev-l-ax-b-1' }, anne)).toMatchObject({ ok: false, code: 'validation_failed' });
    // Fix the markup, but the source rights are still pending.
    run(s, { type: 'update_blocks', revisionId: 'rev-l-ax-b-1', locale: 'fr', blocks: [{ key: 'titre', type: 'heading', text: 'Résoudre ax + b = c' }] }, anne);
    expect(run(s, { type: 'submit', revisionId: 'rev-l-ax-b-1' }, anne)).toMatchObject({ ok: false, code: 'sources_incomplete' });
    const src = findRevision(s.getSnapshot(), 'rev-l-ax-b-1')!.sources[0]!;
    run(s, { type: 'set_rights', revisionId: 'rev-l-ax-b-1', sourceId: src.id, rights: 'cleared' }, anne);
    expect(run(s, { type: 'submit', revisionId: 'rev-l-ax-b-1' }, anne).ok).toBe(true);
    expect(findRevision(s.getSnapshot(), 'rev-l-ax-b-1')!.status).toBe('in_review');
  });

  it('cannot let the author approve a revision they authored, whatever its AI marker', () => {
    const r = run(store(), { type: 'review', revisionId: 'rev-l-operations-1', decision: 'approve', comment: '' }, bruno);
    expect(r.ok).toBe(false);
  });

  it('allows only publisher/admin to withdraw and roll back, with a mandatory reason', () => {
    const s = store();
    expect(run(s, { type: 'withdraw', revisionId: 'rev-l-comparer-1', reason: 'x' }, anne)).toMatchObject({ ok: false, code: 'forbidden_role' });
    expect(run(s, { type: 'withdraw', revisionId: 'rev-l-comparer-1', reason: '' }, gaelle)).toMatchObject({ ok: false, code: 'reason_required' });
    expect(run(s, { type: 'withdraw', revisionId: 'rev-l-comparer-1', reason: 'Droits retirés' }, gaelle).ok).toBe(true);
    expect(findRevision(s.getSnapshot(), 'rev-l-comparer-1')!.status).toBe('withdrawn');
    expect(run(s, { type: 'rollback', lessonId: 'l-etats', reason: 'Erreur dans la v2' }, david).ok).toBe(true);
    expect(findRevision(s.getSnapshot(), 'rev-l-etats-1')!.status).toBe('published');
    expect(findRevision(s.getSnapshot(), 'rev-l-etats-2')!.status).toBe('superseded');
  });

  it('creates a new draft from the published revision, only for editors, only if none is open', () => {
    const s = store();
    expect(run(s, { type: 'create_revision', lessonId: 'l-etats' }, david)).toMatchObject({ ok: false, code: 'forbidden_role' });
    expect(run(s, { type: 'create_revision', lessonId: 'l-comparer' }, anne)).toMatchObject({ ok: false, code: 'revision_open' });
    const r = run(s, { type: 'create_revision', lessonId: 'l-etats' }, anne);
    expect(r.ok && r.revisionId).toBe('rev-l-etats-3');
    expect(findRevision(s.getSnapshot(), 'rev-l-etats-3')!.status).toBe('draft');
  });

  it('writes a synthetic receipt for each success and none for a failure', () => {
    const s = store();
    run(s, { type: 'review', revisionId: 'rev-l-comparer-2', decision: 'changes', comment: '' }, chloe);
    expect(s.getSnapshot().receipts).toHaveLength(0);
    const ok = run(s, { type: 'review', revisionId: 'rev-l-comparer-2', decision: 'approve', comment: '' }, chloe);
    expect(ok.ok && ok.receipt.id).toBe('SYN-0001');
  });

  it('does not mutate previous snapshots and resets to the fixtures', () => {
    const s = store();
    const before = s.getSnapshot();
    run(s, { type: 'review', revisionId: 'rev-l-comparer-2', decision: 'approve', comment: '' }, chloe);
    expect(findRevision(before, 'rev-l-comparer-2')!.status).toBe('in_review');
    s.reset();
    expect(findRevision(s.getSnapshot(), 'rev-l-comparer-2')!.status).toBe('in_review');
    expect(s.getSnapshot().receipts).toEqual([]);
  });

  it('has fixtures covering every status', () => {
    const c = pipelineCounts(buildEditorialFixture());
    for (const [k, n] of Object.entries(c)) expect(n, k).toBeGreaterThan(0);
  });
});
