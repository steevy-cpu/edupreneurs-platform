import type { SectionId } from './roles';

/** Navigation and honest status of every admin area. Statuses are about THIS prototype, never about the product. */
export type ModuleState =
  | 'fixture' // working screen over synthetic fixtures
  | 'partial' // some of the screen is a fixture preview, the rest is a placeholder
  | 'awaiting-backend' // nothing to show: waiting for a backend milestone
  | 'unavailable'; // no source exists at all

export const MODULE_STATE_LABEL: Record<ModuleState, string> = {
  fixture: 'Aperçu synthétique',
  partial: 'Partiel : aperçu synthétique',
  'awaiting-backend': 'En attente du backend',
  unavailable: 'Indisponible',
};

export interface ModuleMeta {
  id: SectionId;
  label: string;
  path: string;
  state: ModuleState;
  /** Admin-00 milestone that delivers the real thing. */
  milestone: string;
  summary: string;
}

export const MODULES: readonly ModuleMeta[] = [
  { id: 'dashboard', label: 'Tableau de bord', path: '/', state: 'fixture', milestone: 'AD-4', summary: 'Les 21 indicateurs du catalogue, avec définition, période et fraîcheur.' },
  { id: 'content', label: 'Contenu éducatif', path: '/contenu', state: 'fixture', milestone: 'AD-3', summary: 'Catalogue, éditeur de révisions, file de relecture, publication.' },
  { id: 'wotd', label: 'Mot du jour', path: '/mot-du-jour', state: 'partial', milestone: 'AD-6', summary: 'Couverture du calendrier (aperçu) ; édition et planification à venir.' },
  { id: 'exams', label: 'Examens et bibliothèque', path: '/examens-bibliotheque', state: 'awaiting-backend', milestone: 'AD-7', summary: 'Ressources, droits, classe pratique ou contrôlée.' },
  { id: 'gold', label: 'Or et succès', path: '/or-succes', state: 'awaiting-backend', milestone: 'AD-6', summary: 'Règles de récompense, succès, politique de séries.' },
  { id: 'leaderboard', label: 'Politique du classement', path: '/classement', state: 'awaiting-backend', milestone: 'AD-6', summary: 'Seuil K, calendrier de rafraîchissement, éligibilité.' },
  { id: 'jude', label: 'Jude IA', path: '/jude-ia', state: 'unavailable', milestone: 'AD-9', summary: 'Configuration, usage, coûts et budgets : module inexistant.' },
  { id: 'notifications', label: 'Notifications', path: '/notifications', state: 'awaiting-backend', milestone: 'AD-5', summary: 'Annonces et campagnes (adaptateur factice aujourd’hui).' },
  { id: 'moderation', label: 'Modération communautaire', path: '/moderation', state: 'unavailable', milestone: 'Social-00', summary: 'File de signalements : la communauté n’existe pas encore.' },
  { id: 'payments', label: 'Paiements et droits d’accès', path: '/paiements', state: 'awaiting-backend', milestone: 'AD-8', summary: 'Droits d’accès, commandes, réconciliation.' },
  { id: 'infra', label: 'Infrastructure et audit', path: '/infrastructure-audit', state: 'awaiting-backend', milestone: 'AD-5', summary: 'Journal d’audit, états de disponibilité, drapeaux.' },
  { id: 'roles', label: 'Rôles et permissions', path: '/roles', state: 'fixture', milestone: 'AD-0 (lecture seule)', summary: 'Matrice des rôles et séparation des tâches, en lecture seule.' },
];

export const MODULE_BY_ID = Object.fromEntries(MODULES.map((m) => [m.id, m])) as Record<SectionId, ModuleMeta>;

export interface PlaceholderSpec {
  /** What the finished area will do, from Admin-00 doc 1. */
  planned: string[];
  /** Backend work still required (doc 4). */
  backend: string[];
  /** Decisions only the owner can take. */
  decisions: string[];
}

export const PLACEHOLDERS: Partial<Record<SectionId, PlaceholderSpec>> = {
  wotd: {
    planned: ['Liste de mots fr/ht et éditeur de révision (mot, définition, exemples, prononciation, audio avec transcription)', 'File de relecture (relecteur ≠ auteur, règle existante)', 'Calendrier en date d’Haïti : un jour publié est immuable (règle de base de données existante)', 'Action « garantir le calendrier » ; retrait d’un mot'],
    backend: ['Routes /words, /calendar, /schedule existent mais ne sont pas derrière le drapeau daily_word_enabled', 'Flux de téléversement audio absent'],
    decisions: ['Activation de la fonctionnalité Mot du jour côté élèves'],
  },
  exams: {
    planned: ['Liste par type : examen d’entraînement, examen contrôlé, livre numérique, PDF, ressource', 'Champ « classe » explicite (entraînement ou contrôlé) qui pilote la livraison (ADR-8)', 'Fiche livre : fichier, empreinte, taille, licence, territoire, validité, règle d’accès, couvertures', 'Retrait / remplacement avec audit'],
    backend: ['Modèle de ressource (kind, class), registre des droits, téléversement avec empreinte, URL signées, éditeur de règles d’accès (Content-Delivery-00, doc 4)'],
    decisions: ['Quels examens sont d’entraînement et lesquels sont contrôlés (ADR-8)', 'Attente de DRM pour un livre sous licence'],
  },
  gold: {
    planned: ['Versions de règles de récompense (montants comme données, date d’activation)', 'Définitions de succès', 'Vue en lecture seule de la règle de série à minuit d’Haïti', 'Signaux de fraude (accès admin seul)'],
    backend: ['Routes de versionnement des règles, des succès et requêtes de fraude'],
    decisions: ['PO-09 et 2-C1…2-C4 : l’activation de toute règle est conditionnée'],
  },
  leaderboard: {
    planned: ['Seuil minimal de groupe K', 'Calendrier de rafraîchissement', 'Critères d’éligibilité'],
    backend: ['Routes de politique de classement (plan 1-2, 2-C2)'],
    decisions: ['Valeur de K', 'Activation du classement : non autorisée dans ce jalon, le code client reste désactivé'],
  },
  jude: {
    planned: ['Configuration modèle/fournisseur et drapeaux par fonction', 'Jetons et coût par jour et par fonction', 'Budgets avec arrêt automatique, taux d’erreur, santé du fournisseur'],
    backend: ['Module entier : magasin de configuration, journal d’usage, budgets, santé du fournisseur. Aucune clé de fournisseur ne doit jamais atteindre le navigateur.'],
    decisions: ['Fournisseur, budgets et plafonds'],
  },
  notifications: {
    planned: ['Annonces', 'Campagnes via la boîte d’envoi', 'Relance d’une notification (support)'],
    backend: ['Console de notifications ; un vrai adaptateur d’envoi (l’adaptateur actuel est factice)'],
    decisions: ['Canaux et règles de consentement pour des mineurs'],
  },
  moderation: {
    planned: ['File de signalements', 'Décisions de modération avec motif et audit'],
    backend: ['La communauté (Social-00) n’existe pas : aucune donnée à modérer'],
    decisions: ['Existence et périmètre de la fonctionnalité sociale'],
  },
  payments: {
    planned: ['Plans et prix', 'Droits d’accès, octrois et révocations', 'Commandes, remboursements, MonCash et autres fournisseurs', 'Réconciliation fournisseur ↔ registre', 'Codes promo et cadeaux'],
    backend: ['Les routes /grants existent (fournisseur factice). Reste : administration des plans, événements fournisseur, commandes/remboursements, adaptateur MonCash, tâche de réconciliation'],
    decisions: ['Seuil d’approbation à deux personnes pour les opérations d’argent', 'Aucune tuile de revenus tant que la réconciliation n’existe pas'],
  },
  infra: {
    planned: ['Journal d’audit (filtre acteur, action, cible, date ; export)', 'Recherche d’un apprenant par le support (vue minimale, motif, audité)', 'Gestion des rôles du personnel (dernier admin protégé)', 'Restauration, contrôles de disponibilité, état des drapeaux'],
    backend: ['API de lecture du journal d’audit', 'Correctif S13 (dernier admin)', 'Script de disponibilité X-1', 'Cycle de vie des comptes bloqué par S3'],
    decisions: ['Durée de conservation du journal d’audit'],
  },
};
