import React from 'react';

import { useApp } from './AppContext';
import { Banner, Body, Button, Card } from './components';

/** Pending / needs-attention counters and a manual "sync now". Reads only local state. */
export function SyncCard() {
  const { t, sync, syncNow, needsReauth, locale } = useApp();
  const { phase, summary, lastReport } = sync;
  const busy = phase !== 'idle';

  let headline: string;
  if (summary.pending > 0) headline = t('syncPending', { count: summary.pending });
  else headline = t('syncAllDone');

  const last = summary.lastSyncAt
    ? t('syncLast', { when: new Date(summary.lastSyncAt).toLocaleString(locale === 'ht' ? 'fr-HT' : 'fr-FR') })
    : t('syncNever');

  return (
    <Card>
      <Body style={{ fontWeight: '700' }}>{t('syncTitle')}</Body>
      <Body>{headline}</Body>
      {summary.needsAttention > 0 ? (
        <Body style={{ fontWeight: '600' }}>{t('syncAttention', { count: summary.needsAttention })}</Body>
      ) : null}
      <Body muted>{last}</Body>
      {needsReauth ? <Banner>{t('syncAuthRequired')}</Banner> : null}
      {!busy && !needsReauth && lastReport?.outcome === 'offline' ? <Banner>{t('syncOffline')}</Banner> : null}
      {!busy && lastReport?.outcome === 'error' ? (
        <Banner tone="bad">{t('syncError', { code: lastReport.errorCode ?? '?' })}</Banner>
      ) : null}
      <Button
        variant="secondary"
        busy={busy}
        label={phase === 'waiting_to_retry' ? t('syncRetrying') : busy ? t('syncRunning') : t('syncNow')}
        onPress={() => void syncNow()}
      />
    </Card>
  );
}
