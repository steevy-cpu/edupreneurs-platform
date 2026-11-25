import { useRouter } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import type { Locale } from '../../core/api/types';
import type { AccountStore } from '../../core/db/accountStore';
import type { ExperienceRemote } from '../../core/experience/remote';
import { refreshRewards, rewardsView, RewardsView } from '../../core/experience/rewards';
import type { Translate } from '../../core/i18n/strings';
import { AppText, Card, ListRow, Pill, SectionHeader, space } from '../../design';

interface Source {
  account: AccountStore;
  remote: ExperienceRemote | null;
  /** Unsynced learning actions (the outbox count the sync card already shows). */
  pendingActions: number;
  /** Changes when a sync run confirmed something: the summary is then read again. */
  syncedAt: string | null;
  now: () => Date;
  isActive: () => boolean;
}

/** The cached server summary first; a refresh in the background when one is due. */
function useRewards({ account, remote, pendingActions, syncedAt, now, isActive }: Source): RewardsView {
  const [view, setView] = useState<RewardsView>({ confirmed: null, pendingActions });
  useEffect(() => {
    let live = true;
    const show = async () => {
      const row = await account.experience.getRewards();
      if (live && isActive()) setView(rewardsView(row, pendingActions));
    };
    (async () => {
      await show();
      if (remote && (await refreshRewards(account, remote, { now, isActive })) === 'updated') await show();
    })().catch(() => undefined);
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, remote, pendingActions, syncedAt]);
  return { ...view, pendingActions };
}

/**
 * Profil: confirmed Gold and streak from the server, and — separately — how
 * many actions are still waiting on this phone. The two are never added up,
 * and the waiting work is never given a Gold value.
 */
export function RewardsCard({ t, locale, ...source }: Source & { t: Translate; locale: Locale }) {
  const { confirmed, pendingActions } = useRewards(source);
  return (
    <View style={styles.section}>
      <SectionHeader title={t('rewardsTitle')} />
      <Card tone={confirmed ? 'highlightSoft' : 'surface'}>
        {confirmed ? (
          <>
            <AppText variant="display" color="highlightText" testID="rewards-confirmed">
              {String(confirmed.balance)}
            </AppText>
            <AppText variant="label">{t('rewardsConfirmed')}</AppText>
            {confirmed.rules_status === 'provisional' ? (
              <View style={styles.pills}>
                <Pill tone="neutral" label={t('rewardsProvisional')} />
              </View>
            ) : null}
            <AppText variant="caption" color="textSecondary">
              {t('rewardsConfirmedAt', { when: new Date(confirmed.fetchedAt).toLocaleString(locale === 'ht' ? 'fr-HT' : 'fr-FR') })}
            </AppText>
            {confirmed.streak && confirmed.streak.current > 0 ? <AppText>{t('rewardsStreak', { days: confirmed.streak.current })}</AppText> : null}
            {confirmed.streak && confirmed.streak.longest > confirmed.streak.current ? (
              <AppText color="textSecondary">{t('rewardsStreakBest', { days: confirmed.streak.longest })}</AppText>
            ) : null}
            {confirmed.achievements > 0 ? <AppText>{t('rewardsAchievements', { count: confirmed.achievements })}</AppText> : null}
            {confirmed.up_to_date ? null : (
              <AppText variant="caption" color="textSecondary">
                {t('rewardsCatchingUp')}
              </AppText>
            )}
          </>
        ) : (
          <AppText color="textSecondary">{t('rewardsNone')}</AppText>
        )}
        {pendingActions > 0 ? (
          <View style={styles.pending}>
            <Pill tone="warning" icon="ring" label={t('rewardsPendingPill')} />
            <AppText>{t('rewardsPending', { count: pendingActions })}</AppText>
          </View>
        ) : null}
      </Card>
    </View>
  );
}

/** Accueil: one quiet row with the confirmed balance, only once the server has sent one. Opens Profil. */
export function RewardsRow({ t, ...source }: Source & { t: Translate }) {
  const router = useRouter();
  const { confirmed, pendingActions } = useRewards(source);
  if (!confirmed) return null;
  return (
    <ListRow
      icon="dot"
      tone="highlight"
      title={t('rewardsHomeRow', { gold: confirmed.balance })}
      subtitle={pendingActions > 0 ? t('rewardsPendingShort') : undefined}
      onPress={() => router.replace('/profile')}
    />
  );
}

const styles = StyleSheet.create({
  section: { gap: space.sm },
  pending: { gap: space.xs },
  pills: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
});
