# Edupreneurs 2.0 — Mobile Product Experience & Design Direction v0.1

**Status:** Proposed design direction, not an implemented screen or a full authenticated usability audit.  
**Source inspection:** Connected Lovable project, commit `3110f7971aad9abbdeb3e2965afd565f5b74b520` (Nov 16, 2026); CSS tokens; dashboard, home, subjects, lessons, mobile navigation, Jude chatbot and gamification source; and the Mobile-01 simulator screenshots provided in conversation.  
**Target:** React Native, Android 7+ and iOS per selected Expo SDK, plus separately planned HTML-first Lite client for unsupported devices.  
**Product name:** Edupreneurs. **Domain:** mon-edupreneur.com.

## Product experience principle

A student should be able to open Edupreneurs and start or resume meaningful learning in one intentional action. Connectivity failures should never conceal downloaded lessons or erase answers. Delight should reinforce learning, not obstruct it.

## Observed design patterns

- Source `src/index.css`: primary HSL 180 88% 27% (~#087E7E), violet secondary HSL 262 83% 58% (~#7C3AED), amber accent HSL 38 100% 50% (~#FF9F00), generous rounded cards (1.25rem), gradient and animation patterns. Tailwind font family Poppins.
- Public OG identity: gold bulb/brain logo on navy, slogan “Explorer · Apprendre · Réussir”. Resolve tension between formal gold/navy identity and playful teal/purple application styling.
- `src/shell/config/navigation.ts`: six bottom destinations (Accueil, Cours, Jeux, Chat, Notifs, Plus) plus theme toggle. Replace with four primary destinations to prioritize learning.
- `src/components/dashboard/tabs/OverviewTab.tsx`: quick actions, Gold/lesson/score/study time/streak, weekly goal, recent subjects and promotional banners. Keep achievement data, but prioritize one clear “continue” action.
- `src/components/LessonPageTemplate.tsx`: seven content tabs (Introduction, Cours, Points clés, Studygram, Activités, Quiz, Notes). Good content inventory, but too much peer-level navigation for a small phone. Reframe as progressive lesson steps.
- `src/pages/Matieres.tsx`: immersive hero background, gradients, badges, grade selector, filters and cards. Keep subject and grade hierarchy, replace decorative hero with compact contextual header.
- `src/components/JudeChatbot.tsx` and `src/shell/FloatingLayer.tsx`: persistent draggable chat overlay. Make Jude an explicit contextual action/route, with offline teacher-authored hints when unavailable.
- `src/components/dashboard/StreakMilestoneModal.tsx`: confetti, voice, auto-dismiss celebration. Use brief optional celebrations, never autoplay media on data-saver and never obscure the next learning step.
- Asset names use both `eric-*` and `jude-*`. Audit the mascot naming and usage; student-facing persona should be consistently called Jude.
- Mobile-01 iOS screenshots: functional large tap targets and clear local-save/sync messages; current presentation is deliberately austere, with generic blue CTA, sparse screen composition and verbose sign-out warning. Keep correctness and simplify visual hierarchy.

## Keep / evolve / retire

**Keep:** Edupreneurs name and slogan; logo concept; Jude mascot; recognizable subject accents; rounded cards; progress and reward concepts; French and Haitian Creole localization; explicit offline labels; large question choices.

**Evolve:** home, subject selection, learning path, question feedback, exam preparation, study review, profile, achievement celebrations, sign-out modal, Jude context entry, brand palette, icon and splash.

**Retire from native critical path:** marketing hero effects, autoplay audio, 3D Jude, persistent draggable overlay, desktop-style dashboards, seven lesson tabs, ambient music and automatic realtime listeners.

## Proposed native information architecture

Bottom tabs: **Accueil · Apprendre · Réviser · Profil**. Contextual Jude CTA on lesson/answer screens (online feature; offline explanation always available). Exams accessible as a clear section within Réviser, not confused with ordinary practice. Games and community remain on the old web experience until safety, moderation and demand justify native development. Do not require an account refresh before showing downloaded content.

### Home

1. Compact greeting, grade indicator and local/sync state (status must mean what it says).
2. Primary card: “Continuer” / “Kontinye” with the last lesson and action.
3. Small weekly progress signal and optional streak/XP; no 5-column KPI strip.
4. “Réviser mes erreurs” when practice history exists.
5. Downloaded lessons (“Disponibles hors connexion”).
6. Optional Jude action and announcements after the core learning content.

### Learning path

Grade → subject → unit → bite-sized steps: **Comprendre → Exemple → Pratiquer → Réviser**. Show one recommended next step, with an always-available subject/lesson index rather than a forced single global track. Each step has a clear offline/download state. Lesson path generated from content metadata and deterministically rendered locally.

### Lesson reader

A readable title, expected learning objective, short content blocks, inline formulas, one optional illustration, “See example”, then “Try a question”. Keep notes/summary accessible via a secondary action; don't put seven horizontally scrollable tabs above the content. Long lessons can still be segmented and revisited. Preserve revision metadata.

### Quiz

One question per screen. Compact progress indicator. Large selected answer affordance. Feedback has icon + explicit text + explanation, not color alone. Save the attempt locally before claiming success. Primary action “Question suivante” anchored where comfortable for thumbs and safe-area-aware. Avoid distracting rewards after every question.

### Progress and sync

Headline: lesson completion; secondary: correctness and review queue. Status: “Enregistré sur ce téléphone”, “En attente de synchronisation”, “Synchronisé”, “Échec — réessayer”. Explain network failures only once with a concise action; detailed diagnostics behind a disclosure. Never call an answer synced before acknowledged.

### Jude

A dedicated, accessible tutoring interface that uses approved curriculum and optional authorized learner context. For offline moments, show the lesson’s vetted explanation; do not pretend an AI answer is available. No unprompted model calls. Use an illustrated lightweight 2D avatar if helpful, not 3D on low-tier devices.

## Design system proposal (confirm with brand review)

- Primary teal ~`#087E7E`; Jude violet ~`#7C3AED`; achievement amber ~`#FF9F00`; logo-inspired deep navy candidate `#142337`; white/off-white surfaces. Separate semantic success/error/warning tokens and test contrast in both themes.
- Avoid reliance on gradient as the only way to recognize actions. No purely decorative background image in core study screens.
- Typography: system font for most reading and UI. Explore Poppins as a limited display accent only if installed-size and readability checks pass. French accents and Haitian Creole diacritics must render correctly.
- Scale: body 16–18 logical px baseline; headline 24–28; supporting 13–14 when accessible; respect system font scaling, including 200% where feasible.
- Spacing: 4 / 8 / 12 / 16 / 24 / 32 logical px; core touch targets >=44 pt on iOS and >=48 dp on Android where feasible.
- Cards: 12–18 px radii; standard borders and restrained shadows. One dominant CTA per screen.
- Motion tiers: Lite (no motion), Standard (short 120–220ms transitions), Enhanced (optional celebration, 2D assets). Respect reduced motion, battery/data saver, low RAM, and avoid autoplay sound.

## Offline and old-phone UX constraints

- SQLite is the source for cached lesson display and pending work, not a network request.
- Show explicit download size and progress; optional media never required for completing structured text practice.
- The primary workflow must remain coherent during offline, request timeout, captive portal, token refresh, low-storage and shared-phone account switch.
- Store/keep protected account data separately, with clear warning before sign-out when work is pending.
- In the Lite web tier, no-JS semantic HTML learning pages and small classic forms come before animation.
- Do not copy rich web dependencies into React Native (Framer Motion, Three.js, PDF.js, Tiptap, browser-only CSS effects).

## Accessibility and educational quality

- Test screen readers (VoiceOver/TalkBack), dynamic text sizing, proper focus order, tap targets, contrast, and wrong-answer recovery.
- Display question explanation in the selected locale; reviewed locale strings and terminology are separate publication records.
- Never equate a wrong answer with personal failure; celebrate effort and improvement without streak guilt or dark patterns.
- Verify any claimed MENFP endorsement/certification; “aligned with” must be substantiated and distinguishable from official endorsement.

## Acceptance plan after Android Mobile-01

**Design-00 (no backend changes):** Create a design-tokens page and five static React Native screen prototypes: home, subject path, lesson, question feedback, progress/offline state. Compare on small Android API 24 and supported iOS simulators. Gather preference/usability feedback from a small opt-in learner/educator cohort. Provide French and Haitian Creole copy for each. No new API or database work.

**Mobile-02:** Implement approved tokens and layouts incrementally without modifying the verified SQLite/sync behavior. Keep current app as fallback; add screenshot/regression tests, on-device measurements, and slow-network/offline acceptance. Enable motion enhancements only after low-memory metrics pass.

**Proposed UX success criteria, to validate in pilot:** Student can find and start the next downloaded lesson in <=2 deliberate taps from home; a first-time user can start a lesson without an instructional tour; no core action needs cloud AI; no data loss on offline/restart; reading remains usable with increased system text size; no clipped buttons on 320–360dp viewport; published lessons have clear locale and offline availability.

## Do not implement yet

Do not ask Fable to redesign in the middle of Android native-validation or to add Jude, payments, community or live games. First complete Mobile-01 and its baseline screenshots/performance measures. Then use this document as the proposed Design-00 brief, with review before code changes.
