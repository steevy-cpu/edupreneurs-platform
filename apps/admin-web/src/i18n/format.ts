const TZ = 'America/Port-au-Prince';

export const fmtNumber = (n: number): string => new Intl.NumberFormat('fr-FR').format(n);
export const fmtPercent = (n: number): string => `${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(n)} %`;

/** Haiti local date and time, e.g. "26 nov. 2026, 04:00 (Haïti)". */
export function fmtDateTime(iso: string): string {
  const s = new Intl.DateTimeFormat('fr-FR', { timeZone: TZ, day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(iso));
  return `${s} (Haïti)`;
}
export function fmtDay(isoDate: string): string {
  return new Intl.DateTimeFormat('fr-FR', { timeZone: 'UTC', day: 'numeric', month: 'short' }).format(new Date(`${isoDate}T12:00:00Z`));
}
export function fmtAge(iso: string, now: Date): string {
  const h = (now.getTime() - new Date(iso).getTime()) / 3_600_000;
  if (h < 1) return `il y a ${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `il y a ${Math.round(h)} h`;
  return `il y a ${Math.round(h / 24)} j`;
}
