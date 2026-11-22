import { ApiError, isTransient } from '../../src/core/api/errors';
import { SnapshotError, validateLessonSnapshot } from '../../src/core/api/validate';
import { STRINGS } from '../../src/core/i18n/strings';
import { backoffDelay } from '../../src/core/sync/engine';

const LESSON = 'b0000000-0000-4000-8000-000000000005';

function snapshot(): Record<string, unknown> {
  return {
    lesson_id: LESSON,
    revision_id: 'c0000000-0000-4000-8000-000000000001',
    revision: 1,
    locale: 'fr',
    title: 'Titre',
    blocks: [{ key: 'p', type: 'paragraph', text: 'Texte' }],
    questions: [
      {
        id: 'd0000000-0000-4000-8000-000000000101',
        question_key: 'q1',
        position: 1,
        kind: 'mcq',
        prompt: { text: '?' },
        response_spec: { choices: [{ id: 'a', text: '1' }, { id: 'b', text: '2' }] },
        answer_key: { correct_choice_id: 'b' },
        explanation: { text: '.' },
      },
    ],
    assessment_mode: 'offline_practice',
  };
}

function reasonFor(mutate: (s: any) => void, expected = { lessonId: LESSON, locale: 'fr' as const }): string {
  const value = snapshot();
  mutate(value);
  try {
    validateLessonSnapshot(value, expected);
  } catch (error) {
    if (error instanceof SnapshotError) return error.reason;
    throw error;
  }
  return 'accepted';
}

describe('lesson snapshot validation', () => {
  test('accepts a complete snapshot', () => {
    expect(reasonFor(() => undefined)).toBe('accepted');
  });

  test.each([
    ['another lesson than requested', (s: any) => (s.lesson_id = 'b0000000-0000-4000-8000-000000000099'), 'wrong_lesson'],
    ['another language than requested', (s: any) => (s.locale = 'ht'), 'wrong_locale'],
    ['no revision id', (s: any) => delete s.revision_id, 'missing_revision_id'],
    ['non-integer revision', (s: any) => (s.revision = '1'), 'missing_revision_number'],
    ['empty body', (s: any) => (s.blocks = []), 'missing_blocks'],
    ['block without type', (s: any) => (s.blocks = [{ key: 'p' }]), 'malformed_block'],
    ['questions missing', (s: any) => delete s.questions, 'missing_questions'],
    ['duplicate question ids', (s: any) => s.questions.push({ ...s.questions[0] }), 'duplicate_question'],
    ['one choice only', (s: any) => (s.questions[0].response_spec.choices = [{ id: 'a', text: '1' }]), 'malformed_choices'],
    ['duplicate choice ids', (s: any) => (s.questions[0].response_spec.choices[1].id = 'a'), 'duplicate_choice'],
    ['answer key not among the choices', (s: any) => (s.questions[0].answer_key.correct_choice_id = 'z'), 'answer_key_not_in_choices'],
    ['no answer key', (s: any) => (s.questions[0].answer_key = {}), 'answer_key_not_in_choices'],
  ])('refuses %s', (_name, mutate, reason) => {
    expect(reasonFor(mutate)).toBe(reason);
  });

  test('refuses non-objects', () => {
    for (const value of [null, 'text', 42, []]) {
      expect(() => validateLessonSnapshot(value, { lessonId: LESSON, locale: 'fr' })).toThrow(SnapshotError);
    }
  });
});

describe('retry backoff', () => {
  test('grows exponentially, is capped, and jitter stays within 50-100%', () => {
    const noJitter = () => 1;
    expect([0, 1, 2, 3, 4, 5, 6].map((n) => backoffDelay(n, 1000, 30000, noJitter))).toEqual([
      1000, 2000, 4000, 8000, 16000, 30000, 30000,
    ]);
    expect(backoffDelay(2, 1000, 30000, () => 0)).toBe(2000);
    for (let i = 0; i < 200; i += 1) {
      const delay = backoffDelay(3, 1000, 30000, Math.random);
      expect(delay).toBeGreaterThanOrEqual(4000);
      expect(delay).toBeLessThanOrEqual(8000);
    }
  });
});

describe('error classification', () => {
  test('only network, timeout and server failures are retried', () => {
    expect(isTransient(new ApiError('network', 'x'))).toBe(true);
    expect(isTransient(new ApiError('timeout', 'x'))).toBe(true);
    expect(isTransient(new ApiError('server', 'x', 503))).toBe(true);
    expect(isTransient(new ApiError('client', 'x', 422))).toBe(false);
    expect(isTransient(new ApiError('auth_required', 'x', 401))).toBe(false);
    expect(isTransient(new ApiError('aborted', 'x'))).toBe(false);
    expect(isTransient(new Error('boom'))).toBe(false);
  });
});

describe('translations', () => {
  test('French and Haitian Creole define exactly the same keys, none empty', () => {
    const fr = Object.keys(STRINGS.fr).sort();
    const ht = Object.keys(STRINGS.ht).sort();
    expect(ht).toEqual(fr);
    for (const locale of ['fr', 'ht'] as const) {
      for (const [key, value] of Object.entries(STRINGS[locale])) {
        expect(`${key}=${value.trim().length > 0}`).toBe(`${key}=true`);
      }
    }
  });
});
