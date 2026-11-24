# Design-00 report — Edupreneurs design system and five screen previews

**Branch:** `design-00` (created from `release-01-verified`, commit `bfcbe08`). Nothing pushed.
**Status:** proposal for visual review. No production screen was replaced.
**Open the screenshots:** `docs/design/design-00/gallery.html` (double-click; works offline).

## 1. What was built

| Piece | Where | Notes |
|---|---|---|
| Design tokens | `apps/student-native/src/design/tokens.ts` | Colours (light + dark, same semantic names), type scale, spacing 4/8/12/16/24/32, radii 12/16/20, sizes, 48 dp minimum touch target, motion durations |
| Theme + layout | `src/design/theme.tsx` | `DesignProvider` (theme, language, reduced-motion), `useLayout()` (text scale, compact layout rules) |
| Contrast checker | `src/design/contrast.ts` | WCAG contrast formula, used by the tests |
| Components | `src/design/components/` | Text, Icon, Button, Card, HeroCard, Pill, ConnectivityPill, ProgressBar, SectionHeader, ListRow, PathNode, StepStrip, LessonHeader, AnswerOption, FeedbackPanel, TabBar, TopBar, ScreenFrame, LoadingState, MessageState, SyncStatusCard |
| French / Creole text | `src/design/strings.fr.ts`, `strings.ht.ts` | 82 keys each, separate catalogs, test enforces identical keys |
| Fixture data | `src/design/preview/fixtures.ts` | Invented data, typed with the app's existing shapes |
| Five previews + gallery | `src/app/design/` (`home`, `path`, `lesson`, `quiz`, `progress`, `index`) | Opened by link, e.g. `monedupreneur://design/quiz?locale=ht&state=incorrect&theme=dark&width=320` |
| Scripts | `apps/student-native/scripts/design-shots.sh`, `design-a11y-audit.py` | Repeatable screenshots and accessibility audit |
| Tests | `tests/unit/design_tokens.test.ts` | 76 checks |

**Isolation.** The previews read fixtures only. They do not import the database, sync engine, API client or session code, and write nothing. No screen in the app links to them. They open only in development builds (`__DEV__`) or a build made with `EXPO_PUBLIC_DESIGN_PREVIEW=1`; otherwise they redirect to the app's start screen.
The only change to an existing file is one added line in `src/app/_layout.tsx` registering the `design` route group without a header.

**Dependencies.** None added. `package.json` and `app.json` are unchanged. System fonts only. Icons are drawn with plain views (no icon font, no SVG library, no image files). No native rebuild and no `expo prebuild` was run: the previews were served by Metro to the existing debug builds.

## 2. The current app, for comparison

Existing screens (`src/app/`): `index` → `sign-in` → `home` → `select` → `lessons` → `lesson/[id]` → `quiz/[id]`, plus `progress`. Navigation is a single stack with a system header. Existing shared components (`src/ui/components.tsx`): `Screen`, `Title`, `Body`, `Card`, `Button`, `Banner`, `Loading`, a fixed `colors` object, and `SyncCard`.

Side-by-side image: `docs/design/design-00/before-after-android.png` (top row existing app, bottom row previews, same 320 dp emulator).

| Area | Existing app | Design-00 proposal | Why |
|---|---|---|---|
| Home | Greeting, three equal buttons, sync card | One dominant "Continuer ma leçon" card, then review, then downloaded lessons | One obvious next action; the UX brief asks for ≤2 taps to resume |
| Navigation | Stack with header and back arrow | Four bottom tabs (Accueil, Apprendre, Réviser, Profil); lesson and quiz are full-screen drill-downs | Fewer, clearer destinations |
| Choosing content | Separate "select" then "lessons" list | Grade and subject chips above a unit path with four step types and written states | Shows where the learner is; nothing is locked |
| Lesson | Title, version, text | Step strip, subject + offline badges, objective, explanation, numbered worked example, key ideas, offline hint, pinned "Essayer une question" | Guided flow instead of a long page |
| Quiz | Options, feedback text, blue button | Radio-style cards with distinct selected / correct / incorrect looks (border + tint + icon + spoken label), feedback panel with the right answer, explanation and "Enregistré sur ce téléphone" | Meaning never depends on colour alone |
| Progress | Sync card first, then lesson rows | Achievements first, review next, sync status last with diagnostics behind "Détails" | Learning before plumbing; four sync states stay distinct |
| Colour | One blue for actions, system greys | Teal action, navy hero, violet for Jude/review, amber for achievement; light and dark | Brand recognition |
| Trade-off | Lesson text starts higher on the page | The lesson header uses more of a 320 dp screen before the text starts | Review: is the header worth the space? |

## 3. Tested, with results

Devices: **Android 7.0 (API 24) emulator**, 480×800, 320 dp wide, 1 GB RAM; **iPhone 17 simulator**, iOS 26.5, 402 pt wide. Both ran the existing *debug* builds with JavaScript from Metro. Emulators and simulators are not physical phones.

| Check | How | Result |
|---|---|---|
| Five screens render, FR and HT | 70 Android + 62 iPhone screenshots | Done, all in the gallery |
| Narrow widths | Android is natively 320 dp; iPhone previews constrained to 320 and 360 | No clipping or overlap found in review |
| Larger text | Android `font_scale` 1.5 and 2.0; iOS sizes mapping to 1.35×, 1.94× and the maximum (3.57×, capped at 2× by the design system) | Readable and scrollable everywhere after fixes (below). At ≥1.6× the pinned action button moves into the scrolling content so it cannot cover the screen |
| Dark mode | `theme=dark` on both platforms | Renders; all colour pairs pass the contrast test |
| States | Home: offline, pending sync, loading, empty, error. Path: offline (download needed). Quiz: idle, selected, correct, incorrect, long text. Progress: synced, pending, failed, rejected ("à vérifier"), empty | All captured |
| Reduced motion | Android animation scales set to 0; iOS `ReduceMotionEnabled` | The gallery header shows "Reduce motion: ON" on both. The only motion in Design-00 (smooth scroll to quiz feedback) becomes an instant jump; screen transitions are already disabled |
| Screen-reader names and touch targets | `design-a11y-audit.py` reads the real accessibility tree on 16 preview/state combinations | **Android: 79 activatable elements, 0 failures (min 48 dp). iPhone: 97 elements, 0 failures (min 44 pt).** Smallest target 48. Logs: `design-00/a11y-android.txt`, `a11y-ios.txt` |
| Contrast | 35 text/background pairs × 2 themes in jest | Pass (4.5:1 text, 3:1 control outlines) |
| Existing tests | `make test`, `make mobile-test`, `tsc` | **209 pgTAP + 144 pytest + 128 jest pass** (the 52 existing mobile tests plus 76 new). 405 earlier tests unaffected |

Problems found on the devices and fixed during this work:
1. Four step labels did not fit 320 dp → only the current step is named ("1/4 · Comprendre").
2. Home hero card overflowed the first screen → two badge pills replaced by one caption line.
3. Grade/subject chips wrapped to three rows → one horizontally scrolling row each.
4. Quiz feedback landed below the fold → the screen scrolls to it after "Vérifier".
5. Re-opening a preview in another state kept the old state → previews reset when the link changes.
6. At 150–200 % text: icons stayed tiny, stat cards broke "14/18" across lines, the wordmark truncated, the tab label "Apprendre" truncated, and the action bar covered half the screen → icons scale (up to 1.5×), stats stack, wordmark collapses to the mark, tab labels shrink to fit, action un-pins.
7. Last letter of "Profil" clipped on Android 7 → label now spans the tab.

**Not tested — please read:**
- No physical phone. No real low-end Android device.
- TalkBack and VoiceOver were not *listened to*; the audit checks only that each control has a name and a large enough target. Reading order and announcements need a human pass.
- The production gate (previews redirect when not a development build) is a one-line constant and was not exercised on a release build, because that needs a native rebuild.
- The existing app's Maestro UI flows were not re-run (its screens are untouched; only the one layout line changed).
- No usability session with learners or educators.
- No component render tests (the jest setup covers platform-free code only).

## 4. Size and runtime cost

Production JavaScript bundle (Hermes bytecode, `expo export`), compared with the Release-01 baseline:

| | Baseline | Design-00 | Difference |
|---|---|---|---|
| Android | 2,723,229 bytes | 2,797,160 bytes | **+73,931 bytes (+2.7 %)** |
| iOS | 2,735,165 bytes | 2,809,088 bytes | **+73,923 bytes (+2.7 %)** |
| Android, gzip | 1,174,320 | 1,210,168 | +35,848 |

This includes the preview screens, fixtures and both text catalogs, which a production build still bundles today even though it cannot open them. Removing or excluding them at Mobile-02 would recover part of this. Native binary size is unchanged (no native code added).

Memory, **indicative only** (debug build, emulator, one run, total PSS): existing first screen 242 MB; previews opened in sequence 247 → 250 → 253 → 256 MB. Debug builds carry development tooling, so these numbers say only that the previews are not dramatically heavier. Start-up and screen-open timings (p50/p95) were not measured; the spec asks for those in release mode after real integration.

## 5. Decisions that need your approval

1. **Violet and amber.** Your brief gives violet `#7C3AED` and amber `#FF9F00`; spec v0.2 proposes `#7139C6` and `#FFB347`. I implemented the brief's values for light mode (white text on `#7C3AED` passes contrast; amber always carries dark text). Dark mode uses lighter variants (`#A98BFF`, `#FFB347`). Confirm or change in `tokens.ts`.
2. **Dark mode.** Built and tested, but the app is locked to light in `app.json`. Ship dark at Mobile-02, later, or not at all?
3. **Tab meanings.** Accueil / Apprendre / Réviser / Profil. **Decided (2026-11-24): the fourth tab stays "Profil"; it is not renamed "Progrès".** In the previews "Profil" shows the Progress screen. Still open: what else belongs under Profil (account, language, sign-out) alongside progress.
4. **Logo.** The navy square with an amber "E" is a placeholder, as are app icon and splash. Supply the real mark.
5. **Haitian Creole wording.** All Creole strings are my drafts and need review by a Creole-speaking educator (e.g. "Chemen aprantisaj ou", "Senkronizasyon", "Apèsi").
6. **Tone.** "Pas tout à fait" / "Pa egzakteman" for wrong answers; "Chaque petit effort compte." Approve the voice.
7. **Step model.** Comprendre → Exemple → Pratiquer → Réviser per unit, with a highlighted "Étape suivante" and nothing locked.
8. **Jude.** Shown only as an offline, pre-written hint card labelled "Jude en direct n'est pas encore disponible". Keep that framing?
9. **Text-size ceiling.** Text scales to 200 % and stops. Raising it means more layout work.
10. **Lesson header density** on small screens (see trade-off in section 2).
11. **Preview code in production bundles** (≈74 KB): keep behind the flag, or strip at Mobile-02.

**Data the previews show that the app cannot supply yet.** These are invented in the fixtures and need a decision before they can be real: lesson objective, key ideas and hint text; step type and per-step completion; "leçon 2 sur 5"; "questions à revoir" count; weekly goal; lessons-completed total. Some can be derived on the phone from existing saved answers; others need content metadata. None was added to the backend.

## 6. Recommended Mobile-02 integration plan

Each step is separately reviewable and leaves the 405 tests green. Database, sync, authentication and SQLite code are not modified.

1. **Adopt tokens under the existing screens.** Point `src/ui/components.tsx` at the design tokens (colours, radii, type). Smallest visible change, no navigation change. Re-run the Maestro flows.
2. **Quiz screen.** Swap in `AnswerOption` and `FeedbackPanel`. Keep the existing rule: await the local save transaction, then show "Enregistré sur ce téléphone".
3. **Lesson reader.** `LessonHeader`, block rendering and pinned action, using only fields that exist; hide objective/key ideas until content provides them.
4. **Progress.** `SyncStatusCard` fed by the real sync summary; "Synchroniser maintenant" calls the existing engine and reports its real result.
5. **Home.** Continue card driven by the last opened saved lesson from local storage.
6. **Tabs and learning path.** Introduce the tab layout last, since it changes navigation and every UI test flow.
7. **Measure in release builds** (start-up, lesson open, memory; p50/p95 with sample counts) on the API 24 emulator and then a physical low-end Android phone.
8. **Human accessibility pass** with TalkBack and VoiceOver, and the Creole terminology review.
9. Decide whether to delete the preview routes or keep them as a living style guide.

## 7. How to look at it yourself

```sh
open /Volumes/T7/EdupreneursDev.sparsebundle          # mount the dev volume
cd /Volumes/EdupreneursDev/Mon-edupreneur
open docs/design/design-00/gallery.html               # all screenshots
```
On a running emulator/simulator with Metro (`npx expo start` in `apps/student-native`), open `monedupreneur://design` for the interactive gallery: pick language and theme, then any screen and state.

## 8. State of the machine

- Android emulator and iPhone simulator now hold the **debug** app (needed for Metro). Installing it replaced the Release-01 builds on both and cleared their synthetic app data. The release APK is still at `/Volumes/EdupreneursDev/artifacts/edupreneurs-release-arm64.apk`. The iOS release app is still in the build output at `/Volumes/EdupreneursDev/xcode-derived-data/edupreneurs/Build/Products/Release-iphonesimulator/Edupreneurs.app`.
- Nothing was deleted from the repository or build folders. Font scale, animation scales and iOS text size were restored to defaults.
- Raw screenshots: `/Volumes/EdupreneursDev/shots/design/`. Bundles: `/Volumes/EdupreneursDev/artifacts/bundle-design00`.
