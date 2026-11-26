# 7. Roadmap (backend and mobile) with gates

Order is chosen so each step is shippable alone and none requires an unfinished overnight feature.

| # | Milestone | Scope | Depends on / gate |
|---|---|---|---|
| **CD-1** | Lesson online/offline slice | **This branch.** Read online + download, unified reader, truthful failures, local-first answers | Merge of PR #3 (mobile-02); PR #20 harness on the base before anyone runs stack-based suites; Creole review of 13 new `ht` strings; device pass (3-8) |
| CD-2 | Manage downloads | "Remove download" action + confirmation, storage screen (size per lesson, total), update-all button, `checkForUpdates` surfaced as a badge | CD-1 |
| CD-3 | Backend: integrity & conditional requests | additive `size_bytes`, `content_sha256`, `content_format` in catalog; `ETag`/`If-None-Match`/gzip on lesson; OpenAPI regenerated; client verifies hash when present | none of the unfinished lanes; `export_openapi --check` |
| CD-4 | Delivery manifest + object storage | `content.objects` & co. (doc 4 §E), pack publisher uploads to R2, `POST /v1/downloads/plan`, signed URLs; phone download manager (partial files, resume, hash, atomic activate, quota) | Owner: storage provider + cost (PO); **content format v2 gates (2-B1…B5)** before any v2 asset is served; staff takedown route (L-B2-3); readiness check X-1 |
| CD-5 | Unit / subject bulk download | queue, progress, Wi-Fi-only, per-lesson atomicity, cancel | CD-4 (or CD-3 with per-lesson requests — viable earlier because lessons are KBs) |
| CD-6 | Library (e-books) | `/v1/library*`, rights register, entitlement check, account-scoped files, streaming vs download, bookmarks/progress via outbox | CD-4; PR #10 entitlements; rights decisions (PO); reader benchmark on a 1–2 GB-RAM phone |
| CD-7 | Exam practice | practice-class exams as downloadable packs; **controlled exams** as online-only session API | Owner classification (doc 6 §4); no key on device for controlled |
| CD-8 | Admin integration | content publish → pack build → withdraw/rollback from the admin web (see Admin-00) | Admin-00 AD-3; staff MFA |

## Backend work list (CD-3/4)

1. Additive response fields + headers; tests that an old client ignores them and that `304` works.
2. `content.*` tables via a reviewed migration (**not** applied by this work); RLS: only the API login reads `content.objects`.
3. Deterministic pack builder → object upload job in the worker (the worker deployment does not exist yet — platform item).
4. `plan` and `access` endpoints; audit event per issuance; flags off by default.
5. Takedown: `withdrawn` status on resource versions, honoured by catalog, plan and access.

## Mobile work list

1. CD-1 → CD-2 UI. 2. Download manager module behind the same `contentAccess` interface (keeps the screens unchanged).
3. File-backed `objects` store using the existing `SqlDatabase` + a thin file adapter (`expo-file-system`), with a Node adapter for tests.
4. Settings: Wi-Fi-only, storage budget. 5. Library screens.

## Out of scope on purpose

Payments/paywall, leaderboard, rewards, onboarding, the overnight lanes' open findings — none is touched or required.
