# 1. Current-state audit (what exists, what is reusable, what is missing)

Read from: `mobile-02` (54fec1c) for the app; `main` and `review/final-verification-2026-11-25` (PR #21) for the
API, contracts and audit findings. "Verified" = read in source in this session; "Tested" = an automated test ran.

## What exists

| Area | Finding | Where |
|---|---|---|
| Catalog API | `GET /v1/catalog?locale=` returns courses → units → lessons, each lesson with `id`, `revision`, `revision_id`, `title`. Only lessons with a published revision in that locale are listed. | `routers/catalog.py` |
| Lesson API | `GET /v1/lessons/{lesson_id}?locale=` — **authenticated**; one published revision with `blocks` and **all questions including `answer_key` and `explanation`**. Unknown / draft / rejected / unpublished → one identical 404. No `ETag`, no hash, no size in the body. | `routers/catalog.py:197` |
| Client API | `ApiClient.getLesson()` with token refresh and the typed error model (`network`, `timeout`, `server`, `auth_required`, `aborted`, `client`). | `core/api/client.ts`, `errors.ts` |
| Snapshot validation | `validateLessonSnapshot` — structural and self-consistency checks (right lesson, right locale, UUID revision and question ids, non-empty blocks, no duplicate questions, answer key refers to a real choice). Its own comment says it is **not** an integrity or authenticity guarantee. | `core/api/validate.ts` |
| Atomic save | `saveLessonOffline`: download completely → validate → one SQLite transaction replacing the old copy. A failure before the transaction leaves the old copy. | `core/learning/actions.ts` |
| Content store | `saved_lessons`, `saved_questions`, `catalog_cache` in the **shared, public** `content` database (same for every account on the phone). | `core/db/contentStore.ts` |
| Account store | `attempts`, `question_progress`, `lesson_progress`, `outbox` in a **per-account** database. `attempts` stores `question_revision_id`, `lesson_revision_id`, `lesson_id` as plain values — **no foreign key to `saved_questions`**. | `core/db/accountStore.ts` |
| Answer path | `answerQuestion` → `recordAnswer`: attempt + progress + outbox row in one transaction; UI confirms only after it resolves; sync is attempted afterwards. | `core/learning/actions.ts`, `app/quiz/[id].tsx` |
| Reader | `app/lesson/[id].tsx` read SQLite only. | `app/lesson/[id].tsx` |
| Content contracts | `pack-manifest.v1`, `pack-lesson.v1`, `lesson-blocks` (v1, v2), question schemas, shared vectors. Packs are content-addressed (`object_key`, `sha256`, `bytes` per lesson; asset list with required/optional). **On PR #7 / #21 only, not on `main`.** | `packages/contracts/content/` |
| Staff content routes | `/packs`, `/packs/{id}/release`, `/packs/{id}/rollback`, `/revisions…`, `/sources…` — editorial workflow, pack and release. **PR #4, unmerged.** | `routers/staff_editorial.py` |
| Entitlements | Grant model and read API behind `EDU_ENTITLEMENTS_ENABLED` (off). **No paywall** — catalog/lesson identical with the flag on. | PR #10 |

## Reusable as-is

- Both API endpoints and the response contract (the brief asks to reuse them) — used unchanged by this slice.
- `validateLessonSnapshot` — online reading and download share it, so an online lesson is held to the same bar.
- `saveLessonOffline` — the explicit download path; reused unchanged.
- `recordAnswer` / `recordLessonCompleted` / outbox / op-ids — unchanged; only their TypeScript parameter types
  were loosened from `SavedLesson` to `{ lessonId, revisionId }`, which is all they ever read.
- The pack manifest and content-addressing model — the right base for bulk and asset delivery (not yet served).

## What is missing

| Gap | Consequence | Addressed in |
|---|---|---|
| No `ETag`, `If-None-Match`, content hash or byte size on lesson/catalog responses | Cannot verify integrity end to end, show size before download, or avoid refetching | doc 4 §A (additive fields) |
| No object storage / CDN delivery; packs are built on the server but nothing serves them to the app | No bulk download, no assets, no resume | doc 4 §B, doc 5 |
| No delivery path for books or practice exams | — | docs 4, 6 |
| No user-visible removal, storage list, quota or eviction | Students cannot free space | doc 5, roadmap CD-2 |
| No entitlement check in the delivery path | Fine today (all content free); required before licensed books | doc 6 |
| No takedown route for live content (audit finding L-B2-3) and no client behaviour for withdrawn content | A withdrawn lesson stays on phones | doc 3 (Withdrawn state), doc 7 |
| Content format v2 is not shippable (audit S6, S12, 2-B) | Math/images/audio/tables cannot be delivered yet | doc 7 gates |
| Lesson response carries `answer_key` | Acceptable for the **practice** contract; unacceptable for any controlled exam | doc 6 §4 |
| Home "continue learning", Review standings and `savedLessonStandings` iterate **saved** lessons only | An online-only lesson's progress is saved and synced but does not appear in Review lists or the Home card until downloaded | ADR-3, known limitation |

## Verified facts that shaped the design

1. **Online answers need no new persisted reference.** Answers reference revision ids by value and the account
   database has no link to the content database, so a lesson that was only read online can be answered, saved,
   synchronised and survive a restart. (Tested: `tests/delivery/contentAccess.test.ts`, "answers to an ONLINE-ONLY lesson".)
2. **Removing a download cannot touch student records**: they live in a different database file; the delete is a
   single transaction on `saved_questions` + `saved_lessons` in `content.db`. (Tested.)
3. **The mobile test harness on `mobile-02` is unsafe against the owner's shared stack** (S4: it truncates learning
   tables and pauses the shared gateway). A docker stack for the owner (`supabase_*_mon-edupreneur`) was running
   during this session. No test in this branch touched it.
