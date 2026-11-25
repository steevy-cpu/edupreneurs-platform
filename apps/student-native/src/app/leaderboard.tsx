import { Redirect, useRouter } from 'expo-router';
import React from 'react';

import { FLAGS } from '../core/experience/flags';
import { Button } from '../design';
import { LeaderboardReview } from '../ui/experience/LeaderboardReview';
import { DetailScreen } from '../ui/shell';
import { useSignedIn } from '../ui/useSession';

/**
 * Leaderboard REVIEW screen. Behind the `leaderboardReview` flag (off by default)
 * and NOT WIRED TO REAL LEARNERS: there is no ranking endpoint, no ranking query
 * and no learner name anywhere in this route. It gives the review component an
 * empty list, so a production build shows "no leaderboard yet".
 *
 * The podium and list filled with synthetic fixtures live in the design preview
 * (src/app/design/leaderboard.tsx), which Metro leaves out of production bundles.
 * This file does not import that fixture; it only offers a link to the preview
 * route in builds where previews exist.
 */
export default function Leaderboard() {
  const app = useSignedIn();
  const router = useRouter();
  if (!app) return <Redirect href="/sign-in" />;
  if (!FLAGS.leaderboardReview) return <Redirect href="/profile" />;
  const { t } = app;
  // Same condition as the preview routes themselves (design/preview/shell.tsx), repeated here so
  // that no preview module is imported by a production screen.
  const previewsExist = (typeof __DEV__ !== 'undefined' && __DEV__) || process.env.EXPO_PUBLIC_DESIGN_PREVIEW === '1';
  return (
    <DetailScreen title={t('lbTitle')} fallback="/profile">
      <LeaderboardReview entries={[]} synthetic={false} t={t} />
      {previewsExist ? (
        <Button
          variant="secondary"
          label={t('lbOpenPreview')}
          testID="leaderboard-open-preview"
          onPress={() => router.push({ pathname: '/design/leaderboard', params: { locale: app.locale } })}
        />
      ) : null}
    </DetailScreen>
  );
}
