/**
 * Metric catalog — transcription of docs/architecture/admin-00/03-metric-catalog.md (M1…M21).
 * This file is the single source of truth for definitions. A metric without a source is `unavailable`
 * and the UI must say why; nothing is inferred (e.g. app opens are NOT derived from sync pulls).
 */

export type MetricId =
  | 'M1' | 'M2' | 'M3' | 'M4' | 'M5' | 'M6' | 'M7' | 'M8' | 'M9' | 'M10' | 'M11'
  | 'M12' | 'M13' | 'M14' | 'M15' | 'M16' | 'M17' | 'M18' | 'M19' | 'M20' | 'M21';

/** Privacy tier: T0 platform aggregate · T1 by grade/subject/lesson with groups < K hidden · T2 individual (audited). */
export type Tier = 'T0' | 'T1' | 'T2' | 'T0/T1' | '—';

/** Backend availability per the catalog: ✅ computable now · 🔧 new queries only · 🆕 needs a new event or module. */
export type SourceReadiness = 'existing' | 'queries' | 'new-event';

export interface MetricDef {
  id: MetricId;
  label: string;
  definition: string;
  /** Existing source tables/events, verbatim from the catalog (names to be confirmed when queries are written). */
  source: string;
  calculation: string;
  tier: Tier;
  readiness: SourceReadiness;
  /** Reporting window shown on the tile. */
  period: string;
  /** Hours between aggregate refreshes; a tile turns amber after 2× this (doc 3). `null` for unavailable metrics. */
  refreshHours: number | null;
  /** Mandatory caveat shown with the tile, when the catalog states one. */
  caveat?: string;
  /** Why this metric has no value in Admin-01, when it has none. */
  unavailableReason?: string;
  /** Restricted to admin even for the dashboard (T2). */
  adminOnly?: boolean;
}

const CAVEAT_OFFLINE_LAG =
  'Le travail hors ligne compte quand le serveur l’accepte, à la date de réception : un élève hors ligne une semaine apparaît actif le jour de sa synchronisation.';

export const METRICS: readonly MetricDef[] = [
  { id: 'M1', label: 'Apprenants inscrits', definition: 'Profils d’apprenants existants et non effacés.', source: 'app.learner_profiles', calculation: 'Nombre de profils non effacés.', tier: 'T0', readiness: 'existing', period: 'À ce jour', refreshHours: 24 },
  { id: 'M2', label: 'Inscriptions dans le temps', definition: 'Nouveaux profils par jour ou semaine (date locale d’Haïti).', source: 'app.learner_profiles.created_at', calculation: 'Regroupement par date.', tier: 'T0', readiness: 'existing', period: '12 dernières semaines', refreshHours: 24 },
  { id: 'M3', label: 'Apprenants actifs en apprentissage (jour / mois)', definition: 'Apprenants ayant au moins une opération d’apprentissage ACCEPTÉE (réponse d’exercice ou leçon terminée) dans la période.', source: 'app.sync_receipts / app.practice_attempts / app.lesson_progress', calculation: 'Apprenants distincts par jour d’Haïti / sur 28 jours glissants.', tier: 'T0', readiness: 'queries', period: 'Jour · 28 jours glissants', refreshHours: 24, caveat: CAVEAT_OFFLINE_LAG },
  { id: 'M4', label: 'Ouvertures / sessions de l’application', definition: 'Aucune.', source: 'aucune (l’application n’émet aucun événement d’ouverture)', calculation: '—', tier: '—', readiness: 'new-event', period: '—', refreshHours: null, unavailableReason: 'Aucun événement d’ouverture n’existe. Ne pas le déduire des synchronisations : un téléphone en arrière-plan serait compté.' },
  { id: 'M5', label: 'Leçons terminées', definition: 'Leçons terminées acceptées par le serveur.', source: 'app.lesson_progress', calculation: 'Nombre par date ; par classe/matière via leçon → unité → cours.', tier: 'T0/T1', readiness: 'existing', period: '7 derniers jours', refreshHours: 24, caveat: CAVEAT_OFFLINE_LAG },
  { id: 'M6', label: 'Activité d’étude', definition: 'Réponses d’exercice acceptées par jour.', source: 'app.practice_attempts', calculation: 'Nombre par date.', tier: 'T0/T1', readiness: 'existing', period: '14 derniers jours', refreshHours: 24, caveat: CAVEAT_OFFLINE_LAG },
  { id: 'M7', label: 'Précision des réponses', definition: 'Part des réponses notées par le SERVEUR qui sont correctes (jamais le verdict provisoire du téléphone).', source: 'app.practice_attempts (is_correct côté serveur)', calculation: 'Correctes / total, par leçon ou classe ; jamais par apprenant sur le tableau de bord.', tier: 'T1', readiness: 'existing', period: '28 derniers jours', refreshHours: 24 },
  { id: 'M8', label: 'Engagement par classe et matière', definition: 'Apprenants actifs distincts et réponses par classe × matière.', source: 'M3 / M6 reliés au catalogue', calculation: 'Regroupement par cours ; groupes < K masqués côté serveur.', tier: 'T1', readiness: 'queries', period: '28 derniers jours', refreshHours: 24 },
  { id: 'M9', label: 'Activité des récompenses', definition: 'Or attribué par jour et succès attribués.', source: 'rewards.ledger, rewards.achievement_awards', calculation: 'Sommes et comptes.', tier: 'T0', readiness: 'existing', period: '7 derniers jours', refreshHours: 24, caveat: 'Données existantes seulement si le drapeau de récompenses a produit des écritures ; les drapeaux client restent désactivés.' },
  { id: 'M10', label: 'Contenus téléchargés', definition: 'Téléchargements commencés/terminés par ressource et par jour, octets servis.', source: 'aucune (ni événement client, ni statistiques CDN ingérées)', calculation: 'Comptage d’événements ou agrégation de journaux CDN.', tier: 'T0', readiness: 'new-event', period: '—', refreshHours: null, unavailableReason: 'Aucune source. Décision du propriétaire requise sur la collecte (Content-Delivery-00, doc 6 §3). Préférence : comptes CDN par objet, sans identifiant d’élève.' },
  { id: 'M11', label: 'Lectures en ligne', definition: 'Leçons lues en ligne par jour.', source: 'aucune (les lectures ne sont pas journalisées, par conception)', calculation: '—', tier: 'T0', readiness: 'new-event', period: '—', refreshHours: null, unavailableReason: 'Non journalisé volontairement. Possible seulement si le propriétaire approuve des compteurs agrégés.' },
  { id: 'M12', label: 'Santé de la synchronisation — serveur', definition: 'Opérations acceptées / en double / rejetées / en conflit par jour, avec codes de rejet.', source: 'app.sync_receipts (+ résultat)', calculation: 'Taux par jour.', tier: 'T0', readiness: 'queries', period: '7 derniers jours', refreshHours: 1 },
  { id: 'M13', label: 'Santé de la synchronisation — appareil', definition: 'Âge de l’opération en attente la plus ancienne, nombre d’échecs.', source: 'aucune (vit sur les téléphones)', calculation: 'Nécessite un rapport client ou un « dernier envoi réussi » par compte.', tier: 'T0', readiness: 'new-event', period: '—', refreshHours: null, unavailableReason: 'Les opérations en attente sont sur les téléphones. app.account_sync_state (dernière activité serveur par compte) est à évaluer.' },
  { id: 'M14', label: 'Participation et résultats aux examens', definition: 'Sessions commencées/closes, distribution des scores.', source: 'module d’examens', calculation: '—', tier: 'T1', readiness: 'new-event', period: '—', refreshHours: null, unavailableReason: 'Le module d’examens n’est pas construit.' },
  { id: 'M15', label: 'Couverture du Mot du jour', definition: 'Jours, parmi les 14 prochains, ayant un mot publié.', source: 'vocab.daily_assignments', calculation: 'Comptage.', tier: 'T0', readiness: 'existing', period: '14 prochains jours (Haïti)', refreshHours: 24 },
  { id: 'M16', label: 'Pipeline de contenu', definition: 'Révisions par statut ; durée médiane brouillon → publié ; éléments en attente de relecture.', source: 'app.lesson_revisions, app.editorial_reviews', calculation: 'Comptages et durées.', tier: 'T0', readiness: 'existing', period: 'À ce jour', refreshHours: 24 },
  { id: 'M17', label: 'Livraison des notifications', definition: 'Boîte d’envoi → livrées / en échec, par type.', source: 'notify.outbox, notify.deliveries', calculation: 'Comptages.', tier: 'T0', readiness: 'existing', period: '7 derniers jours', refreshHours: 24, caveat: 'Sans signification tant qu’un vrai adaptateur d’envoi n’existe pas (adaptateur factice aujourd’hui).' },
  { id: 'M18', label: 'État de l’infrastructure', definition: 'API joignable, base joignable, contrôles de disponibilité (aucun privilège TEMP, liste blanche d’extensions).', source: '/health + script de disponibilité (X-1)', calculation: 'Booléen + horodatage.', tier: 'T0', readiness: 'queries', period: 'Maintenant', refreshHours: 1, caveat: 'Le script X-1 n’est pas construit ; aucun déploiement de worker n’existe encore.' },
  { id: 'M19', label: 'Jude IA : usage, coût, erreurs', definition: 'Jetons, coût, taux d’erreur par fonction et par jour.', source: 'aucune', calculation: '—', tier: 'T0', readiness: 'new-event', period: '—', refreshHours: null, unavailableReason: 'Module inexistant : aucun jeton, coût ou erreur n’est mesuré. Aucun coût réel n’est affiché.' },
  { id: 'M20', label: 'Revenus, abonnements, transactions', definition: 'Commandes, montant payé, droits actifs, remboursements.', source: 'billing.orders, billing.entitlements, billing.refunds', calculation: 'Sommes par devise et période.', tier: 'T0', readiness: 'existing', period: '—', refreshHours: null, unavailableReason: 'Le schéma existe mais aucun fournisseur de paiement réel n’est branché. Aucune tuile de revenus tant que la réconciliation n’existe pas.' },
  { id: 'M21', label: 'Signaux de fraude (Or)', definition: 'Apprenants au rythme de gains anormal ou aux opérations en double répétées.', source: 'rewards.ledger, rewards.processed_operations', calculation: 'Seuils fixés par l’admin.', tier: 'T2', readiness: 'queries', period: '—', refreshHours: null, adminOnly: true, unavailableReason: 'Vue individuelle (T2), réservée à l’admin et auditée ; requêtes à écrire. Ce prototype n’affiche aucun enregistrement individuel.' },
];

export const METRIC_BY_ID: Record<MetricId, MetricDef> = Object.fromEntries(METRICS.map((m) => [m.id, m])) as Record<MetricId, MetricDef>;

export const READINESS_LABEL: Record<SourceReadiness, string> = {
  existing: 'Source existante',
  queries: 'Requêtes à écrire',
  'new-event': 'Nouvel événement ou module requis',
};

export const READINESS_GLYPH: Record<SourceReadiness, string> = { existing: '✅', queries: '🔧', 'new-event': '🆕' };

/** Minimum group size for T1 views. PROVISIONAL: the real value is an owner decision, held server-side. */
export const K_FLOOR = 5;

/** A tile is stale (amber) when older than twice its refresh interval. */
export function isStale(asOf: Date, refreshHours: number | null, now: Date): boolean {
  if (refreshHours === null) return false;
  return now.getTime() - asOf.getTime() > 2 * refreshHours * 3_600_000;
}
