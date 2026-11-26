import { contrastRatio } from '../../src/design/contrast';
import { PREVIEW_STRINGS } from '../../src/design/preview/strings';
import { ColorScheme, darkColors, lightColors, radius, size, space, touch, type } from '../../src/design/tokens';

/** [foreground token, background token, minimum ratio]. 4.5 = body text (AA); 3 = large text and control outlines. */
const PAIRS: [keyof ColorScheme, keyof ColorScheme, number][] = [
  ['text', 'canvas', 4.5],
  ['text', 'surface', 4.5],
  ['text', 'surfaceSunken', 4.5],
  ['textSecondary', 'canvas', 4.5],
  ['textSecondary', 'surface', 4.5],
  ['textOnHero', 'hero', 4.5],
  ['textOnHeroSecondary', 'hero', 4.5],
  ['onAction', 'action', 4.5],
  ['onAction', 'actionPressed', 4.5],
  ['actionText', 'surface', 4.5],
  ['actionText', 'canvas', 4.5],
  ['actionText', 'actionSoft', 4.5],
  ['text', 'actionSoft', 4.5],
  ['onAccent', 'accent', 4.5],
  ['accentText', 'accentSoft', 4.5],
  ['accentText', 'surface', 4.5],
  ['text', 'accentSoft', 4.5],
  ['onHighlight', 'highlight', 4.5],
  ['highlightText', 'highlightSoft', 4.5],
  ['success', 'successSoft', 4.5],
  ['success', 'surface', 4.5],
  ['text', 'successSoft', 4.5],
  ['danger', 'dangerSoft', 4.5],
  ['danger', 'surface', 4.5],
  ['text', 'dangerSoft', 4.5],
  ['warning', 'warningSoft', 4.5],
  ['text', 'warningSoft', 4.5],
  ['disabledText', 'disabledSurface', 4.5],
  ['borderControl', 'surface', 3],
  ['borderControl', 'canvas', 3],
  ['action', 'surface', 3],
  ['action', 'canvas', 3],
  ['success', 'canvas', 3],
  ['danger', 'canvas', 3],
  ['focus', 'canvas', 1.5],
];

describe.each([
  ['light', lightColors],
  ['dark', darkColors],
])('%s palette', (_name, colors) => {
  test.each(PAIRS)('%s on %s has contrast >= %s', (foreground, background, minimum) => {
    const ratio = contrastRatio(colors[foreground], colors[background]);
    expect({ pair: `${foreground}/${background}`, ok: ratio >= minimum, ratio: ratio.toFixed(2) }).toEqual({
      pair: `${foreground}/${background}`,
      ok: true,
      ratio: ratio.toFixed(2),
    });
  });

  test('every colour is an opaque #RRGGBB value', () => {
    for (const value of Object.values(colors)) expect(value).toMatch(/^#[0-9A-F]{6}$/i);
  });
});

test('light and dark palettes define the same semantic names', () => {
  expect(Object.keys(darkColors).sort()).toEqual(Object.keys(lightColors).sort());
});

test('white is never placed on amber (fails contrast)', () => {
  expect(contrastRatio('#FFFFFF', lightColors.highlight)).toBeLessThan(3);
  expect(lightColors.onHighlight).not.toBe('#FFFFFF');
});

test('scales follow the specification', () => {
  expect(Object.values(space)).toEqual([4, 8, 12, 16, 24, 32]);
  expect([radius.sm, radius.md, radius.lg]).toEqual([12, 16, 20]);
  expect(touch.min).toBeGreaterThanOrEqual(48);
  expect(size.buttonHeight).toBeGreaterThanOrEqual(touch.min);
  expect(size.pathNode).toBeGreaterThanOrEqual(touch.min);
  expect(type.body.fontSize).toBeGreaterThanOrEqual(16);
  expect(type.caption.fontSize).toBeGreaterThanOrEqual(13);
});

test('preview-only French and Haitian Creole catalogs define exactly the same keys, none empty', () => {
  expect(Object.keys(PREVIEW_STRINGS.ht).sort()).toEqual(Object.keys(PREVIEW_STRINGS.fr).sort());
  for (const catalog of [PREVIEW_STRINGS.fr, PREVIEW_STRINGS.ht]) {
    for (const [key, value] of Object.entries(catalog)) {
      expect(`${key}:${value.trim().length > 0}`).toBe(`${key}:true`);
    }
  }
});
