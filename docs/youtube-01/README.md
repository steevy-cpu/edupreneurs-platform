# YouTube-01: teacher-approved educational videos in lessons

**Status: draft. Feature flag off. Synthetic data and mocked provider responses only.** No video is shown to any learner, no YouTube quota was used, no production key was used, the prototype's database was not touched, and nothing was merged or deployed.

## Recommendation

**Backend foundation (this PR): PASS for review.** It is additive, off by default, and cannot show a video to a learner unless a second person approved it and the latest metadata check (at most 30 days old) found it public, processed, embeddable, not age-restricted and not blocked in Haiti.

**Student-facing video: HOLD.** Do not enable `EDU_VIDEOS_ENABLED` for learners until all of these are done:

1. **Privacy policy and terms (fr + ht)** that say the app uses YouTube API Services, link to the YouTube Terms of Service and the Google Privacy Policy, disclose the player's cookies and device data, and are accepted before use (Developer Policies III.A.1–2). Legal review for minors.
2. **Child-directed designation decided by counsel** (the audience includes under-13s), then declared through Google Play's Target Audience and Content setting and the iOS self-declaration (Developer Policies III.J).
3. **Metadata refresh job** wired to a worker with a restricted server-side key, and the Data API quota and project registered to this app only (III.D.1).
4. **Mobile player** built to the handoff in `05-mobile-handoff.md` and passed on physical low-end Android and iOS devices, including the Referer test (error 153).
5. **Real videos imported as proposals** and approved by teachers (none are approved today).
6. **Independent review** of this PR and of the mobile implementation.

## Contents

| File | What |
|---|---|
| `01-prototype-audit.md` | How the live prototype searches, stores, shows and removes videos, and its risks |
| `02-policy-compliance.md` | Policy → implementation matrix (verified requirement / recommendation / needs confirmation) |
| `03-architecture.md` | The lightweight video service, workflow, states and refresh policy |
| `04-api-contract.md` | `GET /v1/lessons/{id}/videos` and the data model |
| `05-mobile-handoff.md` | Component specification for the mobile engineer (Claude #2) |
| `06-test-plan.md` | Automated adversarial tests (implemented) and physical-device tests (to run) |
| `07-security-privacy-checklist.md` | Checklist for review and enablement |
| `08-open-questions.md` | Legal and provider uncertainties |

## What this PR adds

* Migration `20261127000200_youtube_videos.sql`: `app.videos` (bounded metadata, availability, staff status, 30-day expiry) and `app.lesson_video_links` (lesson ↔ video, locales, order, purpose, start offset, review state, source). Learner visibility is enforced by row-level security; a material metadata change sends approved links back to review.
* `GET /v1/lessons/{lesson_id}/videos?locale=` behind `EDU_VIDEOS_ENABLED` (default false → 404).
* `edu_api/videos/ids.py`: strict id validation and the only URLs ever built (watch, embed, thumbnail, channel).
* `edu_api/videos/provider.py`: `videos.list` metadata client for a future staff refresh job. Refuses any network call unless a key **and** `EDU_YOUTUBE_LIVE_CALLS_AUTHORIZED` are set; key in a header, never in URLs, logs or errors. Tests use a mocked transport.
* OpenAPI contract and mobile types regenerated (strictly additive).
* Tests: pgTAP `080_youtube_videos.sql` (40 assertions), unit `test_videos_provider.py` (97), HTTP `test_videos.py` (20).

## Reviewed state

Branch `feature/youtube-01`, based on `main` at `1094eb0`. Prototype audited read-only at Lovable commit `8749ddce155194e60a12830ac66a469520937c89`. Policy pages read on 2026-11-26/27 (see `02-…`).
