/**
 * Boundaries that must hold for the experience additions, checked on the source tree:
 * no new dependency, no fixture in a production path, a leaderboard fixture
 * nobody could take for real learners, and no production code path that ranks.
 */
import fs from 'node:fs';
import path from 'node:path';

import { STRINGS } from '../../src/core/i18n/strings';
import { LEADERBOARD_FIXTURE, LEADERBOARD_FIXTURE_MARK } from '../../src/design/preview/leaderboardFixture';

const ROOT = path.resolve(__dirname, '..', '..');
const SRC = path.join(ROOT, 'src');

function sourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.tsx?$/.test(entry.name) && !entry.name.endsWith('.d.ts') ? [full] : [];
  });
}

const isPreview = (file: string) =>
  file.startsWith(path.join(SRC, 'app', 'design') + path.sep) || file.startsWith(path.join(SRC, 'design', 'preview') + path.sep);
const production = sourceFiles(SRC).filter((file) => !isPreview(file));

test('no runtime dependency was added', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8')) as { dependencies: Record<string, string> };
  expect(Object.keys(manifest.dependencies).sort()).toEqual([
    'expo',
    'expo-constants',
    'expo-crypto',
    'expo-linking',
    'expo-router',
    'expo-secure-store',
    'expo-sqlite',
    'expo-status-bar',
    'react',
    'react-dom',
    'react-native',
    'react-native-safe-area-context',
    'react-native-screens',
  ]);
});

test('no production file imports a preview module (fixtures stay out of production bundles)', () => {
  const offenders = production.filter((file) => /from\s+['"][^'"]*design\/preview[^'"]*['"]/.test(fs.readFileSync(file, 'utf8')));
  expect(offenders.map((file) => path.relative(ROOT, file))).toEqual([]);
});

test('the leaderboard fixture is unmistakably synthetic and lives only in the preview folder', () => {
  expect(LEADERBOARD_FIXTURE.length).toBeGreaterThanOrEqual(4);
  expect(LEADERBOARD_FIXTURE.map((entry) => entry.rank)).toEqual(LEADERBOARD_FIXTURE.map((_, index) => index + 1));
  for (const [index, entry] of LEADERBOARD_FIXTURE.entries()) {
    expect(entry.pseudonym.endsWith(LEADERBOARD_FIXTURE_MARK)).toBe(true);
    expect(entry.pseudonym).not.toMatch(/\s/); // one made-up word, never a first name + surname
    expect(entry.gold % 100).toBe(0); // round placeholders, not plausible scores
    if (index > 0) expect(entry.gold).toBeLessThan(LEADERBOARD_FIXTURE[index - 1].gold);
  }
  expect(new Set(LEADERBOARD_FIXTURE.map((entry) => entry.pseudonym)).size).toBe(LEADERBOARD_FIXTURE.length);
  expect(LEADERBOARD_FIXTURE.filter((entry) => entry.isMe)).toHaveLength(1);

  // None of the pseudonyms appears anywhere in production source or in the app's strings.
  const names = LEADERBOARD_FIXTURE.map((entry) => entry.pseudonym.replace(LEADERBOARD_FIXTURE_MARK, ''));
  for (const file of production) {
    const text = fs.readFileSync(file, 'utf8');
    for (const name of names) expect(`${path.relative(ROOT, file)}:${text.includes(name)}`).toBe(`${path.relative(ROOT, file)}:false`);
  }
  const catalog = JSON.stringify(STRINGS);
  for (const name of names) expect(catalog.includes(name)).toBe(false);
});

test('the production leaderboard route has no data source: no request, no store, no fixture', () => {
  const route = fs.readFileSync(path.join(SRC, 'app', 'leaderboard.tsx'), 'utf8');
  expect(route).toContain('entries={[]}');
  expect(route).not.toMatch(/useRemote|experience\.|fetch\(|account\./);
  // and the adapter offers no ranking call at all
  const adapter = fs.readFileSync(path.join(SRC, 'core', 'experience', 'remote.ts'), 'utf8');
  expect(adapter).not.toMatch(/leaderboard|rank/i);
});

test('there are still exactly four tabs', () => {
  const chrome = fs.readFileSync(path.join(SRC, 'design', 'components', 'Chrome.tsx'), 'utf8');
  expect(chrome).toContain(`export type TabKey = 'home' | 'learn' | 'review' | 'profile';`);
});
