# Lane VOCAB — Word of the Day (F13)

Branch `overnight/word-of-the-day` · schema `vocab` · migrations `2026112404*` · pgTAP `160–164` ·
flag `EDU_DAILY_WORD_ENABLED` (default **off**).

Status after turn 1: data model, immutable Haiti-date schedule, editorial workflow at SQL level and
the learner endpoint are built and tested on the lane's own local stack. **Not built yet:** the HTTP
staff routes (`/v1/staff/vocab/*`) — they need the staff lane's roles (see "Awaiting staff wiring").

All vocabulary in this repository is synthetic test/demo text written for this mission. It has not
been reviewed by an educator or a native Haitian Creole speaker. **A real educator must review real
words before any learner sees one.**

## 1. Learner contract — `GET /v1/daily-word`

Mounted only when `EDU_DAILY_WORD_ENABLED=true`. With the flag off the route does not exist: the
answer is the standard `404 {"error": {"code": "not_found", …}}` (with or without a token) and
`packages/contracts/openapi.json` is byte-identical to `main`. Because the committed OpenAPI file is
generated with flags off, **it does not contain this route**; this section is the contract.

Request: `GET /v1/daily-word?locale=fr|ht` with `Authorization: Bearer <Supabase access token>`,
optionally `If-None-Match: <etag>`. There is no other input: no date, no time zone, no user id.
Unknown query parameters and client clock headers are ignored.

`200 OK` (example from the demo seed; `Content-Type: application/json`):

```json
{
  "haiti_date": "2026-11-24",
  "locale": "fr",
  "requested_locale": "fr",
  "is_fallback_locale": false,
  "word": {
    "word_id": "89fbb51a-7f0f-42e3-bd20-49d06f5ee58b",
    "revision_id": "d6511064-1eeb-4fe2-8748-860c85658ca4",
    "revision": 1,
    "term": "courage",
    "pronunciation": "cou-rage",
    "part_of_speech": "noun",
    "definition": "Force intérieure qui aide à faire face à une difficulté ou à la peur.",
    "example": "Il faut du courage pour poser une question devant toute la classe.",
    "gloss": "kouraj"
  },
  "audio": null,
  "valid_until": "2026-11-25T05:00:00Z"
}
```

| Field | Type | Notes |
|---|---|---|
| `haiti_date` | `YYYY-MM-DD` | The `America/Port-au-Prince` date the word belongs to, from the **server** clock |
| `locale` | `fr` \| `ht` | Language actually served |
| `requested_locale` | `fr` \| `ht` | Echo of the query parameter |
| `is_fallback_locale` | boolean | `true` ⇔ `locale != requested_locale` (no approved translation today → French) |
| `word.word_id` | uuid | Stable identity of the word; the same in both languages on a given day |
| `word.revision_id`, `word.revision` | uuid, int | The exact immutable revision served |
| `word.term` | string ≤ 60 chars | |
| `word.pronunciation` | string ≤ 80 \| `null` | Pronunciation help as text |
| `word.part_of_speech` | enum | `noun verb adjective adverb pronoun preposition conjunction interjection determiner expression` — the app shows its own localised label |
| `word.definition` | string ≤ 300 | Single line, no control characters |
| `word.example` | string ≤ 240 | |
| `word.gloss` | string ≤ 80 \| `null` | Short gloss in the *other* language |
| `audio` | object \| `null` | `{ "asset_id": uuid, "mime_type": "audio/mpeg"\|"audio/mp4"\|"audio/aac"\|"audio/ogg", "byte_size": 1…102400, "duration_ms": 1…15000, "sha256": "<64 hex>" }`. Metadata only: **no download route exists yet**, and the app must never autoplay |
| `valid_until` | RFC 3339 UTC instant | The next Haiti midnight (`…T05:00:00Z` in winter, `…T04:00:00Z` in summer time) |

Response headers on `200`: `ETag: "dw1-<32 hex>"` (strong), `Cache-Control: private, no-cache`,
`X-Request-ID`.

| HTTP | `error.code` | When | Headers |
|---|---|---|---|
| 304 | — (no body) | `If-None-Match` matches the current tag (weak comparison; lists and `*` accepted) | `ETag`, `Cache-Control: private, no-cache` |
| 401 | `unauthenticated` | Missing / invalid token | `WWW-Authenticate: Bearer` |
| 404 | `daily_word_not_available` | Flag on, but no word is assigned to today, or its rights were withdrawn | `Cache-Control: private, no-store` |
| 404 | `not_found` | Flag off (route not mounted) | |
| 405 | `method_not_allowed` | Any method but GET | |
| 422 | `validation_error` | `locale` missing or not `fr`/`ht` | |
| 503 | `dependency_unavailable` | Database or Auth keys unavailable | `Retry-After: 5` |

Behaviour worth knowing:

- The ETag is derived from the assignment identity: `(haiti_date, requested_locale, served locale,
  revision_id, audio asset or none)`. It is the same for every account. The French and the Creole
  request have different tags. It changes at Haiti midnight, and during a day only if a recording
  or a translation is withdrawn for rights reasons.
- Size: the largest word the database accepts, with a recording, is **1338 bytes** of uncompressed
  JSON (budget 1536; enforced by a table constraint plus `test_response_size_budget`). A typical
  demo word is about 520 bytes. A 304 has no body.
- Reading records nothing: no Gold, no mastery, no history, no audit row, no profile.
- A word approved, edited or retired **during** a day never changes that day's answer.

## 2. Offline cache contract for the app

Store, per account and per `requested_locale`, the last `200` body verbatim plus its `ETag`.

1. **Show from cache first.** Opening the card never requires the network.
2. **A cached entry is "today's word" only while `now < valid_until`**, where `now` is the device
   clock. This is the only place the device clock is used, and only to decide a *label*; the server
   alone decides which word belongs to which date.
3. **When `now >= valid_until`** the entry is no longer today's word. If a fetch succeeds, replace
   it. If the fetch fails (offline, timeout, 5xx), keep showing the cached entry with the explicit
   label **"Dernier mot téléchargé · <haiti_date>"** / **"Dènye mo telechaje · <haiti_date>"**
   (Creole wording is a draft pending native review) — never the "Mot du jour" title, never
   today's date.
4. **Revalidate cheaply**: when online and the card is shown (at most once per app start / return
   to foreground), send `If-None-Match`. `304` → keep the entry. `200` → replace entry and tag.
5. **`404 daily_word_not_available`**: there is no word today. If the cached entry's
   `haiti_date` is older than today it stays "last downloaded word"; if the cached entry claimed to
   be valid (`now < valid_until`) it has been withdrawn — remove it. Retry on next foreground, not
   in a loop.
6. **`404 not_found`**: the feature is off on this server — hide the card, keep the cache.
7. **`401`**: refresh the token as for every route; do not clear the cache.
8. **Device clock wrong?** A clock set in the past keeps labelling an old word as today's until
   the next successful fetch; a clock in the future labels today's word "last downloaded". Both
   heal on the next `200`, because the body carries the authoritative `haiti_date`. If the response
   `haiti_date` differs from the device's idea of the date, trust the response.
9. Language switch: the two locales are two cache entries; do not show the French entry as the
   Creole one unless the server said so (`is_fallback_locale: true`, shown as "en français").
10. Sign-out / account switch: the content is not personal, but keep the cache per account like the
    rest of the local database so that nothing crosses accounts by construction.
11. Audio: show the affordance only if `audio != null`; never autoplay; never download on a metered
    connection without a tap. (No download route exists yet.)

## 3. Data model (schema `vocab`, private, RLS on every table, **no policy at all**)

| Table | Purpose |
|---|---|
| `sources` | Source / licence record with `rights_status` (`unverified → cleared \| restricted \| blocked`); who/when of each rights decision is stamped by the server |
| `words` | Stable identity (`slug`), `is_active` (retired words are never chosen for a new date) |
| `word_revisions` | One independent revision per locale; bounded single-line text; `draft → in_review → approved \| rejected`; author, approver, `source_id` (NOT NULL) |
| `reviews` | Append-only verdicts (`approved` / `rejected`), server-stamped time |
| `audio_assets` | Metadata of an optional recording: object key, `byte_size ≤ 102400`, sha256, mime, `duration_ms ≤ 15000`, its own rights record. No storage, no TTS, no autoplay column |
| `daily_assignments` | `(haiti_date, locale) → word_revision_id` + `assigned_via` (`auto`/`staff`), `assigned_by`, `assigned_at`. **The schedule of record** |

Rules enforced by triggers (they hold for every writer, including the owner role):

- A revision can only be inserted as a draft. Authorship is immutable. Submitted content is frozen.
  Approved **and rejected** revisions are immutable; a correction is a new revision.
- A review needs an active `reviewer`/`admin` role and **reviewer ≠ author**; the *latest* review
  decides; `approved_by` must be that reviewer; `approved_at` and `reviewed_at` are the server's.
- **Rights gate:** approval requires the revision's source to be `cleared`, and its recording's
  source too if it has one.
- Recording metadata can only change while the revision is a draft.
- Schedule: a date that has opened in Haiti (today or earlier) can never be updated or deleted; a
  past date can never be inserted; today can be inserted only if it has no row yet; future dates
  (≤ 366 days ahead) can be rescheduled; only an approved, rights-cleared revision of an active
  word is assignable; at COMMIT every date has one word across its locales and a French row.

`vocab.ensure_assignments(p_from date, p_days int)` (1–62 days): takes a transaction-level advisory
lock, then for each unassigned date ≥ today picks the **active word used least recently** (never
used first; then oldest most-recent date over the whole schedule; then `created_at`; then `id`) and
records French + Creole rows of that word. It also adds a missing Creole row to a *future* date when
the translation of the same word has since been approved, and frees and re-chooses a *future* date
whose word was retired or lost its rights. It never back-fills, never touches an opened day, never
invents a word (empty pool → nothing). Twice or concurrently → same schedule.

Learner read: `vocab.daily_word(p_locale)` is the **only** object in the schema the student API
role can use (EXECUTE on that function, USAGE on the schema, no table privilege). It has no time
parameter. The only clock seam is `vocab.daily_word_at(p_locale, p_now)`, executable by nobody.

## 4. Recorded choices

| Choice | Decision | Why / status |
|---|---|---|
| Who schedules | `publisher` (or `admin`), **not** `editor` | Separation of duties, same as pack release: the person who writes a word does not decide when learners get it |
| Who decides rights | `publisher` / `admin` | Synthetic default. **BLOCKED_BY_OWNER (PO-17/18 family: rights)** — who may clear rights is a legal decision |
| One word per day for both languages | Enforced (deferred constraint) | "Missing translation → French" only makes sense if French is the same word. Reversible |
| French is mandatory for a scheduled word | Enforced | French is the fallback language |
| Rights withdrawn after scheduling | The word (or only its recording / translation) disappears for learners; the schedule row stays | Takedown without rewriting history. **BLOCKED_BY_OWNER**: confirm this is the wanted takedown behaviour |
| Late fill of *today* | Allowed only when today has no row | A day that showed "no word" can get one; a word already shown is never replaced |
| Verdicts | `approved` / `rejected` only | The brief's states; "changes requested" = reject with a note + new revision |
| Only the author edits/submits a draft | Enforced in the workflow functions | Otherwise a second editor could rewrite a draft and then review "someone else's" text |
| Audio hard cap | 102 400 bytes, ≤ 15 s, 4 compact mime types | Synthetic default for slow, expensive data. Owner may tune (PO-08 family) |
| Size limits of text | 60 / 80 / 300 / 240 / 80 chars and 800 bytes of JSON in total | Keeps the response ≤ 1.5 KB in the worst case |
| View / history tracking | **Not built** | Needs consent — PO-04. `vocab.erase_learner(uuid)` returns `{}` |
| Haitian Creole demo wording | Draft | Pending native-speaker / educator review |

## 5. Awaiting staff wiring (next turn, after the staff lane's B1 is merged)

Complete and tested at SQL level, `EXECUTE` granted to **nobody**:

`register_source`, `set_source_rights`, `create_word`, `create_draft`, `update_draft`, `set_audio`,
`remove_audio`, `submit_revision`, `review_revision`, `review_queue`, `schedule_word`,
`unschedule_date`, `calendar`, `staff_ensure_assignments`, `retire_word`; plus the worker-facing
`ensure_assignments` and the hook `erase_learner`.

Two seams in `20261124040200_vocab_functions.sql`, each a single function to replace:

- `vocab._require_staff(VARIADIC roles)` — today reads `app.staff_roles` for the actor; becomes
  `staff.require_role(...)`.
- `vocab._audit(action, target_kind, target_id, details)` — today inserts into `app.audit_events`
  (`actor_kind 'staff'`, outcome `allowed`); becomes `ops.audit_write(...)`. A refused call raises,
  so it leaves no row: refusals must be audited at the API boundary.

SQLSTATE → HTTP mapping the routes will use: `42501` → 403, `P0002` → 404, `22023` → 422,
`23514` / `23505` / `P0001` → 409 or 422.

## 6. Daily notification — design only (nothing is sent or scheduled)

One in-app event per Haiti date, written to the future `notify` outbox by the worker:

- **When**: right after the worker's nightly `vocab.ensure_assignments(today, N)` run, for
  *tomorrow's* date, with `not_before = vocab.haiti_day_start(tomorrow) + <owner-chosen local hour>`
  (quiet hours and the hour itself are PO-10).
- **Idempotency key**: `daily_word:<haiti_date>` — one event per date whatever the number of runs.
- **Payload**: `{ "kind": "daily_word", "haiti_date": "YYYY-MM-DD" }` only. **No term and no
  definition**: the text stays in one place (the endpoint), so a later rights withdrawal cannot
  leave the word in a notification, and the outbox holds no content to localise.
- **Audience**: an in-app banner for learners who open the app that day; any push delivery needs
  the consent and policy decisions of PO-04 / PO-10 and is out of scope.
- **Delivery-time check**: the adapter drops the event if `vocab.daily_word_at` has no row for that
  date at send time (word withdrawn) or if `now >= valid_until`.
- No per-learner row is created by `vocab`; fan-out, read state and preferences belong to `notify`.

## 7. Known gaps and residual risks

- No HTTP staff routes yet; "learner token refused on staff routes" is proven only at the database
  (the API's real login role and a learner actor are refused by every staff function).
- The route is absent from the committed OpenAPI file and from the app's generated types (flag off).
- No audio download route and no storage: `audio` is metadata only.
- Midnight race: the day guard uses the instant of the write. A reschedule of *tomorrow* that starts
  before midnight and commits after it can still change the word during the first moments of the
  day (bounded by the transaction's duration; the API's statement timeout is 5 s). Closing it fully
  needs a freeze window before midnight — an owner/product choice.
- Staff accounts are referenced by `created_by` / `approved_by` / `reviewer_id` / `assigned_by` with
  `ON DELETE RESTRICT`: erasing a staff account that authored words needs a decision (not a learner
  erasure; out of scope here).
- A pool smaller than the horizon repeats words (one word → the same word every day). There is no
  "minimum gap" rule; that is a product decision.
- The temporary audit seam writes rows a learner-erasure job would not need to touch (no learner
  data), but its `actor_kind` is hard-coded to `staff`.
- Tests that place a word on "today" assume the Haiti date does not change during the test.

## 8. Tests

| Owner's named test | Where |
|---|---|
| Haiti midnight boundary (UTC instants) | `supabase/tests/164_vocab_haiti_time.sql` |
| DST transitions (2017-03-12, 2017-11-05, 2015) and a no-DST year (2016); next 23 h / 25 h days served correctly | `164_vocab_haiti_time.sql` |
| Missing translation | `163_vocab_learner_read.sql`; `tests/integration/test_vocab_daily_word.py::test_missing_translation_falls_back_to_french` |
| Word edited after assignment | `162_vocab_schedule.sql`; `163`; `test_word_edited_after_assignment_keeps_todays_word` |
| Idempotent daily publication | `162_vocab_schedule.sql` |
| Concurrent daily publication | `tests/integration/test_vocab_schedule.py::test_concurrent_daily_publication_yields_one_schedule` |
| Rejected / draft / future content invisible | `163`; `test_draft_in_review_rejected_and_future_content_is_invisible` |
| Cross-account behaviour | `163`; `test_cross_account_same_word_and_nothing_is_recorded` |
| Response size budget | `test_response_size_budget` (+ table constraint tested in `161`) |
| Audio size cap | `161_vocab_editorial_workflow.sql`; `test_audio_size_cap_is_enforced_by_the_database` |
| Licence / rights gate | `161` (approval), `162` (assignment, pool), `163` and `test_rights_withdrawn_hides_word_or_recording` (read) |
| Learner token refused on staff routes | **HTTP part pending.** Database part: `160`, `161`, `test_api_database_login_reaches_one_function_only` |
| Data API cannot reach `vocab` | `160_vocab_structure.sql`; `test_vocab_schema_is_not_reachable_through_the_supabase_data_api` |

Also: `tests/unit/test_vocab_etag.py` (entity tag, `If-None-Match`, flag default).

```sh
export UV_CACHE_DIR=/Volumes/EdupreneursDev/caches/uv npm_config_cache=/Volumes/EdupreneursDev/caches/npm
make lint && make typecheck && uv run python scripts/export_openapi.py --check
make db-reset && make test-db && uv run pytest -q && make test-db
uv run python scripts/seed_vocab_demo.py      # optional: DEMO words on the local stack
```
