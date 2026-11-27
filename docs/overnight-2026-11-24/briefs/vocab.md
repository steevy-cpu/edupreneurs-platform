# Lane VOCAB — Word of the Day (F13, owner priority)

Worktree `/Volumes/EdupreneursDev/worktrees/overnight/vocab` · branch `overnight/word-of-the-day` ·
stack API 56421 / DB 56422 · schema `vocab` · migrations `2026112404xxxx_*` · pgTAP `160–179_*`.

Owned paths: `supabase/migrations/2026112404*`, `supabase/tests/16*.sql`, `supabase/tests/17*.sql`,
`services/api/src/edu_api/vocab/**`, `services/api/src/edu_api/routers/daily_word.py`,
`services/api/src/edu_api/routers/staff_vocab.py`, `tests/**/test_vocab_*.py`, `tests/vocab_fixtures.py`,
`scripts/seed_vocab_demo.py` (synthetic demo words for a local stack),
`docs/overnight-2026-11-24/lanes/vocab.md`.

Requirements reference: the prototype's daily word (see Platform-00
`/Volumes/EdupreneursDev/worktrees/platform-00/docs/architecture/platform-00/01-feature-inventory.md`,
search "word"). Do not open, copy or connect to the prototype; re-design from the description.

## Data model (schema `vocab`, all private, RLS on)
- `words` (stable identity) and `word_revisions` per locale (`fr`/`ht`): term, pronunciation/phonetic
  text, part of speech, definition, worked usage example, optional short gloss in the other language,
  status `draft → in_review → approved | rejected`, author, approver, source/licence record,
  bounded lengths on every text column. An approved revision is immutable; editing means a new revision.
- `reviews` append-only; **reviewer ≠ author**; inserting directly as approved is impossible; a
  revision without a cleared source/licence record cannot be approved (same spirit as lessons).
- `audio_assets` metadata only (object key, bytes with a small hard cap, sha256, mime, duration,
  rights record). No storage service, no TTS, no autoplay flag. Local fixture bytes only in tests.
- `daily_assignments (haiti_date, locale) → word_revision_id`, with who/when. **This table is the
  schedule of record.** A trigger makes an assignment immutable once its date is today-or-past in
  `America/Port-au-Prince`; future dates can be rescheduled by staff. Only approved revisions can be
  assigned. Editing or retiring a word later never changes a past date's word.
- `vocab.ensure_assignments(p_from date, p_days int)`: idempotently fills *unassigned* future dates
  from the approved pool in a deterministic order (e.g. least recently used, then stable id) and
  records them **before the day opens**. Never "index = day modulo count of active words".
  Running it twice, or concurrently, yields the same schedule (test both).
- `vocab.erase_learner(uuid)` hook: returns an empty result (this schema stores no per-learner rows;
  view/history tracking is deliberately **not** built — it needs consent, PO-04).

## Learner API (flag `EDU_DAILY_WORD_ENABLED`, default off → 404 in the standard error shape)
`GET /v1/daily-word?locale=fr|ht` (authenticated like every `/v1` route):
- Resolves today's Haiti date on the server. Returns `haiti_date`, `locale`, `requested_locale`,
  `is_fallback_locale`, the word (ids, term, pronunciation, part of speech, definition, example,
  optional gloss), optional `audio` metadata (`null` when none), and `valid_until` (the instant of
  the next Haiti midnight, so the app can label a cached word as "last downloaded" afterwards).
- Missing translation for the requested locale → the French assignment with `is_fallback_locale:
  true`; nothing assigned at all → 404 `daily_word_not_available` (never an invented word).
- Strong `ETag` derived from the assignment identity; `If-None-Match` → 304; `Cache-Control: private`.
- Response is small: assert a size budget in a test (target ≤ 1.5 KB uncompressed JSON).
- Opening the word creates no Gold, no mastery, no tracking row.
- Read access for `edu_api` goes through RLS policies or a definer read function that exposes only
  approved revisions that are assigned to a date ≤ today (future and rejected words are invisible).

## Staff API (after the staff lane's B1 is merged — the director will message you)
Under `/v1/staff/vocab`, via `vocab.*` definer functions that call `staff.require_role` and
`ops.audit_write`: create/edit draft, submit, review (different person, role `reviewer`), list
queue, schedule/reschedule a future date (role `publisher` or `editor` — document the choice),
view the calendar, run `ensure_assignments`. Until B1 arrives, build and test the workflow at the
SQL level with an explicit role-check seam, then wire the routes.

## Tests the owner asked for by name
Haiti midnight boundary (23:59:59 vs 00:00:00 local, expressed as UTC instants), DST transitions
of `America/Port-au-Prince` (use real historical transition dates from the tz database and a
no-DST year), missing translation, word edited after assignment, idempotent and concurrent daily
publication, rejected/draft/future content invisible to learners, cross-account behaviour, response
size budget, audio size cap, licence/rights gate, learner token refused on staff routes, Data API
cannot reach `vocab`. SQL functions take an explicit `p_now timestamptz DEFAULT now()` *only* on
internal/test seams — the HTTP API never accepts a client clock.

## Also write (lane doc)
The offline cache contract for the app (what to store, the `valid_until` rule, the exact "last
downloaded word" behaviour, no false claim that yesterday's word is today's), and the design of the
daily in-app notification **event** through the future `notify` outbox. Do not send or schedule anything.
