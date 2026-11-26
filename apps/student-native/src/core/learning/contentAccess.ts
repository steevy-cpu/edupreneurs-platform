import { ApiClient } from '../api/client';
import { isTransient } from '../api/errors';
import type { LessonResponse, Locale } from '../api/types';
import { validateLessonSnapshot } from '../api/validate';
import { ContentStore, SavedLesson } from '../db/contentStore';
import { saveLessonOffline, SaveLessonResult } from './actions';

/**
 * Unified access to one published lesson, in two explicit modes:
 *
 *   read online   — fetched through the authenticated API, validated, held in memory only
 *   downloaded    — saved in the content SQLite by an explicit "Download" action
 *
 * Both produce the same `ReadableLesson`, so the reader and the quiz screens are the
 * same components for both. Reading online NEVER writes to `saved_lessons`: a lesson is
 * "downloaded" only after `downloadForOffline` has committed.
 *
 * The student's own work (answers, completion, pending sync operations) is a separate
 * concern and is always written to the account database by the existing actions.
 */

export type LessonSource = 'online' | 'downloaded';

/** What the reader and quiz need. `savedAt` is null for a lesson that is not downloaded. */
export type ReadableLesson = Omit<SavedLesson, 'savedAt'> & {
  source: LessonSource;
  savedAt: string | null;
};

function fromSnapshot(snapshot: LessonResponse, source: LessonSource, savedAt: string | null): ReadableLesson {
  return {
    lessonId: snapshot.lesson_id,
    locale: snapshot.locale,
    revisionId: snapshot.revision_id,
    revision: snapshot.revision,
    title: snapshot.title,
    blocks: snapshot.blocks,
    questions: snapshot.questions,
    source,
    savedAt,
  };
}

/**
 * In-memory holder for lessons read online during this app run. Nothing here survives a
 * restart, and nothing here counts as "downloaded". It exists so that opening the exercises
 * from the reader (or coming back to the reader) does not refetch the same lesson.
 * Bounded, so a long session cannot grow memory on a low-RAM phone.
 */
export class SessionLessonCache {
  private readonly entries = new Map<string, { lesson: ReadableLesson; at: number }>();

  constructor(
    private readonly options: { maxEntries?: number; ttlMs?: number; clock?: () => number } = {},
  ) {}

  private key(lessonId: string, locale: Locale): string {
    return `${locale}:${lessonId}`;
  }

  get(lessonId: string, locale: Locale): ReadableLesson | null {
    const key = this.key(lessonId, locale);
    const entry = this.entries.get(key);
    if (!entry) return null;
    const now = (this.options.clock ?? Date.now)();
    if (now - entry.at > (this.options.ttlMs ?? 15 * 60_000)) {
      this.entries.delete(key);
      return null;
    }
    return entry.lesson;
  }

  put(lesson: ReadableLesson): void {
    const key = this.key(lesson.lessonId, lesson.locale);
    this.entries.delete(key); // re-insert so the newest is last
    this.entries.set(key, { lesson, at: (this.options.clock ?? Date.now)() });
    const max = this.options.maxEntries ?? 4;
    while (this.entries.size > max) {
      const oldest = this.entries.keys().next().value as string;
      this.entries.delete(oldest);
    }
  }

  clear(): void {
    this.entries.clear();
  }

  get size(): number {
    return this.entries.size;
  }
}

/** The downloaded copy of a lesson, or null. Reads SQLite only; never the network. */
export async function getDownloaded(
  content: ContentStore,
  lessonId: string,
  locale: Locale,
): Promise<ReadableLesson | null> {
  const saved = await content.getLesson(lessonId, locale);
  return saved ? { ...saved, source: 'downloaded' } : null;
}

/**
 * Fetch a published lesson through the API for reading now. Validates it exactly like a
 * download does, and keeps it in memory only. Throws (an ApiError or SnapshotError) on any
 * failure; nothing is stored in that case.
 */
export async function readOnline(
  api: Pick<ApiClient, 'getLesson'>,
  cache: SessionLessonCache,
  lessonId: string,
  locale: Locale,
  options: { refresh?: boolean } = {},
): Promise<ReadableLesson> {
  if (!options.refresh) {
    const hit = cache.get(lessonId, locale);
    if (hit) return hit;
  }
  const snapshot = validateLessonSnapshot(await api.getLesson(lessonId, locale), { lessonId, locale });
  const lesson = fromSnapshot(snapshot, 'online', null);
  cache.put(lesson);
  return lesson;
}

export type OpenResult =
  | { kind: 'ready'; lesson: ReadableLesson }
  /** Online reading was asked for but failed. `downloaded` is the saved copy, if there is one, to offer instead. */
  | { kind: 'unavailable'; reason: 'offline' | 'not_found' | 'session' | 'invalid'; downloaded: ReadableLesson | null }
  /** Opened without asking for the network and there is no saved copy. */
  | { kind: 'missing' };

function reasonOf(error: unknown): 'offline' | 'not_found' | 'session' | 'invalid' {
  if (isTransient(error)) return 'offline';
  const kind = (error as { kind?: string } | null)?.kind;
  const status = (error as { status?: number | null } | null)?.status;
  if (kind === 'auth_required' || kind === 'aborted') return 'session';
  if (status === 404) return 'not_found';
  return 'invalid';
}

/**
 * Open a lesson for the reader.
 *   mode 'saved'  — SQLite only (the default, and the only mode that works with no connection)
 *   mode 'online' — the network; on failure the result says why and carries the saved copy, if any
 */
export async function openLesson(
  deps: { api: Pick<ApiClient, 'getLesson'> | null; content: ContentStore; cache: SessionLessonCache },
  lessonId: string,
  locale: Locale,
  mode: 'saved' | 'online',
): Promise<OpenResult> {
  if (mode === 'saved') {
    const lesson = await getDownloaded(deps.content, lessonId, locale);
    return lesson ? { kind: 'ready', lesson } : { kind: 'missing' };
  }
  try {
    if (!deps.api) throw Object.assign(new Error('no session'), { kind: 'auth_required' });
    return { kind: 'ready', lesson: await readOnline(deps.api, deps.cache, lessonId, locale) };
  } catch (error) {
    return {
      kind: 'unavailable',
      reason: reasonOf(error),
      downloaded: await getDownloaded(deps.content, lessonId, locale),
    };
  }
}

/**
 * Explicit download for offline study (the existing, tested path): download completely →
 * validate → replace in one transaction. A failure leaves any previous copy untouched.
 */
export function downloadForOffline(
  api: Pick<ApiClient, 'getLesson'>,
  content: ContentStore,
  lessonId: string,
  locale: Locale,
  env: { now: () => Date },
): Promise<SaveLessonResult> {
  return saveLessonOffline(api, content, lessonId, locale, env);
}

/**
 * Remove the downloaded copy of a lesson (and its saved questions). This touches only the
 * shared public content database: the student's answers, completions and pending sync
 * operations live in the account database and are not reachable from here.
 */
export function removeDownloaded(content: ContentStore, lessonId: string, locale: Locale): Promise<boolean> {
  return content.deleteLesson(lessonId, locale);
}

export type UpdateStatus = 'not_downloaded' | 'up_to_date' | 'update_available';

/**
 * Compare the downloaded revision with the revision the catalog currently lists.
 * Reads only local data (the cached catalog); the catalog refresh is a separate step.
 */
export async function checkForUpdates(
  content: ContentStore,
  lessonId: string,
  locale: Locale,
): Promise<UpdateStatus> {
  const saved = await content.getLessonInfo(lessonId, locale);
  if (!saved) return 'not_downloaded';
  const cached = await content.getCatalog(locale);
  if (!cached) return 'up_to_date';
  for (const course of cached.catalog.courses) {
    for (const unit of course.units) {
      const listed = unit.lessons.find((lesson) => lesson.id === lessonId);
      if (listed) return listed.revision_id === saved.revisionId ? 'up_to_date' : 'update_available';
    }
  }
  return 'up_to_date';
}
