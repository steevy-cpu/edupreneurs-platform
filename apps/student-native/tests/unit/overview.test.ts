import { STRINGS } from '../../src/core/i18n/strings';
import { LessonStanding, pickContinueLesson, syncDisplayOf } from '../../src/core/learning/overview';

function standing(lessonId: string, completed: boolean): LessonStanding {
  return {
    lessonId,
    title: lessonId,
    revision: 1,
    revisionId: `${lessonId}-r1`,
    questionCount: 5,
    answered: 0,
    correct: 0,
    missedQuestionIds: [],
    waiting: 0,
    refused: 0,
    completed,
    completionState: completed ? 'synced' : null,
  };
}

describe('Continue learning', () => {
  const lessons = [standing('one', true), standing('two', false), standing('three', false)];
  test('nothing saved: no card', () => {
    expect(pickContinueLesson([], 'one')).toBeNull();
  });
  test('the lesson opened last wins, even if it is finished', () => {
    expect(pickContinueLesson(lessons, 'one')!.lessonId).toBe('one');
  });
  test('otherwise the first unfinished saved lesson', () => {
    expect(pickContinueLesson(lessons, null)!.lessonId).toBe('two');
    expect(pickContinueLesson(lessons, 'no-longer-saved')!.lessonId).toBe('two');
  });
  test('everything finished: the first saved lesson, so the student can revisit', () => {
    expect(pickContinueLesson([standing('one', true)], null)!.lessonId).toBe('one');
  });
});

describe('sync display', () => {
  test('"synced" only when nothing is waiting and nothing was refused', () => {
    expect(syncDisplayOf({ pending: 0, needsAttention: 0 }, 'ok')).toBe('synced');
    expect(syncDisplayOf({ pending: 0, needsAttention: 0 }, null)).toBe('synced');
    expect(syncDisplayOf({ pending: 1, needsAttention: 0 }, 'ok')).toBe('pending');
    expect(syncDisplayOf({ pending: 1, needsAttention: 0 }, 'offline')).toBe('failed');
    expect(syncDisplayOf({ pending: 1, needsAttention: 0 }, 'error')).toBe('failed');
    expect(syncDisplayOf({ pending: 1, needsAttention: 0 }, 'auth_required')).toBe('failed');
    expect(syncDisplayOf({ pending: 0, needsAttention: 2 }, 'ok')).toBe('attention');
    expect(syncDisplayOf({ pending: 3, needsAttention: 2 }, 'ok')).toBe('pending');
  });
});

describe('navigation labels', () => {
  test('the fourth tab is Profil in French and Pwofil in Haitian Creole', () => {
    expect(STRINGS.fr.tabProfile).toBe('Profil');
    expect(STRINGS.ht.tabProfile).toBe('Pwofil');
    expect([STRINGS.fr.tabHome, STRINGS.fr.tabLearn, STRINGS.fr.tabReview]).toEqual(['Accueil', 'Apprendre', 'Réviser']);
  });
});
