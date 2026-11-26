/**
 * Fixture data for the Design-00 previews. Invented, static, and never written
 * anywhere. Shapes reuse the app's existing types (catalog, saved lesson,
 * practice question, sync summary) so the previews cannot drift into inventing
 * data the backend does not provide.
 */
import type { CatalogCourse, PracticeQuestion } from '../../core/api/types';
import type { SyncSummary } from '../../core/db/accountStore';
import type { SavedLesson } from '../../core/db/contentStore';
import type { StepState } from '../components/Learning';
import type { DesignLocale } from '../theme';

const FR = {
  grade: '9e année fondamentale',
  subject: 'Mathématiques',
  course: 'Mathématiques 9e AF',
  unit: 'Équations du premier degré',
  lessonTitle: 'Résoudre une équation simple',
  objective: 'Résoudre une équation du premier degré à une inconnue.',
  intro:
    'Une équation est une égalité qui contient un nombre inconnu, souvent noté x. Résoudre l’équation, c’est trouver la valeur de x qui rend l’égalité vraie.',
  rule: 'Une équation est comme une balance en équilibre. Si l’on fait la même opération des deux côtés, la balance reste en équilibre.',
  exampleTitle: 'x + 3 = 10',
  exampleSteps: ['On retire 3 de chaque côté : x + 3 − 3 = 10 − 3', 'x = 7', 'Vérification : 7 + 3 = 10 ✓'],
  concepts: [
    'Une équation garde son égalité si l’on fait la même opération des deux côtés.',
    'Pour isoler x, on utilise l’opération inverse.',
    'On vérifie toujours en remplaçant x par la valeur trouvée.',
  ],
  hint: 'Pour isoler x, cherche l’opération inverse de celle qui est écrite.',
  question: 'Résous : x + 5 = 12',
  questionLong:
    'Marie a acheté des cahiers. Elle en donne 5 à son frère et il lui en reste 12. Si x représente le nombre de cahiers achetés au départ, quelle équation faut-il résoudre et quelle est la valeur de x ?',
  explanation: 'On retire 5 de chaque côté : x = 12 − 5 = 7.',
  steps: [
    'Qu’est-ce qu’une équation ?',
    'Un exemple pas à pas',
    'Cinq questions pour s’entraîner',
    'Revoir les points difficiles',
    'Équations avec une multiplication',
    'Problèmes de la vie courante',
  ],
  otherLessons: ['Résoudre une équation simple', 'Équations avec une multiplication'],
  lastConfirmed: 'aujourd’hui à 14:05',
  detail: 'Dernière tentative : serveur injoignable (délai dépassé). Nouvelle tentative au retour de la connexion.',
};

const HT: typeof FR = {
  grade: '9èm ane fondamantal',
  subject: 'Matematik',
  course: 'Matematik 9èm AF',
  unit: 'Ekwasyon premye degre',
  lessonTitle: 'Rezoud yon ekwasyon senp',
  objective: 'Rezoud yon ekwasyon premye degre ki gen yon sèl enkoni.',
  intro:
    'Yon ekwasyon se yon egalite ki gen yon nonb nou pa konnen, nou souvan rele l x. Rezoud ekwasyon an vle di jwenn valè x ki fè egalite a vre.',
  rule: 'Yon ekwasyon tankou yon balans ki an ekilib. Si nou fè menm operasyon an nan de bò yo, balans lan rete an ekilib.',
  exampleTitle: 'x + 3 = 10',
  exampleSteps: ['Nou retire 3 nan chak bò: x + 3 − 3 = 10 − 3', 'x = 7', 'Verifikasyon: 7 + 3 = 10 ✓'],
  concepts: [
    'Yon ekwasyon rete vre si nou fè menm operasyon an nan de bò yo.',
    'Pou jwenn x, nou sèvi ak operasyon ki kontrè a.',
    'Nou toujou verifye lè nou ranplase x ak valè nou jwenn nan.',
  ],
  hint: 'Pou jwenn x, chèche operasyon ki kontrè ak sa ki ekri a.',
  question: 'Rezoud: x + 5 = 12',
  questionLong:
    'Mari achte kèk kaye. Li bay frè l 5 ladan yo epi li rete 12. Si x se kantite kaye li te achte okòmansman, ki ekwasyon nou dwe rezoud epi ki valè x genyen?',
  explanation: 'Nou retire 5 nan chak bò: x = 12 − 5 = 7.',
  steps: [
    'Kisa yon ekwasyon ye?',
    'Yon egzanp etap pa etap',
    'Senk kesyon pou pratike',
    'Revize pwen ki difisil yo',
    'Ekwasyon ak yon miltiplikasyon',
    'Pwoblèm nan lavi chak jou',
  ],
  otherLessons: ['Rezoud yon ekwasyon senp', 'Ekwasyon ak yon miltiplikasyon'],
  lastConfirmed: 'jodi a a 14:05',
  detail: 'Dènye esè: nou pa t ka jwenn sèvè a (tan an fini). N ap eseye ankò lè entènèt la retounen.',
};

export function copy(locale: DesignLocale) {
  return locale === 'ht' ? HT : FR;
}

export const GRADES = ['7AF', '8AF', '9AF', 'NS1', 'NS2', 'NS3', 'NS4'] as const;

export function subjects(locale: DesignLocale): string[] {
  return locale === 'ht' ? ['Matematik', 'Fizik', 'Kreyòl', 'Fransè'] : ['Mathématiques', 'Physique', 'Créole', 'Français'];
}

export function course(locale: DesignLocale): CatalogCourse {
  const c = copy(locale);
  return {
    id: 'b0000000-0000-4000-8000-000000000003',
    slug: 'mathematiques-9af',
    title: c.course,
    grade: { code: '9AF', label: c.grade },
    subject: { slug: 'mathematiques', label: c.subject },
    units: [
      {
        id: 'b0000000-0000-4000-8000-000000000004',
        slug: 'equations-premier-degre',
        position: 1,
        title: c.unit,
        lessons: c.otherLessons.map((title, i) => ({
          id: `b0000000-0000-4000-8000-00000000000${5 + i}`,
          slug: `lesson-${i + 1}`,
          position: i + 1,
          title,
          revision_id: `c0000000-0000-4000-8000-00000000000${1 + i}`,
          revision: 1,
        })),
      },
    ],
  };
}

export function lesson(locale: DesignLocale): SavedLesson {
  const c = copy(locale);
  return {
    lessonId: 'b0000000-0000-4000-8000-000000000005',
    locale,
    revisionId: locale === 'ht' ? 'c0000000-0000-4000-8000-000000000002' : 'c0000000-0000-4000-8000-000000000001',
    revision: 1,
    title: c.lessonTitle,
    savedAt: '2026-11-22T14:00:00.000Z',
    serverGoneAt: null,
    blocks: [
      { key: 'intro', type: 'paragraph', text: c.intro },
      { key: 'regle', type: 'paragraph', text: c.rule },
      {
        key: 'exemple',
        type: 'example',
        title: c.exampleTitle,
        steps: c.exampleSteps,
      },
    ],
    questions: [question(locale, false)],
  };
}

export function question(locale: DesignLocale, long: boolean): PracticeQuestion {
  const c = copy(locale);
  return {
    id: 'd0000000-0000-4000-8000-000000000101',
    question_key: 'addition',
    position: 1,
    kind: 'mcq',
    prompt: { text: long ? c.questionLong : c.question },
    response_spec: {
      choices: [
        { id: 'a', text: 'x = 5' },
        { id: 'b', text: long ? 'x − 5 = 12, x = 17' : 'x = 7' },
        { id: 'c', text: 'x = 12' },
        { id: 'd', text: long ? 'x + 5 = 12, x = 7' : 'x = 17' },
      ],
    },
    answer_key: { correct_choice_id: 'b' },
    explanation: {
      text: long
        ? locale === 'ht'
          ? 'Mari te gen x kaye, li bay 5: x − 5 = 12. Nou ajoute 5 nan chak bò: x = 17.'
          : 'Marie avait x cahiers et en donne 5 : x − 5 = 12. On ajoute 5 de chaque côté : x = 17.'
        : c.explanation,
    },
  };
}

export interface PathStep {
  kind: 'understand' | 'example' | 'practice' | 'review';
  title: string;
  state: StepState;
}

export function pathSteps(locale: DesignLocale, offline: boolean): PathStep[] {
  const titles = copy(locale).steps;
  return [
    { kind: 'understand', title: titles[0], state: 'completed' },
    { kind: 'example', title: titles[1], state: 'completed' },
    { kind: 'practice', title: titles[2], state: 'recommended' },
    { kind: 'review', title: titles[3], state: 'available' },
    {
      kind: 'understand',
      title: titles[4],
      state: offline ? 'unavailable' : 'available',
    },
    { kind: 'practice', title: titles[5], state: 'unavailable' },
  ];
}

export const PROGRESS = {
  lessonsDone: 3,
  lessonsTotal: 8,
  correct: 14,
  answered: 18,
  weeklyDone: 2,
  weeklyTotal: 3,
  toReview: 5,
};

export const SYNC: Record<'synced' | 'pending' | 'failed' | 'attention', SyncSummary> = {
  synced: {
    pending: 0,
    needsAttention: 0,
    lastSyncAt: '2026-11-22T19:05:00.000Z',
  },
  pending: {
    pending: 5,
    needsAttention: 0,
    lastSyncAt: '2026-11-22T19:05:00.000Z',
  },
  failed: { pending: 5, needsAttention: 0, lastSyncAt: null },
  attention: {
    pending: 0,
    needsAttention: 2,
    lastSyncAt: '2026-11-22T19:05:00.000Z',
  },
};
