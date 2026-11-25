-- Word of the Day: the product day is the America/Port-au-Prince calendar date.
--   * the midnight boundary, written as UTC instants;
--   * real historical daylight-saving transitions from the tz database
--     (Haiti: DST 2012-2015, NONE in 2016, DST again from 2017-03-12);
--   * the word actually served on each side of a midnight, including the next
--     23-hour and 25-hour days the tz database announces.
-- Only the owner-only clock seam vocab.daily_word_at(locale, p_now) takes a time.
BEGIN;
SELECT * FROM no_plan();
-- Never straddle Haiti midnight: if the date changes within 5 seconds, wait for it.
DO $$ BEGIN
    PERFORM pg_sleep(GREATEST(0, 5 - EXTRACT(epoch FROM
        vocab.haiti_day_start(vocab.haiti_date(clock_timestamp()) + 1) - clock_timestamp()))::int
        * CASE WHEN vocab.haiti_day_start(vocab.haiti_date(clock_timestamp()) + 1) - clock_timestamp() < interval '5 seconds' THEN 1 ELSE 0 END);
END $$;

-- (TRUNCATE is refused by a trigger; switched off for this fixture only, inside the rolled-back transaction.)
ALTER TABLE vocab.daily_assignments DISABLE TRIGGER no_truncate;
ALTER TABLE vocab.word_revisions DISABLE TRIGGER no_truncate;
ALTER TABLE vocab.reviews DISABLE TRIGGER no_truncate;
TRUNCATE vocab.daily_assignments, vocab.audio_assets, vocab.reviews, vocab.word_revisions, vocab.words, vocab.sources;
ALTER TABLE vocab.daily_assignments ENABLE TRIGGER no_truncate;
ALTER TABLE vocab.word_revisions ENABLE TRIGGER no_truncate;
ALTER TABLE vocab.reviews ENABLE TRIGGER no_truncate;
SET CONSTRAINTS ALL IMMEDIATE;

-- ====================== pure date arithmetic (no rows needed) ======================
-- Winter: Haiti is UTC-5. Local 23:59:59 on 14 Jan = 04:59:59 UTC on 15 Jan.
SELECT is(vocab.haiti_date('2026-01-15 04:59:59+00'), '2026-01-14'::date, 'MIDNIGHT (winter): 23:59:59 local is still the previous day');
SELECT is(vocab.haiti_date('2026-01-15 05:00:00+00'), '2026-01-15'::date, 'MIDNIGHT (winter): 00:00:00 local opens the new day');
SELECT is(vocab.haiti_day_start('2026-01-15'), '2026-01-15 05:00:00+00'::timestamptz, 'a winter day starts at 05:00 UTC');
-- Summer (a DST year): Haiti is UTC-4. Local 23:59:59 on 14 Jul = 03:59:59 UTC on 15 Jul.
SELECT is(vocab.haiti_date('2019-07-15 03:59:59+00'), '2019-07-14'::date, 'MIDNIGHT (summer, DST year): 23:59:59 local is still the previous day');
SELECT is(vocab.haiti_date('2019-07-15 04:00:00+00'), '2019-07-15'::date, 'MIDNIGHT (summer, DST year): 00:00:00 local opens the new day');
SELECT is(vocab.haiti_day_start('2019-07-15'), '2019-07-15 04:00:00+00'::timestamptz, 'a summer day of a DST year starts at 04:00 UTC');
-- A device in another zone, or UTC "today", is irrelevant: at 02:00 UTC it is still yesterday in Haiti.
SELECT is(vocab.haiti_date('2026-01-15 02:00:00+00'), '2026-01-14'::date, 'the UTC date is not the product date');
SELECT is(vocab.haiti_date('2026-01-15 03:00:00+01'), '2026-01-14'::date, 'an instant written in another offset gives the same Haiti date');

-- ---- DST START 2017-03-12 (02:00 EST -> 03:00 EDT): a 23-hour day -------------------
SELECT is(vocab.haiti_date('2017-03-12 04:59:59+00'), '2017-03-11'::date, 'DST start: 23:59:59 EST on 11 March');
SELECT is(vocab.haiti_date('2017-03-12 05:00:00+00'), '2017-03-12'::date, 'DST start: midnight of 12 March is still at 05:00 UTC');
SELECT is(vocab.haiti_date('2017-03-12 06:59:59+00'), '2017-03-12'::date, 'DST start: 01:59:59 EST');
SELECT is(vocab.haiti_date('2017-03-12 07:00:00+00'), '2017-03-12'::date, 'DST start: 03:00:00 EDT, same day');
SELECT is(vocab.haiti_date('2017-03-13 03:59:59+00'), '2017-03-12'::date, 'DST start: 23:59:59 EDT on 12 March');
SELECT is(vocab.haiti_date('2017-03-13 04:00:00+00'), '2017-03-13'::date, 'DST start: the NEXT midnight is at 04:00 UTC, one hour earlier');
SELECT is(vocab.haiti_date('2017-03-13 04:30:00+00'), '2017-03-13'::date, 'DST start: a fixed "UTC-5" rule would still say 12 March here; the tz rule says 13 March');
SELECT is(EXTRACT(epoch FROM vocab.haiti_day_start('2017-03-13') - vocab.haiti_day_start('2017-03-12'))::int / 3600, 23, 'DST start: 12 March 2017 lasted 23 hours');

-- ---- DST END 2017-11-05 (02:00 EDT -> 01:00 EST): a 25-hour day ----------------------
SELECT is(vocab.haiti_date('2017-11-05 03:59:59+00'), '2017-11-04'::date, 'DST end: 23:59:59 EDT on 4 November');
SELECT is(vocab.haiti_date('2017-11-05 04:00:00+00'), '2017-11-05'::date, 'DST end: midnight of 5 November is at 04:00 UTC');
SELECT is(vocab.haiti_date('2017-11-06 04:00:00+00'), '2017-11-05'::date, 'DST end: 24 hours later it is STILL 5 November (23:00 EST)');
SELECT is(vocab.haiti_date('2017-11-06 04:59:59+00'), '2017-11-05'::date, 'DST end: 23:59:59 EST on 5 November');
SELECT is(vocab.haiti_date('2017-11-06 05:00:00+00'), '2017-11-06'::date, 'DST end: the next midnight is at 05:00 UTC');
SELECT is(EXTRACT(epoch FROM vocab.haiti_day_start('2017-11-06') - vocab.haiti_day_start('2017-11-05'))::int / 3600, 25, 'DST end: 5 November 2017 lasted 25 hours');

-- ---- 2016: Haiti did NOT observe daylight saving time -----------------------------------
SELECT is(vocab.haiti_date('2016-07-15 04:00:00+00'), '2016-07-14'::date, 'NO-DST YEAR: in July 2016, 04:00 UTC is 23:00 the previous day (UTC-5 all year)');
SELECT is(vocab.haiti_date('2016-07-15 04:59:59+00'), '2016-07-14'::date, 'NO-DST YEAR: 23:59:59 local');
SELECT is(vocab.haiti_date('2016-07-15 05:00:00+00'), '2016-07-15'::date, 'NO-DST YEAR: midnight is at 05:00 UTC even in summer');
SELECT is(EXTRACT(epoch FROM vocab.haiti_day_start('2016-03-14') - vocab.haiti_day_start('2016-03-13'))::int / 3600, 24, 'NO-DST YEAR: the second Sunday of March 2016 lasted 24 hours');
SELECT is((SELECT count(*)::int FROM generate_series('2016-01-01'::date, '2016-12-31'::date, interval '1 day') g
           WHERE vocab.haiti_day_start(g::date + 1) - vocab.haiti_day_start(g::date) <> interval '24 hours'), 0,
    'NO-DST YEAR: every day of 2016 lasted exactly 24 hours');
SELECT is((SELECT string_agg(g::date::text || '=' || (EXTRACT(epoch FROM vocab.haiti_day_start(g::date + 1) - vocab.haiti_day_start(g::date))::int / 3600), ',' ORDER BY g)
           FROM generate_series('2015-01-01'::date, '2017-12-31'::date, interval '1 day') g
           WHERE vocab.haiti_day_start(g::date + 1) - vocab.haiti_day_start(g::date) <> interval '24 hours'),
    '2015-03-08=23,2015-11-01=25,2017-03-12=23,2017-11-05=25',
    'the tz database gives exactly these transitions for 2015-2017 (none in 2016)');

-- ---- every day, 2012-2030: a day starts at local midnight and is never skipped -----------
SELECT is((SELECT count(*)::int FROM generate_series('2012-01-01'::date, '2030-12-31'::date, interval '1 day') g
           WHERE vocab.haiti_date(vocab.haiti_day_start(g::date)) <> g::date
              OR vocab.haiti_date(vocab.haiti_day_start(g::date) - interval '1 microsecond') <> g::date - 1
              OR (vocab.haiti_day_start(g::date) AT TIME ZONE 'America/Port-au-Prince')::time <> '00:00'), 0,
    'for every date 2012-2030: day_start is local 00:00, belongs to that date, and the instant before belongs to the previous date');

-- ====================== the schedule freeze (clock seam) ======================
SELECT is(vocab.schedule_freeze(), interval '10 minutes', 'the schedule of a day freezes 10 minutes before it opens');
-- 15 Jan 2026 opens at 05:00:00 UTC; it is frozen from 04:50:00 UTC (23:50 local on the 14th).
SELECT is(vocab.is_day_locked('2026-01-15', '2026-01-15 04:49:59+00'), false, 'FREEZE: 23:49:59 local, the next day can still be rescheduled');
SELECT is(vocab.is_day_locked('2026-01-15', '2026-01-15 04:50:00+00'), true, 'FREEZE: at 23:50:00 local the next day is locked');
SELECT is(vocab.is_day_locked('2026-01-15', '2026-01-15 04:59:59+00'), true, 'FREEZE: 23:59:59 local, locked');
SELECT is(vocab.is_day_locked('2026-01-15', '2026-01-15 05:00:00+00'), true, 'an opened day is locked');
SELECT is(vocab.is_day_locked('2026-01-15', '2027-01-01 00:00:00+00'), true, 'a past day is locked for ever');
SELECT is(vocab.is_day_locked('2026-01-16', '2026-01-15 05:00:00+00'), false, 'the day after tomorrow is not locked');
-- The freeze follows the real length of the day: 13 March 2017 opened at 04:00 UTC (after a 23-hour day).
SELECT is(vocab.is_day_locked('2017-03-13', '2017-03-13 03:49:59+00'), false, 'FREEZE on a 23-hour day: open until 10 minutes before the real midnight');
SELECT is(vocab.is_day_locked('2017-03-13', '2017-03-13 03:50:00+00'), true, 'FREEZE on a 23-hour day: locked from 03:50 UTC, not 04:50');
SELECT is(vocab.is_day_locked('2017-11-06', '2017-11-06 04:49:59+00'), false, 'FREEZE on a 25-hour day: still open at 04:49:59 UTC');
SELECT is(vocab.is_day_locked('2017-11-06', '2017-11-06 04:50:00+00'), true, 'FREEZE on a 25-hour day: locked from 04:50 UTC');
SELECT is((SELECT count(*)::int FROM generate_series('2012-01-01'::date, '2030-12-31'::date, interval '1 day') g
           WHERE NOT vocab.is_day_locked(g::date, vocab.haiti_day_start(g::date) - interval '10 minutes')
              OR vocab.is_day_locked(g::date, vocab.haiti_day_start(g::date) - interval '10 minutes 1 second')), 0,
    'for every date 2012-2030 the lock begins exactly 10 minutes before local midnight');

-- ====================== the word served around a midnight ======================
CREATE TEMP TABLE ids (k text PRIMARY KEY, v uuid NOT NULL);
CREATE FUNCTION pg_temp.id(p_k text) RETURNS uuid LANGUAGE sql AS $fn$ SELECT v FROM ids WHERE k = p_k $fn$;
CREATE FUNCTION pg_temp.today() RETURNS date LANGUAGE sql AS $fn$ SELECT vocab.haiti_date(clock_timestamp()) $fn$;
CREATE FUNCTION pg_temp.term_at(p_now timestamptz) RETURNS text LANGUAGE sql AS $fn$
    SELECT COALESCE((SELECT term FROM vocab.daily_word_at('fr', p_now)), '(none)') $fn$;
CREATE FUNCTION pg_temp.word(p_slug text, p_term text) RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE v_word uuid; v_rev uuid;
BEGIN
    PERFORM set_config('edu.actor_id', 'a0000000-0000-4000-8000-000000000003', true);
    v_word := vocab.create_word(p_slug);
    v_rev := vocab.create_draft(v_word, 'fr', p_term, NULL, 'noun', 'Définition synthétique.', 'Exemple synthétique.', NULL,
                                'e1000000-0000-4000-8000-000000000001');
    PERFORM vocab.submit_revision(v_rev);
    PERFORM set_config('edu.actor_id', 'a0000000-0000-4000-8000-000000000004', true);
    PERFORM vocab.review_revision(v_rev, 'approved');
    PERFORM set_config('edu.actor_id', '', true);
    INSERT INTO ids VALUES (p_slug, v_word), (p_slug || ':rev', v_rev);
END;
$fn$;
CREATE FUNCTION pg_temp.put(p_date date, p_slug text) RETURNS void LANGUAGE sql AS $fn$
    INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via)
    VALUES (p_date, 'fr', pg_temp.id(p_slug), pg_temp.id(p_slug || ':rev'), 'auto') $fn$;

INSERT INTO vocab.sources (id, source_title, licence, created_by) VALUES
  ('e1000000-0000-4000-8000-000000000001', 'Synthetic test source', 'synthetic-test-only', 'a0000000-0000-4000-8000-000000000003');
UPDATE vocab.sources SET rights_status = 'cleared';
SELECT pg_temp.word('w-first', 'PREMIER');
SELECT pg_temp.word('w-second', 'SECOND');

-- The next 23-hour and 25-hour days according to the tz database (at least two
-- days ahead, so both the day and the following one can be scheduled).
CREATE TEMP TABLE days AS
SELECT pg_temp.today() + 2 AS plain,
       (SELECT min(g::date) FROM generate_series(pg_temp.today() + 2, pg_temp.today() + 364, interval '1 day') g
         WHERE vocab.haiti_day_start(g::date + 1) - vocab.haiti_day_start(g::date) = interval '23 hours') AS short_day,
       (SELECT min(g::date) FROM generate_series(pg_temp.today() + 2, pg_temp.today() + 364, interval '1 day') g
         WHERE vocab.haiti_day_start(g::date + 1) - vocab.haiti_day_start(g::date) = interval '25 hours') AS long_day;
SELECT isnt((SELECT short_day FROM days), NULL, 'the tz database announces an upcoming 23-hour day for Haiti');
SELECT isnt((SELECT long_day FROM days), NULL, 'the tz database announces an upcoming 25-hour day for Haiti');

-- An ordinary pair of days. (If "plain + 1" happens to be a transition day the assertions still hold.)
SELECT pg_temp.put((SELECT plain FROM days), 'w-first');
SELECT pg_temp.put((SELECT plain + 1 FROM days), 'w-second');
SELECT is(pg_temp.term_at(vocab.haiti_day_start((SELECT plain FROM days)) - interval '1 second'), '(none)',
    'the day before has no word: NOTHING is served (never the next day''s word early)');
SELECT is(pg_temp.term_at(vocab.haiti_day_start((SELECT plain FROM days))), 'PREMIER', '00:00:00 local: the day''s word');
SELECT is(pg_temp.term_at(vocab.haiti_day_start((SELECT plain + 1 FROM days)) - interval '1 second'), 'PREMIER', '23:59:59 local: still the same word');
SELECT is(pg_temp.term_at(vocab.haiti_day_start((SELECT plain + 1 FROM days))), 'SECOND', '00:00:00 local next day: the next word');
SELECT is((SELECT valid_until FROM vocab.daily_word_at('fr', vocab.haiti_day_start((SELECT plain FROM days)) + interval '9 hours')),
    vocab.haiti_day_start((SELECT plain + 1 FROM days)), 'valid_until is exactly the instant the next word takes over');
SELECT is(pg_temp.term_at(vocab.haiti_day_start((SELECT plain + 2 FROM days))), '(none)',
    'after the last scheduled day NOTHING is served (yesterday''s word is never presented as today''s)');

-- The next 23-hour day and the day after it.
DELETE FROM vocab.daily_assignments WHERE haiti_date IN ((SELECT short_day FROM days), (SELECT short_day + 1 FROM days));
SELECT pg_temp.put((SELECT short_day FROM days), 'w-first');
SELECT pg_temp.put((SELECT short_day + 1 FROM days), 'w-second');
SELECT is(pg_temp.term_at(vocab.haiti_day_start((SELECT short_day FROM days))), 'PREMIER', '23-HOUR DAY: 00:00:00 local');
SELECT is(pg_temp.term_at(vocab.haiti_day_start((SELECT short_day FROM days)) + interval '22 hours 59 minutes 59 seconds'), 'PREMIER', '23-HOUR DAY: 23:59:59 local, 22 h 59 min 59 s after its start');
SELECT is(pg_temp.term_at(vocab.haiti_day_start((SELECT short_day FROM days)) + interval '23 hours'), 'SECOND', '23-HOUR DAY: the next word takes over after 23 hours, not 24');
SELECT is((SELECT EXTRACT(epoch FROM valid_until - vocab.haiti_day_start(haiti_date))::int / 3600
           FROM vocab.daily_word_at('fr', vocab.haiti_day_start((SELECT short_day FROM days)) + interval '1 hour')), 23,
    '23-HOUR DAY: valid_until is 23 hours after the day started');

-- The next 25-hour day and the day after it.
DELETE FROM vocab.daily_assignments WHERE haiti_date IN ((SELECT long_day FROM days), (SELECT long_day + 1 FROM days));
SELECT pg_temp.put((SELECT long_day FROM days), 'w-first');
SELECT pg_temp.put((SELECT long_day + 1 FROM days), 'w-second');
SELECT is(pg_temp.term_at(vocab.haiti_day_start((SELECT long_day FROM days))), 'PREMIER', '25-HOUR DAY: 00:00:00 local');
SELECT is(pg_temp.term_at(vocab.haiti_day_start((SELECT long_day FROM days)) + interval '24 hours'), 'PREMIER', '25-HOUR DAY: 24 hours later it is still the same day and the same word');
SELECT is(pg_temp.term_at(vocab.haiti_day_start((SELECT long_day FROM days)) + interval '24 hours 59 minutes 59 seconds'), 'PREMIER', '25-HOUR DAY: 23:59:59 local');
SELECT is(pg_temp.term_at(vocab.haiti_day_start((SELECT long_day FROM days)) + interval '25 hours'), 'SECOND', '25-HOUR DAY: the next word takes over after 25 hours');
SELECT is((SELECT EXTRACT(epoch FROM valid_until - vocab.haiti_day_start(haiti_date))::int / 3600
           FROM vocab.daily_word_at('fr', vocab.haiti_day_start((SELECT long_day FROM days)) + interval '24 hours 30 minutes')), 25,
    '25-HOUR DAY: valid_until is 25 hours after the day started');

-- The day guard uses the same Haiti date: today is frozen from 00:00:00 local.
SELECT pg_temp.put(pg_temp.today(), 'w-first');
SELECT throws_ok($$DELETE FROM vocab.daily_assignments WHERE haiti_date = vocab.haiti_date(clock_timestamp())$$,
    'P0001', 'The word of a day that has already opened cannot be changed', 'the guard''s "today" is the Haiti date of the server clock');
SELECT is(pg_temp.term_at(clock_timestamp()), 'PREMIER', 'and the reader''s "today" is the same date');
SELECT is(vocab.is_day_locked(vocab.haiti_date(clock_timestamp()), clock_timestamp()), true, 'the guard and is_day_locked agree that today is locked');
-- The guard really uses the lock: a day far ahead can be deleted, and the same
-- function decides both (the trigger passes clock_timestamp()).
SELECT lives_ok($$DELETE FROM vocab.daily_assignments WHERE haiti_date = (SELECT long_day + 1 FROM days)$$, 'an unlocked future day can be changed');
SELECT ok((SELECT prosrc LIKE '%vocab.is_day_locked(OLD.haiti_date, v_clock)%' AND prosrc LIKE '%clock_timestamp()%'
           FROM pg_proc WHERE pronamespace = 'vocab'::regnamespace AND proname = 'guard_daily_assignment'),
    'the day guard decides with vocab.is_day_locked on the server clock');

SELECT * FROM finish();
ROLLBACK;
