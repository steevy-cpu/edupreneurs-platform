import type { Block } from '../domain/blocks';
import type { Course, EditorialState, Revision, SourceRef } from '../domain/editorial';

/**
 * SYNTHETIC editorial fixtures. Lesson text is invented for the demo (plain French, format v1 blocks only)
 * and is NOT curriculum content. Authors are the synthetic personas of domain/roles.ts.
 */

const h = (key: string, text: string): Block => ({ key, type: 'heading', text });
const p = (key: string, text: string): Block => ({ key, type: 'paragraph', text });
const ex = (key: string, title: string, steps: string[]): Block => ({ key, type: 'example', title, steps });
const co = (key: string, tone: 'tip' | 'warning' | 'remember', text: string): Block => ({ key, type: 'callout', tone, text });

const src = (id: string, title: string, kind: SourceRef['kind'], licence: string, rights: SourceRef['rights']): SourceRef => ({ id, title, kind, licence, rights });
const ORIGINAL = (id: string) => src(id, 'Rédaction originale (synthétique)', 'original', 'Propriété Edupreneurs', 'cleared');

const T = '2026-11-';
const h0 = (action: string, actor: string, day: string, reason?: string) => ({ at: `${T}${day}T14:00:00.000Z`, actor, action, reason });

export const COURSES: Course[] = [
  {
    id: 'c-7af-math', grade: '7AF', subject: 'Mathématiques', title: 'Mathématiques 7AF',
    units: [{ id: 'u-7af-entiers', title: 'Nombres entiers', lessons: [{ id: 'l-operations', title: 'Les quatre opérations' }, { id: 'l-multiples', title: 'Multiples et diviseurs' }] }],
  },
  {
    id: 'c-8af-sci', grade: '8AF', subject: 'Sciences expérimentales', title: 'Sciences expérimentales 8AF',
    units: [{ id: 'u-8af-matiere', title: 'La matière', lessons: [{ id: 'l-etats', title: 'Les états de la matière' }] }],
  },
  {
    id: 'c-9af-math', grade: '9AF', subject: 'Mathématiques', title: 'Mathématiques 9AF',
    units: [
      { id: 'u-9af-fractions', title: 'Fractions', lessons: [{ id: 'l-comparer', title: 'Comparer des fractions' }, { id: 'l-additionner', title: 'Additionner des fractions' }, { id: 'l-equivalentes', title: 'Fractions équivalentes' }] },
      { id: 'u-9af-equations', title: 'Équations simples', lessons: [{ id: 'l-ax-b', title: 'Résoudre ax + b = c' }, { id: 'l-relatifs', title: 'Nombres relatifs' }] },
    ],
  },
  {
    id: 'c-9af-fr', grade: '9AF', subject: 'Français', title: 'Français 9AF',
    units: [{ id: 'u-9af-recit', title: 'Le récit', lessons: [{ id: 'l-schema', title: 'Le schéma narratif' }] }],
  },
  {
    id: 'c-ns1-ss', grade: 'NS1', subject: 'Sciences sociales', title: 'Sciences sociales NS1',
    units: [{ id: 'u-ns1-ind', title: 'Indépendance d’Haïti', lessons: [{ id: 'l-1804', title: 'Le 1er janvier 1804' }] }],
  },
  {
    id: 'c-ns2-en', grade: 'NS2', subject: 'Anglais', title: 'Anglais NS2',
    units: [{ id: 'u-ns2-tenses', title: 'Tenses', lessons: [{ id: 'l-pp', title: 'Present perfect' }] }],
  },
];

const fractionsV1: Block[] = [
  h('titre', 'Comparer des fractions'),
  p('meme-denominateur', 'Quand deux fractions ont le même dénominateur, la plus grande est celle qui a le plus grand numérateur.'),
  ex('exemple-1', 'Exemple', ['Comparons 3/8 et 5/8.', 'Les dénominateurs sont égaux (8).', '5 est plus grand que 3, donc 5/8 est plus grande que 3/8.']),
  co('retenir', 'remember', 'Même dénominateur : on compare seulement les numérateurs.'),
];
const fractionsV2: Block[] = [
  ...fractionsV1.slice(0, 3),
  p('denominateurs-differents', 'Quand les dénominateurs sont différents, on les rend d’abord égaux en cherchant un dénominateur commun.'),
  ex('exemple-2', 'Exemple avec dénominateurs différents', ['Comparons 1/2 et 3/5.', 'Dénominateur commun : 10.', '1/2 = 5/10 et 3/5 = 6/10.', '6/10 est plus grand que 5/10, donc 3/5 est plus grande que 1/2.']),
  co('retenir', 'remember', 'Dénominateurs différents : chercher un dénominateur commun avant de comparer.'),
];
const fractionsHt: Block[] = [
  h('titre', 'Konpare fraksyon'),
  p('menm-denominate', 'Lè de fraksyon gen menm denominatè, fraksyon ki gen pi gwo nimeratè a se pi gwo a.'),
];

const rev = (r: Partial<Revision> & Pick<Revision, 'id' | 'lessonId' | 'number' | 'status' | 'authorId' | 'authorName' | 'blocks' | 'sources'>): Revision => ({
  aiAssisted: false, reviews: [], history: [], ...r,
});

export function buildEditorialFixture(): EditorialState {
  const revisions: Revision[] = [
    // — Comparer des fractions: v1 published, v2 awaiting review (reviewer sees a diff)
    rev({ id: 'rev-l-comparer-1', lessonId: 'l-comparer', number: 1, status: 'published', authorId: 'p-anne', authorName: 'Anne (synthétique)', blocks: { fr: fractionsV1, ht: fractionsHt }, sources: [ORIGINAL('s1')],
      reviews: [{ reviewerId: 'p-chloe', reviewerName: 'Chloé (synthétique)', decision: 'approve', comment: 'Clair et exact.', at: `${T}03T15:00:00.000Z` }],
      history: [h0('Révision créée', 'Anne (synthétique)', '02'), h0('Approuvée', 'Chloé (synthétique)', '03'), h0('Publiée (synthétique)', 'David (synthétique)', '04', 'Première publication')] }),
    rev({ id: 'rev-l-comparer-2', lessonId: 'l-comparer', number: 2, status: 'in_review', authorId: 'p-anne', authorName: 'Anne (synthétique)', blocks: { fr: fractionsV2 }, sources: [ORIGINAL('s1')],
      history: [h0('Révision créée', 'Anne (synthétique)', '20'), h0('Soumise à la relecture', 'Anne (synthétique)', '24')] }),
    // — Additionner: approved, authored by Bruno → ready for a publisher who is not Bruno
    rev({ id: 'rev-l-additionner-1', lessonId: 'l-additionner', number: 1, status: 'approved', authorId: 'p-bruno', authorName: 'Bruno (synthétique)',
      blocks: { fr: [h('titre', 'Additionner des fractions'), p('regle', 'Pour additionner deux fractions de même dénominateur, on additionne les numérateurs et on garde le dénominateur.'), ex('exemple', 'Exemple', ['2/7 + 3/7', '(2 + 3)/7 = 5/7'])] },
      sources: [ORIGINAL('s2'), src('s3', 'Programme officiel 9AF (extrait cité)', 'curriculum', 'Citation courte, source indiquée', 'cleared')],
      reviews: [{ reviewerId: 'p-chloe', reviewerName: 'Chloé (synthétique)', decision: 'approve', comment: '', at: `${T}22T10:00:00.000Z` }],
      history: [h0('Soumise à la relecture', 'Bruno (synthétique)', '21'), h0('Approuvée', 'Chloé (synthétique)', '22')] }),
    // — Fractions équivalentes: approved, authored by Hélène (editor+publisher): she cannot publish her own
    rev({ id: 'rev-l-equivalentes-1', lessonId: 'l-equivalentes', number: 1, status: 'approved', authorId: 'p-helene', authorName: 'Hélène (synthétique)',
      blocks: { fr: [h('titre', 'Fractions équivalentes'), p('idee', 'Deux fractions sont équivalentes quand elles représentent la même quantité, par exemple 1/2 et 2/4.'), co('astuce', 'tip', 'Multiplier le numérateur et le dénominateur par le même nombre donne une fraction équivalente.')] },
      sources: [ORIGINAL('s4')],
      reviews: [{ reviewerId: 'p-chloe', reviewerName: 'Chloé (synthétique)', decision: 'approve', comment: '', at: `${T}23T10:00:00.000Z` }],
      history: [h0('Approuvée', 'Chloé (synthétique)', '23')] }),
    // — ax+b=c: draft by Anne with a validation error (markup) and rights pending → submit blocked
    rev({ id: 'rev-l-ax-b-1', lessonId: 'l-ax-b', number: 1, status: 'draft', authorId: 'p-anne', authorName: 'Anne (synthétique)',
      blocks: { fr: [h('titre', 'Résoudre ax + b = c'), p('methode', 'On isole x en deux temps : on retire b des deux côtés, puis on divise par a. <b>Attention</b> au signe.'), ex('exemple', 'Exemple', ['2x + 3 = 11', '2x = 11 − 3 = 8', 'x = 8 / 2 = 4'])] },
      sources: [src('s5', 'Manuel scolaire (page 42)', 'textbook', 'Droits non vérifiés', 'pending')],
      history: [h0('Révision créée', 'Anne (synthétique)', '25')] }),
    // — Le schéma narratif: published v1, v2 changes requested with reviewer comment
    rev({ id: 'rev-l-schema-1', lessonId: 'l-schema', number: 1, status: 'published', authorId: 'p-bruno', authorName: 'Bruno (synthétique)',
      blocks: { fr: [h('titre', 'Le schéma narratif'), p('etapes', 'Un récit comporte cinq étapes : situation initiale, élément perturbateur, péripéties, dénouement, situation finale.')] }, sources: [ORIGINAL('s6')],
      history: [h0('Publiée (synthétique)', 'David (synthétique)', '10')] }),
    rev({ id: 'rev-l-schema-2', lessonId: 'l-schema', number: 2, status: 'changes_requested', authorId: 'p-bruno', authorName: 'Bruno (synthétique)',
      blocks: { fr: [h('titre', 'Le schéma narratif'), p('etapes', 'Un récit comporte cinq étapes : situation initiale, élément perturbateur, péripéties, dénouement, situation finale.'), ex('ex-conte', 'Un conte connu', ['Situation initiale : …'])] }, sources: [ORIGINAL('s6')],
      reviews: [{ reviewerId: 'p-chloe', reviewerName: 'Chloé (synthétique)', decision: 'changes', comment: 'L’exemple est inachevé : donner les cinq étapes du conte choisi.', at: `${T}25T09:00:00.000Z` }],
      history: [h0('Soumise à la relecture', 'Bruno (synthétique)', '24'), h0('Changements demandés', 'Chloé (synthétique)', '25', 'L’exemple est inachevé : donner les cinq étapes du conte choisi.')] }),
    // — Les quatre opérations: AI-assisted draft
    rev({ id: 'rev-l-operations-1', lessonId: 'l-operations', number: 1, status: 'draft', authorId: 'p-bruno', authorName: 'Bruno (synthétique)', aiAssisted: true,
      blocks: { fr: [h('titre', 'Les quatre opérations'), p('intro', 'Addition, soustraction, multiplication et division sont les quatre opérations de base.'), co('verifier', 'warning', 'Brouillon assisté par IA (synthétique) : vérifier chaque affirmation avant soumission.')] },
      sources: [], history: [h0('Brouillon généré (synthétique)', 'Bruno (synthétique)', '25')] }),
    // — Multiples et diviseurs: withdrawn
    rev({ id: 'rev-l-multiples-1', lessonId: 'l-multiples', number: 1, status: 'withdrawn', authorId: 'p-anne', authorName: 'Anne (synthétique)',
      blocks: { fr: [h('titre', 'Multiples et diviseurs'), p('def', 'Un multiple de 3 est un nombre de la table de 3.')] },
      sources: [src('s7', 'Document tiers (synthétique)', 'web', 'Droits retirés par le titulaire', 'restricted')],
      history: [h0('Publiée (synthétique)', 'David (synthétique)', '05'), h0('Retirée (synthétique)', 'Gaëlle (synthétique)', '18', 'Droits retirés par le titulaire')] }),
    // — États de la matière: v1 superseded, v2 published (rollback possible)
    rev({ id: 'rev-l-etats-1', lessonId: 'l-etats', number: 1, status: 'superseded', authorId: 'p-anne', authorName: 'Anne (synthétique)',
      blocks: { fr: [h('titre', 'Les états de la matière'), p('etats', 'La matière existe à l’état solide, liquide et gazeux.')] }, sources: [ORIGINAL('s8')], history: [] }),
    rev({ id: 'rev-l-etats-2', lessonId: 'l-etats', number: 2, status: 'published', authorId: 'p-anne', authorName: 'Anne (synthétique)',
      blocks: { fr: [h('titre', 'Les états de la matière'), p('etats', 'La matière existe à l’état solide, liquide et gazeux.'), ex('eau', 'L’eau', ['Solide : la glace', 'Liquide : l’eau', 'Gaz : la vapeur d’eau']), co('retenir', 'remember', 'Un changement d’état ne change pas la nature de la matière.')] }, sources: [ORIGINAL('s8')], history: [] }),
    // — 1804: draft, rights unknown
    rev({ id: 'rev-l-1804-1', lessonId: 'l-1804', number: 1, status: 'draft', authorId: 'p-anne', authorName: 'Anne (synthétique)',
      blocks: { fr: [h('titre', 'Le 1er janvier 1804'), p('fait', 'L’indépendance d’Haïti est proclamée aux Gonaïves le 1er janvier 1804.')] },
      sources: [src('s9', 'Ouvrage d’histoire (à identifier)', 'textbook', 'À déterminer', 'unknown')], history: [] }),
    // — Present perfect: in review (author Bruno)
    rev({ id: 'rev-l-pp-1', lessonId: 'l-pp', number: 1, status: 'in_review', authorId: 'p-bruno', authorName: 'Bruno (synthétique)',
      blocks: { fr: [h('titre', 'Present perfect'), p('forme', 'Le present perfect se forme avec have ou has, suivi du participe passé : I have studied.')] }, sources: [ORIGINAL('s10')],
      history: [h0('Soumise à la relecture', 'Bruno (synthétique)', '26')] }),
  ];
  return { courses: COURSES, revisions, receipts: [] };
}
