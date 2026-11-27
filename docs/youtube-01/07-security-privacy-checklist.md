# 7. Security and privacy checklist

Ticked items are done in this PR and tested. Unticked items are gates before enablement.

## Backend

- [x] Video ids validated to the exact YouTube alphabet and length in Python and in a database CHECK
- [x] Every URL sent to the app built from a validated id (no stored URL is ever returned)
- [x] Metadata bounded (title ≤ 200, channel ≤ 120, duration ≤ 4 h) and cleaned of control and bidirectional characters
- [x] Learner visibility decided by row-level security, not by application code
- [x] Approval by an active reviewer who is not the proposer
- [x] Non-presentable videos (removed, private, not processed, not embeddable, age-restricted, blocked in Haiti) hidden and not approvable
- [x] Stored metadata valid ≤ 30 days; expired metadata hidden
- [x] Material metadata changes return links to review
- [x] Made-for-Kids recorded per video; missing value rejects the video
- [x] Staff disable / withdraw with a reason
- [x] Student API role cannot read reviewer identities, notes, staff reasons or legacy references, and cannot write
- [x] No learner-facing search; learner requests never call YouTube and spend no quota
- [x] Provider key only server-side, header-only, to `https://www.googleapis.com` only, redirects off, never in URLs, logs, errors, responses, contract, `repr` or settings dumps
- [x] Two switches for live provider calls (key + explicit authorization), both off by default
- [x] Feature flag off by default; rollback by flag
- [ ] Metadata refresh worker (needs the staff/worker stack, PR #4)
- [ ] Staff API and Admin screens for propose / approve / withdraw (none yet; staff currently need database access)
- [ ] Rate limit on staff search, when built
- [ ] Google Cloud: one project for this app; key restricted to YouTube Data API v3 and to the server's egress; rotation schedule
- [ ] Purge of removed video rows after 7 days

## App (see `05-mobile-handoff.md`)

- [ ] Player only after tap; one at a time; destroyed on blur/background
- [ ] Referer `https://<application id>` via `baseUrl`; `origin` and `widget_referrer` set; no `noreferrer`
- [ ] No overlays, no player modification, no ad blocking, no `controls=0`, no autoplay
- [ ] Player viewport ≥ 200 × 200 at every size and font scale
- [ ] No thumbnails or video in offline storage
- [ ] No analytics or tracking SDK on video screens
- [ ] No rewards, streaks or completion tied to watching
- [ ] No write actions to YouTube (likes, subscriptions, comments, uploads)
- [ ] Error handling (2, 5, 100, 101, 150, 153) with "Ouvrir dans YouTube"

## Privacy and legal

- [ ] Privacy policy (fr + ht) states use of YouTube API Services, links the Google Privacy Policy and the YouTube Terms of Service, and discloses the player's cookies and device data; accepted before use
- [ ] Decision: is the app child-directed (counsel); if so, Google Play Target Audience and iOS self-declaration
- [ ] Guardian information for under-13s, per counsel
- [ ] Contact address in the privacy policy
- [ ] Owner confirms no personalized advertising anywhere in the app

## Content

- [ ] Legacy videos imported only as proposals, refreshed, and re-approved by teachers
- [ ] Reviewers named; review guidance (accuracy, language, age suitability, channel trust, related videos from the same channel)
