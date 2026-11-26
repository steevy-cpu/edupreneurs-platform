# Edupreneurs — Design-00 Experience Specification v0.2

**Status:** Proposed visual direction and interactive HTML reference. Not an implemented React Native interface, an accessibility certification, or an authenticated usability test.

**Evidence basis:** `Edupreneurs_UX_Direction_v0.1.md` (read in full); Lovable source inspection at commit `3110f7971aad9abbdeb3e2965afd565f5b74b520` (`src/index.css`, `src/shell/config/navigation.ts`, `src/components/dashboard/tabs/OverviewTab.tsx`, `src/components/LessonPageTemplate.tsx`, `src/pages/Matieres.tsx`, `src/components/JudeChatbot.tsx`); Mobile-01 iOS screenshots supplied in the conversation; Android Release-01 validation report as shared by owner. iOS Release-01 results were still pending when this brief was written.

**Product name:** Edupreneurs. **Domain:** mon-edupreneur.com. Keep established native bundle identifiers/deep links until deliberately reviewed.

## 1. Product experience contract

One minute after launching the app, a learner should know their grade/subject, what lesson to continue, whether it is saved offline, and whether recent work is awaiting synchronization. The first usable lesson view must not require an AI call or optional network request. Recognition and recall of the product come from its colors, tone, mascot and consistent interactions—not animated effects.

### Non-negotiables

- Do not change previously validated SQLite, sync, authentication or backend behavior during the design-only milestone.
- Preserve explicit differentiation between **saved locally**, **pending sync**, **server confirmed**, **sync failure**, and **download not installed**. Connectivity indicators must not falsely imply successful sync.
- On a shared phone, student A's private state remains inaccessible to B through account switches. A device logout with pending work must have a safe, understandable path.
- French and Haitian Creole are peers, not an English-first interface with secondary strings. Require educator/editor review of translated terminology.
- Layouts must work at 320/360/390 logical-point widths with dynamic text, VoiceOver/TalkBack, and reduced motion.
- The baseline uses no 3D, autoplay audio, external fonts, remote images, or continually active realtime subscriptions.

## 2. Visual system proposal

| Token | Proposed | Purpose / caution |
|---|---|---|
| `brand.teal` | `#087E7E` | Main learning action; verify contrast in final states |
| `brand.navy` | `#142337` | Strong headers and higher-value hero surfaces; proposed logo-inspired value |
| `brand.violet` | `#7139C6` | Jude and review context; proposed adjusted native shade |
| `brand.amber` | `#FFB347` | Achievement accents with dark foreground, not white-on-amber |
| `surface.canvas` | `#F4F7F5` | Quiet light background |
| `surface.card` | `#FFFFFF` | Primary reading surface |
| `text.primary` | `#142337` | Main text |
| `text.secondary` | `#566778` | Secondary copy; check contrast against white and background |
| `border.default` | `#DCE6E2` | Dividers and outline cards |
| `status.good` | `#136D43` | Correct answer / acknowledged status; also icon and wording |
| `status.bad` | `#A5343C` | Incorrect answer; no punitive language |
| `radius.sm/md/lg` | `12/16/20` | Practical consistency instead of many one-off radii |
| `space` | `4/8/12/16/24/32` | Core spacing scale in logical pixels |
| `touch.min` | iOS ≥44pt, Android ≥48dp | Primary targets; tab hit regions must meet target |
| `type` | System fonts; 16–18 body, 24–28 headline | Optimize old device rendering; support OS font scaling |

The teal/purple/amber family is grounded in Lovable tokens, but colors above form a *proposed updated palette* and are not all exact legacy values. Original Lovable teal is HSL(180,88%,27%), approximately `#087E7E`. Original secondary purple is ~`#7C3AED`. Do not change current branding assets without owner approval. Accessibility validation must cover all interactive states.

## 3. Information architecture

Bottom navigation: **Accueil | Apprendre | Réviser | Profil**. Avoid six destinations + theme toggle from the existing web bottom bar. Jude appears contextually as an optional tutoring affordance, not a persistent draggable button. Exam practice is a subsection of Réviser, distinct from casual, answer-key-visible offline drills.

#### Screen A — Home

- Top: Edupreneurs wordmark, grade badge, compact connectivity indicator (not equivalent to sync success).
- One dominant “Continue learning” card with subject, next unit, progress and offline availability.
- Below: one review recommendation and downloaded lessons.
- No five-column KPI row and no marketing hero/particles.
- One-tap continuation for a known downloaded lesson.

#### Screen B — Learning Path

- Clear grade and subject context.
- Unit and 4 step types: **Comprendre → Exemple → Pratiquer → Réviser**.
- Visual connection between step nodes; clearly mark completed/current/future, with text status.
- Learning-path progress derives from local saved state, is not gated on a network request.
- All legitimately available lessons remain navigable; no punitive lock mechanic that prevents revisiting.

#### Screen C — Lesson Reader

- Title, subject, revision context and objective up front.
- Short semantic text blocks, readable maths, one example, inline hint from approved content, then “Try a question”.
- Avoid seven-tab interface and horizontal scrolling navigation.
- Notes/summary remain reachable as secondary actions in a later implementation.
- Optional Jude AI appears only if online and permitted; offline hints never masquerade as live AI.

#### Screen D — Question + Feedback

- One question per screen, count and small progress strip.
- Distinct selected state, then correct/incorrect state with explicit icon and text (color alone never carries meaning).
- Save answer in SQLite transaction **before** “saved on this phone” confirmation; do not modify current write ordering.
- Explanations remain visible while offline; bottom CTA and feedback remain reachable on 480×800 and with large text.
- Wrong answers invite another explanation or revision; no shame/over-celebration.

#### Screen E — Progress / Offline Status

- Lead with learning progress: completed lessons, accuracy and next review.
- Keep synchronization state visible but lower in hierarchy.
- “Saved locally”, “pending sync”, “confirmed” and “rejected/retry” are distinct; last server acknowledgment time only if actually known.
- No misleading simulated “sync now” success in a real app. Native must call the existing sync engine and wait for acknowledgement.

## 4. Interactive reference

`Edupreneurs_Design00_Interactive_Prototype.html` is a self-contained offline HTML document with no external dependencies. It simulates:

- Four-tab navigation plus two drill-down screens (lesson and quiz).
- French / Haitian Creole language switching.
- Online / offline status presentation.
- 320 / 360 / 390 px phone widths.
- Selecting and checking an answer, with locally styled feedback.

**This is a visual/interaction demonstration only.** It does *not* access SQLite, Supabase, FastAPI, production accounts, or actual network state; simulated progress counts are illustrative. All marks, icons, and demo data should be treated as temporary placeholders until approved brand assets/real app state are wired.

## 5. Accessibility and performance gates

- Screen reader: every element has an accessible name, appropriate role, sensible focus order, and announced feedback/status. Test, don't infer from markup.
- Text scaling: test 100%, 150% and 200%; no clipped question actions; scroll when necessary.
- Visual: verify contrast for dark/light/disabled/selected/success/error states, and do not communicate meaning through color alone.
- Interaction: minimum targets; one obvious primary CTA; no autoplay audio/particles/3D on the critical path.
- Device matrix: Android API 24 1GB low-memory emulator at 480×800, smallest available supported iPhone simulation, plus a modern control. Emulator success is not physical-phone proof.
- Measurement: screenshot and record p50/p95 cached-home/lesson opens and memory in release mode after actual implementation, with sample count; never claim the prototype meets these targets.
- Usability pilot: ask 5–8 volunteers / educators to do "find your downloaded math lesson", "answer once offline", "find unsent work", "switch languages" without verbal hints. Report completion, confusion, and time. Get appropriate guardian/educator consent and avoid recording student data.

## 6. Design-00 Fable task (separate from Mobile-02)

### Inputs
- This `Edupreneurs_Design00_Spec_v0.2.md`.
- `Edupreneurs_UX_Direction_v0.1.md` in `docs/design/`.
- `Edupreneurs_Design00_Interactive_Prototype.html` for layout/flow reference only.
- Existing React Native screens and native-validation reports.

### Work
1. Confirm Release-01 status. Do not alter its in-progress iOS build/worktree.
2. Work on a `design-00` branch/worktree after Release-01 is safe and committed; preserve `mobile-01` history.
3. Define typed design tokens and reusable RN presentation primitives under `apps/student-native/src/design/` or a similarly clean boundary.
4. Build isolated, fixture-driven RN previews of Home, Learning Path, Lesson Reader, Question Feedback and Progress/Sync; keep current authenticated routes and sync workflow untouched.
5. Use only existing reviewed data shapes for UI fixtures. Do not invent API endpoints or migrations.
6. Provide FR/HT strings as separate reviewed catalogs; do not rely on automatic translation in the runtime.
7. Capture paired iOS/Android screenshots for both languages; test 320/360/390 widths and system font scaling. Document physical device tests as pending.
8. Include normal, loading, empty, offline, pending sync, error, selected answer, correct answer, incorrect answer, and long-copy states.
9. Prefer stable static icons and compressed 2D Jude assets if approved. Do not add Framer Motion, Three.js, a WebView, extra icon packs or heavy fonts merely for styling.
10. Compare proposed screens to current screenshots and document what changed, why, and how it affects task completion and device constraints.

### Acceptance / stop rules
- No regressions to 405 automated tests.
- No change in database/auth/SQLite/sync logic; design previews must use fake local fixtures and not write canonical data.
- No destructive `expo prebuild` or native rebuild unless required and separately approved.
- No clipped critical UI at small sizes or larger text settings.
- Demo preview must not be exposed to production users through navigation.
- Do not push/deploy to stores. Request design approval before wiring new screens into real navigation.

## 7. Next implementation sequence

**Release-01 final check → Design-00 design review → Mobile-02 incremental UI integration → physical low-end Android test → optional richer motion/Jude interface.**

Avoid shipping UI polish before the offline, authentication, session and progress contracts have proven stable.
