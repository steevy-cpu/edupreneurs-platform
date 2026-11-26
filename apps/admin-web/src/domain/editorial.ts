import type { Block } from './blocks';
import { validateBlocks } from './blocks';
import { can, type Persona } from './roles';

/**
 * Editorial workflow — DEMONSTRATION state machine over synthetic data.
 * The rules mirror Admin-00 doc 2 so reviewers can see their shape; the REAL rules are enforced by
 * FastAPI and SQL. Nothing here persists, calls a network or reaches a database.
 */

export type Locale = 'fr' | 'ht';
export type RevStatus = 'draft' | 'in_review' | 'changes_requested' | 'approved' | 'published' | 'withdrawn' | 'superseded';
export type RightsStatus = 'cleared' | 'pending' | 'unknown' | 'restricted';

export interface SourceRef {
  id: string;
  title: string;
  kind: 'original' | 'curriculum' | 'textbook' | 'web';
  licence: string;
  rights: RightsStatus;
}

export interface ReviewEntry { reviewerId: string; reviewerName: string; decision: 'approve' | 'changes'; comment: string; at: string }
export interface HistoryEntry { at: string; actor: string; action: string; reason?: string }

export interface Revision {
  id: string;
  lessonId: string;
  number: number;
  status: RevStatus;
  authorId: string;
  authorName: string;
  aiAssisted: boolean;
  blocks: Partial<Record<Locale, Block[]>>;
  sources: SourceRef[];
  reviews: ReviewEntry[];
  history: HistoryEntry[];
}

export interface Lesson { id: string; title: string }
export interface Unit { id: string; title: string; lessons: Lesson[] }
export interface Course { id: string; grade: string; subject: string; title: string; units: Unit[] }

export interface Receipt {
  /** Synthetic audit receipt: nothing was written anywhere. */
  id: string;
  action: string;
  target: string;
  actorId: string;
  actor: string;
  at: string;
  reason?: string;
}

export interface EditorialState {
  courses: Course[];
  revisions: Revision[];
  receipts: Receipt[];
}

export type Command =
  | { type: 'create_revision'; lessonId: string }
  | { type: 'update_blocks'; revisionId: string; locale: Locale; blocks: Block[] }
  | { type: 'add_source'; revisionId: string; source: Omit<SourceRef, 'id'> }
  | { type: 'set_rights'; revisionId: string; sourceId: string; rights: RightsStatus }
  | { type: 'remove_source'; revisionId: string; sourceId: string }
  | { type: 'submit'; revisionId: string }
  | { type: 'review'; revisionId: string; decision: 'approve' | 'changes'; comment: string }
  | { type: 'publish'; revisionId: string; reason: string }
  | { type: 'rollback'; lessonId: string; reason: string }
  | { type: 'withdraw'; revisionId: string; reason: string };

export type Failure =
  | 'not_found' | 'forbidden_role' | 'not_author' | 'own_revision' | 'wrong_status' | 'validation_failed'
  | 'sources_incomplete' | 'comment_required' | 'reason_required' | 'revision_open' | 'nothing_to_rollback';

export type Result = { ok: true; receipt: Receipt; revisionId?: string } | { ok: false; code: Failure; message: string };

const fail = (code: Failure, message: string): Result => ({ ok: false, code, message });

export const STATUS_LABEL: Record<RevStatus, string> = {
  draft: 'Brouillon',
  in_review: 'En relecture',
  changes_requested: 'Changements demandés',
  approved: 'Approuvée',
  published: 'Publiée',
  withdrawn: 'Retirée',
  superseded: 'Remplacée',
};

export const RIGHTS_LABEL: Record<RightsStatus, string> = {
  cleared: 'Droits confirmés',
  pending: 'Droits en attente',
  unknown: 'Droits inconnus',
  restricted: 'Droits restreints',
};

export const findRevision = (s: EditorialState, id: string) => s.revisions.find((r) => r.id === id);
export const revisionsOfLesson = (s: EditorialState, lessonId: string) =>
  s.revisions.filter((r) => r.lessonId === lessonId).sort((a, b) => b.number - a.number);
export const lessonTitle = (s: EditorialState, lessonId: string): string => {
  for (const c of s.courses) for (const u of c.units) for (const l of u.lessons) if (l.id === lessonId) return l.title;
  return lessonId;
};

/** The "headline" revision of a lesson for list views: published, else the newest. */
export function headlineRevision(s: EditorialState, lessonId: string): Revision | undefined {
  const all = revisionsOfLesson(s, lessonId);
  return all.find((r) => r.status === 'published') ?? all[0];
}

export function sourcesReady(r: Revision): boolean {
  return r.sources.length > 0 && r.sources.every((x) => x.rights === 'cleared');
}

export function pipelineCounts(s: EditorialState): Record<RevStatus, number> {
  const c: Record<RevStatus, number> = { draft: 0, in_review: 0, changes_requested: 0, approved: 0, published: 0, withdrawn: 0, superseded: 0 };
  for (const r of s.revisions) c[r.status] += 1;
  return c;
}

/**
 * Why a given persona can or cannot perform an action on a revision — used both to enforce the demo
 * rules and to explain disabled buttons in words (never only grey them out).
 */
export interface Affordance { allowed: boolean; reason?: string }
const yes: Affordance = { allowed: true };
const no = (reason: string): Affordance => ({ allowed: false, reason });

export function canEditDraft(p: Persona, r: Revision): Affordance {
  if (!p.roles.includes('editor')) return no('Réservé au rôle éditeur. L’administrateur ne modifie pas les brouillons.');
  if (r.status !== 'draft') return no('Une révision soumise est figée : créer une nouvelle révision.');
  if (r.authorId !== p.id) return no('Seul l’auteur modifie son brouillon.');
  return yes;
}
function translationError(r: Revision): string | undefined {
  if (validateBlocks(r.blocks.fr).length) return 'Le texte français contient des erreurs de validation.';
  if (r.blocks.ht !== undefined && validateBlocks(r.blocks.ht).length) return 'Le texte créole contient des erreurs de validation.';
}

export function rollbackTarget(s: EditorialState, current: Revision) {
  if (current.status !== 'published') return undefined;
  return revisionsOfLesson(s, current.lessonId).find(r => r.status === 'superseded' && r.number < current.number);
}

export function canSubmit(p: Persona, r: Revision): Affordance {
  const base = canEditDraft(p, r);
  if (!base.allowed) return base;
  const error = translationError(r);
  if (error) return no(error);
  if (!sourcesReady(r)) return no('Sources et droits confirmés requis avant soumission.');
  return yes;
}
export function canReview(p: Persona, r: Revision): Affordance {
  if (!p.roles.includes('reviewer')) return no('Réservé au rôle relecteur.');
  if (r.status !== 'in_review') return no('Seule une révision en relecture peut être relue.');
  if (r.authorId === p.id) return no('Séparation des tâches : on ne relit pas sa propre révision.');
  return yes;
}
export function canPublish(p: Persona, r: Revision): Affordance {
  if (!can(p.roles, 'pack.release') || !(p.roles.includes('publisher') || p.roles.includes('admin'))) return no('Réservé aux rôles publicateur et administrateur.');
  if (r.status !== 'approved') return no('Seule une révision approuvée peut être publiée.');
  if (r.authorId === p.id) return no('Séparation des tâches (à ajouter côté serveur) : l’auteur ne publie pas sa propre révision.');
  return yes;
}
export function canWithdraw(p: Persona, r: Revision): Affordance {
  if (!(p.roles.includes('publisher') || p.roles.includes('admin'))) return no('Réservé aux rôles publicateur et administrateur.');
  if (r.status !== 'published') return no('Seule une révision publiée peut être retirée.');
  return yes;
}
export function canCreateRevision(p: Persona, s: EditorialState, lessonId: string): Affordance {
  if (!p.roles.includes('editor')) return no('Réservé au rôle éditeur.');
  if (s.revisions.some((r) => r.lessonId === lessonId && (r.status === 'draft' || r.status === 'in_review')))
    return no('Une révision est déjà ouverte pour cette leçon.');
  return yes;
}

function receipt(s: EditorialState, action: string, target: string, actor: Persona, now: Date, reason?: string): Receipt {
  return { id: `SYN-${String(s.receipts.length + 1).padStart(4, '0')}`, action, target, actorId: actor.id, actor: actor.name, at: now.toISOString(), reason };
}

/** Pure reducer: returns the next state and the result. The input state is never mutated. */
export function apply(state: EditorialState, cmd: Command, actor: Persona, now: Date): { state: EditorialState; result: Result } {
  const update = (id: string, f: (r: Revision) => Revision): Revision[] => state.revisions.map((r) => (r.id === id ? f(r) : r));
  const ok = (rev: Revision[], rc: Receipt, revisionId?: string) => ({
    state: { ...state, revisions: rev, receipts: [...state.receipts, rc] },
    result: { ok: true, receipt: rc, revisionId } as Result,
  });
  const bad = (code: Failure, message: string) => ({ state, result: fail(code, message) });
  const hist = (r: Revision, action: string, reason?: string): Revision => ({ ...r, history: [...r.history, { at: now.toISOString(), actor: actor.name, action, reason }] });

  if (cmd.type === 'create_revision') {
    if (!state.courses.some(c => c.units.some(u => u.lessons.some(l => l.id === cmd.lessonId)))) return bad('not_found', 'Leçon introuvable.');
    const aff = canCreateRevision(actor, state, cmd.lessonId);
    if (!aff.allowed) return bad(actor.roles.includes('editor') ? 'revision_open' : 'forbidden_role', aff.reason!);
    const prev = revisionsOfLesson(state, cmd.lessonId);
    const base = prev[0]?.status === 'changes_requested' ? prev[0] : headlineRevision(state, cmd.lessonId);
    const rev: Revision = {
      id: `rev-${cmd.lessonId}-${(prev[0]?.number ?? 0) + 1}`,
      lessonId: cmd.lessonId,
      number: (prev[0]?.number ?? 0) + 1,
      status: 'draft',
      authorId: actor.id,
      authorName: actor.name,
      aiAssisted: false,
      blocks: base ? structuredClone(base.blocks) : { fr: [{ key: 'titre', type: 'heading', text: 'Nouvelle leçon' }] },
      sources: base ? structuredClone(base.sources) : [],
      reviews: [],
      history: [{ at: now.toISOString(), actor: actor.name, action: 'Révision créée' }],
    };
    const rc = receipt(state, 'create_revision', rev.id, actor, now);
    return { state: { ...state, revisions: [...state.revisions, rev], receipts: [...state.receipts, rc] }, result: { ok: true, receipt: rc, revisionId: rev.id } };
  }

  if (cmd.type === 'rollback') {
    if (!(actor.roles.includes('publisher') || actor.roles.includes('admin'))) return bad('forbidden_role', 'Réservé aux rôles publicateur et administrateur.');
    if (!cmd.reason.trim()) return bad('reason_required', 'Un motif est obligatoire.');
    const all = revisionsOfLesson(state, cmd.lessonId);
    const current = all.find((r) => r.status === 'published');
    const target = current && rollbackTarget(state, current);
    if (!current || !target) return bad('nothing_to_rollback', 'Aucune version antérieure à rétablir.');
    if (target.authorId === actor.id) return bad('own_revision', 'L’auteur ne peut pas republier sa propre révision.');
    const rev = state.revisions.map((r) =>
      r.id === current.id ? hist({ ...r, status: 'superseded' }, 'Annulée (retour arrière)', cmd.reason)
        : r.id === target.id ? hist({ ...r, status: 'published' }, 'Rétablie (retour arrière)', cmd.reason) : r);
    return ok(rev, receipt(state, 'rollback', `${current.id} → ${target.id}`, actor, now, cmd.reason), target.id);
  }

  const r = findRevision(state, cmd.revisionId);
  if (!r) return bad('not_found', 'Révision introuvable.');

  switch (cmd.type) {
    case 'update_blocks': {
      const a = canEditDraft(actor, r);
      if (!a.allowed) return bad(!actor.roles.includes('editor') ? 'forbidden_role' : r.status !== 'draft' ? 'wrong_status' : 'not_author', a.reason!);
      return ok(update(r.id, (x) => ({ ...x, blocks: { ...x.blocks, [cmd.locale]: cmd.blocks } })), receipt(state, 'update_blocks', `${r.id}/${cmd.locale}`, actor, now), r.id);
    }
    case 'add_source':
    case 'set_rights':
    case 'remove_source': {
      const a = canEditDraft(actor, r);
      if (!a.allowed) return bad(!actor.roles.includes('editor') ? 'forbidden_role' : r.status !== 'draft' ? 'wrong_status' : 'not_author', a.reason!);
      if (cmd.type !== 'add_source' && !r.sources.some(s => s.id === cmd.sourceId)) return bad('not_found', 'Source introuvable.');
      let next = r.sources.length + 1;
      while (r.sources.some(s => s.id === `src-${next}-${r.id}`)) next++;
      const f = (x: Revision): Revision =>
        cmd.type === 'add_source' ? { ...x, sources: [...x.sources, { ...cmd.source, id: `src-${next}-${x.id}` }] }
          : cmd.type === 'set_rights' ? { ...x, sources: x.sources.map((s) => (s.id === cmd.sourceId ? { ...s, rights: cmd.rights } : s)) }
            : { ...x, sources: x.sources.filter((s) => s.id !== cmd.sourceId) };
      return ok(update(r.id, f), receipt(state, cmd.type, r.id, actor, now), r.id);
    }
    case 'submit': {
      const a = canSubmit(actor, r);
      if (!a.allowed) {
        const code: Failure = !actor.roles.includes('editor') ? 'forbidden_role' : r.status !== 'draft' ? 'wrong_status' : r.authorId !== actor.id ? 'not_author' : translationError(r) ? 'validation_failed' : 'sources_incomplete';
        return bad(code, a.reason!);
      }
      return ok(update(r.id, (x) => hist({ ...x, status: 'in_review' }, 'Soumise à la relecture')), receipt(state, 'submit', r.id, actor, now), r.id);
    }
    case 'review': {
      const a = canReview(actor, r);
      if (!a.allowed) return bad(!actor.roles.includes('reviewer') ? 'forbidden_role' : r.authorId === actor.id ? 'own_revision' : 'wrong_status', a.reason!);
      if (cmd.decision === 'changes' && !cmd.comment.trim()) return bad('comment_required', 'Un commentaire est obligatoire pour demander des changements.');
      const entry: ReviewEntry = { reviewerId: actor.id, reviewerName: actor.name, decision: cmd.decision, comment: cmd.comment.trim(), at: now.toISOString() };
      return ok(update(r.id, (x) => hist({ ...x, status: cmd.decision === 'approve' ? 'approved' : 'changes_requested', reviews: [...x.reviews, entry] }, cmd.decision === 'approve' ? 'Approuvée' : 'Changements demandés', cmd.comment.trim() || undefined)), receipt(state, `review:${cmd.decision}`, r.id, actor, now, cmd.comment.trim() || undefined), r.id);
    }
    case 'publish': {
      const a = canPublish(actor, r);
      if (!a.allowed) return bad(!(actor.roles.includes('publisher') || actor.roles.includes('admin')) ? 'forbidden_role' : r.status !== 'approved' ? 'wrong_status' : 'own_revision', a.reason!);
      if (!cmd.reason.trim()) return bad('reason_required', 'Un motif est obligatoire.');
      const rev = state.revisions.map((x) =>
        x.id === r.id ? hist({ ...x, status: 'published' }, 'Publiée (synthétique)', cmd.reason)
          : x.lessonId === r.lessonId && x.status === 'published' ? hist({ ...x, status: 'superseded' }, 'Remplacée par une nouvelle publication') : x);
      return ok(rev, receipt(state, 'publish', r.id, actor, now, cmd.reason), r.id);
    }
    case 'withdraw': {
      const a = canWithdraw(actor, r);
      if (!a.allowed) return bad(!(actor.roles.includes('publisher') || actor.roles.includes('admin')) ? 'forbidden_role' : 'wrong_status', a.reason!);
      if (!cmd.reason.trim()) return bad('reason_required', 'Un motif est obligatoire.');
      return ok(update(r.id, (x) => hist({ ...x, status: 'withdrawn' }, 'Retirée (synthétique)', cmd.reason)), receipt(state, 'withdraw', r.id, actor, now, cmd.reason), r.id);
    }
  }
}
