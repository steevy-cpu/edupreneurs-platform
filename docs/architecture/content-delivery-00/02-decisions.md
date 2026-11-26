# 2. Architecture decision records

Each ADR: **Decision · Why · Consequences · Status**. "Owner" marks a choice the product owner must confirm.

## ADR-1 — Two explicit modes, one reader, one access service
**Decision.** Every lesson offers *Lire maintenant* (read online) and *Télécharger* (save). One reader and one quiz
screen render both; a single module (`core/learning/contentAccess.ts`) is the only place that knows where a lesson
came from (`source: 'online' | 'downloaded'`).
Operations: `openLesson(mode)`, `readOnline`, `getDownloaded`, `downloadForOffline`, `removeDownloaded`, `checkForUpdates`.
**Why.** Two readers drift apart; one reader with a `source` flag cannot. **Consequences.** UI differences are limited to
badges and the download button. **Status.** Implemented for lessons.

## ADR-2 — Online reading is memory-only and never silently becomes a download
**Decision.** A lesson read online is held in a bounded in-memory cache (4 entries, 15-minute TTL, cleared on sign-out),
only so the exercises screen and "back" do not refetch. It is not written to SQLite, not shown as downloaded, and does not
become the Home "continue" lesson. Only `Télécharger` writes `saved_lessons`.
**Why.** The brief forbids converting online-only into a download; a low-RAM phone needs the bound.
**Consequences.** After a restart an online-read lesson is gone until read or downloaded again (truthful).
**Status.** Implemented, tested (cache bound, expiry, nothing persisted).

## ADR-3 — Student work is local-first and independent of how the lesson was opened
**Decision.** Answers, completions and outbox rows reference revision ids by value and are written to the account database
before any confirmation — identical for online and downloaded lessons. **No extension of the SQLite model is required.**
**Why.** `attempts` has no foreign key to content; verified in source and by test (answer with the network gone → pending,
survives restart, other account sees nothing).
**Consequences / known limitation.** Review lists and the Home card are built from *saved* lessons, so progress on an
online-only lesson is stored and synced but not shown there until the lesson is downloaded. Candidate follow-up (owner):
store a minimal `(question_revision_id, lesson_id, title)` reference per answered online lesson so Review can say
"download to review". Not built, because it adds data without a product decision.
**Status.** Implemented. Follow-up needs an owner decision.

## ADR-4 — The server stays authoritative for scoring
**Decision.** The phone's verdict is provisional ("Résultat provisoire…", existing copy). The server re-scores on sync.
**Why.** Unchanged from the existing contract; online reading does not change it. **Status.** Unchanged.

## ADR-5 — One distribution architecture for every resource kind
**Decision.** Lessons, unit packs, books, practice-exam packs and media are all **resources** with: an immutable, versioned
identity; metadata in PostgreSQL; bytes in object storage (e.g. Cloudflare R2) addressed by SHA-256; a *delivery manifest*
listing objects with size, hash and required/optional; the same client download manager and the same lifecycle (doc 3).
**Why.** Separate download systems per kind multiply bugs (resume, verification, eviction) and storage screens.
**Consequences.** The existing `pack-manifest-1` is the lesson/pack specialisation; books and exams get sibling manifests
with the same envelope. **Status.** Design (doc 4). Owner: provider choice and cost.

## ADR-6 — Content-addressed objects, revision-aware caching
**Decision.** An object's key is its SHA-256. A revision is a list of object hashes. `ETag` = the revision id (lessons) or
sha256 (objects). Objects are immutable → `Cache-Control: public, max-age=31536000, immutable` on the CDN; catalog/manifest
responses are `private, no-cache` with conditional requests.
**Why.** Free integrity verification, free deduplication of shared images, trivial rollback, no cache invalidation.

## ADR-7 — Downloads are explicit, student-controlled and never block starting
**Decision.** No automatic download of units, subjects or the library. Bulk (unit/subject) is an explicit action showing
size first, per-lesson atomic, cancellable, Wi-Fi-only toggle. Keep the previous valid revision until the new one is
verified and activated. **Status.** Lessons implemented; bulk designed.

## ADR-8 — Two assessment classes; protected answer keys never reach the client
**Decision.** *Practice* (today's contract: key + explanation shipped, provisional local feedback) may be online or
downloadable. *Controlled / supervised* exams are online-only, server-timed, **server-scored, no answer key on the
client**, and are out of scope for download. See doc 6 §4. **Status.** Design; needs owner confirmation of which papers are which class.

## ADR-9 — Licensed documents are checked at issuance, not at the object
**Decision.** Books are delivered through an *access* call that checks authentication + entitlement + rights and returns a
short-lived signed URL (stream) or a manifest (download). The object store never serves a licensed object anonymously.
**Why.** Entitlements live in PostgreSQL; the CDN cannot evaluate them. **Status.** Design; depends on PR #10 and the
rights register (PO decisions).
