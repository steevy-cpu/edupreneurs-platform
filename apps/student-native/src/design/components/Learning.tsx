import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { useDesign, useLayout } from '../theme';
import { radius, size, space, touch } from '../tokens';
import { Icon } from './Icon';
import { Pill } from './Surfaces';
import { AppText } from './Text';

// ---------------------------------------------------------------- learning path
export type StepState = 'completed' | 'recommended' | 'available' | 'unavailable';

/**
 * One step of the learning path: a node on a vertical line plus its label.
 * The state is always written out ("Terminé", "Étape suivante", …) as well as
 * drawn, and every step stays tappable — nothing is locked as a punishment.
 */
export function PathNode({
  index,
  title,
  kind,
  state,
  first,
  last,
  onPress,
  detail,
  action,
}: {
  index: number;
  title: string;
  /** e.g. "Comprendre", "Pratiquer" */
  kind: string;
  state: StepState;
  first?: boolean;
  last?: boolean;
  onPress?: () => void;
  /** Extra status line under the state pill, e.g. "Nouvelle version disponible". */
  detail?: string;
  /** Optional control under the text, e.g. a download button. */
  action?: React.ReactNode;
}) {
  const { colors, t } = useDesign();
  // Very large text: the narrow column beside the node cannot hold a button label without breaking words,
  // so the actions move below the whole row, at full width.
  const { roomy } = useLayout();
  const stateLabel = {
    completed: t('stateDone'),
    recommended: t('stateRecommended'),
    available: t('stateAvailable'),
    unavailable: t('stateUnavailable'),
  }[state];
  const recommended = state === 'recommended';
  const diameter = recommended ? size.pathNodeRecommended : size.pathNode;
  const node = {
    completed: {
      bg: colors.action,
      border: colors.action,
      fg: colors.onAction,
    },
    recommended: {
      bg: colors.highlight,
      border: colors.highlight,
      fg: colors.onHighlight,
    },
    available: {
      bg: colors.surface,
      border: colors.action,
      fg: colors.actionText,
    },
    unavailable: {
      bg: colors.surfaceSunken,
      border: colors.borderControl,
      fg: colors.textSecondary,
    },
  }[state];
  // Gentle zig-zag so the path reads as a journey, not a list.
  const offset = [0, 20, 32, 20][index % 4];
  const lineColor = state === 'completed' ? colors.action : colors.border;

  const text = (
    <>
      <AppText variant="caption" color="textSecondary">
        {kind}
      </AppText>
      <AppText variant="bodyStrong">{title}</AppText>
      <Pill
        label={stateLabel}
        tone={state === 'completed' ? 'success' : recommended ? 'highlight' : state === 'unavailable' ? 'neutral' : 'action'}
      />
      {detail ? (
        <AppText variant="caption" color="textSecondary">
          {detail}
        </AppText>
      ) : null}
    </>
  );
  const label = [kind, title, stateLabel, detail].filter(Boolean).join('. ');
  return (
    <View>
    <View style={styles.pathRow}>
      <View style={[styles.rail, { marginLeft: offset }]}>
        <View style={[styles.connector, { backgroundColor: first ? 'transparent' : lineColor }]} />
        <View
          style={{
            width: diameter,
            height: diameter,
            borderRadius: diameter / 2,
            borderWidth: 3,
            borderStyle: state === 'unavailable' ? 'dashed' : 'solid',
            backgroundColor: node.bg,
            borderColor: node.border,
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {state === 'completed' ? (
            <Icon name="check" color={node.fg} size={26} />
          ) : state === 'unavailable' ? (
            <Icon name="download" color={node.fg} size={22} />
          ) : state === 'recommended' ? (
            <Icon name="play" color={node.fg} size={24} />
          ) : (
            <AppText variant="heading" style={{ color: node.fg }}>
              {index + 1}
            </AppText>
          )}
        </View>
        <View style={[styles.connector, { backgroundColor: last ? 'transparent' : colors.border }]} />
      </View>
      <View style={styles.pathText}>
        {/* The words are the tap target when the step can be opened; a step that cannot be opened is plain text. */}
        {onPress ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={label}
            onPress={onPress}
            style={({ pressed }) => [styles.pathPress, pressed && { opacity: 0.7 }]}
          >
            {text}
          </Pressable>
        ) : (
          <View accessible accessibilityLabel={label} style={styles.pathPress}>
            {text}
          </View>
        )}
        {roomy ? action : null}
      </View>
    </View>
    {!roomy && action ? <View style={styles.pathActionFull}>{action}</View> : null}
    </View>
  );
}

// ------------------------------------------------------------------ lesson flow
/** The guided flow that replaces seven competing tabs: where am I in this lesson? */
export function StepStrip({ steps, current }: { steps: string[]; current: number }) {
  const { colors } = useDesign();
  return (
    <View
      accessible
      accessibilityRole="progressbar"
      accessibilityLabel={`${steps[current]} (${current + 1}/${steps.length})`}
      accessibilityValue={{ min: 1, max: steps.length, now: current + 1 }}
      style={styles.strip}
    >
      <View style={styles.stripBars}>
        {steps.map((step, i) => (
          <View
            key={step}
            style={[
              styles.stripBar,
              {
                backgroundColor: i <= current ? colors.action : colors.surfaceSunken,
              },
            ]}
          />
        ))}
      </View>
      {/* Only the current step is named: four labels do not fit a 320 dp phone or large text. */}
      <AppText variant="caption" color="actionText" style={{ fontWeight: '800' }}>
        {current + 1}/{steps.length} · {steps[current]}
      </AppText>
    </View>
  );
}

export function LessonHeader({
  subject,
  title,
  meta,
  offline,
  online,
}: {
  subject?: string;
  title: string;
  meta: string;
  offline?: string;
  /** Shown for a lesson read online and not downloaded. */
  online?: string;
}) {
  return (
    <View style={{ gap: space.sm }}>
      <View style={styles.wrapRow}>
        {subject ? <Pill label={subject} tone="action" /> : null}
        {offline ? <Pill label={offline} tone="success" icon="check" /> : null}
        {online ? <Pill label={online} tone="neutral" /> : null}
      </View>
      <AppText variant="display" accessibilityRole="header">
        {title}
      </AppText>
      <AppText variant="caption" color="textSecondary">
        {meta}
      </AppText>
    </View>
  );
}

// ------------------------------------------------------------------------- quiz
export type OptionState = 'idle' | 'selected' | 'correct' | 'incorrect' | 'dimmed';

/**
 * A large answer card. Selection and results are shown by border, background,
 * an icon AND words in the accessibility label — never by colour alone.
 */
export function AnswerOption({
  label,
  state,
  onPress,
  resultLabel,
}: {
  label: string;
  state: OptionState;
  onPress?: () => void;
  /** Spoken after the answer, e.g. "Bonne réponse". */
  resultLabel?: string;
}) {
  const { colors } = useDesign();
  const look = {
    idle: { bg: colors.surface, border: colors.borderControl, fg: colors.text },
    selected: { bg: colors.actionSoft, border: colors.action, fg: colors.text },
    correct: {
      bg: colors.successSoft,
      border: colors.success,
      fg: colors.text,
    },
    incorrect: {
      bg: colors.dangerSoft,
      border: colors.danger,
      fg: colors.text,
    },
    dimmed: {
      bg: colors.surface,
      border: colors.border,
      fg: colors.textSecondary,
    },
  }[state];
  const locked = state === 'correct' || state === 'incorrect' || state === 'dimmed';
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityLabel={resultLabel ? `${label}. ${resultLabel}` : label}
      accessibilityState={{
        selected: state === 'selected' || state === 'correct' || state === 'incorrect',
        disabled: locked,
      }}
      disabled={locked}
      onPress={onPress}
      style={[styles.option, { backgroundColor: look.bg, borderColor: look.border }]}
    >
      <View
        style={[
          styles.radio,
          {
            borderColor: state === 'correct' ? colors.success : state === 'incorrect' ? colors.danger : look.border,
            backgroundColor: state === 'correct' ? colors.success : state === 'incorrect' ? colors.danger : 'transparent',
          },
        ]}
      >
        {state === 'selected' ? <View style={[styles.radioDot, { backgroundColor: colors.action }]} /> : null}
        {state === 'correct' ? <Icon name="check" color={colors.surface} size={16} /> : null}
        {state === 'incorrect' ? <Icon name="cross" color={colors.surface} size={14} /> : null}
      </View>
      <View style={{ flex: 1 }}>
        <AppText variant="maths" style={{ color: look.fg }}>
          {label}
        </AppText>
      </View>
    </Pressable>
  );
}

/** Feedback after an answer: icon + explicit words + explanation + "saved on this phone". */
export function FeedbackPanel({
  correct,
  title,
  detail,
  explanation,
  savedLabel,
}: {
  correct: boolean;
  title: string;
  detail?: string;
  explanation: string;
  savedLabel: string;
}) {
  const { colors } = useDesign();
  const tone = correct ? colors.success : colors.danger;
  return (
    <View
      accessible
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      accessibilityLabel={[title, detail, explanation, savedLabel].filter(Boolean).join('. ')}
      style={[
        styles.feedback,
        {
          backgroundColor: correct ? colors.successSoft : colors.dangerSoft,
          borderColor: tone,
        },
      ]}
    >
      <View style={styles.feedbackHead}>
        <View style={[styles.feedbackIcon, { backgroundColor: tone }]}>
          <Icon name={correct ? 'check' : 'cross'} color={colors.surface} size={18} />
        </View>
        <AppText variant="heading" style={{ color: tone, flex: 1 }}>
          {title}
        </AppText>
      </View>
      {detail ? <AppText variant="bodyStrong">{detail}</AppText> : null}
      <AppText>{explanation}</AppText>
      <View style={styles.savedRow}>
        <Icon name="download" color={colors.textSecondary} size={16} />
        <AppText variant="caption" color="textSecondary" style={{ flex: 1 }}>
          {savedLabel}
        </AppText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  pathActionFull: { paddingBottom: space.md },
  pathRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.lg,
    minHeight: touch.min,
  },
  rail: { alignItems: 'center', width: size.pathNodeRecommended },
  connector: { width: 4, height: 14, borderRadius: 2 },
  pathText: { flex: 1, gap: space.sm, paddingVertical: space.sm },
  pathPress: { gap: space.xs, minHeight: touch.min, justifyContent: 'center' },
  strip: { gap: space.xs },
  stripBars: { flexDirection: 'row', gap: space.sm },
  stripBar: { flex: 1, height: 6, borderRadius: radius.pill },
  wrapRow: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  option: {
    minHeight: 56,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    borderWidth: 2,
    borderRadius: radius.md,
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
  },
  radio: {
    width: 26,
    height: 26,
    borderRadius: 13,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  radioDot: { width: 12, height: 12, borderRadius: 6 },
  feedback: {
    borderWidth: 2,
    borderRadius: radius.md,
    padding: space.lg,
    gap: space.sm,
  },
  feedbackHead: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  feedbackIcon: {
    width: 30,
    height: 30,
    borderRadius: 15,
    alignItems: 'center',
    justifyContent: 'center',
  },
  savedRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.xs,
    marginTop: space.xs,
  },
});
