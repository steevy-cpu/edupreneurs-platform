import { Redirect, useFocusEffect, useRouter } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import type { Locale } from '../core/api/types';
import { FLAGS } from '../core/experience/flags';
import { GradeChoices, gradeChoices } from '../core/experience/grades';
import {
  beginOrResumeOnboarding,
  confirmOnboardingGrade,
  finishOnboarding,
  goToOnboardingStep,
  isFinished,
  noteOnboardingLocale,
  selectOnboardingGrade,
  skipOnboardingGrade,
  stepIndex,
} from '../core/experience/onboarding';
import { syncOnboarding } from '../core/experience/onboardingSync';
import { ONBOARDING_STEPS } from '../core/experience/schema';
import type { OnboardingRecord, OnboardingStep } from '../core/experience/store';
import type { StringKey } from '../core/i18n/strings';
import { AppText, Button, Card, Chip, ListRow, LoadingState, Notice, ScreenFrame, space, StepStrip, TopBar } from '../design';
import { useRemote } from '../ui/remote';
import { OfflinePill } from '../ui/shell';
import { useSignedIn } from '../ui/useSession';

const STEP_NAME: Record<OnboardingStep, StringKey> = {
  welcome: 'onbStepWelcome',
  language: 'onbStepLanguage',
  grade: 'onbStepGrade',
  downloads: 'onbStepOffline',
  ready: 'onbStepReady',
};

const LANGUAGES: { locale: Locale; label: string }[] = [
  { locale: 'fr', label: 'Français' },
  { locale: 'ht', label: 'Kreyòl' },
];

/**
 * First-run onboarding: welcome → language → grade → how offline works → ready.
 *
 * Everything is read from and written to this account's SQLite database; no
 * step needs the network. Each tap is committed before the screen moves, so
 * reopening the app shows the same step with the same choices. Learning data is
 * never read, changed or removed here.
 */
export default function Onboarding() {
  const app = useSignedIn();
  const router = useRouter();
  const remote = useRemote();
  const [record, setRecord] = useState<OnboardingRecord | null>(null);
  const [choices, setChoices] = useState<GradeChoices | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const session = app?.session;
  const locale = app?.locale;

  useFocusEffect(
    useCallback(() => {
      if (!FLAGS.onboarding || !app || !session || !locale) return;
      let live = true;
      (async () => {
        const { content, env } = app.services;
        const opened = await beginOrResumeOnboarding(session.account, env.now());
        const grades = await gradeChoices(content, locale);
        if (!live || !session.isActive()) return;
        setRecord(opened);
        setChoices(grades);
        // Another phone may already have finished the introduction for this account.
        if (FLAGS.onboardingSync && remote && !isFinished(opened.status)) {
          await syncOnboarding(session.account, remote, { now: env.now, isActive: () => session.isActive() });
          const merged = await session.account.experience.getOnboarding();
          if (live && session.isActive() && merged) setRecord(merged);
        }
      })().catch(() => live && setFailed(true));
      return () => {
        live = false;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [session, locale, remote]),
  );

  if (!app) return <Redirect href="/sign-in" />;
  if (!FLAGS.onboarding) return <Redirect href="/home" />;
  const { t } = app;
  const account = app.session.account;
  const now = () => app.services.env.now();

  if (record && isFinished(record.status)) return <Redirect href="/home" />;
  if (!record || !choices) {
    return (
      <ScreenFrame top={<TopBar trailing={<OfflinePill />} />}>
        {failed ? <Notice tone="danger">{t('errorBody')}</Notice> : <LoadingState label={t('loading')} />}
      </ScreenFrame>
    );
  }

  /** Run one committed change; the screen only moves once SQLite has it. */
  const commit = async (work: () => Promise<OnboardingRecord | null>) => {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    try {
      const next = await work();
      if (next && app.session.isActive()) setRecord(next);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const goTo = (step: OnboardingStep) => commit(() => goToOnboardingStep(account, step, now()));

  const finish = async (how: 'completed' | 'skipped', destination: '/home' | '/learn') => {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    try {
      await finishOnboarding(account, how, now());
    } catch {
      setFailed(true);
      setBusy(false);
      return;
    }
    if (FLAGS.onboardingSync && remote) {
      // Background only: the flow is finished whether or not the server hears about it now.
      void syncOnboarding(account, remote, { now, isActive: () => app.session.isActive(), force: true });
    }
    router.replace(destination);
  };

  const chooseLanguage = (next: Locale) =>
    commit(async () => {
      await app.setLocale(next);
      const grades = await gradeChoices(app.services.content, next);
      setChoices(grades);
      return noteOnboardingLocale(account, next, now());
    });

  const index = stepIndex(record.step);
  const back = index > 0 ? () => void goTo(ONBOARDING_STEPS[index - 1]) : undefined;
  const selectedGrade = choices.grades.find((grade) => grade.code === record.gradeCode) ?? null;
  const error = failed ? <Notice tone="danger">{t('onbSaveFailed')}</Notice> : null;

  let body: React.ReactNode;
  let action: React.ReactNode;

  switch (record.step) {
    case 'welcome':
      body = (
        <>
          <AppText variant="display" accessibilityRole="header">
            {t('onbWelcomeTitle')}
          </AppText>
          <AppText>{t('onbWelcomeBody')}</AppText>
          <View style={styles.stack}>
            <ListRow icon="learn" title={t('onbWelcomePoint1')} />
            <ListRow icon="check" tone="accent" title={t('onbWelcomePoint2')} />
            <ListRow icon="download" tone="highlight" title={t('onbWelcomePoint3')} />
          </View>
        </>
      );
      action = (
        <>
          <Button label={t('onbStart')} busy={busy} testID="onboarding-start" onPress={() => void goTo('language')} />
          <Button label={t('onbSkipAll')} variant="secondary" disabled={busy} testID="onboarding-skip" onPress={() => void finish('skipped', '/home')} />
        </>
      );
      break;

    case 'language':
      body = (
        <>
          <AppText variant="display" accessibilityRole="header">
            {t('onbLanguageTitle')}
          </AppText>
          <View accessibilityRole="radiogroup" style={styles.stack}>
            {LANGUAGES.map((language) => (
              <Chip
                key={language.locale}
                label={language.label}
                selected={app.locale === language.locale}
                testID={`onboarding-locale-${language.locale}`}
                onPress={() => void chooseLanguage(language.locale)}
              />
            ))}
          </View>
          <AppText color="textSecondary">{t('onbLanguageBody')}</AppText>
        </>
      );
      action = <Button label={t('onbContinue')} busy={busy} testID="onboarding-continue" onPress={() => void goTo('grade')} />;
      break;

    case 'grade':
      body = (
        <>
          <AppText variant="display" accessibilityRole="header">
            {t('onbGradeTitle')}
          </AppText>
          <AppText color="textSecondary">{t('onbGradeBody')}</AppText>
          {choices.fromCatalog ? null : (
            <Notice tone="info" role="text">
              {t('onbGradeOfflineList')}
            </Notice>
          )}
          {/* One full-width choice per line: long class names wrap instead of being cut at 320 dp or large text. */}
          <View accessibilityRole="radiogroup" style={styles.stack}>
            {choices.grades.map((grade) => (
              <Chip
                key={grade.code}
                label={`${grade.code} · ${grade.label}`}
                selected={grade.code === record.gradeCode}
                testID={`onboarding-grade-${grade.code}`}
                onPress={() => void commit(() => selectOnboardingGrade(account, grade.code, now()))}
              />
            ))}
          </View>
        </>
      );
      action = (
        <>
          <Button
            label={t('onbContinue')}
            busy={busy}
            disabled={selectedGrade === null}
            testID="onboarding-continue"
            onPress={() => void commit(() => confirmOnboardingGrade(account, now()))}
          />
          <Button
            label={t('onbGradeLater')}
            variant="secondary"
            disabled={busy}
            testID="onboarding-grade-later"
            onPress={() => void commit(() => skipOnboardingGrade(account, now()))}
          />
        </>
      );
      break;

    case 'downloads':
      body = (
        <>
          <AppText variant="display" accessibilityRole="header">
            {t('onbOfflineTitle')}
          </AppText>
          <View style={styles.stack}>
            <ListRow icon="download" title={t('onbOffline1Title')} subtitle={t('onbOffline1Body')} />
            <ListRow icon="learn" title={t('onbOffline2Title')} subtitle={t('onbOffline2Body')} />
            <ListRow icon="check" tone="accent" title={t('onbOffline3Title')} subtitle={t('onbOffline3Body')} />
            <ListRow icon="ring" tone="highlight" title={t('onbOffline4Title')} subtitle={t('onbOffline4Body')} />
          </View>
        </>
      );
      action = <Button label={t('onbUnderstood')} busy={busy} testID="onboarding-continue" onPress={() => void goTo('ready')} />;
      break;

    default:
      body = (
        <>
          <AppText variant="display" accessibilityRole="header">
            {t('onbReadyTitle')}
          </AppText>
          <Card tone="actionSoft">
            <AppText variant="bodyStrong">
              {t('onbReadyLanguage', { language: LANGUAGES.find((language) => language.locale === app.locale)?.label ?? '' })}
            </AppText>
            <AppText variant="bodyStrong">
              {selectedGrade ? t('onbReadyGrade', { grade: `${selectedGrade.code} · ${selectedGrade.label}` }) : t('onbReadyNoGrade')}
            </AppText>
          </Card>
          <AppText>{t('onbReadyBody')}</AppText>
        </>
      );
      action = (
        <>
          <Button label={t('onbReadyChoose')} busy={busy} testID="onboarding-finish-learn" onPress={() => void finish('completed', '/learn')} />
          <Button
            label={t('onbReadyHome')}
            variant="secondary"
            disabled={busy}
            testID="onboarding-finish-home"
            onPress={() => void finish('completed', '/home')}
          />
        </>
      );
  }

  return (
    <ScreenFrame top={<TopBar onBack={back} trailing={<OfflinePill />} />} action={action}>
      <StepStrip steps={ONBOARDING_STEPS.map((step) => t(STEP_NAME[step]))} current={index} />
      {body}
      {error}
    </ScreenFrame>
  );
}

const styles = StyleSheet.create({
  stack: { gap: space.sm },
});
