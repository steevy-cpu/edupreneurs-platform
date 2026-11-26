# Lesson navigation — Mobile-03 addendum

**Status: design proposal, not implemented.** The owner's seven-section requirement supersedes the earlier Design-00 recommendation to retire the seven lesson tabs. [Open the static visual preview](lesson-navigation-preview.html). It depicts proposed layouts, not a working app or a device screenshot. No content schema, database, route or network behavior changes are included in this addendum.

## Prototype evidence: Studygram

The connected Lovable project `14710ec1-c1bf-40aa-b397-6fddd23c28b4`, commit `3110f7971aad9abbdeb3e2965afd565f5b74b520`, was inspected read-only on 2026-11-26. `src/components/LessonPageTemplate.tsx` has the seven lesson tabs and a horizontally scrolling mobile tab strip with a rounded, filled green active tab. It renders `LessonStudygramTab` with the lesson title, content, examples, objective, grade and subject.

`src/features/matieres/components/tabs/LessonStudygramTab.tsx` presents a visual revision sheet: colored clusters, branching concept nodes and a radial summary; an “À retenir” cluster has an optional Jude voice control. `src/features/matieres/hooks/useStudygramVisual.ts` describes four pedagogical sections (explanation, deeper study, key takeaways, visual summary), checks a versioned browser localStorage cache, marks it stale after seven days and calls `generate-studygram-visual` on a cache miss or regeneration. Its UI contains loading, error, retry and regeneration states. This is source inspection, not an authenticated runtime or offline test; it does not establish educational accuracy, successful generation, cache durability or native availability. Studygram is a lesson-specific visual study aid, not evidence of a social feed.

## Placement and behavior

The four existing app destinations remain **Accueil / Akèy · Apprendre / Aprann · Réviser / Revize · Profil / Pwofil**. A lesson opens as the existing detail screen from Home or Learn; its existing back behavior returns the learner to the prior context. The seven entries belong inside the lesson, not in the global bottom bar. Practice remains the existing quiz detail flow. This preserves the current navigation structure.

Proposed section index, in prototype order (Creole copy is draft and requires educator review):

| # | French | Haitian Creole proposal | Present native foundation / availability |
|---|---|---|---|
| 1 | Introduction | Entwodiksyon | Existing title and lesson context can form a simple introduction; no objective may be invented. |
| 2 | Contenu & Exemples | Kontni ak egzanp | Existing ordered lesson blocks and examples; reuse the current online/downloaded reader without rewriting or truncating content. |
| 3 | Points Clés | Pwen kle | No verified dedicated key-points content in the current contract. Reserve in the design inventory; do not manufacture a summary or enable a tab. |
| 4 | Studygram | Studygram | Prototype visual study aid described above; no native data contract or generation exists. Reserve only; do not show a working-looking control or claim offline access. |
| 5 | Activités | Aktivite | No separate activities contract is established. Reserve until approved content and behavior exist; do not relabel quiz questions as activities. |
| 6 | Quiz | Kwiz | Existing practice questions and answer flow can be reached through the established action when available. Maintain the existing online/offline distinction and saved-answer semantics. |
| 7 | Mes notes | Nòt mwen | No verified native notes feature or persistence contract. Reserve only; do not offer a fake editor or save action. |

The diagram's complete index communicates the intended information architecture to reviewers. **Production rule:** expose only sections supported for the current lesson; absence is not a disabled fake action. A future content or feature proposal must explicitly define which sections are available and their offline behavior before exposing them. No new semantics are inferred from arbitrary block headings. For the currently supported lesson, keep the existing single reader and practice transition intact until a separately reviewed implementation can map real data without loss.

## Layout and interaction specification

- At 320dp, show a clearly labeled **Sections de la leçon / Seksyon leson an** index. When the index is open, use a two-column wrapping layout with readable full labels and at least 48dp targets; active section uses the existing `action`/`onAction` colors and rounded pill shape, plus an explicit selected state. The index and content scroll together. Do not depend on horizontal swiping or tiny abbreviated labels to discover sections.
- At 1.3× and 2×, allow labels and controls to grow vertically; switch to a single column when a two-column layout cannot fit, without truncation. The section index may be collapsed into one full-width control showing the current section to protect reading space; its expanded list must remain discoverable, scrollable, and contain all *available* sections. Do not add this control to the real app until section navigation exists.
- On selection, retain the lesson context; move accessibility focus to the selected section heading, announce the current section, and provide a labeled expanded/collapsed state for the index. Define and device-test the exact back and focus behavior before implementation. Do not falsely mark unvisited or unsupported sections complete.
- Keep full long-form lesson text, examples and explanations in reading order. The current quiz action and reader modes remain authoritative. Never imply a downloaded Studygram or notes exist when they do not.
- Use `canvas`, `surface`, `text`, `textSecondary`, `action`, `onAction`, `accentSoft` and `highlightSoft` semantic tokens, with teal/navy/violet/amber brand anchors. Teal is the active navigation color; violet and amber are restrained context cues, never the sole carrier of meaning. No new palette, external fonts, animation or image assets are needed.
- Use native primitives, mount only the current section where possible, and do not generate content, prefetch audio or make a network call for decoration. Offline lessons and practice remain usable independently of future sections. If a future Studygram is approved, its storage, availability, authorship, freshness, accessibility and network cost require a separate reviewed design; do not copy the prototype's automatic AI call into the current app.

## Acceptance before any implementation

Verify both locales at 320dp and a larger screen, font scales 1.0/1.3/2.0, 48dp targets, contrast, focus order, TalkBack, reduced motion, full scrolling and online/offline reader/quiz regression on API 24. Validate translations with a Haitian Creole educator and review the seven-section mapping with the owner. The preview is static browser artwork and provides no emulator, screen-reader or performance evidence.
