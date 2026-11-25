-- Word of the Day: the schedule guards exercised THROUGH THE TRIGGERS with the
-- owner-only clock seam (vocab._clock / setting vocab.test_clock). Review F1/F3.
-- Constraints stay DEFERRED here on purpose: SET CONSTRAINTS ALL IMMEDIATE is
-- used as "the commit happens now".
BEGIN;
SELECT * FROM no_plan();
ALTER TABLE vocab.daily_assignments DISABLE TRIGGER no_truncate;
ALTER TABLE vocab.word_revisions DISABLE TRIGGER no_truncate;
ALTER TABLE vocab.reviews DISABLE TRIGGER no_truncate;
TRUNCATE vocab.daily_assignments, vocab.audio_assets, vocab.reviews, vocab.word_revisions, vocab.words, vocab.sources;
ALTER TABLE vocab.daily_assignments ENABLE TRIGGER no_truncate;
ALTER TABLE vocab.word_revisions ENABLE TRIGGER no_truncate;
ALTER TABLE vocab.reviews ENABLE TRIGGER no_truncate;

CREATE FUNCTION pg_temp.clock(p_at timestamptz) RETURNS void LANGUAGE sql AS
$fn$ SELECT set_config('vocab.test_clock', COALESCE(p_at::text, ''), true) $fn$;
CREATE FUNCTION pg_temp.day() RETURNS date LANGUAGE sql AS $fn$ SELECT vocab.haiti_date(clock_timestamp()) + 6 $fn$;
CREATE FUNCTION pg_temp.opens() RETURNS timestamptz LANGUAGE sql AS $fn$ SELECT vocab.haiti_day_start(pg_temp.day()) $fn$;

INSERT INTO vocab.sources (id, source_title, licence, created_by) VALUES
  ('e1000000-0000-4000-8000-000000000001', 'Synthetic test source', 'synthetic-test-only', 'a0000000-0000-4000-8000-000000000003');
UPDATE vocab.sources SET rights_status = 'cleared';
INSERT INTO vocab.words (id, slug, created_by) VALUES
  ('f1000000-0000-4000-8000-00000000000a', 'w-a', 'a0000000-0000-4000-8000-000000000003'),
  ('f1000000-0000-4000-8000-00000000000b', 'w-b', 'a0000000-0000-4000-8000-000000000003');
INSERT INTO vocab.word_revisions (id, word_id, locale, revision, term, part_of_speech, definition, example, source_id, created_by) VALUES
  ('c1000000-0000-4000-8000-00000000000a', 'f1000000-0000-4000-8000-00000000000a', 'fr', 1, 'A', 'noun', 'd', 'e', 'e1000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000003'),
  ('c1000000-0000-4000-8000-00000000000b', 'f1000000-0000-4000-8000-00000000000b', 'fr', 1, 'B', 'noun', 'd', 'e', 'e1000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000003');
UPDATE vocab.word_revisions SET status = 'in_review';
INSERT INTO vocab.reviews (word_revision_id, reviewer_id, verdict)
SELECT id, 'a0000000-0000-4000-8000-000000000004', 'approved' FROM vocab.word_revisions;
UPDATE vocab.word_revisions SET status = 'approved', approved_by = 'a0000000-0000-4000-8000-000000000004', approved_at = now();
INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via)
VALUES (pg_temp.day(), 'fr', 'f1000000-0000-4000-8000-00000000000a', 'c1000000-0000-4000-8000-00000000000a', 'auto');
SET CONSTRAINTS ALL IMMEDIATE;
SET CONSTRAINTS ALL DEFERRED;

-- ---- the seam is the owner's only ------------------------------------------------
SELECT is(vocab._clock() > now() - interval '1 minute', true, 'without an override the guards use the real clock');
SELECT lives_ok($$SELECT pg_temp.clock('2001-01-01 00:00:00+00')$$, 'fixture: override set');
SELECT is(vocab._clock(), '2001-01-01 00:00:00+00'::timestamptz, 'the owner login can pin the guards'' clock');
SELECT ok((SELECT prosrc LIKE '%session_user = ''postgres''%' FROM pg_proc WHERE pronamespace = 'vocab'::regnamespace AND proname = '_clock'),
    'the override is honoured only for the owner''s database login (API, staff and worker logins get the real clock: see the pytest suite)');

-- ---- FREEZE, through the trigger ----------------------------------------------------
SELECT pg_temp.clock(pg_temp.opens() - interval '10 minutes 1 second');
SELECT lives_ok($$UPDATE vocab.daily_assignments SET assigned_via = 'auto' WHERE haiti_date = pg_temp.day()$$,
    'FREEZE via trigger: 10 min 1 s before the day opens it can still be changed');
SELECT pg_temp.clock(pg_temp.opens() - interval '10 minutes');
SELECT throws_ok($$UPDATE vocab.daily_assignments SET assigned_via = 'auto' WHERE haiti_date = pg_temp.day()$$,
    'P0001', 'The schedule of a day is frozen shortly before it opens', 'FREEZE via trigger: exactly 10 minutes before, an UPDATE is refused');
SELECT throws_ok($$DELETE FROM vocab.daily_assignments WHERE haiti_date = pg_temp.day()$$,
    'P0001', 'The schedule of a day is frozen shortly before it opens', 'FREEZE via trigger: a DELETE is refused');
SELECT pg_temp.clock(pg_temp.opens() - interval '1 second');
SELECT throws_ok($$DELETE FROM vocab.daily_assignments WHERE haiti_date = pg_temp.day()$$,
    'P0001', 'The schedule of a day is frozen shortly before it opens', 'FREEZE via trigger: one second before midnight');
SELECT pg_temp.clock(pg_temp.opens());
SELECT throws_ok($$DELETE FROM vocab.daily_assignments WHERE haiti_date = pg_temp.day()$$,
    'P0001', 'The word of a day that has already opened cannot be changed', 'at midnight the day is opened');

-- ---- PLAIN COMMIT AFTER MIDNIGHT -----------------------------------------------------
SELECT pg_temp.clock(pg_temp.opens() - interval '30 minutes');
SELECT lives_ok($$UPDATE vocab.daily_assignments SET word_id = 'f1000000-0000-4000-8000-00000000000b', word_revision_id = 'c1000000-0000-4000-8000-00000000000b' WHERE haiti_date = pg_temp.day()$$,
    '23:30: a reschedule is accepted (its commit-time check is pending)');
SELECT pg_temp.clock(pg_temp.opens() + interval '1 second');
SELECT throws_ok('SET CONSTRAINTS ALL IMMEDIATE', 'P0001', 'The day opened before this schedule change was committed',
    'COMMIT AFTER MIDNIGHT: the change made at 23:30 is refused when it commits at 00:00:01');
-- (throws_ok rolled back to its savepoint: the pending check is still queued; consume it before midnight.)
SELECT pg_temp.clock(pg_temp.opens() - interval '29 minutes');
SELECT lives_ok('SET CONSTRAINTS ALL IMMEDIATE', 'the same change committed at 23:31 is fine');
SELECT is((SELECT word_id FROM vocab.daily_assignments WHERE haiti_date = pg_temp.day()), 'f1000000-0000-4000-8000-00000000000b'::uuid, 'and it took effect');

-- ---- F1 in one session: the early-fired check cannot be used to free the lock --------
SELECT is((SELECT count(*)::int FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND mode = 'ExclusiveLock'
           AND ((classid::bigint << 32) | objid::bigint) = vocab._day_key(pg_temp.day())), 1,
    'F1: the transaction that changed the day holds the day''s exclusive lock until it ends, whatever SET CONSTRAINTS did');
SELECT pg_temp.clock(NULL);

SELECT * FROM finish();
ROLLBACK;
