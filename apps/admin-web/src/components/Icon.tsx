import type { SectionId } from '../domain/roles';

const PATHS: Record<SectionId, string> = {
  dashboard: 'M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z',
  content: 'M4 4h12l4 4v12H4V4zm2 2v12h12V9h-4V6H6zm2 6h8v2H8v-2zm0 4h6v2H8v-2z',
  roles: 'M12 2l8 3v6c0 5-3.4 9.3-8 11-4.6-1.7-8-6-8-11V5l8-3zm0 5a3 3 0 100 6 3 3 0 000-6zm-5 11c1.2 1.4 3 2.5 5 3.1 2-.6 3.8-1.7 5-3.1-.5-1.9-2.8-3-5-3s-4.5 1.1-5 3z',
  wotd: 'M5 3h14a1 1 0 011 1v16a1 1 0 01-1 1H5a1 1 0 01-1-1V4a1 1 0 011-1zm2 4v2h10V7H7zm0 4v2h10v-2H7zm0 4v2h6v-2H7z',
  exams: 'M4 5a2 2 0 012-2h12a2 2 0 012 2v14l-4-3-4 3-4-3-4 3V5z',
  gold: 'M12 2l2.9 6.3 6.9.7-5.2 4.6 1.5 6.8L12 17l-6.1 3.4 1.5-6.8L2.2 9l6.9-.7L12 2z',
  leaderboard: 'M4 20h4v-8H4v8zm6 0h4V4h-4v16zm6 0h4v-12h-4v12z',
  jude: 'M12 3a8 8 0 00-8 8c0 2 .7 3.8 1.9 5.200L5 21l4.200-1.400A8 8 0 1012 3zm-3 7h2v2H9v-2zm4 0h2v2h-2v-2z',
  notifications: 'M12 22a2 2 0 002-2h-4a2 2 0 002 2zm6-6V11a6 6 0 00-5-5.900V4a1 1 0 00-2 0v1.100A6 6 0 006 11v5l-2 2v1h16v-1l-2-2z',
  moderation: 'M12 2l9 4v6c0 5-3.8 9.4-9 10-5.200-.6-9-5-9-10V6l9-4zm-1 6v5h2V8h-2zm0 6v2h2v-2h-2z',
  payments: 'M3 6a2 2 0 012-2h14a2 2 0 012 2v2H3V6zm0 4h18v8a2 2 0 01-2 2H5a2 2 0 01-2-2v-8zm3 4v2h5v-2H6z',
  infra: 'M4 4h16v6H4V4zm0 10h16v6H4v-6zm3-7v2h2V7H7zm0 10v2h2v-2H7z',
};

export function Icon({ name }: { name: SectionId }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="currentColor">
      <path d={PATHS[name]} />
    </svg>
  );
}
