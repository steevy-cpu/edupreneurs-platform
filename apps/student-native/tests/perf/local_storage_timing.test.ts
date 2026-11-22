/**
 * Timing of the local-storage paths, measured in Node on the development Mac.
 *
 * THIS IS NOT A DEVICE MEASUREMENT. It shows that the queries themselves are
 * cheap and need no network; it says nothing about a low-memory Android phone,
 * where app start-up, the JS engine and flash storage dominate.
 */
import { answerQuestion, saveLessonOffline } from '../../src/core/learning/actions';
import { credentials, Device, resetServerLearningState, SEED } from '../support/device';

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

test('cold open of saved lesson and durable answer write (Node, development machine)', async () => {
  resetServerLearningState();
  const device = new Device();
  try {
    let app = await device.boot();
    const { email, password } = await credentials('student_a');
    const session = await app.sessions.signIn(email, password);
    await saveLessonOffline(device.api(app.sessions, session), app.content, SEED.lessonId, 'fr', device.env);
    device.network.mode = 'offline';

    const coldOpen: number[] = [];
    for (let i = 0; i < 15; i += 1) {
      await device.kill();
      const start = performance.now();
      app = await device.boot(); // open both databases, run migrations check, restore session
      const lesson = await app.content.getLesson(SEED.lessonId, 'fr');
      await app.session!.account.questionProgress(SEED.lessonId);
      coldOpen.push(performance.now() - start);
      expect(lesson!.questions).toHaveLength(5);
    }

    const lesson = (await app.content.getLesson(SEED.lessonId, 'fr'))!;
    const writes: number[] = [];
    for (let i = 0; i < 50; i += 1) {
      const start = performance.now();
      await answerQuestion(app.session!.account, lesson, lesson.questions[i % 5], 'a', device.env);
      writes.push(performance.now() - start);
    }
    const networkCallsWhileOffline = device.network.calls.filter((c) => !c.url.includes('/auth/')).length;

    // eslint-disable-next-line no-console
    console.log(
      `[perf, Node on dev Mac, NOT a phone] cold open storage + read saved lesson: median ${median(coldOpen).toFixed(1)} ms ` +
        `(max ${Math.max(...coldOpen).toFixed(1)} ms) | durable answer write (attempt + projection + outbox, fsync): ` +
        `median ${median(writes).toFixed(1)} ms (max ${Math.max(...writes).toFixed(1)} ms)`,
    );
    expect(median(coldOpen)).toBeLessThan(1000);
    expect(networkCallsWhileOffline).toBeGreaterThan(0); // the save itself used the network ...
    const before = device.network.calls.length;
    await app.content.getLesson(SEED.lessonId, 'fr');
    expect(device.network.calls.length).toBe(before); // ... reopening never does
  } finally {
    await device.dispose();
  }
});
