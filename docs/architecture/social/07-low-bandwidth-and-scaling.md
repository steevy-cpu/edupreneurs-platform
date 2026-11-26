# 7. Low-bandwidth and scaling strategy

Assumptions about the learner's situation (same as the rest of the project):
an inexpensive Android phone, little free storage, prepaid mobile data bought
in small amounts, a connection that is slow and drops often, and long periods
with no connection at all. **Every design choice below is judged in bytes and
in "what does the learner see when it fails".**

## Rules

1. **Lessons first, always.** Social traffic never competes with lesson sync.
2. **Text first.** No images, video, avatars-as-images, link previews or web fonts.
3. **Small pages, asked for explicitly.** 10 posts per page; the learner taps "Voir plus".
4. **No always-on connection.** No WebSocket, no long-polling, no Supabase Realtime, no background polling.
5. **Don't download what hasn't changed.** `ETag` / `304` on every list the app re-opens.
6. **The phone is the first copy.** What was read stays readable offline; what was written is safe on the phone until the server confirms it.
7. **Fail in words.** Every failure has a defined, translated state — never a spinner that does not end.

## Byte budgets (targets to measure in Social-02, test PERF-05)

| Call | When | Target size, gzip | Notes |
|---|---|---|---|
| `GET /v1/social/me` | Once per app start, if the feature is on | ≤ 0.6 KB; `304` ≈ 0.2 KB | Decides whether anything else is ever called |
| `GET /v1/social/updates` | When the community area is opened; at most every 2 min while it stays open | ≤ 0.5 KB typical | The only repeated call |
| `GET /v1/social/feed` (10 posts) | When opened and something changed | ≤ 3 KB | 280-character excerpts |
| `GET /v1/social/posts/{id}` + first comments page | When a post is opened | ≤ 4 KB | Full text |
| `POST …/posts` | On send | ≤ 1.5 KB request (gzip above 1 KB) | |
| `GET /v1/social/guidelines` | Once per version | ≤ 3 KB | Then cached |

A learner who opens the community once a day, reads two pages and opens three
posts should use **under 25 KB a day** — less than one compressed photo.
A learner who never opens it uses about 0.2 KB per app start, and nothing if
the feature is off for them (the app remembers `not_enrolled` for a day).

These are estimates from the response models, not measurements.

## Separation from the offline learning outbox

| | Learning (exists) | Social (proposed) |
|---|---|---|
| Local tables | account store, content store, outbox | new `social_*` tables in the same per-account SQLite file |
| Outbox | learning operations (`practice_answer`, `lesson_completed`) | `social_outbox` — a different table, different code |
| Endpoint | `POST /v1/sync/push`, `GET /v1/sync/pull` | `/v1/social/*` |
| Engine | `core/sync/engine.ts` | new `core/social/outboxEngine.ts` |
| Order | 1st | 2nd — starts only after the learning push of that session finished or was skipped |
| On failure | retries with backoff | stops for this session; **never** delays, blocks or retries inside the learning engine |
| Item lifetime | until accepted | drafts expire (see below) |
| Sign-out with unsent items | existing behaviour and warning | separate, plainer warning; unsent social drafts can be discarded without touching learning data |

Hard rules for the implementation (each has a test in doc 08):

- The learning engine does not import or call anything social.
- A full or corrupt social cache cannot stop a lesson from opening. Social
  storage has a size cap (default 2 MB) and is the first thing evicted when the phone is short of space.
- Learning sync runs and completes with the social module switched off, failing, or returning errors.
- The two outboxes are never sent in the same HTTP request.

## Local cache (reads)

| Stored | Kept until |
|---|---|
| My social status (`me`) | replaced by the next successful call; trusted for 24 h |
| My communities | replaced; `ETag` kept |
| Up to 50 most recent posts per community (excerpt, and full text if opened) | replaced by newer pages; removed when `updates` says `visible: false`; whole cache dropped on `cache_reset` |
| Comments of posts I opened (most recent 100 per post) | same |
| My submissions and their states | replaced |
| Community rules (current version, both languages if downloaded) | version change |
| `updates` cursor, `ETag`s | — |

- Cached social content older than **7 days without a successful refresh** is
  hidden behind "Connecte-toi pour mettre à jour" — stale conversations among
  minors should not linger, and a removed post must not survive indefinitely on an offline phone.
- Everything is per account and deleted from the device on sign-out (social
  cache is not worth keeping across accounts on a shared phone).
- Nothing social is written to shared storage, backups or the system search index.

## Social outbox (writes)

| Action offline | What the learner sees immediately | Sent when online | Expires |
|---|---|---|---|
| Post / comment | Saved as a draft: "Sera envoyé quand tu seras connecté" | Yes, oldest first | After 7 days unsent: kept as an editable draft, not sent automatically (a week-old reply to a moved-on conversation should be a choice) |
| Reaction | Shown at once | Yes; several taps on one item collapse to the last state | 7 days |
| **Report** | Content hidden locally at once: "Signalement enregistré" | **Yes — first in the queue, before posts** | Never |
| Block | Applied locally at once | Yes | Never |
| Delete own content | Hidden locally at once | Yes | Never |
| Join with a code | Not available offline ("Connexion nécessaire") | — | — |

Outbox limits: 20 drafts, 100 reactions. Each item carries its `client_op_id`
from the moment it is created.

## Offline and failure states

Every state has a fixed text in French and Haitian Creole and a defined next
step. The app never shows a raw error.

| State | Cause | What the learner sees | What happens next |
|---|---|---|---|
| `feature_off` | `not_enrolled`, or the API setting is off | No community entry point at all | Re-checked once a day |
| `offline_fresh` | No network; cache newer than 7 days | Cached feed, banner "Hors ligne — dernière mise à jour hier" | Refresh on reconnect when the screen is opened |
| `offline_stale` | No network; cache older than 7 days | "Connecte-toi pour voir les nouveautés" | — |
| `offline_empty` | No network; never loaded | Friendly empty state, no spinner | — |
| `loading` | Request in flight | Cached content stays visible; small indicator | Timeout 15 s → `slow_network` |
| `slow_network` | Timeout or 5xx | Cached content + "Réseau lent. Réessayer" | Manual retry; no automatic loop |
| `draft_queued` | Written offline | Draft with a clock icon | Sent by the social outbox |
| `sending` | Being sent | Draft with a sending indicator | — |
| `pending_review` | Server accepted (202) | "En attente de validation" | State updates through `updates` / `me/submissions` |
| `published` | Approved | Appears in the feed | — |
| `not_accepted` | Rejected | Reason sentence + "Modifier et renvoyer" (creates a **new** submission) | — |
| `removed` | Taken down later | Notice with the reason sentence | — |
| `send_failed_retry` | Network error, 500, 503 | Stays queued, "Nouvel essai plus tard" | Retried next session with the **same** `client_op_id` |
| `send_failed_final` | 404 (the post is gone), 409, 422 | "Ce message n'a pas pu être envoyé" + why; kept as a draft if the text can be fixed | No retry |
| `limit_reached` | 429 | "Tu as atteint la limite pour aujourd'hui" | No retry before `Retry-After` |
| `read_only` | `submissions_closed`, `community_read_only`, outside open hours | Composer disabled with the reason | Drafts stay on the phone |
| `muted` / `suspended` | Sanction | Clear notice with the end date; while suspended, the cache is cleared | — |
| `consent_needed` | `social_not_active` | "Demande à ton école" | — |
| `session_expired` | 401 after a refresh attempt | Existing sign-in flow | Drafts are kept for the same account |

Two failure rules matter most:

- **A lost answer must not create a duplicate.** The retry carries the same
  `client_op_id`; the server answers `replayed: true`.
- **A removed post must leave the phone.** `updates` returns its id with
  `visible: false`; if the phone has been away too long (`cache_reset`), it drops the social cache entirely.

## What "feature-scoped realtime in later phases" means

Not in Social-01 to Social-03. If a later phase wants faster conversation:

| Step | What | Gate |
|---|---|---|
| A (Social-03) | Adaptive polling of `updates`: 2 min while the community screen is open, doubling when nothing changes, stopping in the background and in data-saver mode | none — it is not a persistent connection |
| B (Social-04, optional) | Content-free push notification ("Tu as du nouveau dans ta classe") through the platform push services | privacy review; opt-in; quiet hours |
| C (later, optional) | A short-lived stream for **one screen** (e.g. a scheduled teacher question-and-answer hour): opened when the screen opens, closed when it closes or after 15 min, with automatic fallback to polling | measured battery and data cost on a low-end phone; pre-moderation still applies, so "live" means "as fast as the moderator" |

Never: a connection opened at app start, presence ("en ligne"), typing indicators, read receipts.

## Optional compressed media (later, not approved)

Summary of the constraints recorded in `migrations/future/F002_media.sql`:
images only, one per post, compressed on the phone to ≤ 150 KB with location
data stripped, uploaded to private storage, reviewed by a human with the post,
never auto-downloaded on mobile data ("Photo · 120 Ko · Toucher pour afficher"),
thumbnails ≤ 15 KB. One image costs the same data as roughly fifty feed pages —
which is the argument for keeping the first release text-only.

## Server-side scaling

Expected load is small; the limits come from moderation staff long before they
come from PostgreSQL. This section shows the design does not have a cliff.

### Sizing

| | Pilot | Early growth | Stretch |
|---|---|---|---|
| Learners enrolled | 150 | 1 500 | 15 000 |
| Communities | 5 | 50 | 500 |
| New posts + comments per day | ~75 | ~750 | ~7 500 |
| Rows after one year (posts + comments) | ~27 k | ~270 k | ~2.7 M |
| Feed reads per day | ~500 | ~5 000 | ~50 000 (< 1 per second on average) |
| Moderator-hours per day (doc 06) | 0.6 | 6.3 | 63 — **not viable with central pre-moderation** |

The stretch column is included to make one point: the database is fine at that
size; the operating model is not. Growth must be gated on moderation capacity.

### Why reads stay cheap

- A feed page is one index range scan on `(community_id, publish_seq DESC)
  WHERE status = 'published'` — it reads about as many index entries as rows returned, at any table size.
- The home feed queries each of the caller's communities (≤ 10) through the
  same index and merges ≤ 10 × page size rows.
- Author profile, "my reaction" and counts come in the same query (joins on
  primary keys; counts are stored, not computed).
- Row-level-security helpers do a few primary-key lookups per row. With pages
  of ≤ 20 rows that is tens of lookups. To be measured (PERF-01); if it is too
  slow, the planned fix is to resolve membership and blocks once per request
  into a set and pass them into the query — without removing the policy.

### Why writes stay cheap

- A submission is two inserts and one counter upsert.
- Visibility changes take one global row lock (`visibility_clock`). Only
  moderator decisions, reports that hide, and deletions take it; each holds it
  for a few milliseconds. Ceiling: on the order of hundreds per second — a
  thousand times the stretch scenario. If it ever matters, split the clock per community.
- Reactions update one counter on the post row. A post with a sudden burst of
  reactions serialises them; acceptable at these sizes.

### Connections

| Pool | Role | Size (default) | Statement timeout |
|---|---|---|---|
| A (existing) | `edu_api_login` | 5 + 5 | 5 s |
| B | `edu_social_login` | 4 + 2 | 3 s |
| C | `edu_social_mod_login` | 2 + 0 | 5 s |

Separate pools mean a slow social query queues behind other social queries,
not in front of lesson sync. Total connections must fit the managed plan's
limit; behind a transaction-mode pooler the statement cache must be disabled
(existing setting) — this combination is **untested** today and is prerequisite P-3.

### Caching

| What | Where | Lifetime |
|---|---|---|
| Community rules, community metadata | In-process memory in the API | 5 min |
| `updates` answer per account | In-process memory | 120 s (protects the database from eager clients) |
| Feed pages, post content | **Not cached on the server** — authorisation is per person, and wrongly shared cache is the worst possible bug here | — |
| Everything authorised | The phone | see above |
| Shared proxies / CDN | Nothing: `Cache-Control: private, no-store` | — |

### Growth steps, in order, each only when measured need appears

1. Response compression and `ETag`s (Social-02).
2. Per-request membership/block sets if policy helpers show up in query plans.
3. Monthly partitioning of `notification_events`, then `audit_events`, when they exceed a few million rows.
4. Archive communities at the end of a school year (D-13) so "hot" data stays one year deep.
5. A read replica for moderation metrics.
6. Per-community visibility clocks.

Not planned: Redis, a search engine, a message broker, a separate service. Each
would be a new thing for a very small team to run, and nothing above needs them.

### Observability (no content in any of it)

Per route: request count, error rate by code, p50/p95 latency, response bytes.
Per pool: wait time, saturation. Domain gauges: queue size by priority, oldest
open item, overdue items, submissions/hour, reports/hour, `429`s per hour.
Alert thresholds are listed in doc 06.
