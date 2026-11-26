import React from 'react';
import Profile from '../../src/app/profile';
import LessonReader from '../../src/app/lesson/[id]';
import { navigation } from '../support/expoRouterMock';
import { ApiClient } from '../../src/core/api/client';
import { completeLesson } from '../../src/core/learning/actions';
import { Phone } from '../support/screenHarness';

const mockPhone: { current?: Phone } = {};
jest.mock('../../src/ui/AppContext', () => ({ useApp: () => mockPhone.current!.app }));

it.each(['fr', 'ht'] as const)('service recovery preserves both queued operations in Profile (%s)', async locale => {
  const phone = await new Phone().start();
  mockPhone.current = phone;
  try {
    const app = await phone.signIn('student.a', locale);
    const account = app.session.account;
    for (const id of ['one', 'two']) {
      await completeLesson(account, { lessonId: id, revisionId: id }, app.services.env);
    }
    await app.refreshSummary();
    const queued = await account.pendingOperations(10);
    expect(queued).toHaveLength(2);
    app.sync.lastReport = { outcome: 'offline', errorCode: 'unreachable', confirmed: 0, needsAttention: 0, pulled: 0 };
    let online = false;
    const reads: string[] = [];
    const client = new ApiClient({
      baseUrl: 'https://qa.invalid',
      getAccessToken: async () => 'synthetic',
      onReachability: value => { app.sync.serviceReachable = value; },
      fetchImpl: async (input, options) => {
        reads.push(String(input));
        expect(options?.method).toBe('GET');
        if (!online) throw new TypeError('Synthetic connection loss');
        return { status: 200, text: async () => '{}' } as Response;
      },
    });
    await expect(client.getMe()).rejects.toMatchObject({ kind: 'network' });
    const before = await phone.render(<Profile />);
    expect(before.has(app.t('offline'))).toBe(true);
    expect(before.has(app.t('syncOffline'))).toBe(true);
    online = true;
    await client.getMe();
    const after = await phone.render(<Profile />);
    expect(after.has(app.t('offline'))).toBe(false);
    expect(after.has(app.t('syncOffline'))).toBe(false);
    expect(app.sync.lastReport.confirmed).toBe(0);
    expect(await account.pendingOperations(10)).toEqual(queued);
    expect((await account.syncSummary()).lastSyncAt).toBeNull();
    expect(reads).toEqual(['https://qa.invalid/v1/me', 'https://qa.invalid/v1/me']);
  } finally {
    await phone.dispose();
  }
});

it.each(['fr', 'ht'] as const)('an HTTP 200 with unreadable content does not diagnose Internet loss (%s)', async locale => {
  const phone = await new Phone().start();
  mockPhone.current = phone;
  try {
    const app = await phone.signIn('student.a', locale);
    app.api = new ApiClient({
      baseUrl: 'https://qa.invalid',
      getAccessToken: async () => 'synthetic',
      onReachability: value => { app.sync.serviceReachable = value; },
      fetchImpl: async () => ({ status: 200, text: async () => 'temporarily unavailable' }) as Response,
    });
    navigation.params = { id: 'qa-lesson', mode: 'online' };
    const screen = await phone.render(<LessonReader />);
    expect(screen.labels()).toContain(app.t('readerRetry'));
    expect(await phone.content.listSavedLessons(locale)).toEqual([]);
    expect({ noInternetMessage: screen.has(app.t('readerFailOffline')), offlineBadge: screen.has(app.t('offline')) })
      .toEqual({ noInternetMessage: false, offlineBadge: false });
  } finally {
    await phone.dispose();
  }
});
