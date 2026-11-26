import type { LeaderboardEntry } from '../../ui/experience/LeaderboardReview';

/**
 * SYNTHETIC leaderboard for the design preview and for tests. Not learners.
 *
 * Every pseudonym is a Haitian plant or animal followed by "-TEST", and the
 * Gold values are round placeholders: nobody could mistake a row for a person
 * or for a real score. This file is under src/design/preview, which Metro
 * blocks from production bundles (metro.config.js); no production screen
 * imports it.
 */
export const LEADERBOARD_FIXTURE_MARK = '-TEST';

export const LEADERBOARD_FIXTURE: LeaderboardEntry[] = [
  { rank: 1, pseudonym: 'Colibri-TEST', gold: 900 },
  { rank: 2, pseudonym: 'Flamboyant-TEST', gold: 800 },
  { rank: 3, pseudonym: 'Lambi-TEST', gold: 700 },
  { rank: 4, pseudonym: 'Mapou-TEST', gold: 600 },
  { rank: 5, pseudonym: 'Zandolit-TEST', gold: 500, isMe: true },
  { rank: 6, pseudonym: 'Kayiman-TEST', gold: 400 },
  { rank: 7, pseudonym: 'Palmis-TEST', gold: 300 },
  { rank: 8, pseudonym: 'Tako-TEST', gold: 200 },
];
