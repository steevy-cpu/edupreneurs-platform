/** Brand palette (Edupreneurs identity) — mirrored in styles/app.css custom properties; a test checks the contrast pairs. */
export const BRAND = { teal: '#087E7E', navy: '#142337', violet: '#7C3AED', amber: '#FF9F00' } as const;

export const TEXT_PAIRS: ReadonlyArray<{ name: string; fg: string; bg: string; min: number }> = [
  { name: 'body text on page', fg: '#142337', bg: '#F3F5F8', min: 4.5 },
  { name: 'muted text on surface', fg: '#4B5870', bg: '#FFFFFF', min: 4.5 },
  { name: 'teal link on surface', fg: '#066464', bg: '#FFFFFF', min: 4.5 },
  { name: 'white on teal button', fg: '#FFFFFF', bg: '#087E7E', min: 4.5 },
  { name: 'white on navy sidebar', fg: '#FFFFFF', bg: '#142337', min: 4.5 },
  { name: 'sidebar muted on navy', fg: '#B9C4D6', bg: '#142337', min: 4.5 },
  { name: 'navy on amber banner', fg: '#142337', bg: '#FF9F00', min: 4.5 },
  { name: 'violet text on violet tint', fg: '#4C1D95', bg: '#EDE5FD', min: 4.5 },
  { name: 'ok badge', fg: '#14663F', bg: '#E3F4EC', min: 4.5 },
  { name: 'warn badge', fg: '#6B4000', bg: '#FFF1D6', min: 4.5 },
  { name: 'danger badge', fg: '#8F1D1D', bg: '#FBE4E4', min: 4.5 },
  { name: 'neutral badge', fg: '#33415A', bg: '#E8ECF2', min: 4.5 },
  { name: 'info badge', fg: '#065858', bg: '#DDF1F1', min: 4.5 },
  { name: 'heat cell dark text', fg: '#FFFFFF', bg: '#066464', min: 4.5 },
];

function lum(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!;
}
export function contrast(a: string, b: string): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}
