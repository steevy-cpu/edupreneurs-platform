# 1. The prototype's YouTube feature (read-only audit)

Lovable project `14710ec1-c1bf-40aa-b397-6fddd23c28b4`, commit `8749ddce155194e60a12830ac66a469520937c89`. Source read with read-only tools only. **No database query was made, the site was not run, and no key value was read or copied** (both functions read `YOUTUBE_API_KEY` from the environment; no literal key was found in the files read). [V] = verified in source, [I] = inferred.

The figures given in the brief (255 lesson–video associations across 251 lessons, 242 distinct curated ids, 264 lessons with a direct `youtube_url`) come from the owner's inventory; they were not re-counted here.

## How it works

| Stage | What the prototype does |
|---|---|
| **Search** | Two edge functions, both `search.list` only (never `videos.list`) [V]. `youtube-search`: `type=video, videoEmbeddable=true, videoDuration=medium, relevanceLanguage=fr, regionCode=HT, safeSearch=strict`, 1–25 results, then drops results mentioning "english". Query = first three words of the lesson title + subject + fixed words (no student data, no grade) [V]. |
| **AI suggestion** | `suggest-youtube-videos`: Gemini 2.5 Flash writes 2–3 French queries from the lesson title, subject, grade and first 1000 characters of content; runs `search.list`; drops banned ids; keyword "educational" check; returns the top 2 [V]. |
| **Access to search** | Both functions have `verify_jwt = false` and serve requests **without a signed-in user**; CORS `*`; rate limit 100/min per user or 20/min per IP taken from a client-supplied header [V]. |
| **Approval** | **None.** `lesson_videos` has no review state: adding a row makes it live [V]. In the editor, AI suggestions need a click; but `process-ai-job` and `BatchLessonGenerator` write the top result into `lessons.youtube_url` automatically, the latter possibly publishing the lesson in the same step [V]. |
| **Storage** | `lesson_videos(id, lesson_id → cascade, youtube_url, video_id, title, description, order_index, is_primary, added_by, timestamps)`. No channel, duration, status, Made-for-Kids, embeddability or fetch time; title and description are null for manually added links; **never refreshed** [V]. Read policy `USING (true)`, including anonymous [V]. |
| **`lessons.youtube_url`** | Legacy single link, copied into `lesson_videos` on 2026-01-01. Not displayed on student lesson pages (when `lesson_videos` is empty a **live search runs instead**), but still used in PDF/download export, the editor preview and an MCP tool [V]. |
| **Display** | Plain `<iframe>` `youtube-nocookie.com/embed/{id}?rel=0&modestbranding=1`, `loading="lazy"`, `allow` includes `autoplay`; **loaded when the tab renders, not on tap**; title (if any) and "regardez-la sur YouTube" link; **no channel attribution** on lesson pages [V]. Passion modules: thumbnail grid, iframe on tap, channel shown [V]. Editor tools use `www.youtube.com/embed` [V]. |
| **Background player** | The IFrame API script is injected on **every page** by a global music provider; study music plays through a **0×0 hidden player** with `controls:0, autoplay:1` [V]. |
| **Freshness and status** | No check of deletion, privacy, embeddability, `madeForKids`, age rating or duration; no player error handling beyond a static "if the video doesn't show" link [V]. |
| **Removal** | Delete a row (cascades from lesson deletion). Ban table `banned_youtube_videos(video_id unique, banned_by, reason)` [V]. |
| **Rewards / tracking** | No Gold or points for watching; no watch tracking; GA4 id is a placeholder [V]. |
| **Privacy** | The privacy policy does not mention YouTube or Google video services; the cookie banner does not gate the embeds or the IFrame API script [V]. |

## Risks found

1. **Unauthenticated quota spend:** anyone on the internet can call both search functions (and spend Gemini credit through the suggestion function).
2. **Unreviewed live search results are shown to minors** on every lesson without a curated video, and in passion modules. Only `safeSearch=strict` and keyword filters protect them.
3. **The ban list does not protect students:** it is readable only by editors, not applied in `youtube-search` or the student fallback search, and a ban does not remove existing references.
4. **Automatic insertion without review** into `lessons.youtube_url` (which reaches PDFs and exports).
5. **No metadata validation or refresh:** deleted, private, non-embeddable, age-restricted or Made-for-Kids status is unknown; stored text is never refreshed (Developer Policies III.E.4 requires refresh or deletion within 30 days and the per-video Made-for-Kids lookup).
6. **Hidden 0×0 autoplaying player for background audio**, which conflicts with the minimum player size (200×200), the autoplay-visibility rule and the ban on background playback (RMF; III.I.9).
7. **Eager iframes**: up to four players contact YouTube and use data as soon as the tab renders.
8. **No privacy disclosure** of YouTube/Google, and no consent gating.
9. **Permission mismatch**: row-level security lets editors delete videos that the UI reserves for admins [I: depends on `is_content_editor`].
10. **No player failure handling and no channel attribution** on lesson pages.

## What is worth keeping

* The curated associations (242 ids across 251 lessons): **as import material**, each becoming a *proposal* that a teacher re-approves after a fresh `videos.list` check.
* The search constraints (`safeSearch=strict`, `videoEmbeddable=true`, `regionCode=HT`, `relevanceLanguage=fr`) as the default for a **staff-only** search tool.
* No rewards for watching (already compliant).

## What must not be carried over

Live search for students, automatic insertion, the open search endpoints, `youtube-nocookie` (privacy-enhanced mode is for websites only), the hidden music player, eager iframe loading, and the public-read video table.

## Could not verify

Live database state and row counts; final effective RLS; the definition of `is_content_editor`; key restrictions in Google Cloud; whether any trigger awards Gold on passion progress; runtime network behaviour.
