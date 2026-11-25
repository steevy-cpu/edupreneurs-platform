import { useRouter } from 'expo-router';
import React from 'react';

import { TopBar, useDesign } from '../../design';
import { LEADERBOARD_FIXTURE } from '../../design/preview/leaderboardFixture';
import { PreviewScreenShell, usePreviewParams } from '../../design/preview/shell';
import { LeaderboardReview } from '../../ui/experience/LeaderboardReview';

/**
 * Design preview of the leaderboard review screen, with SYNTHETIC fixture rows.
 * Development builds and EXPO_PUBLIC_DESIGN_PREVIEW=1 builds only (the shell
 * redirects otherwise, and Metro leaves this route out of production bundles).
 *
 *   monedupreneur://design/leaderboard?locale=fr|ht&state=default|podium|empty&width=320
 */
function Content() {
  const { t } = useDesign();
  const { state } = usePreviewParams();
  const entries = state === 'empty' ? [] : state === 'podium' ? LEADERBOARD_FIXTURE.slice(0, 3) : LEADERBOARD_FIXTURE;
  return <LeaderboardReview entries={entries} synthetic t={t} />;
}

function Top() {
  const router = useRouter();
  const { t } = useDesign();
  return <TopBar title={t('lbTitle')} onBack={() => (router.canGoBack() ? router.back() : router.replace('/design'))} />;
}

export default function LeaderboardPreview() {
  return (
    <PreviewScreenShell tab={null} top={() => <Top />}>
      <Content />
    </PreviewScreenShell>
  );
}
