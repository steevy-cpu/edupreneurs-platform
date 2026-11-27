# 3. Architecture: a lightweight educational-video service

```
Lesson (text-first, offline-capable)
   └─ approved video metadata (server, refreshed ≤ 30 days)
         └─ lightweight card: thumbnail · title · channel · duration · "YouTube"
               └─ learner taps Watch ──► official YouTube embedded player (WebView, online only)
                                            └─ fallback: "Ouvrir dans YouTube"
```

## Principles

| Requirement | How |
|---|---|
| Video is optional | The lesson text is complete on its own; videos come from a separate endpoint; an empty list is normal |
| Text-first, offline lessons | Lesson packs never contain video or thumbnails. Offline, the card shows "needs a connection"; the lesson still works |
| No automatic playback, no background playback | The player is created only after the tap; it is destroyed when the screen loses focus or the app goes to background |
| No downloading, no player modification, no ad interference | Only the official embed; nothing over it; no request interception (`02-…` rows 2, 4) |
| No rewards for watching | No event about viewing exists; completion and Gold never depend on a video |
| No unreviewed recommendations | A video reaches learners only through an approved link; there is no learner search; AI or search results are only *proposals* |
| No learner data to YouTube | Learner requests never call YouTube. The YouTube player itself receives what any embed receives (IP, device data, cookies); that is disclosed, not prevented |
| Availability per video | Stored `embeddable`, `privacy_status`, `upload_status`, `age_restricted`, `blocked_in_ht`, `availability`, checked at every refresh; anything not presentable is hidden |
| Staff control | `videos.status` (`active` / `disabled` / `withdrawn` with a reason) and link `review_status` (`withdrawn`) |
| Learner control | A per-device setting "Afficher les vidéos" (default on) and "Économiser les données" (data saver: no thumbnails, text cards only). Stored on the device, not on the server, so nothing about the preference leaves it |
| Child-directed safeguards | No write actions to YouTube, no ads sold, no analytics on video screens, Made-for-Kids recorded per video, age-restricted excluded |

## Data model

`app.videos` (one row per YouTube video): validated `provider_video_id`; bounded `title` (≤ 200), `channel_id`, `channel_title` (≤ 120), `duration_seconds` (≤ 4 h), `audio_language`; `made_for_kids`, `age_restricted`, `embeddable`, `privacy_status`, `upload_status`, `blocked_in_ht`; `metadata_fetched_at`, `metadata_expires_at` (≤ +30 days); `availability` (`available` / `removed`); staff `status` and `status_reason`; `legacy_ref`.

`app.lesson_video_links` (lesson ↔ video): `locales` (fr, ht or both), `position` (1–20), `purpose` (explanation, example, exercise_help, enrichment), `start_seconds` (inside the video), `review_status` (proposed → approved / rejected; approved → needs_review / withdrawn), `source` (teacher, staff_search, legacy_import, ai_suggestion), `proposed_by`, `reviewed_by` (an active reviewer, never the proposer), `reviewed_at`, `review_note`, `legacy_ref`.

No table stores anything about a learner and video (no views, no progress).

## Visibility rule (enforced by row-level security)

A link is visible to a learner if and only if: link `approved`; video `active`, `available`, `embeddable`, not age-restricted, not blocked in Haiti, `public` or `unlisted`, `processed`; `metadata_expires_at > now()`; lesson active and in a published course; lesson has a published revision in the requested language; the link lists that language.

## States

```
link:  proposed ──approve (reviewer ≠ proposer, video presentable)──► approved
          │                                                            │  │
          └─reject─► rejected                material metadata change ─┘  └─ withdraw ─► withdrawn
                                                    ▼
                                              needs_review ──approve──► approved
video: active ⇄ disabled (reason) ; active → withdrawn (reason)
       availability: available ⇄ removed (provider no longer returns it)
```

Material change = channel, Made-for-Kids, age rating, embeddability, or duration changed by more than 5 seconds. A title change alone is applied and shown (DP III.E.4.f) without re-review.

## Metadata refresh policy

* **Source:** `videos.list?part=snippet,contentDetails,status` in batches of ≤ 50 ids (1 quota unit per call).
* **Cadence:** every video refreshed at least every **7 days** (target), and never shown after **30 days** without a refresh (hard rule, DP III.E.4).
* **Outcomes:** found and parseable → update metadata and expiry; not returned → `availability = removed` (hidden at once); returned but malformed or missing `madeForKids`/`embeddable` → treated as not presentable and reported to staff.
* **Deletion:** rows for videos removed for more than 7 days, with no approved link, are purged (DP III.E.4.g).
* **Who runs it:** a background worker (staff stack, PR #4) with the server-side key. In this PR the client and parser exist and are tested with mocked responses; the job itself is not wired, so **all metadata in tests is synthetic** and nothing is refreshed automatically yet.
* **Failure:** provider error or quota exhaustion leaves existing rows untouched; they expire on schedule and disappear rather than being shown stale.

## Importing the prototype's videos

`lesson_videos` rows and `lessons.youtube_url` values → `video_id_from_url` (https on known hosts only) → one `videos.list` refresh → `app.videos` + `lesson_video_links` with `source = legacy_import`, `review_status = proposed`. No legacy video is shown until a teacher approves it here. This belongs to the content migration (Codex #1's lane) and is not done in this PR.

## Staff search (future, not in this PR)

A staff-only screen in Admin; free text normalised by `staff_search_terms` (≤ 100 characters, control characters removed); fixed safety parameters (`safeSearch=strict`, `videoEmbeddable=true`, `type=video`, `regionCode=HT`); results shown unmodified as YouTube results (DP III.C.5); adding a result creates a *proposal*. Rate-limited per staff account; never available to learners.
