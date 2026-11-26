# 4. API contracts and storage model (proposed — nothing here is applied)

Rule: **additive only** on `/v1`. A client built today must keep working unchanged. Anything format-aware waits for the
format-negotiation work (correction plan 2-B2).

## A. Changes to existing endpoints (additive, small)

| Endpoint | Change | Why |
|---|---|---|
| `GET /v1/catalog` | per lesson add optional `size_bytes`, `content_sha256`, `content_format` | show size **before** download (brief §8) and verify it after |
| `GET /v1/lessons/{id}` | response header `ETag: "<revision_id>"`, `Cache-Control: private, no-cache`; honour `If-None-Match` → `304`; allow gzip/br | cheap "check for updates", revision-aware caching |
| both | optional `Content-Length`-correct gzip; no body change | low-bandwidth |

Client: when `content_sha256` is present, compute SHA-256 over the canonical bytes received and refuse on mismatch
(`SnapshotError('hash_mismatch')`); when absent (today) keep the current structural validation and say so in docs.

## B. New: delivery manifest (one envelope for every resource kind)

```
POST /v1/downloads/plan            auth required
{ "items": [ {"kind":"lesson|pack|book|exam_practice","id":"<uuid>","locale":"fr|ht"} ] }   ≤ 200 items

200 { "manifest_version": "delivery-manifest-1",
      "items": [ { "kind","id","locale","revision_id",
                   "objects": [ { "sha256","bytes","media_type","required":true,
                                  "url":"<signed, 10 min>", "expires_at":"…" } ],
                   "total_required_bytes":123, "total_optional_bytes":456 } ],
      "denied": [ { "id":"…", "reason":"not_entitled|withdrawn|not_found" } ] }
```

* A lesson item reuses `pack-manifest-1`'s lesson entry (`object_key`, `sha256`, `bytes`, `questions`, `assets`) so there is
  one verification routine. The pack build (`/staff/packs`) already produces this; serving it is the missing piece.
* The plan call is the **only** place entitlement is evaluated (ADR-9). URLs are short-lived and unguessable.
* Planning has no side effects; it can be called to show "this will use 38 MB" before the student agrees.

## C. New: library (books)

```
GET  /v1/library?locale=fr                  → [{book_id, title, author, pages, bytes, cover_sha256, formats, access:{read_online, download}}]
POST /v1/library/{book_id}/access {mode:"stream"|"download"}
  → { "url":"<signed, 5–10 min>", "bytes":…, "sha256":…, "media_type":"application/pdf",
      "supports_range":true, "expires_at":"…" }      403 not_entitled · 451 rights_withdrawn
PUT  /v1/library/{book_id}/progress {page, position, updated_at}   (account-scoped; sync-style, last-writer by timestamp)
```
Bookmarks and progress ride the existing outbox as new operation kinds (`book_progress`, `book_bookmark`), so they are
durable and idempotent like answers.

## D. New: exams

```
GET  /v1/exams?kind=practice|controlled
practice:   same shape as a lesson (blocks + questions with key/explanation)  → may be downloaded
controlled: POST /v1/exams/{id}/sessions → {session_id, questions WITHOUT answer_key, expires_at}
            POST /v1/exams/{id}/sessions/{sid}/answers  → stored server-side; score only after close
```
Controlled exams are online-only and are not part of any download manifest (ADR-8).

## E. Server storage model (PostgreSQL metadata + object storage)

```
content.objects            (sha256 PK, bytes, media_type, storage_key, created_at)            -- immutable
content.resource_versions  (id, resource_kind, resource_id, locale, revision, status, manifest_json, created_at)
content.resource_objects   (resource_version_id, sha256, required bool, role)                 -- which objects a version needs
content.rights             (resource_id, license, territory, valid_from, valid_to, entitlement_rule)   -- books/papers
```
PostgreSQL holds identity, editorial status, rights and references; **never** the large bytes. Object keys: `sha256/ab/cd/<hash>`
(no student data, no PII, no title). Immutable → CDN `immutable`. Private bucket; delivery only through signed URLs.
Existing `app.lesson_revisions` stays the source of truth for lesson text; lesson objects are a **derived** build artefact
(deterministic pack builder).

## F. On-phone storage

Existing, unchanged: `content.db` (`saved_lessons`, `saved_questions`, `catalog_cache`) and per-account databases.

New (for bulk, assets, books — milestones CD-4 onward):

```
content.db
  downloads(resource_kind, resource_id, locale, revision_id, state, bytes_total, bytes_done,
            manifest_json, last_error, updated_at, PRIMARY KEY(resource_kind, resource_id, locale))
  objects(sha256 PRIMARY KEY, bytes, relative_path, last_used_at, pinned)       -- files under app-private storage
files:  <documentDirectory>/objects/ab/<sha256>            (verified, immutable)
        <cacheDirectory>/partial/<sha256>.part             (resumable, deletable by the OS)
account-scoped for licensed books:  <documentDirectory>/accounts/<account-id>/books/<book_id>
```
Public lesson content stays shared across accounts (as today). **Licensed books are stored per account** so switching
accounts never exposes another student's entitled files. Student work stays in account databases only.
