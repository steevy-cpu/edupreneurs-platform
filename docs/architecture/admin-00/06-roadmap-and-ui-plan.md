# 6. Roadmap and UI plan

## Stack (recommendation, not yet adopted)

React 19 + TypeScript + Vite; TanStack Router/Query; API client generated from `packages/contracts/openapi.json` (same check as the
mobile app: `check:api`); a small accessible component set built on the Design-00 tokens (reuse colours/typography; do not import React
Native code); charts via a single maintained library; i18n fr first. Tests: Vitest + Testing Library, Playwright for role-boundary flows
against an isolated local stack. **Choose boring, auditable dependencies; fewer is better for a staff tool handling minors' data.**

Location `apps/admin-web/`; its own `package.json`; CI job separate from mobile. It must not import from `apps/student-native`.

## Milestones

| # | Milestone | Deliverable | Gate |
|---|---|---|---|
| **AD-0** | This specification | docs 1–6 | owner review |
| AD-1 | Scaffold on synthetic data | shell, nav, environment banner, role-aware menu, tiles with definitions/freshness, **MSW/fixture API only**, no real URL | metric catalog agreed (doc 3); contract shapes agreed |
| AD-2 | Staff auth + MFA | login, enrolment, step-up, session handling (backend + SPA) | staff identity decision; security review |
| AD-3 | Content workflow UI | catalogue tree, revision editor, review queue, sources/rights, pack preview/release/rollback/**withdraw** | takedown route; content v2 gates for non-text blocks; PR #4 merged |
| AD-4 | Dashboard v1 | M1, M2, M3, M5–M8, M12, M15, M16, M18 on aggregate tables | worker + aggregate tables; K decided |
| AD-5 | Admin & safety | roles, audit log viewer, support lookup, announcements, ops view | S13 fix, audit read API |
| AD-6 | Word of the Day & Gold consoles | calendar/review; rule versioning, leaderboard policy | owner decisions PO-09, 2-C* |
| AD-7 | Library & exams console | resources, rights, class field | Content-Delivery-00 CD-4…CD-7 |
| AD-8 | Payments console | read-only first, then reconciliation | billing modules approved |
| AD-9 | Jude AI console | config, usage, budgets | module exists |

## First screens to build in AD-1 (so reviewers see the real shape early)

1. Dashboard with **every** tile from the catalog, including honest "not available — needs event" states.
2. Revision editor with the 320 dp phone preview using the real lesson block renderer rules (plain text only).
3. Role matrix viewer (read-only) generated from doc 2's data to prove the menu hides what a role cannot use.

## Open owner decisions that block Admin work

Staff identity provider and MFA method; whether `analyst`/`support` roles are wanted; retention of audit logs; value of K;
whether aggregate download/read counters may be collected; two-person approval threshold for money-moving actions; hosting of the SPA.
