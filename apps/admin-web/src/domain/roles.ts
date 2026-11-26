/**
 * Roles and permissions — transcription of docs/architecture/admin-00/02-roles-and-permissions.md.
 *
 * IMPORTANT: this is DEMONSTRATION DATA. Real authorisation is enforced by FastAPI (and by the
 * `staff.*` SQL functions below it). Nothing in the browser is a security control.
 */

export type Role = 'editor' | 'reviewer' | 'publisher' | 'analyst' | 'support' | 'admin';

export const ROLES: readonly Role[] = ['editor', 'reviewer', 'publisher', 'analyst', 'support', 'admin'];

export interface RoleInfo {
  id: Role;
  label: string;
  /** `exists`: present in app.staff_roles today. `proposed`: needs owner approval + a reviewed migration. */
  state: 'exists' | 'proposed';
  purpose: string;
}

export const ROLE_INFO: Record<Role, RoleInfo> = {
  editor: { id: 'editor', label: 'Éditeur', state: 'exists', purpose: 'Crée et modifie ses propres brouillons, joint les sources, soumet.' },
  reviewer: { id: 'reviewer', label: 'Relecteur', state: 'exists', purpose: 'Relit les révisions soumises (jamais les siennes).' },
  publisher: { id: 'publisher', label: 'Publicateur', state: 'exists', purpose: 'Construit les paquets, publie, annule une publication.' },
  analyst: { id: 'analyst', label: 'Analyste', state: 'proposed', purpose: 'Lit uniquement les statistiques agrégées.' },
  support: { id: 'support', label: 'Support', state: 'proposed', purpose: 'Recherche minimale d’un apprenant, relance de notification, lecture des droits.' },
  admin: { id: 'admin', label: 'Administrateur', state: 'exists', purpose: 'Gère les rôles, les droits d’accès, le calendrier ; ne relit ni n’approuve les brouillons d’autrui.' },
};

export type Level = 'yes' | 'limited' | 'no';

export interface Capability {
  id: string;
  label: string;
  cells: Record<Role, Level>;
  /** Short qualifier per role, shown next to the symbol (never colour alone). */
  notes?: Partial<Record<Role, string>>;
  footnote?: 'admin-not-author';
}

const row = (
  id: string,
  label: string,
  [editor, reviewer, publisher, analyst, support, admin]: [Level, Level, Level, Level, Level, Level],
  notes?: Capability['notes'],
  footnote?: Capability['footnote'],
): Capability => ({ id, label, cells: { editor, reviewer, publisher, analyst, support, admin }, notes, footnote });

export const CAPABILITIES: readonly Capability[] = [
  row('draft.own', 'Créer / modifier son propre brouillon de révision', ['yes', 'no', 'no', 'no', 'no', 'no'], undefined, 'admin-not-author'),
  row('sources.manage', 'Joindre / détacher des sources, fiche de droits', ['yes', 'limited', 'no', 'no', 'no', 'no'], { editor: 'les siennes', reviewer: 'lecture' }, 'admin-not-author'),
  row('revision.submit', 'Soumettre une révision', ['yes', 'no', 'no', 'no', 'no', 'no'], { editor: 'la sienne' }, 'admin-not-author'),
  row('revision.review', 'Relire / approuver / demander des changements', ['no', 'yes', 'no', 'no', 'no', 'no'], { reviewer: 'pas la sienne' }),
  row('pack.release', 'Construire un paquet, publier, annuler, retirer', ['no', 'no', 'yes', 'no', 'no', 'yes']),
  row('wotd.draft', 'Mot du jour : rédiger / modifier', ['yes', 'no', 'no', 'no', 'no', 'no']),
  row('wotd.review', 'Mot du jour : relire / approuver', ['no', 'yes', 'no', 'no', 'no', 'no'], { reviewer: 'pas le sien' }),
  row('wotd.schedule', 'Mot du jour : planifier, retirer', ['no', 'no', 'yes', 'no', 'no', 'yes']),
  row('analytics.read', 'Statistiques agrégées', ['limited', 'limited', 'limited', 'yes', 'no', 'yes'], { editor: 'son contenu', reviewer: 'limité', publisher: 'limité' }),
  row('learner.lookup', 'Recherche d’un apprenant (vue minimale, motif obligatoire)', ['no', 'no', 'no', 'no', 'yes', 'yes']),
  row('learner.data', 'Voir réponses / texte de profil d’un apprenant', ['no', 'no', 'no', 'no', 'no', 'limited'], { admin: 'accès d’urgence : motif + second approbateur' }),
  row('entitlement.grant', 'Accorder / révoquer un droit d’accès', ['no', 'no', 'no', 'no', 'limited', 'yes'], { support: 'lecture' }),
  row('staff.roles', 'Accorder / révoquer des rôles du personnel', ['no', 'no', 'no', 'no', 'no', 'yes'], { admin: 'dernier admin protégé' }),
  row('audit.read', 'Journal d’audit (lecture)', ['limited', 'limited', 'limited', 'no', 'limited', 'yes'], { editor: 'ses actions', reviewer: 'ses actions', publisher: 'ses actions', support: 'ses actions', admin: 'tout' }),
  row('policy.write', 'Règles de récompense, politique de classement, drapeaux', ['no', 'no', 'no', 'no', 'no', 'yes'], { admin: 'avec step-up' }),
  row('jude.config', 'Configuration et budgets de Jude IA', ['no', 'no', 'no', 'no', 'no', 'yes']),
  row('notify.manage', 'Annonces / notifications', ['no', 'no', 'limited', 'no', 'limited', 'yes'], { publisher: 'brouillon' }),
];

export const ADMIN_NOT_AUTHOR_NOTE =
  'L’administrateur ne modifie ni n’approuve les brouillons d’autrui (règle vérifiée, audit M-B2-1). ' +
  'Un admin qui doit rédiger prend le rôle « éditeur » et est alors soumis à ses règles.';

export function capabilityById(id: string): Capability {
  const c = CAPABILITIES.find((x) => x.id === id);
  if (!c) throw new Error(`unknown capability ${id}`);
  return c;
}

/** Effective level of a person holding several roles: the strongest level of the union. */
export function levelFor(roles: readonly Role[], capabilityId: string): Level {
  const cap = capabilityById(capabilityId);
  let best: Level = 'no';
  for (const r of roles) {
    const l = cap.cells[r];
    if (l === 'yes') return 'yes';
    if (l === 'limited') best = 'limited';
  }
  return best;
}

export const can = (roles: readonly Role[], capabilityId: string): boolean => levelFor(roles, capabilityId) !== 'no';

// ---------------------------------------------------------------- sections / navigation

export type SectionId =
  | 'dashboard'
  | 'content'
  | 'roles'
  | 'wotd'
  | 'exams'
  | 'gold'
  | 'leaderboard'
  | 'jude'
  | 'notifications'
  | 'moderation'
  | 'payments'
  | 'infra';

export type SectionAccess = Partial<Record<Role, 'full' | 'limited'>>;

/**
 * Which sections each role is shown. DERIVED from the capability matrix (the matrix is per action,
 * not per screen). Where Admin-00 says nothing, access defaults to admin only (deny by default).
 */
export const SECTION_ACCESS: Record<SectionId, { access: SectionAccess; basis: string }> = {
  dashboard: {
    access: { editor: 'limited', reviewer: 'limited', publisher: 'limited', analyst: 'full', admin: 'full' },
    basis: 'Capacité « Statistiques agrégées ».',
  },
  content: {
    access: { editor: 'full', reviewer: 'full', publisher: 'full', admin: 'full' },
    basis: 'Brouillons, relecture, publication ; l’admin publie mais n’édite pas.',
  },
  roles: {
    access: { editor: 'full', reviewer: 'full', publisher: 'full', analyst: 'full', support: 'full', admin: 'full' },
    basis: 'Lecture seule de la documentation des rôles ; la gestion réelle des rôles reste réservée à l’admin (serveur).',
  },
  wotd: {
    access: { editor: 'full', reviewer: 'full', publisher: 'full', admin: 'full' },
    basis: 'Capacités « Mot du jour ».',
  },
  exams: { access: { admin: 'full' }, basis: 'Non spécifié dans Admin-00 : admin seul par défaut.' },
  gold: { access: { admin: 'full' }, basis: 'Règles de récompense : admin.' },
  leaderboard: { access: { admin: 'full' }, basis: 'Politique de classement : admin.' },
  jude: { access: { admin: 'full' }, basis: 'Configuration et budgets : admin.' },
  notifications: {
    access: { publisher: 'limited', support: 'limited', admin: 'full' },
    basis: 'Capacité « Annonces / notifications ».',
  },
  moderation: { access: { admin: 'full' }, basis: 'Non spécifié dans Admin-00 (Social-00) : admin seul par défaut.' },
  payments: {
    access: { support: 'limited', admin: 'full' },
    basis: 'Droits d’accès : support en lecture, admin complet.',
  },
  infra: {
    access: { editor: 'limited', reviewer: 'limited', publisher: 'limited', support: 'limited', admin: 'full' },
    basis: 'Audit : chacun ses actions ; admin tout.',
  },
};

export function sectionLevel(roles: readonly Role[], section: SectionId): 'full' | 'limited' | 'none' {
  const acc = SECTION_ACCESS[section].access;
  let best: 'full' | 'limited' | 'none' = 'none';
  for (const r of roles) {
    const l = acc[r];
    if (l === 'full') return 'full';
    if (l === 'limited') best = 'limited';
  }
  return best;
}

// ---------------------------------------------------------------- separation of duties

export interface SeparationRule {
  id: string;
  text: string;
  /** exists: already enforced server-side today · to-add: required, not built · open: known open finding */
  status: 'exists' | 'to-add' | 'open';
  statusNote: string;
  /** Rule demonstrated by the synthetic editorial workflow of this prototype. */
  demonstrated: boolean;
}

export const SEPARATION_RULES: readonly SeparationRule[] = [
  { id: 'sod-1', text: 'Le relecteur n’est jamais l’auteur de la révision.', status: 'exists', statusNote: 'Existe côté serveur.', demonstrated: true },
  { id: 'sod-2', text: 'Une révision soumise est figée ; toute modification crée une nouvelle révision.', status: 'exists', statusNote: 'Existe côté serveur.', demonstrated: true },
  { id: 'sod-3', text: 'L’auteur n’est jamais le publicateur de la même révision.', status: 'to-add', statusNote: 'À ajouter, ou à documenter comme choix du propriétaire pour une très petite équipe.', demonstrated: true },
  { id: 'sod-4', text: 'Le dernier administrateur utilisable ne peut pas être révoqué (y compris comptes bannis/supprimés).', status: 'open', statusNote: 'Constat ouvert S13.', demonstrated: false },
  { id: 'sod-5', text: 'Actions sensibles (publier, annuler, retirer, rôles, droits, drapeaux) : step-up MFA de moins de 5 minutes.', status: 'to-add', statusNote: 'Nécessite l’authentification du personnel (AD-2). Simulé ici par un avertissement, sans MFA.', demonstrated: false },
  { id: 'sod-6', text: 'Aucune action du personnel n’est faisable par les identités worker/service via le web.', status: 'to-add', statusNote: 'Logins de base de données distincts.', demonstrated: false },
];

// ---------------------------------------------------------------- synthetic personas (NOT accounts)

export interface Persona {
  id: string;
  name: string;
  roles: Role[];
  /** Why this persona exists in the demo. */
  hint: string;
}

/** Synthetic people for the role preview. They are not accounts and have no credentials. */
export const PERSONAS: readonly Persona[] = [
  { id: 'p-anne', name: 'Anne (synthétique)', roles: ['editor'], hint: 'Auteure de plusieurs brouillons.' },
  { id: 'p-bruno', name: 'Bruno (synthétique)', roles: ['editor'], hint: 'Autre éditeur : ne peut pas modifier les brouillons d’Anne.' },
  { id: 'p-chloe', name: 'Chloé (synthétique)', roles: ['reviewer'], hint: 'Relit les révisions soumises par d’autres.' },
  { id: 'p-david', name: 'David (synthétique)', roles: ['publisher'], hint: 'Publie, annule, retire.' },
  { id: 'p-helene', name: 'Hélène (synthétique)', roles: ['editor', 'publisher'], hint: 'Deux rôles : peut rédiger et publier, mais jamais la même révision.' },
  { id: 'p-eva', name: 'Eva (synthétique)', roles: ['analyst'], hint: 'Rôle proposé : statistiques seulement.' },
  { id: 'p-farid', name: 'Farid (synthétique)', roles: ['support'], hint: 'Rôle proposé : recherche minimale seulement.' },
  { id: 'p-gaelle', name: 'Gaëlle (synthétique)', roles: ['admin'], hint: 'Administratrice : publie mais n’édite pas les brouillons d’autrui.' },
];

export const DEFAULT_PERSONA_ID = 'p-gaelle';

export const personaById = (id: string): Persona => PERSONAS.find((p) => p.id === id) ?? PERSONAS.find((p) => p.id === DEFAULT_PERSONA_ID)!;
