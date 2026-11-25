/**
 * The grades offered on the onboarding "class" step.
 *
 * Source of truth: the catalogue the app already has in SQLite (the grades that
 * really have courses). When no catalogue has been cached yet — first start
 * with no connection — the standard list of the Haitian school system from the
 * 7th fundamental year to the last year of the "Nouveau Secondaire" is offered
 * instead, so the step always works offline.
 */
import type { Locale } from '../api/types';
import type { ContentStore } from '../db/contentStore';

export interface GradeOption {
  code: string;
  label: string;
}

const FALLBACK: { code: string; fr: string; ht: string }[] = [
  { code: '7AF', fr: '7e année fondamentale', ht: '7èm ane fondamantal' },
  { code: '8AF', fr: '8e année fondamentale', ht: '8èm ane fondamantal' },
  { code: '9AF', fr: '9e année fondamentale', ht: '9èm ane fondamantal' },
  { code: 'NS1', fr: 'Nouveau Secondaire 1', ht: 'Nouvo Segondè 1' },
  { code: 'NS2', fr: 'Nouveau Secondaire 2', ht: 'Nouvo Segondè 2' },
  { code: 'NS3', fr: 'Nouveau Secondaire 3', ht: 'Nouvo Segondè 3' },
  { code: 'NS4', fr: 'Nouveau Secondaire 4', ht: 'Nouvo Segondè 4' },
];

export function fallbackGrades(locale: Locale): GradeOption[] {
  return FALLBACK.map((grade) => ({ code: grade.code, label: grade[locale] }));
}

export interface GradeChoices {
  grades: GradeOption[];
  /** False when the list is the built-in one because no catalogue is on the phone yet. */
  fromCatalog: boolean;
}

export async function gradeChoices(content: ContentStore, locale: Locale): Promise<GradeChoices> {
  const cached = await content.getCatalog(locale);
  const fromCatalog = new Map<string, string>();
  for (const course of cached?.catalog.courses ?? []) fromCatalog.set(course.grade.code, course.grade.label);
  if (fromCatalog.size === 0) return { grades: fallbackGrades(locale), fromCatalog: false };
  // Standard school order first, then anything the catalogue has that the built-in list does not know.
  const order = new Map(FALLBACK.map((grade, index) => [grade.code, index]));
  const grades = [...fromCatalog.entries()]
    .map(([code, label]) => ({ code, label }))
    .sort((a, b) => (order.get(a.code) ?? 99) - (order.get(b.code) ?? 99) || a.code.localeCompare(b.code));
  return { grades, fromCatalog: true };
}
