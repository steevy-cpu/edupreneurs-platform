# Admin-01 independent QA

**Verdict.** Ready for owner review as a synthetic-only administration frontend with the stacked corrections in [draft PR #29](https://github.com/steevy-cpu/edupreneurs-platform/pull/29). PR #27 by itself retains reproducible defects.

The review started from [8a5d6d3](https://github.com/steevy-cpu/edupreneurs-platform/commit/8a5d6d3f28062e2090cc71862723e90cc0dd4429) on `feature/admin-01-web-dashboard`. Work took place in a separate worktree on `fix/admin-01-independent-qa`. The first CI commit, `ce2877d`, preserved the exact candidate app tree so the same browser probes could exercise the original build. Reviewed application tree: `31972f4a0308c87b96e14bb4f271b6e19a4efd9e`.

## Findings and retest evidence

| Area | Observed on the candidate | Corrected behavior and evidence |
|---|---|---|
| Metric catalog and fixtures | M4 carried T0, M5/M6 omitted T0, and the daily M3 headline disagreed with its chart. M8 conflated missing cells with suppression and unknown answer counts with zero. | All 21 tier and readiness entries are compared with Admin-00. The daily series supplies the headline. Missing, suppressed and unknown cells render separately. A simulated below-K group has both counts suppressed. |
| Scope of role previews | Editor saw platform aggregates and another persona’s session audit receipt. The 17×6 capability cells themselves matched the specification. | Own-content M16 counts use the editor’s author ID. M5/M7/M8 and the median have no attributable editor fixture and show unavailable. Limited audit reads use stable actor IDs. Admin retains the full synthetic receipt list. |
| Editorial state | An invalid supplied Kreyòl translation passed a French-only submission gate. Rollback could republish an author’s own revision or move forward on a second rollback. A returned draft could lose the changes under review. | Submission checks French and any supplied translation. Rollback identifies the exact older target in the dialog and checks its author. A new draft carries forward the latest returned text. |
| Editorial controls | Saving after a language change could save an untouched translation. Removing and adding sources could create duplicate IDs. The submission dialog discarded its reviewer note. | Save operates on the changed locale, reset restores the visible draft, source IDs stay unique, missing targets fail without a receipt, and submission notes enter synthetic history and receipts. |
| Accessibility and layout | Dashboard heatmap contrast failed at all three widths. The editor had two primary headings and overflowed at 320 px. The skip link changed the hash route, hidden menu links took focus, Escape failed to restore menu focus, and dismissing a completed dialog lost focus. | Single editor heading, shrinkable layout, higher heatmap contrast and accessible block-error descriptions. Keyboard probes exercise the skip link, responsive menu, dialog, receipt and focus after dismissal. |
| Build controls | No dedicated admin CI, generated TypeScript build state tracked, and a CSP substring check accepted extra source expressions. | Admin CI installs from the lockfile, runs the verification script and tests the production build in Chrome. Build state is ignored. The built policy check verifies complete directives and rejects duplicates. Scanner diagnostics redact suspect values. |

The original `npm run verify` passed **124/124** despite these issues. Eight focused regression cases failed on the original application, covering translation validation, rollback direction and authorship, returned text, receipt scope, editor analytics, unknown heatmap data and the M3 headline. The production-browser baseline failed **12 assertions**. The first correction rerun narrowed that to small-text contrast in the heatmap at the three widths. [Baseline browser run](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45878525199) · [Intermediate browser run](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45879404731)

## All 21 metrics

The readiness column describes the specification’s data source. The presentation column describes what the reviewer found in this frontend. All displayed figures use deterministic fixtures or the current in-memory editorial session. The global French banner identifies the demo and every populated or stale metric has its own synthetic badge. [Admin-00 metric definitions](../../architecture/admin-00/03-metric-catalog.md)

| ID | Definition | Tier | Source readiness | Presentation |
|---|---|---|---|---|
| M1 | Non-erased learner profiles | T0 | Existing | Synthetic total and 7-day change |
| M2 | New profiles by Haiti calendar day/week | T0 | Existing | Weekly series |
| M3 | Distinct learners with accepted learning activity | T0 | Queries | Daily and rolling 28-day counts, with offline-arrival caveat |
| M4 | App sessions/opens | — | New event | Unavailable, no inference from sync |
| M5 | Accepted lesson completions | T0/T1 | Existing | Seven daily counts and total |
| M6 | Accepted practice answers | T0/T1 | Existing | Daily counts and 14-day total |
| M7 | Correct share of server-scored answers | T1 | Existing | Synthetic 7AF class, sample size, no individual result |
| M8 | Distinct active learners and answers by grade/subject | T1 | Queries | 28-day grid, simulated K=5 suppression |
| M9 | Gold awarded by day and achievement awards | T0 | Conditional existing | Daily gold, seven-day totals, flag dependency disclosed |
| M10 | Resource downloads and bytes served | T0 | New collection | Unavailable |
| M11 | Online lesson reads | T0 | New approved counters | Unavailable |
| M12 | Server sync outcomes and rejection reasons | T0 | Queries | Four daily outcome rates, rejected counts and codes, stale fixture |
| M13 | Device pending age and failures | T0 | New telemetry | Unavailable |
| M14 | Exam sessions and score distribution | T1 | New module | Unavailable |
| M15 | Upcoming days with published vocabulary | T0 | Existing | Fourteen-day coverage |
| M16 | Revisions by status, waiting review, median elapsed time | T0 | Existing | Session counts and separate synthetic median. Editor sees own counts |
| M17 | Delivered/failed notifications by kind | T0 | Existing, dummy adapter | Labelled synthetic example by kind, no claim of actual delivery |
| M18 | API/DB health and readiness checks | T0 | Queries | Simulated API/DB status, worker and X-1 unknown |
| M19 | AI usage, cost and errors | T0 | New source | Unavailable |
| M20 | Financial totals and entitlements | T0 | Schema only, no reconciliation | Reason displayed, no revenue amount |
| M21 | Individual anomalous earning or duplicate operations | T2 | Queries, admin only | Restricted for other roles, unavailable for admin, no learner rows |

## Roles, security and integration boundary

- The 102 permission cells match the four existing roles and the two proposed roles. Editors author their own drafts, reviewers assess other authors’ frozen submissions, and publishers/admins can release an approved revision subject to the separation rule. Admin alone cannot edit or review drafts. The matrix identifies the limited and proposed capabilities. Unimplemented modules remain explanatory screens. [Admin-00 permissions](../../architecture/admin-00/02-roles-and-permissions.md)
- The French selector says “Aperçu de rôle (synthétique, pas une connexion)”. Analyste and Support are marked proposed in the selector and matrices. Selecting a persona changes the in-memory preview. There is no staff identity, credential exchange or MFA challenge.
- Traced edits, review, publish, rollback, withdrawal and reset to the in-memory store. Actions produce synthetic receipts. React renders editor-provided strings as text and the validator rejects markup at submission. Chrome displayed inert formatting markup literally, saved it in memory and discarded it on reload.
- Inspected fixture provenance, runtime dependencies, asset URLs and build outputs. Source and distribution scans found no private service URL, known secret pattern or environment read. No student records or authentication material were found. The scanner allows known dependency documentation/namespace strings. Only static requests were observed during the exercised flows. The built meta policy blocked a same-origin test request through `connect-src 'none'`.
- No server, shared database or external service participated in these tests. Server-side roles, MFA, student privacy enforcement with real data, and deployment headers such as `frame-ancestors` require separate review before any live integration. K suppression here demonstrates presentation on synthetic data.

## Verification and limits

| Check | Result on the corrected frontend |
|---|---|
| Installation and static analysis | Clean lockfile installation, TypeScript and ESLint passed |
| Vitest | 135/135 across 10 files, including the 11 independent regression tests |
| Production build and scans | Vite production build passed. Source scan covered 36 files. Distribution scan covered all four built assets and passed the strict meta-CSP and source-map checks |
| Chrome | 61/61 assertions. Four pages at 1440×900, 820×1100 and 320×740. No document overflow, duplicate primary heading, reported axe violation or uncaught application exception |
| Visual inspection | Reviewed all 12 renders. Cards stack on narrow screens, the editor wraps its controls and the queue and roles tables scroll within their own labelled regions. The orange synthetic banner stays visible when the page scrolls |
| Evidence | [Corrected verification on 92b0731](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45879861916) · [Full-size screenshots and results.json](https://github.com/steevy-cpu/edupreneurs-platform/actions/runs/45879861916/artifacts/15146957348) · [Screenshot matrix retained in Git](browser-matrix.jpg) |

The local sandbox refused a loopback listener. The real-browser runs used the production build on a disposable GitHub runner. The dedicated workflow repeats the same browser assertions and retains the full-size captures.

Chrome automation covered keyboard navigation, focus, overflow, accessible names and automated WCAG rules. This review did not include a human screen-reader session, Safari/Firefox, touch hardware, printing or deployment headers. These results establish readiness only for the synthetic milestone.
