# Verification and release readiness

Candidate base: `4abb2e241c9909aee7c191d05b70307f851eb154`. Work is source-level and is not device-accepted. The previous Design-00 and mobile-integration images are historical reference material, not before images from this candidate. No after gallery has been captured. The public prototype page returned no inspectable rendered content through the available browser; the prior documented source review is the visual reference.

The primary-tab changes use existing semantic colors, typography and spacing. No changes are intended to learning actions, navigation routes, sync, data storage, authentication, API contracts, flags, assets or dependencies. Review-card text colors against the light accent surface calculate to 13.35:1 (primary) and 5.52:1 (secondary); interactive controls and actual device rendering still require verification. The changes add no assets or animation. Startup, scrolling, memory and bundle size have not been measured; no performance claim is made.

Release acceptance remains open:

- [ ] Capture exact-base and candidate screenshots on the same API 24, 320dp, 1 GB emulator in French and Haitian Creole at 1.0, 1.3 and 2.0 font scales, including offline and reduced motion; inspect a larger display.
- [ ] Verify real tab screens, sign-in, onboarding, catalog, readers, practice and all feedback states; fixture previews alone cannot establish production screen behavior.
- [ ] Check touch bounds, reading order, TalkBack, large-text scrolling, contrast and clipping on devices; obtain a Creole educator's review.
- [ ] Run hardened isolated full mobile harness with a uniquely identified disposable stack; never use the owner's shared stack.
- [ ] Compare release bundle sizes and measure startup, scroll and memory on the target device; test a physical low-end Android and iOS device when available.
- [ ] Owner review of visual direction, Jude artwork and wording. No Jude functionality is enabled.

The local ADB command initially failed to bind in the sandbox. With host access it returned an empty device list. A GitHub-hosted screenshot workflow and its artifacts have not been created or run; existing `design-shots.sh` captures fixture preview screens and cannot by itself prove production-screen changes. Do not interpret it as a complete before/after solution.

## Checks on this candidate

- `tsc --noEmit` and `tsc --noEmit -p tests`: passed.
- `jest -c jest.delivery.config.js --runInBand --testPathIgnorePatterns test_api_port`: 19 suites / 331 tests passed. This stack-free selection covers component, navigation, online/offline reading, delivery and unit behavior; it does not replace integration against a disposable backend. The port-binding suite was excluded because the sandbox denied localhost listeners.
- `jest -c jest.delivery.config.js --runInBand tests/unit/design_tokens.test.ts`: 78 tests passed, including secondary text on the accent surface in both palettes.
- `git diff --check`: passed before commit.
- Expo lint: unavailable as configured; the project has no ESLint configuration or lint script, and `expo lint` attempted to install one. The attempted package changes were removed. No lint pass is claimed.

The initial run with an incomplete dependency directory produced module-not-found failures and three socket-denial timeouts. After pinned dependencies were installed from the local npm cache, the stack-free selection above passed. The full hardened suite was not run.
