import type { LessonResponse, Locale } from './types';

/** Why a downloaded lesson snapshot was refused. The saved copy is never touched in that case. */
export class SnapshotError extends Error {
  constructor(readonly reason: string) {
    super(`invalid lesson snapshot: ${reason}`);
    this.name = 'SnapshotError';
  }
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Structural validation of a lesson snapshot before it replaces the saved copy.
 *
 * This checks that the snapshot is complete and self-consistent and is the
 * lesson + language that was asked for. It is NOT an integrity or authenticity
 * guarantee: the API provides no checksum or signature yet (see MOBILE_01_REPORT).
 */
export function validateLessonSnapshot(
  value: unknown,
  expected: { lessonId: string; locale: Locale },
): LessonResponse {
  if (!isRecord(value)) throw new SnapshotError('not_an_object');
  const lesson = value as Partial<LessonResponse>;
  if (lesson.lesson_id !== expected.lessonId) throw new SnapshotError('wrong_lesson');
  if (lesson.locale !== expected.locale) throw new SnapshotError('wrong_locale');
  if (typeof lesson.revision_id !== 'string' || !UUID.test(lesson.revision_id)) {
    throw new SnapshotError('missing_revision_id');
  }
  if (typeof lesson.revision !== 'number' || !Number.isInteger(lesson.revision) || lesson.revision < 1) {
    throw new SnapshotError('missing_revision_number');
  }
  if (typeof lesson.title !== 'string' || lesson.title.length === 0) {
    throw new SnapshotError('missing_title');
  }
  if (!Array.isArray(lesson.blocks) || lesson.blocks.length === 0) {
    throw new SnapshotError('missing_blocks');
  }
  for (const block of lesson.blocks) {
    if (!isRecord(block) || typeof block.type !== 'string' || typeof block.key !== 'string') {
      throw new SnapshotError('malformed_block');
    }
  }
  if (!Array.isArray(lesson.questions)) throw new SnapshotError('missing_questions');

  const seen = new Set<string>();
  for (const question of lesson.questions) {
    if (!isRecord(question) || typeof question.id !== 'string' || !UUID.test(question.id)) {
      throw new SnapshotError('malformed_question');
    }
    if (seen.has(question.id)) throw new SnapshotError('duplicate_question');
    seen.add(question.id);
    if (typeof question.position !== 'number' || typeof question.kind !== 'string') {
      throw new SnapshotError('malformed_question');
    }
    if (!isRecord(question.prompt) || !isRecord(question.explanation)) {
      throw new SnapshotError('malformed_question');
    }
    if (question.kind === 'mcq') {
      const choices = isRecord(question.response_spec) ? question.response_spec.choices : null;
      if (!Array.isArray(choices) || choices.length < 2) throw new SnapshotError('malformed_choices');
      const ids = new Set<string>();
      for (const choice of choices) {
        if (!isRecord(choice) || typeof choice.id !== 'string' || typeof choice.text !== 'string') {
          throw new SnapshotError('malformed_choices');
        }
        ids.add(choice.id);
      }
      if (ids.size !== choices.length) throw new SnapshotError('duplicate_choice');
      const correct = isRecord(question.answer_key) ? question.answer_key.correct_choice_id : null;
      if (typeof correct !== 'string' || !ids.has(correct)) {
        throw new SnapshotError('answer_key_not_in_choices');
      }
    }
  }
  return lesson as LessonResponse;
}
