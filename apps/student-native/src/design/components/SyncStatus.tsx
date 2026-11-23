import React, { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { useDesign } from '../theme';
import { radius, space, touch } from '../tokens';
import { Button } from './Button';
import { Icon } from './Icon';
import { AppText } from './Text';

/**
 * What the live app's sync engine reports, reduced to what a student needs.
 * The four states are deliberately distinct and each has its own words:
 *   synced   every answer has been confirmed by the server
 *   pending  answers are saved on the phone and waiting to be sent
 *   failed   the last attempt could not reach the server (work is still saved)
 *   attention  the server refused some answers; they will not be re-sent
 */
export type SyncDisplayState = 'synced' | 'pending' | 'failed' | 'attention';

export function SyncStatusCard({
  state,
  pendingCount,
  lastConfirmed,
  onSync,
  technicalDetail,
}: {
  state: SyncDisplayState;
  pendingCount: number;
  /** Already formatted for the locale; null if the server has never confirmed anything. */
  lastConfirmed: string | null;
  onSync?: () => void;
  /** Diagnostic text kept behind a disclosure so it never dominates the screen. */
  technicalDetail?: string;
}) {
  const { colors, t } = useDesign();
  const [open, setOpen] = useState(false);
  const look = {
    synced: {
      fg: colors.success,
      bg: colors.successSoft,
      icon: 'check' as const,
      title: t('syncSynced'),
    },
    pending: {
      fg: colors.warning,
      bg: colors.warningSoft,
      icon: 'ring' as const,
      title: t('syncPending', { count: pendingCount }),
    },
    failed: {
      fg: colors.warning,
      bg: colors.warningSoft,
      icon: 'ring' as const,
      title: t('syncFailed'),
    },
    attention: {
      fg: colors.danger,
      bg: colors.dangerSoft,
      icon: 'cross' as const,
      title: t('syncAttention', { count: pendingCount }),
    },
  }[state];
  return (
    <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
      <AppText variant="label" color="textSecondary" accessibilityRole="header">
        {t('syncTitle')}
      </AppText>
      <View style={styles.head}>
        <View style={[styles.icon, { backgroundColor: look.bg }]}>
          <Icon name={look.icon} color={look.fg} size={18} />
        </View>
        <AppText variant="bodyStrong" style={{ flex: 1 }}>
          {look.title}
        </AppText>
      </View>
      {state === 'pending' || state === 'failed' ? <AppText color="textSecondary">{t('syncPendingHelp')}</AppText> : null}
      <AppText variant="caption" color="textSecondary">
        {lastConfirmed ? t('syncLast', { when: lastConfirmed }) : t('syncNever')}
      </AppText>
      {state !== 'synced' ? <Button label={t('syncNow')} variant="secondary" onPress={onSync} /> : null}
      {technicalDetail ? (
        <>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ expanded: open }}
            accessibilityLabel={t('details')}
            onPress={() => setOpen(!open)}
            style={styles.disclosure}
          >
            <AppText variant="label" color="actionText">
              {t('details')}
            </AppText>
            <View style={{ transform: [{ rotate: open ? '90deg' : '0deg' }] }}>
              <Icon name="chevron" color={colors.actionText} size={14} />
            </View>
          </Pressable>
          {open ? (
            <AppText variant="caption" color="textSecondary">
              {technicalDetail}
            </AppText>
          ) : null}
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: space.lg,
    gap: space.sm,
  },
  head: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  icon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  disclosure: {
    minHeight: touch.min,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.xs,
    alignSelf: 'flex-start',
  },
});
