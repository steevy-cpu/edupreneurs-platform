/**
 * Renders one real screen of the app in Node.
 *
 *   storage   real SQLite files in a temp directory (the same store classes the phone uses)
 *   app state a hand-built stand-in for AppContext, so a test decides the sync state it wants to show
 *   lesson    a tiny synthetic lesson written through ContentStore.replaceLesson
 *
 * No network is involved at any point.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import React from 'react';
import { act, create, ReactTestInstance, ReactTestRenderer } from 'react-test-renderer';

import type { CatalogResponse, LessonResponse, Locale } from '../../src/core/api/types';
import { AccountStore, SyncSummary } from '../../src/core/db/accountStore';
import { ContentStore } from '../../src/core/db/contentStore';
import { translator } from '../../src/core/i18n/strings';
import type { SyncReport } from '../../src/core/sync/engine';
import { DesignProvider } from '../../src/design';
import { nodeDatabases } from './nodeSqlite';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// react-test-renderer prints one deprecation notice per render; it is the only renderer
// that works without a native runtime, so the notice is dropped. Every other error is kept.
const reportError = console.error.bind(console);
console.error = (...args: unknown[]) => {
  if (typeof args[0] === 'string' && args[0].includes('react-test-renderer is deprecated')) return;
  reportError(...args);
};

export const LESSON_ID = 'lesson-1';
export const OTHER_LESSON_ID = 'lesson-2';

export function lessonSnapshot(locale: Locale = 'fr', lessonId = LESSON_ID): LessonResponse {
  const question = (n: number, prompt: string, correct: string) => ({
    id: `${lessonId}-${locale}-q${n}`,
    question_key: `q${n}`,
    position: n,
    kind: 'mcq',
    prompt: { text: prompt },
    response_spec: {
      choices: [
        { id: 'a', text: 'x = 2' },
        { id: 'b', text: 'x = 7' },
      ],
    },
    answer_key: { correct_choice_id: correct },
    explanation: { text: `Explication ${n}` },
  });
  return {
    assessment_mode: 'offline_practice',
    lesson_id: lessonId,
    locale,
    revision: 3,
    revision_id: `${lessonId}-${locale}-r3`,
    title: locale === 'fr' ? 'Résoudre une équation simple' : 'Rezoud yon ekwasyon senp',
    blocks: [
      { key: 'h1', type: 'heading', text: 'La règle de la balance' },
      { key: 'p1', type: 'paragraph', text: 'Une équation est une égalité.' },
      { key: 'e1', type: 'example', title: 'x + 5 = 12', steps: ['On retire 5', 'x = 7'] },
      { key: 'c1', type: 'callout', text: 'Vérifie toujours ta réponse.' },
      { key: 'u1', type: 'something-new', text: 'Bloc d’un type inconnu.' },
    ],
    questions: [question(1, 'Résous : x + 5 = 12', 'b'), question(2, 'Résous : 5x = 10', 'a')],
  };
}

export function catalog(locale: Locale = 'fr'): CatalogResponse {
  return {
    locale,
    courses: [
      {
        id: 'course-1',
        slug: 'maths-9af',
        title: 'Mathématiques 9AF',
        grade: { code: '9AF', label: '9e année fondamentale' },
        subject: { slug: 'mathematiques', label: 'Mathématiques' },
        units: [
          {
            id: 'unit-1',
            slug: 'equations',
            title: 'Équations du premier degré',
            position: 1,
            lessons: [
              {
                id: LESSON_ID,
                slug: 'l1',
                position: 1,
                revision: 3,
                revision_id: `${LESSON_ID}-${locale}-r3`,
                title: 'Résoudre une équation simple',
              },
              {
                id: OTHER_LESSON_ID,
                slug: 'l2',
                position: 2,
                revision: 1,
                revision_id: `${OTHER_LESSON_ID}-${locale}-r1`,
                title: 'Vérifier une solution',
              },
            ],
          },
        ],
      },
    ],
  };
}

export interface FakeApp {
  boot: 'ready';
  bootError: null;
  services: { content: ContentStore; env: { newId: () => string; now: () => Date } };
  session: { email: string; userId: string; account: AccountStore; isActive: () => boolean; needsReauth: () => boolean };
  needsReauth: boolean;
  locale: Locale;
  t: ReturnType<typeof translator>;
  sync: { phase: 'idle' | 'syncing' | 'waiting_to_retry'; summary: SyncSummary; lastReport: SyncReport | null };
  api: null;
  calls: string[];
  setLocale(locale: Locale): Promise<void>;
  signIn(): Promise<void>;
  signOut(): Promise<void>;
  syncNow(): Promise<SyncReport | null>;
  refreshSummary(): Promise<void>;
}

export class Phone {
  readonly dir = fs.mkdtempSync(path.join(os.tmpdir(), 'edu-screen-'));
  private readonly open = nodeDatabases(this.dir);
  content!: ContentStore;
  private accounts = new Map<string, AccountStore>();
  private counter = 0;
  renderer: ReactTestRenderer | null = null;
  app!: FakeApp;

  async start(): Promise<this> {
    this.content = await ContentStore.open(await this.open('content'));
    return this;
  }

  /** Sign a (synthetic) student in: their own database file, like the real SessionManager. */
  async signIn(name: 'student.a' | 'student.b', locale: Locale = 'fr'): Promise<FakeApp> {
    const userId = `user-${name}`;
    let account = this.accounts.get(userId);
    if (!account) {
      account = await AccountStore.open(await this.open(`account-${userId}`), userId);
      this.accounts.set(userId, account);
    }
    const app: FakeApp = {
      boot: 'ready',
      bootError: null,
      services: {
        content: this.content,
        env: {
          newId: () => `00000000-0000-4000-8000-${String((this.counter += 1)).padStart(12, '0')}`,
          now: () => new Date(Date.UTC(2026, 10, 24, 12, 0, (this.counter += 1))),
        },
      },
      session: { email: `${name}@edupreneur.test`, userId, account, isActive: () => this.app === app, needsReauth: () => false },
      needsReauth: false,
      locale,
      t: translator(locale),
      sync: { phase: 'idle', summary: await account.syncSummary(), lastReport: null },
      api: null,
      calls: [],
      setLocale: async (next) => void app.calls.push(`setLocale ${next}`),
      signIn: async () => undefined,
      signOut: async () => void app.calls.push('signOut'),
      syncNow: async () => {
        app.calls.push('syncNow');
        return app.sync.lastReport;
      },
      refreshSummary: async () => {
        app.sync = { ...app.sync, summary: await account.syncSummary() };
      },
    };
    this.app = app;
    return app;
  }

  async render(screen: React.ReactElement): Promise<Screen> {
    await this.unmount();
    await act(async () => {
      this.renderer = create(
        <DesignProvider theme="light" locale={this.app.locale}>
          {screen}
        </DesignProvider>,
      );
    });
    const view = new Screen(this.renderer!);
    await view.settle();
    return view;
  }

  async unmount(): Promise<void> {
    if (!this.renderer) return;
    const renderer = this.renderer;
    this.renderer = null;
    await act(async () => renderer.unmount());
  }

  async dispose(): Promise<void> {
    await this.unmount();
    await this.content.close().catch(() => undefined);
    for (const account of this.accounts.values()) await account.close().catch(() => undefined);
    fs.rmSync(this.dir, { recursive: true, force: true });
  }
}

function flatten(children: unknown): string {
  if (children === null || children === undefined || typeof children === 'boolean') return '';
  if (typeof children === 'string' || typeof children === 'number') return String(children);
  if (Array.isArray(children)) return children.map(flatten).join('');
  return '';
}

export class Screen {
  constructor(private readonly renderer: ReactTestRenderer) {}

  /** Let pending promises (SQLite reads, effects) finish and React re-render. */
  async settle(rounds = 6): Promise<void> {
    for (let i = 0; i < rounds; i += 1) {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 15));
      });
    }
  }

  /** Every piece of text on the screen, in reading order. */
  texts(): string[] {
    return this.renderer.root
      .findAll((node) => (node.type as unknown) === 'Text')
      .map((node) => flatten(node.props.children))
      .filter((text) => text.length > 0);
  }

  text(): string {
    return this.texts().join('\n');
  }

  has(fragment: string): boolean {
    return this.text().includes(fragment);
  }

  pressables(): ReactTestInstance[] {
    return this.renderer.root.findAll((node) => (node.type as unknown) === 'Pressable');
  }

  /** Accessible names of everything that can be pressed (what a screen reader would announce). */
  labels(): string[] {
    return this.pressables().map((node) => String(node.props.accessibilityLabel ?? ''));
  }

  find(label: string | RegExp): ReactTestInstance {
    const match = this.pressables().find((node) => {
      const name = String(node.props.accessibilityLabel ?? '');
      return typeof label === 'string' ? name === label : label.test(name);
    });
    if (!match) throw new Error(`no pressable labelled ${label}; have: ${this.labels().join(' | ')}`);
    return match;
  }

  async press(label: string | RegExp): Promise<void> {
    const node = this.find(label);
    if (node.props.disabled) throw new Error(`"${label}" is disabled`);
    await act(async () => {
      (node.props.onPress as () => void)();
    });
    await this.settle(3);
  }

  redirect(): string | null {
    const found = this.renderer.root.findAll((node) => (node.type as unknown) === 'Redirect');
    return found.length > 0 ? String(found[0].props.href) : null;
  }
}
