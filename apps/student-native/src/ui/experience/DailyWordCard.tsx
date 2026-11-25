import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import type { Locale } from '../../core/api/types';
import type { AccountStore } from '../../core/db/accountStore';
import { dailyWordView, DailyWordView, formatHaitiDate, refreshDailyWord } from '../../core/experience/dailyWord';
import type { ExperienceRemote } from '../../core/experience/remote';
import type { Translate } from '../../core/i18n/strings';
import { AppText, Card, Pill, space } from '../../design';

/**
 * Word of the Day on Accueil.
 *
 * Drawn from this account's SQLite cache first; the network (when there is a
 * server adapter) only brings a newer word in the background. Text only: no
 * image, nothing plays by itself. When nothing has ever been downloaded the
 * card is simply absent — the app never makes up a word.
 *
 * The heading says "Mot du jour" ONLY while the server's deadline for the word
 * has not passed; afterwards it says "Dernier mot téléchargé · <date>".
 */
export function DailyWordCard({
  account,
  remote,
  locale,
  t,
  now,
  isActive,
}: {
  account: AccountStore;
  /** Null when offline features are all there is (no session adapter): the cache is still shown. */
  remote: ExperienceRemote | null;
  locale: Locale;
  t: Translate;
  now: () => Date;
  isActive: () => boolean;
}) {
  const [view, setView] = useState<DailyWordView | null>(null);

  useEffect(() => {
    let live = true;
    const show = async () => {
      const row = await account.experience.getDailyWord(locale);
      if (live && isActive()) setView(dailyWordView(row, now()));
    };
    (async () => {
      await show(); // the cached word first: no waiting on the network
      if (!remote) return;
      const outcome = await refreshDailyWord(account, remote, locale, { now, isActive });
      if (outcome !== 'cached_today' && outcome !== 'throttled' && outcome !== 'aborted') await show();
    })().catch(() => undefined);
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, remote, locale]);

  if (!view) return null;
  const { word } = view;
  const today = view.freshness === 'today';
  const date = formatHaitiDate(view.haitiDate, locale);
  const details = [word.part_of_speech, word.pronunciation ? t('wordPronunciation', { text: word.pronunciation }) : null].filter(
    (part): part is string => Boolean(part),
  );

  return (
    <Card tone={today ? 'highlightSoft' : 'surface'}>
      <View style={styles.pills}>
        {today ? (
          <>
            <Pill tone="highlight" label={t('wordToday')} />
            <Pill tone="neutral" label={date} />
          </>
        ) : (
          <Pill tone="neutral" icon="ring" label={t('wordLastDownloaded', { date })} />
        )}
      </View>
      <AppText variant="title" accessibilityRole="header">
        {word.term}
      </AppText>
      {details.length > 0 ? (
        <AppText variant="caption" color="textSecondary">
          {details.join(' · ')}
        </AppText>
      ) : null}
      <AppText>{word.definition}</AppText>
      {word.example ? (
        <View style={styles.example}>
          <AppText variant="caption" color="textSecondary">
            {t('wordExample')}
          </AppText>
          <AppText>{word.example}</AppText>
        </View>
      ) : null}
      {word.gloss ? (
        <AppText color="textSecondary">{t(view.servedLocale === 'fr' ? 'wordGlossHt' : 'wordGlossFr', { gloss: word.gloss })}</AppText>
      ) : null}
      {view.isFallbackLocale ? (
        <AppText variant="caption" color="textSecondary">
          {t('wordFallbackLocale')}
        </AppText>
      ) : null}
      {view.hasAudio ? (
        <View style={styles.pills}>
          <Pill tone="neutral" label={t('wordAudioSoon')} />
        </View>
      ) : null}
      {!today && view.lastOutcome === 'unreachable' ? (
        <AppText variant="caption" color="textSecondary">
          {t('wordStaleOffline')}
        </AppText>
      ) : null}
      {!today && view.lastOutcome === 'none_today' ? (
        <AppText variant="caption" color="textSecondary">
          {t('wordNoneToday')}
        </AppText>
      ) : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  pills: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  example: { gap: space.xs },
});
