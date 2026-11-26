# 4. API needs per module

Legend: **have** = route exists on `review/final-verification-2026-11-25` (draft, unmerged, flags/staff surface off) · **gap** = missing.
All staff routes live under `/v1/staff/*`, are bound to staff identities (not learner tokens), are audited, and stay unreachable from the
internet until the gates in doc 5 are met. The admin web consumes an **OpenAPI-generated client** from `packages/contracts/openapi.json`.

| Module | Have | Gap (to design and build) |
|---|---|---|
| Auth for staff | — | Staff sign-in, **MFA (TOTP + recovery codes)**, session list/revoke, step-up endpoint, safe account recovery (admin-assisted with second approver) |
| A. Dashboard | `/health` | `GET /v1/staff/metrics/{metric_id}?from&to&group_by` over scheduled aggregate tables; `GET /v1/staff/status` (readiness); aggregate tables + worker jobs; K-suppression done **server-side** |
| B. Content | `/revisions` (create/edit/get), `/revisions/{id}/sources`, `/submit`, `/review-queue`, `/revisions/{id}/review(s)`, `/lessons`, `/lessons/{id}/revisions`, `/packs`, `/packs/{id}/release`, `/packs/{id}/rollback`, `/sources`, `/sources/{id}/rights` | **Withdraw/takedown** (L-B2-3); catalog tree read model (grade→subject→unit→lesson with status); revision **diff**; asset upload + attach/detach routes (author-checked functions exist: #18); AI-draft endpoint (provider call from the server only; stores `ai_assisted` marker and model id); pack build **preview** (manifest dry-run); full-text search |
| C. Exams & library | — | Resource model (`kind`, `class: practice|controlled`), rights register, upload with hash, signed-URL issuance, entitlement rule editor — see Content-Delivery-00 doc 4 |
| D. Word of the Day | `/words`, `/words/{id}/revisions`, `/words/{id}/retire`, review routes, `/revisions/{id}/audio`, `/calendar`, `/schedule/{haiti_date}`, `/schedule/ensure` | Not behind `daily_word_enabled` (known); audio upload flow |
| E. Gold & engagement | rules as data (DB), leaderboard config tables | Staff routes for rule versioning, achievement definitions, leaderboard policy (K floor, refresh schedule — plan items 1-2, 2-C2), fraud query endpoints |
| F. Jude AI | — | Entire module: config store, flags, usage ledger, budgets, provider health |
| G. Administration | `/roles` (list/grant/revoke, last-admin check — S13 open), audit events table | **Audit log read API** (filter/export), support lookup (minimal view + reason), announcements, notifications console, moderation, ops/readiness view, lifecycle routes (blocked by S3) |
| H. Payments | `/grants`, `/grants/{id}/revoke`, `/learners/{id}/grants` (admin grants, mock provider) | Plans/prices admin, provider events viewer, orders/refunds, MonCash adapter, **reconciliation** job + queue, promo codes, gifts |

## Contract conventions for all new staff routes

* Request carries `Idempotency-Key` for mutations; response returns an **audit receipt id**.
* Errors use the existing envelope (`error.code`, stable codes); 403 for missing role, 401 for missing/expired MFA step-up (code `step_up_required`).
* Lists are cursor-paginated and server-filtered; no unbounded exports.
* Free text is validated by the same plain-text rules as content (no control/invisible characters, no markup) and rendered as text.
* Every route has a role row in doc 2 and a test that each *other* role gets 403.

## Data the web app must never receive

Service-role keys, database URLs, object-storage secrets, provider API keys, raw learner answer text, other staff members' sessions,
signing keys. The browser gets short-lived signed URLs for specific assets only.
