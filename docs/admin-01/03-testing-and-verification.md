# Testing and verification

All run in `apps/admin-web` on the final commit: `npm run verify` → **exit 0**.

| Check | Result |
|---|---|
| `tsc -b --noEmit` (strict) | clean |
| ESLint (incl. rules banning raw HTML, fetch/XHR, browser storage, eval) | clean |
| Vitest | **9 files, 124 tests, all pass** |
| `check:src` (36 source files) | no raw HTML, network, storage, eval, env reads, secrets, URLs |
| `vite build` | OK: 1 JS (~365 kB, ~113 kB gzip) + 1 CSS (~16 kB) |
| `check:dist` (4 files) | no secret/private endpoint/unexpected URL; strict CSP with `connect-src 'none'`; no source maps |

## What the tests cover (brief item → evidence)
* **Boot and navigation:** `app.test.tsx` (boot, banner, skip link, route changes, 404, mobile menu `aria-expanded`).
* **Metric definitions:** `catalog.test.ts` parses Admin-00 doc 3 and compares M1–M21 (id, tier, availability); every metric has definition/source/calculation/period; every tile shows definition, period, freshness.
* **Unavailable states:** M4, M10, M11, M13, M14, M19, M20 render “Indisponible” with reason; fixtures contain no data for them; M21 restricted to admin.
* **Synthetic labelling:** every fixture/stale tile carries the “Synthétique” badge; banner LOCAL / DONNÉES SYNTHÉTIQUES; no password/email field exists.
* **Role visibility:** menu per persona, URL refusal, live switch, limited analytics view; `roles.test.ts` parses Admin-00 doc 2 cell by cell.
* **Editorial transitions:** `editorial.test.ts` (reviewer ≠ author, comment mandatory, author ≠ publisher, admin cannot edit drafts, frozen revisions, rights/validation gate, publish supersedes, rollback, withdraw, receipts, immutability) and UI flow in `content.test.tsx`.
* **Block contract:** limits compared with the published JSON schema; markup/control characters/v2 types rejected.
* **Keyboard/accessibility:** axe-core on 8 pages + an open dialog (0 violations, colour-contrast rule disabled in jsdom); focus trap, Escape, focus return; reorder buttons instead of drag; computed WCAG-AA contrast for 14 token pairs.
* **Responsive:** CSS contract test (breakpoints, drawer, scroll regions) **plus real rendering** (below).
* **No secrets/endpoints in built assets:** `check:dist`, scanners unit-tested with planted secrets; runtime test with `fetch`/XHR stubbed to throw.

## Real-browser verification
`npm run screenshots` drives headless Google Chrome (DevTools protocol, no extra dependency) against `vite preview` of the production build and
saved 15 screenshots in `docs/admin-01/screenshots/` at 1440, 820 and 390 px, with a measured horizontal page overflow of **0 px** on every one.
This found and fixed a real bug: visually-hidden spans inside scrolling tables caused a 482 px page overflow on phones (jsdom could not see it).
Only Chrome was used; Safari/Firefox are unverified. I viewed the dashboard, editor, publish dialog and narrow dashboard renders by eye;
the others were captured and overflow-checked but not individually reviewed.

## Not verified
Real keyboard/screen-reader sessions (NVDA/VoiceOver); actual colour contrast in the browser beyond the token calculation; printing; any browser but Chrome;
performance on weak hardware; anything involving a backend (none exists here). Backend and mobile suites were deliberately **not** run.
