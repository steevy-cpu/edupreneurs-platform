/**
 * Read-only views for the redesigned screens (Mobile-02).
 *
 * Everything here reads SQLite through the existing stores and returns plain
 * data for a screen to draw. Nothing here writes learning data, talks to the
 * network, or computes anything the stores do not already hold: no estimates,
 * no placeholder numbers. If a value is unknown it is absent, not invented.
 */
import type { CatalogResponse, Locale } from '../api/types';
import type { AccountStore, LessonRef, SyncState } from '../db/accountStore';
import type { ContentStore, SavedLessonInfo } from '../db/contentStore';
import { LessonFreshness, lessonFreshness } from './contentAccess';

export const PREF_GRADE = 'grade_code';
export const PREF_SUBJECT = 'subject_slug';
/** Account-scoped: the lesson this student opened most recently on this phone. */
export const PREF_LAST_LESSON = 'last_lesson_id';

/** Where one saved lesson stands for the signed-in student, from local records only. */
export interface LessonStanding {
  lessonId: string;
  title: string;
  revision: number;
  revisionId: string;
  /** `downloaded`: a copy is on this phone. `online`: only a reference is kept; the lesson must be fetched to open it. */
  availability: 'downloaded' | 'online';
  /** Questions of the saved revision that this app version can present. Null for an online-only lesson: it is not known without fetching it. */
  questionCount: number | null;
  /** How many of those have at least one recorded answer. */
  answered: number;
  /** Last answer correct (server verdict when known, otherwise the provisional local one). */
  correct: number;
  /** Ids of questions whose last answer was wrong. */
  missedQuestionIds: string[];
  /** Answers saved on the phone that the server has not acknowledged yet. */
  waiting: number;
  /** Answers the server refused (they will not be re-sent). */
  refused: number;
  completed: boolean;
  /** Sync state of the completion record; null when the lesson is not completed. */
  completionState: SyncState | null;
}

export async function lessonStanding(content: ContentStore, account: AccountStore, info: SavedLessonInfo): Promise<LessonStanding | null> {
  const lesson = await content.getLesson(info.lessonId, info.locale);
  if (!lesson) return null;
  const questions = lesson.questions.filter((question) => question.kind === 'mcq');
  const progress = await account.questionProgress(info.lessonId);
  const completion = await account.lessonProgress(info.lessonId);
  let answered = 0;
  let correct = 0;
  let waiting = 0;
  let refused = 0;
  const missedQuestionIds: string[] = [];
  for (const question of questions) {
    const record = progress.get(question.id);
    if (!record) continue;
    answered += 1;
    if (record.lastIsCorrect === true) correct += 1;
    if (record.lastIsCorrect === false) missedQuestionIds.push(question.id);
    if (record.lastSyncState === 'pending') waiting += 1;
    if (record.lastSyncState === 'needs_attention') refused += 1;
  }
  return {
    lessonId: info.lessonId,
    availability: 'downloaded',
    title: info.title,
    revision: info.revision,
    revisionId: info.revisionId,
    questionCount: questions.length,
    answered,
    correct,
    missedQuestionIds,
    waiting,
    refused,
    completed: Boolean(completion?.completed),
    completionState: completion?.completed ? completion.syncState : null,
  };
}

/**
 * Standing of a lesson that is NOT on this phone, from the student's own records only (question progress,
 * completion). It cannot know how many questions the lesson has, so `questionCount` is null — never a guess.
 */
export async function refStanding(account: AccountStore, ref: LessonRef): Promise<LessonStanding> {
  const progress = await account.questionProgress(ref.lessonId);
  const completion = await account.lessonProgress(ref.lessonId);
  let correct = 0;
  let waiting = 0;
  let refused = 0;
  const missedQuestionIds: string[] = [];
  for (const record of progress.values()) {
    if (record.lastIsCorrect === true) correct += 1;
    if (record.lastIsCorrect === false) missedQuestionIds.push(record.questionRevisionId);
    if (record.lastSyncState === 'pending') waiting += 1;
    if (record.lastSyncState === 'needs_attention') refused += 1;
  }
  return {
    lessonId: ref.lessonId,
    availability: 'online',
    title: ref.title,
    revision: ref.revision,
    revisionId: ref.revisionId,
    questionCount: null,
    answered: progress.size,
    correct,
    missedQuestionIds,
    waiting,
    refused,
    completed: Boolean(completion?.completed),
    completionState: completion?.completed ? completion.syncState : null,
  };
}

/**
 * Everything this student has studied in this language: downloaded lessons first, then lessons only
 * opened online (most recent first). A lesson whose download was removed stays here, as an online lesson.
 */
export async function learningStandings(content: ContentStore, account: AccountStore, locale: Locale): Promise<LessonStanding[]> {
  const downloaded = await savedLessonStandings(content, account, locale);
  const have = new Set(downloaded.map((lesson) => lesson.lessonId));
  const online: LessonStanding[] = [];
  for (const ref of await account.listLessonRefs(locale)) {
    if (!have.has(ref.lessonId)) online.push(await refStanding(account, ref));
  }
  return [...downloaded, ...online];
}

/** Every lesson saved on this phone in this language, with the student's standing. */
export async function savedLessonStandings(content: ContentStore, account: AccountStore, locale: Locale): Promise<LessonStanding[]> {
  const out: LessonStanding[] = [];
  for (const info of await content.listSavedLessons(locale)) {
    const standing = await lessonStanding(content, account, info);
    if (standing) out.push(standing);
  }
  return out;
}

export interface LearnerTotals {
  /** Lessons with a copy on this phone. */
  lessonsSaved: number;
  /** Lessons studied from any source (downloaded or online). */
  lessonsStudied: number;
  lessonsCompleted: number;
  questionsAnswered: number;
  questionsCorrect: number;
  questionsMissed: number;
  answersWaiting: number;
}

export function totalsOf(standings: LessonStanding[]): LearnerTotals {
  return {
    lessonsSaved: standings.filter((lesson) => lesson.availability === 'downloaded').length,
    lessonsStudied: standings.length,
    lessonsCompleted: standings.filter((lesson) => lesson.completed).length,
    questionsAnswered: standings.reduce((sum, lesson) => sum + lesson.answered, 0),
    questionsCorrect: standings.reduce((sum, lesson) => sum + lesson.correct, 0),
    questionsMissed: standings.reduce((sum, lesson) => sum + lesson.missedQuestionIds.length, 0),
    answersWaiting: standings.reduce((sum, lesson) => sum + lesson.waiting, 0),
  };
}

/**
 * The lesson offered by "Continue learning": the one opened last if this student still has a
 * record of it (downloaded or online), otherwise the first lesson not yet finished, otherwise the
 * first. Null when the student has studied nothing — the card is then not shown at all.
 */
export function pickContinueLesson(standings: LessonStanding[], lastLessonId: string | null): LessonStanding | null {
  if (standings.length === 0) return null;
  return standings.find((lesson) => lesson.lessonId === lastLessonId) ?? standings.find((lesson) => !lesson.completed) ?? standings[0];
}

export interface LessonContext {
  gradeCode: string;
  gradeLabel: string;
  subjectLabel: string;
  unitTitle: string;
  /** 1-based place of the lesson in its unit, in catalog order. */
  lessonNumber: number;
}

/** Subject / unit of a lesson, if the cached catalog lists it. */
export function findLessonContext(catalog: CatalogResponse | null, lessonId: string): LessonContext | null {
  for (const course of catalog?.courses ?? []) {
    for (const unit of course.units) {
      const ordered = [...unit.lessons].sort((a, b) => a.position - b.position);
      const index = ordered.findIndex((lesson) => lesson.id === lessonId);
      if (index >= 0) {
        return {
          gradeCode: course.grade.code,
          gradeLabel: course.grade.label,
          subjectLabel: course.subject.label,
          unitTitle: unit.title,
          lessonNumber: index + 1,
        };
      }
    }
  }
  return null;
}

export type PathLessonState = 'completed' | 'recommended' | 'available' | 'unavailable';

export interface PathLesson {
  lessonId: string;
  title: string;
  /** 1-based place in the unit. */
  number: number;
  /** Null when the lesson is not saved on this phone: it must be downloaded first. */
  saved: SavedLessonInfo | null;
  /** From the lesson-completion record (lesson level; step-level completion is not stored). */
  completed: boolean;
  /** A newer revision is published than the one saved here. */
  updateAvailable: boolean;
  /** Where the saved copy stands relative to the last catalog this phone fetched; null when nothing is saved. */
  freshness: LessonFreshness | null;
  state: PathLessonState;
}

export interface PathUnit {
  id: string;
  title: string;
  number: number;
  lessons: PathLesson[];
  completedCount: number;
}

export interface PathView {
  /** False when no catalog has ever been cached in this language. */
  catalogKnown: boolean;
  catalogFetchedAt: string | null;
  grades: { code: string; label: string }[];
  /** Subjects offered for the selected grade. */
  subjects: { slug: string; label: string }[];
  grade: string | null;
  subject: string | null;
  units: PathUnit[];
  /** Saved lessons that the selected course does not list; they stay reachable. */
  otherSaved: SavedLessonInfo[];
}

/**
 * The learning path for a grade and subject, built from the cached catalog,
 * the saved lessons and the completion records. Never waits for the network.
 */
export async function loadPath(
  content: ContentStore,
  account: AccountStore,
  locale: Locale,
  selection: { grade: string | null; subject: string | null },
): Promise<PathView> {
  const cached = await content.getCatalog(locale);
  const courses = cached?.catalog.courses ?? [];
  const saved = await content.listSavedLessons(locale);
  const savedById = new Map(saved.map((lesson) => [lesson.lessonId, lesson]));

  const grades = new Map<string, string>();
  for (const course of courses) grades.set(course.grade.code, course.grade.label);
  const grade = selection.grade !== null && grades.has(selection.grade) ? selection.grade : null;

  const subjects = new Map<string, string>();
  for (const course of courses) {
    if (course.grade.code === grade) subjects.set(course.subject.slug, course.subject.label);
  }
  const subject = selection.subject !== null && subjects.has(selection.subject) ? selection.subject : null;

  const course = courses.find((c) => c.grade.code === grade && c.subject.slug === subject) ?? null;
  const units: PathUnit[] = [];
  const listed = new Set<string>();
  let recommendedGiven = false;
  if (course) {
    const orderedUnits = [...course.units].sort((a, b) => a.position - b.position);
    for (const [unitIndex, unit] of orderedUnits.entries()) {
      const lessons: PathLesson[] = [];
      const orderedLessons = [...unit.lessons].sort((a, b) => a.position - b.position);
      for (const [lessonIndex, lesson] of orderedLessons.entries()) {
        listed.add(lesson.id);
        const copy = savedById.get(lesson.id) ?? null;
        const completed = Boolean((await account.lessonProgress(lesson.id))?.completed);
        let state: PathLessonState;
        if (completed) state = 'completed';
        else if (!copy) state = 'unavailable';
        else if (!recommendedGiven) {
          state = 'recommended';
          recommendedGiven = true;
        } else state = 'available';
        lessons.push({
          lessonId: lesson.id,
          title: copy?.title ?? lesson.title,
          number: lessonIndex + 1,
          saved: copy,
          completed,
          updateAvailable: copy !== null && copy.revisionId !== lesson.revision_id,
          freshness: copy ? lessonFreshness(copy, cached) : null,
          state,
        });
      }
      units.push({
        id: unit.id,
        title: unit.title,
        number: unitIndex + 1,
        lessons,
        completedCount: lessons.filter((lesson) => lesson.completed).length,
      });
    }
  }

  return {
    catalogKnown: cached !== null,
    catalogFetchedAt: cached?.fetchedAt ?? null,
    grades: [...grades.entries()].map(([code, label]) => ({ code, label })),
    subjects: [...subjects.entries()].map(([slug, label]) => ({ slug, label })),
    grade,
    subject,
    units,
    otherSaved: saved.filter((lesson) => !listed.has(lesson.lessonId)),
  };
}

export type SyncDisplay = 'synced' | 'pending' | 'failed' | 'attention';

/**
 * Which of the four sync states to show. "synced" is returned ONLY when nothing
 * is waiting and nothing was refused: it can never be shown for work the server
 * has not acknowledged.
 */
export function syncDisplayOf(summary: { pending: number; needsAttention: number }, lastOutcome: string | null): SyncDisplay {
  if (summary.pending > 0)
    return lastOutcome === 'offline' || lastOutcome === 'error' || lastOutcome === 'auth_required' ? 'failed' : 'pending';
  if (summary.needsAttention > 0) return 'attention';
  return 'synced';
}

/** dd/mm/yyyy in the phone's own time zone, for "verified on …". Empty for an unparseable value. */
export function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const two = (n: number) => String(n).padStart(2, '0');
  return `${two(date.getDate())}/${two(date.getMonth() + 1)}/${date.getFullYear()}`;
}
