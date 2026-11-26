# 5. Download and cache-management specification

Targets: old, low-RAM Android (API 24-class), unreliable and metered connections.
Numbers marked **(proposal)** are starting values for the owner to confirm and for device testing to tune; none was measured here.

## 1. Download algorithm (every resource kind)

1. **Plan.** Ask for the manifest (doc 4 §B); show total *required* bytes before the student confirms.
2. **Check space.** Require `required_bytes × 1.2 + 50 MB reserve` **(proposal)** free. Otherwise state `NoSpace`, name the amount needed, offer the storage screen. Never start and fail halfway.
3. **Fetch each object** into `cache/partial/<sha256>.part`:
   * stream to disk in chunks (**never** hold a file > 1 MB in JavaScript memory; lesson JSON is KBs and may be buffered);
   * resume with `Range` + `If-Range: <etag>`; if the server ignores Range, restart that object;
   * retry transient errors with the existing back-off (`isTransient`: network / timeout / server); stop on 4xx.
4. **Verify** SHA-256 and byte length of each completed object (streaming digest). Mismatch → delete the part, state `DownloadFailed(hash_mismatch)`. Truncated → continue/restart, never accept.
5. **Validate** content (schema/semantic validators for lessons, the existing `validateLessonSnapshot` today).
6. **Move** verified objects to `objects/ab/<sha256>` with an atomic rename (same volume).
7. **Activate** in **one SQLite transaction**: upsert `downloads` row → `Downloaded`, point the resource to the new revision, replace `saved_*` rows. Only after commit does any UI say *available offline*.
8. **Collect garbage** (two-phase): objects of the *previous* revision that are no longer referenced are deleted after step 7, never before.

If anything fails before step 7, the previous revision is untouched (**implemented and tested for lessons**: truncated, offline, wrong lesson, wrong locale, malformed, storage failure on write).

## 2. Interruption and restart

* On app start, every `downloads` row in `Downloading/Verifying/Activating` is reclassified: parts are kept for resume; the row becomes `Queued` (auto-resume only if the student's "download over mobile data" setting allows it) — it is **never** shown as downloaded.
* An OS kill during step 7 is safe: the transaction either committed or did not.
* `cache/partial` may be cleared by the OS at any time; the manager must tolerate a missing part.

## 3. Bulk (unit / subject) downloads

Always explicit; show lessons count and size first. Executed as a queue of independent per-lesson downloads (concurrency 1 on low-RAM devices **(proposal)**, 2 otherwise). Cancel or failure keeps every lesson already completed; the unit shows `n of m downloaded`. "Wi-Fi only" is a setting, default on for bulk **(proposal; owner decision)**. Opening the app, a catalog or a library **never** starts a download.

## 4. Quotas and eviction

| Store | Quota (proposal) | Eviction |
|---|---|---|
| Downloaded resources (explicit) | Student-visible budget, default 1 GB, adjustable; hard refuse when device free space < reserve | **Never automatic.** The student removes; the storage screen sorts by size and last opened. |
| Session cache (online-read lessons) | 4 lessons, 15 min, memory only (**implemented**) | LRU + TTL + cleared on sign-out |
| Partial files | — | Deleted when older than 24 h or unreferenced |
| Thumbnails / covers | 50 MB **(proposal)** | LRU |

Removal is available per lesson, unit, subject, book; it deletes content bytes and `saved_*`/`downloads` rows **only** (**implemented for lessons at service level, tested; UI = milestone CD-2**). Progress, attempts, achievements and the outbox are in different databases and are never reachable from the removal code.

## 5. Update policy

* Catalog refresh compares `revision_id` (and later `content_sha256`) with the downloaded one → `UpdateAvailable` (**implemented**).
* Updates are explicit by default. Optional "update my downloads on Wi-Fi" is a later setting. An update runs the full algorithm above, so the old revision remains until the new one is verified.
* If the student has unsynchronised answers for the old revision they remain valid: the server scores by `question_revision_id`, which is immutable.

## 6. Failure matrix

| Failure | Result |
|---|---|
| Offline at start | `ReadFailed`/`DownloadFailed(offline)`; previous copy kept |
| Connection lost mid-object | resume later; nothing activated |
| Truncated body | rejected; previous copy kept |
| Hash mismatch / corrupted | part deleted; `DownloadFailed(integrity)`; previous copy kept |
| 401 / session ended | stop; `session` message; no retry loop |
| 404 (withdrawn) | `not_found` message; downloaded copy governed by Withdrawn policy |
| Disk full during write | SQLite/file error → transaction rolled back / part removed; previous copy kept (**tested** via fault injection on `saved_questions`) |
| App killed mid-download | recomputed at start (§2) |

## 7. Large documents (books)

Streaming read: use the viewer's native range/stream support from a short-lived signed URL; never load the file into JS memory. Download: stream to `cache/partial`, verify, rename into the account-scoped books directory, then open by file URI. Show size before download; resumable as above; bookmarks/progress in the outbox. Reader choice (native PDF viewer vs. a library) must be benchmarked on a 1–2 GB-RAM device **before** commitment — not done here.
