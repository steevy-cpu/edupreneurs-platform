import React from 'react';

import type { Translate } from '../../core/i18n/strings';
import { TOUR_STEPS, TourOffer } from '../../core/experience/tour';
import { AppText, Button, Card } from '../../design';

/**
 * The tour offer on Accueil: an ordinary card BELOW the learning content, never
 * a pop-up. It can be declined for good; the tour stays available in Profil.
 */
export function TourInvite({
  offer,
  t,
  onStart,
  onDecline,
}: {
  offer: TourOffer;
  t: Translate;
  onStart: () => void;
  onDecline: () => void;
}) {
  if (offer === 'none') return null;
  return (
    <Card tone="accentSoft">
      <AppText variant="heading" accessibilityRole="header">
        {t('tourInviteTitle')}
      </AppText>
      <AppText>{t('tourInviteBody', { count: TOUR_STEPS.length })}</AppText>
      <Button
        variant="secondary"
        label={offer === 'resume' ? t('tourInviteResume') : t('tourInviteStart')}
        testID="tour-invite-start"
        onPress={onStart}
      />
      {offer === 'start' ? <Button variant="secondary" label={t('tourInviteDecline')} testID="tour-invite-decline" onPress={onDecline} /> : null}
    </Card>
  );
}
