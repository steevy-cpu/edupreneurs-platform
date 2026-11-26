# Mobile-03 source audit and proposed changes

Baseline: `4abb2e241c9909aee7c191d05b70307f851eb154` (merged PR #25 and #26). This audit precedes the presentation edits. Existing images in `docs/design/design-00/` and `docs/mobile-integration-2026-11-26/screenshots/` are historical references, not captures of this commit. ADB could not start: the sandbox denied its TCP 5037 listener. The public prototype returned an empty, script-rendered page to the available browser; its current UI and interactions could not be verified. The Design-00 UX direction and specification record an earlier Lovable source review and provide the reference instead.

| Area | Current issue and reference | Learner benefit / impact | Proposed file |
| --- | --- | --- | --- |
| Home | Continue card has no explicit section label; Design-00 calls for one obvious next action. | Faster scanning; a short translated caption, no image or animation. | `src/app/home.tsx` |
| Learn / grade / subject | Unit card has a progress bar but the label follows it; Design-00 emphasizes written progress. | Read the context before the indicator, including with a screen reader; no extra data. | `src/app/learn.tsx` |
| Review | Review cards have the same plain surface as other content, although the system reserves violet for review. | A restrained accent helps identify revision; semantic color and no new assets. | `src/app/review.tsx` |
| Profile | Account fields run together inside one card. Design-00 uses distinct information groups. | Clearer account and course selection at enlarged text; no behavioral change. | `src/app/profile.tsx` |
| Online and downloaded lesson | Shared long-form typography and structured examples already exist; historical captures do not establish current rendering. | Preserve full text and existing behavior; device typography verification remains required. | `src/app/lesson/[id].tsx` |
| Practice / feedback | Existing large radio cards, written result and explanatory feedback already follow Design-00. | Preserve established controls; validate contrast and target size in existing tests. | `src/design/components/Learning.tsx` |
| Sign-in / onboarding | Existing forms and locally gated flow require device review before visual changes. | Avoid disrupting sign-in and first-run behavior without baseline evidence. | `src/app/sign-in.tsx`, `src/app/onboarding.tsx` |
| Empty, loading, error, offline | Shared state components and explicit connectivity/sync labels already exist. | Maintain truthful states; actual offline and screen-reader verification pending. | `src/design/components/Chrome.tsx`, `src/ui/shell.tsx` |

No palette change is proposed. The original teal, navy, violet and amber anchors remain in `tokens.ts`. All proposed changes are static native views, with no added network, asset, animation, or dependency cost. Device layout, text scaling, contrast of any new combination, scrolling and performance must still be checked.
