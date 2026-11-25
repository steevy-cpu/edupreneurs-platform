import React from 'react';
import { StyleSheet, View } from 'react-native';

import type { Translate } from '../../core/i18n/strings';
import { AppText, Card, MessageState, Notice, Pill, radius, SectionHeader, space, useDesign, useLayout } from '../../design';

export interface LeaderboardEntry {
  rank: number;
  /** A pseudonym. This component is only ever given synthetic ones (tests and design previews). */
  pseudonym: string;
  gold: number;
  isMe?: boolean;
}

/**
 * REVIEW SCREEN — NOT WIRED TO REAL LEARNERS.
 *
 * A podium (ranks 1–3) and a ranked list, for the owners to look at and decide
 * on. It has no data source of its own: it draws the `entries` it is given.
 * The production app gives it none (no ranking exists in any production code
 * path); tests and the design preview give it clearly synthetic fixtures and
 * set `synthetic`, which puts a notice above everything.
 */
export function LeaderboardReview({ entries, synthetic, t }: { entries: LeaderboardEntry[]; synthetic: boolean; t: Translate }) {
  const { colors } = useDesign();
  const { textScale, compact } = useLayout();
  if (entries.length === 0) {
    return <MessageState title={t('lbNotAvailableTitle')} body={t('lbNotAvailableBody')} />;
  }
  const ordered = [...entries].sort((a, b) => a.rank - b.rank);
  const podium = ordered.filter((entry) => entry.rank <= 3);
  const others = ordered.filter((entry) => entry.rank > 3);
  // Three columns need room: with large text or a narrow screen the podium becomes three full-width rows.
  const stacked = compact || textScale > 1.2;
  // Visual order of a podium: 2nd, 1st, 3rd. Reading order (and stacked order) stays 1, 2, 3.
  const columns = stacked ? podium : [podium[1], podium[0], podium[2]].filter((entry): entry is LeaderboardEntry => Boolean(entry));
  const height = (rank: number) => (stacked ? undefined : rank === 1 ? 96 : rank === 2 ? 72 : 56);

  const label = (entry: LeaderboardEntry) =>
    `${t('lbEntryLabel', { rank: entry.rank, name: entry.pseudonym, gold: entry.gold })}${entry.isMe ? `. ${t('lbYou')}` : ''}`;

  return (
    <>
      {synthetic ? <Notice tone="warning">{t('lbSyntheticNotice')}</Notice> : null}

      <View style={styles.section}>
        <SectionHeader title={t('lbPodium')} />
        <View style={stacked ? styles.podiumStacked : styles.podium}>
          {columns.map((entry) => (
            <View key={entry.rank} accessible accessibilityLabel={label(entry)} style={stacked ? styles.stackedItem : styles.column}>
              <AppText variant="label" align="center" numberOfLines={stacked ? undefined : 2}>
                {entry.pseudonym}
              </AppText>
              <AppText variant="caption" color="textSecondary" align="center">
                {t('lbGold', { gold: entry.gold })}
              </AppText>
              {entry.isMe ? <Pill tone="accent" label={t('lbYou')} /> : null}
              <View
                style={[
                  styles.step,
                  {
                    minHeight: height(entry.rank) ?? 44,
                    backgroundColor: entry.rank === 1 ? colors.highlight : colors.highlightSoft,
                    borderColor: colors.highlight,
                  },
                ]}
              >
                <AppText variant="title" style={{ color: entry.rank === 1 ? colors.onHighlight : colors.highlightText }}>
                  {String(entry.rank)}
                </AppText>
              </View>
            </View>
          ))}
        </View>
      </View>

      {others.length > 0 ? (
        <View style={styles.section}>
          <SectionHeader title={t('lbOthers')} />
          {others.map((entry) => (
            <Card key={entry.rank} tone={entry.isMe ? 'accentSoft' : 'surface'}>
              <View accessible accessibilityLabel={label(entry)} style={styles.row}>
                <View style={[styles.rank, { backgroundColor: colors.surfaceSunken }]}>
                  <AppText variant="label" maxFontSizeMultiplier={1.3}>
                    {String(entry.rank)}
                  </AppText>
                </View>
                <View style={styles.rowText}>
                  <AppText variant="bodyStrong">{entry.pseudonym}</AppText>
                  <AppText variant="caption" color="textSecondary">
                    {t('lbGold', { gold: entry.gold })}
                  </AppText>
                </View>
                {entry.isMe ? <Pill tone="accent" label={t('lbYou')} /> : null}
              </View>
            </Card>
          ))}
        </View>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  section: { gap: space.sm },
  podium: { flexDirection: 'row', alignItems: 'flex-end', gap: space.sm },
  podiumStacked: { gap: space.sm },
  column: { flex: 1, alignItems: 'center', gap: space.xs },
  stackedItem: { gap: space.xs, alignItems: 'stretch' },
  step: {
    alignSelf: 'stretch',
    borderWidth: 1,
    borderTopLeftRadius: radius.sm,
    borderTopRightRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: space.xs,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  rank: { minWidth: 40, minHeight: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center', paddingHorizontal: space.xs },
  rowText: { flex: 1 },
});
