# Admin-00 — dedicated web administration and analytics

**Status: architecture and specification. Draft. No code, no deployment, no migration, no staff endpoint exposed.**
Branch `admin-00` (from `main`). Date: 2026-11-26.

**Decision recorded:** administration is a **separate, desktop-first React web application** (`apps/admin-web/`, future
`admin.mon-edupreneur.com`) that talks **only** to FastAPI staff endpoints. It is never part of the student mobile app, never holds
a service-role credential, and never reaches PostgreSQL directly.

| # | Document | Contents |
|---|---|---|
| 1 | [01-information-architecture.md](01-information-architecture.md) | Modules A–H, navigation, wireframe-level screens |
| 2 | [02-roles-and-permissions.md](02-roles-and-permissions.md) | Role matrix (existing + proposed), separation-of-duties rules |
| 3 | [03-metric-catalog.md](03-metric-catalog.md) | Every dashboard metric: definition, event source, calculation, privacy tier, availability |
| 4 | [04-api-needs.md](04-api-needs.md) | Per module: what the staff API already has, what is missing |
| 5 | [05-security-and-deployment.md](05-security-and-deployment.md) | Threat model, MFA, sessions, audit, gates before any public deployment |
| 6 | [06-roadmap-and-ui-plan.md](06-roadmap-and-ui-plan.md) | Stack, milestones, scaffold plan |

## Honest baseline (verified in source on `review/final-verification-2026-11-25`, PR #21)

* **Exists, unmerged:** staff boundary, `app.staff_roles` (`editor|reviewer|publisher|admin`), `app.audit_events`, editorial workflow
  (revisions, sources and rights, reviews, submit, pack release, rollback), Word of the Day staff routes, entitlement grants, role administration
  (PR #4, #7, #9, #10). All are **drafts** with open findings; none is enabled.
* **Does not exist:** staff sign-in and **MFA** (design only), a content **takedown** route (L-B2-3), any **analytics API** or
  aggregate tables, an admin frontend, audit writes for *reads* of student data, support tooling, payments/reconciliation, Jude AI
  usage metering, notifications console, moderation.
* **Therefore:** the dashboard in this spec is mostly a *list of things to build*. Every metric is marked `available now`, `needs a
  new query`, or `needs a new event/module`. **No metric is invented**: if its source does not exist it says so.
* The original Lovable Control Center was inspected **only through the platform-00 inventory** (source reading, never run). It is
  not modified and not used as a requirement source beyond that inventory: it keyed admin by a fixed id list and wrote audit rows from
  the browser — both are the patterns this design replaces.

## Not done here (on purpose)

* **No synthetic-data scaffold.** It was within scope "if safe", but a scaffold before the API contract, MFA design and metric
  definitions are agreed would fix the wrong shapes. Plan and first screens are in doc 6 (milestone AD-1).
* No decision is taken on retention, minors' data access or payments: these are listed as owner decisions where they arise.
