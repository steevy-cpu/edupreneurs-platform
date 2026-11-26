/**
 * Edupreneurs design tokens — the single source of visual truth.
 *
 * Screens and components never hard-code a colour, size or radius: they read a
 * token. Light and dark palettes expose the SAME semantic names, so a component
 * written once works in both themes.
 *
 * Every text/background pair used by the components is checked against WCAG
 * contrast thresholds in tests/unit/design_tokens.test.ts.
 *
 * Status: PROPOSED (Design-00). Brand values await owner approval; see
 * docs/design/DESIGN_00_REPORT.md.
 */

/** Brand anchors. Do not use directly for text: go through `ColorScheme`. */
export const brand = {
  teal: '#087E7E',
  navy: '#142337',
  violet: '#7C3AED',
  amber: '#FF9F00',
} as const;

export interface ColorScheme {
  // surfaces
  canvas: string; //            screen background
  surface: string; //           cards, reading surface
  surfaceSunken: string; //     wells, tracks, skeletons
  hero: string; //              the one high-emphasis card per screen
  // text
  text: string;
  textSecondary: string;
  textOnHero: string;
  textOnHeroSecondary: string;
  // lines
  border: string; //            decorative dividers and card outlines
  borderControl: string; //     outlines that identify a control (>= 3:1 on its surface)
  focus: string;
  // primary action (teal)
  action: string;
  actionPressed: string;
  onAction: string;
  actionSoft: string; //        tinted background for teal-accented content
  actionText: string; //        teal used AS TEXT or icon on canvas/surface
  // Jude / review (violet)
  accent: string;
  onAccent: string;
  accentSoft: string;
  accentText: string;
  // achievement (amber) — always with dark text, never white
  highlight: string;
  onHighlight: string;
  highlightSoft: string;
  highlightText: string;
  // feedback
  success: string;
  successSoft: string;
  danger: string;
  dangerSoft: string;
  warning: string;
  warningSoft: string;
  // disabled
  disabledSurface: string;
  disabledText: string;
}

export const lightColors: ColorScheme = {
  canvas: '#F4F7F5',
  surface: '#FFFFFF',
  surfaceSunken: '#E6EDEA',
  hero: brand.navy,
  text: '#142337',
  textSecondary: '#4F5F70',
  textOnHero: '#FFFFFF',
  textOnHeroSecondary: '#C9DDE0',
  border: '#DCE6E2',
  borderControl: '#6F857D',
  focus: brand.amber,
  action: brand.teal,
  actionPressed: '#056464',
  onAction: '#FFFFFF',
  actionSoft: '#E3F2EF',
  actionText: '#06706F',
  accent: brand.violet,
  onAccent: '#FFFFFF',
  accentSoft: '#EEE9FC',
  accentText: '#5B2DB0',
  highlight: brand.amber,
  onHighlight: '#142337',
  highlightSoft: '#FFF1D6',
  highlightText: '#7A4B00',
  success: '#136D43',
  successSoft: '#E4F5EA',
  danger: '#A5343C',
  dangerSoft: '#FFF1F1',
  warning: '#7A4B00',
  warningSoft: '#FFF1D6',
  disabledSurface: '#E6EDEA',
  disabledText: '#566574',
};

export const darkColors: ColorScheme = {
  canvas: '#0E1722',
  surface: '#172536',
  surfaceSunken: '#0A111A',
  hero: '#1F3550',
  text: '#F1F5F4',
  textSecondary: '#A9B8C4',
  textOnHero: '#FFFFFF',
  textOnHeroSecondary: '#C9DDE0',
  border: '#2C3D50',
  borderControl: '#7F95A8',
  focus: brand.amber,
  action: '#2BB5AE',
  actionPressed: '#239C96',
  onAction: '#06131C',
  actionSoft: '#123536',
  actionText: '#5FD3CB',
  accent: '#A98BFF',
  onAccent: '#140B2E',
  accentSoft: '#2A1F4A',
  accentText: '#C3B0FF',
  highlight: '#FFB347',
  onHighlight: '#142337',
  highlightSoft: '#3A2A0A',
  highlightText: '#FFC766',
  success: '#6FD49A',
  successSoft: '#12301F',
  danger: '#FF9AA2',
  dangerSoft: '#3A1A1E',
  warning: '#FFC766',
  warningSoft: '#3A2A0A',
  disabledSurface: '#1D2B3B',
  disabledText: '#8496A6',
};

/** Spacing scale, in density-independent pixels. */
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;

export const radius = { sm: 12, md: 16, lg: 20, pill: 999 } as const;

/**
 * Type scale. System fonts only (no font files to download or keep in memory).
 * Sizes scale with the phone's text-size setting; `maxScale` stops layouts from
 * breaking at extreme settings while still allowing 200 %.
 */
export const type = {
  display: { fontSize: 28, lineHeight: 34, fontWeight: '800' },
  title: { fontSize: 22, lineHeight: 28, fontWeight: '800' },
  heading: { fontSize: 18, lineHeight: 24, fontWeight: '700' },
  body: { fontSize: 17, lineHeight: 26, fontWeight: '400' },
  bodyStrong: { fontSize: 17, lineHeight: 26, fontWeight: '700' },
  label: { fontSize: 15, lineHeight: 20, fontWeight: '700' },
  caption: { fontSize: 13, lineHeight: 18, fontWeight: '600' },
  maths: { fontSize: 20, lineHeight: 28, fontWeight: '600' },
} as const;
export type TypeVariant = keyof typeof type;
export const maxScale = 2;

/** Minimum touch target: 48 dp satisfies both Android (48) and iOS (44). */
export const touch = { min: 48 } as const;

export const size = {
  buttonHeight: 52,
  tabBarHeight: 60,
  pathNode: 56,
  pathNodeRecommended: 64,
  icon: 24,
  progressBar: 8,
} as const;

/** Motion tiers. Design-00 ships "lite": nothing moves unless the OS allows it. */
export const motion = { fast: 120, standard: 200 } as const;

/** Flat, cheap elevation: a border in light mode instead of large blurred shadows. */
export const elevation = {
  card: {
    shadowColor: '#132D2D',
    shadowOpacity: 0.06,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
} as const;
