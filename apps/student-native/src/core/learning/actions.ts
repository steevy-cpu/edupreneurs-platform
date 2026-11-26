import { ApiClient } from '../api/client';
import type { Locale, PracticeQuestion } from '../api/types';
import { validateLessonSnapshot } from '../api/validate';
import { AccountStore, LessonRef } from '../db/accountStore';
import { ContentStore, SavedLessonInfo } from '../db/contentStore';

export interface Environment {
  /** RFC 4122 v4 UUID, lower case. */
  newId: () => string;
  now: () => Date;
}

export interface Choice {
  id: string;
  text: string;
}

export function choicesOf(question: PracticeQuestion): Choice[] {
  const choices = (question.response_spec as { choices?: unknown }).choices;
  return Array.isArray(choices) ? (choices as Choice[]) : [];
}

export function correctChoiceOf(question: PracticeQuestion): string | null {
  const id = (question.answer_key as { correct_choice_id?: unknown }).correct_choice_id;
  return typeof id === 'string' ? id : null;
}

export function textOf(value: Record<string, unknown>): string {
  return typeof value.text === 'string' ? value.text : '';
}

/** What an answer or completion needs to know about its lesson. Title/locale/revision, when present, are kept as a minimal reference. */
export type LessonIdentity = Pick<SavedLessonInfo, 'lessonId' | 'revisionId'> &
  Partial<Pick<SavedLessonInfo, 'locale' | 'title' | 'revision'>>;

function refOf(lesson: LessonIdentity, at: string): LessonRef | undefined {
  if (!lesson.locale || !lesson.title || typeof lesson.revision !== 'number') return undefined;
  return { lessonId: lesson.lessonId, locale: lesson.locale, title: lesson.title, revisionId: lesson.revisionId, revision: lesson.revision, at };
}

export interface AnswerReceipt {
  opId: string;
  /** Provisional verdict from the downloaded answer key. The server re-scores on sync. */
  isCorrect: boolean;
}

/**
 * Save an answer on the phone. Resolves only AFTER the local transaction has
 * committed — callers show "saved" feedback after awaiting this, never before.
 */
export async function answerQuestion(
  account: AccountStore,
  lesson: LessonIdentity,
  question: PracticeQuestion,
  choiceId: string,
  env: Environment,
): Promise<AnswerReceipt> {
  if (question.kind !== 'mcq') throw new Error('unsupported question kind');
  if (!choicesOf(question).some((choice) => choice.id === choiceId)) {
    throw new Error('choice is not part of this question');
  }
  const opId = env.newId().toLowerCase();
  const isCorrect = correctChoiceOf(question) === choiceId;
  await account.recordAnswer({
    opId,
    questionRevisionId: question.id,
    lessonRevisionId: lesson.revisionId,
    lessonId: lesson.lessonId,
    choiceId,
    localIsCorrect: isCorrect,
    recordedAt: env.now().toISOString(),
    ref: refOf(lesson, env.now().toISOString()),
  });
  return { opId, isCorrect };
}

/** Mark the saved revision of a lesson as finished. False if it already was. */
export function completeLesson(
  account: AccountStore,
  lesson: LessonIdentity,
  env: Environment,
): Promise<boolean> {
  return account.recordLessonCompleted({
    opId: env.newId().toLowerCase(),
    lessonId: lesson.lessonId,
    lessonRevisionId: lesson.revisionId,
    recordedAt: env.now().toISOString(),
    ref: refOf(lesson, env.now().toISOString()),
  });
}

export interface SaveLessonResult {
  revisionId: string;
  /** 'new' first save, 'updated' a different revision replaced the saved one, 'unchanged' same revision. */
  outcome: 'new' | 'updated' | 'unchanged';
}

/**
 * Download one lesson snapshot and save it for offline study.
 *
 * Order matters: download completely → validate → replace in one transaction.
 * Any failure before the transaction (network cut, truncated body, wrong lesson
 * or language, malformed content) leaves the previously saved copy untouched.
 */
export async function saveLessonOffline(
  api: Pick<ApiClient, 'getLesson'>,
  content: ContentStore,
  lessonId: string,
  locale: Locale,
  env: Pick<Environment, 'now'>,
): Promise<SaveLessonResult> {
  const previous = await content.getLessonInfo(lessonId, locale);
  const downloaded = await api.getLesson(lessonId, locale);
  const snapshot = validateLessonSnapshot(downloaded, { lessonId, locale });
  if (previous && previous.revisionId === snapshot.revision_id) {
    return { revisionId: snapshot.revision_id, outcome: 'unchanged' };
  }
  await content.replaceLesson(snapshot, env.now().toISOString());
  return { revisionId: snapshot.revision_id, outcome: previous ? 'updated' : 'new' };
}

/** Fetch the catalog and cache it. Screens read the cache; this only refreshes it. */
export async function refreshCatalog(
  api: Pick<ApiClient, 'getCatalog'>,
  content: ContentStore,
  locale: Locale,
  env: Pick<Environment, 'now'>,
): Promise<void> {
  const catalog = await api.getCatalog(locale);
  if (!catalog || catalog.locale !== locale || !Array.isArray(catalog.courses)) {
    throw new Error('unexpected catalog response');
  }
  await content.saveCatalog(catalog, env.now().toISOString());
}
