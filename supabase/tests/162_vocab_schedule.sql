-- Word of the Day: the schedule of record.
--   * vocab.ensure_assignments: deterministic order, idempotent, never back-fills,
--     never invents a word, never touches a day that has opened;
--   * the day guard: today-or-past is immutable, the future can be rescheduled;
--   * a word edited or retired after assignment never changes a recorded date.
-- (The CONCURRENT run of ensure_assignments needs several connections; it is in
--  tests/integration/test_vocab_schedule.py.)
BEGIN;
SELECT * FROM no_plan();

TRUNCATE vocab.daily_assignments, vocab.audio_assets, vocab.reviews, vocab.word_revisions, vocab.words, vocab.sources;
-- The "one word per day, French included" rule is checked at COMMIT in real
-- use. Check it after every statement here so each assertion sees it.
SET CONSTRAINTS ALL IMMEDIATE;

INSERT INTO auth.users (instance_id, id, aud, role, email) VALUES
  ('00000000-0000-0000-0000-000000000000', 'a0000000-0000-4000-8000-000000000021', 'authenticated', 'authenticated', 'vocab.publisher@edupreneur.test');
INSERT INTO app.staff_roles (user_id, role) VALUES ('a0000000-0000-4000-8000-000000000021', 'publisher');

CREATE TEMP TABLE ids (k text PRIMARY KEY, v uuid NOT NULL);
CREATE FUNCTION pg_temp.id(p_k text) RETURNS uuid LANGUAGE sql AS $fn$ SELECT v FROM ids WHERE k = p_k $fn$;
CREATE FUNCTION pg_temp.today() RETURNS date LANGUAGE sql AS $fn$ SELECT vocab.haiti_date(clock_timestamp()) $fn$;
-- The French (or other) revision recorded for today + p_offset days.
CREATE FUNCTION pg_temp.slug_on(p_offset integer) RETURNS text LANGUAGE sql AS $fn$
    SELECT w.slug FROM vocab.daily_assignments a JOIN vocab.words w ON w.id = a.word_id
    WHERE a.haiti_date = pg_temp.today() + p_offset AND a.locale = 'fr' $fn$;
CREATE FUNCTION pg_temp.locales_on(p_offset integer) RETURNS text LANGUAGE sql AS $fn$
    SELECT COALESCE(string_agg(a.locale, ',' ORDER BY a.locale), '') FROM vocab.daily_assignments a
    WHERE a.haiti_date = pg_temp.today() + p_offset $fn$;
CREATE FUNCTION pg_temp.schedule_digest() RETURNS text LANGUAGE sql AS $fn$
    SELECT COALESCE(md5(string_agg(a::text, '|' ORDER BY a.haiti_date, a.locale)), 'empty') FROM vocab.daily_assignments a $fn$;

-- A revision taken through the REAL workflow (editor writes, reviewer approves).
CREATE FUNCTION pg_temp.revision(p_key text, p_word uuid, p_locale text, p_source uuid, p_outcome text DEFAULT 'approved')
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE v_rev uuid;
BEGIN
    PERFORM set_config('edu.actor_id', 'a0000000-0000-4000-8000-000000000003', true);
    v_rev := vocab.create_draft(p_word, p_locale, 'terme ' || p_key, NULL, 'noun',
                                'Définition synthétique ' || p_key, 'Exemple synthétique ' || p_key, NULL, p_source);
    INSERT INTO ids VALUES (p_key, v_rev);
    IF p_outcome <> 'draft' THEN
        PERFORM vocab.submit_revision(v_rev);
        PERFORM set_config('edu.actor_id', 'a0000000-0000-4000-8000-000000000004', true);
        PERFORM vocab.review_revision(v_rev, p_outcome);
    END IF;
    PERFORM set_config('edu.actor_id', '', true);
END;
$fn$;

INSERT INTO vocab.sources (id, source_title, licence, created_by) VALUES
  ('e1000000-0000-4000-8000-000000000001', 'Synthetic test source', 'synthetic-test-only', 'a0000000-0000-4000-8000-000000000003'),
  ('e1000000-0000-4000-8000-000000000002', 'Synthetic test source (rights withdrawn later)', 'synthetic-test-only', 'a0000000-0000-4000-8000-000000000003');
UPDATE vocab.sources SET rights_status = 'cleared';

-- ---- nothing approved yet: the fill invents nothing ------------------------------
SELECT is((SELECT count(*)::int FROM vocab.ensure_assignments(pg_temp.today(), 7)), 0, 'EMPTY POOL: ensure_assignments creates nothing');
SELECT is((SELECT count(*)::int FROM vocab.daily_assignments), 0, 'and the schedule stays empty (no invented word)');

-- Fixed ids make the expected order readable: w-a < w-b < w-c < ...
INSERT INTO vocab.words (id, slug, created_by) VALUES
  ('f1000000-0000-4000-8000-00000000000a', 'w-a', 'a0000000-0000-4000-8000-000000000003'),  -- French only (for now)
  ('f1000000-0000-4000-8000-00000000000b', 'w-b', 'a0000000-0000-4000-8000-000000000003'),  -- French + Creole
  ('f1000000-0000-4000-8000-00000000000c', 'w-c', 'a0000000-0000-4000-8000-000000000003'),  -- French + Creole, own source
  ('f1000000-0000-4000-8000-00000000000d', 'w-draft', 'a0000000-0000-4000-8000-000000000003'),
  ('f1000000-0000-4000-8000-00000000000e', 'w-rejected', 'a0000000-0000-4000-8000-000000000003'),
  ('f1000000-0000-4000-8000-00000000000f', 'w-creole-only', 'a0000000-0000-4000-8000-000000000003'),
  ('f1000000-0000-4000-8000-000000000010', 'w-in-review', 'a0000000-0000-4000-8000-000000000003');
INSERT INTO ids SELECT 'w-' || right(id::text, 1), id FROM vocab.words WHERE slug IN ('w-a', 'w-b', 'w-c');
SELECT pg_temp.revision('a_fr1', pg_temp.id('w-a'), 'fr', 'e1000000-0000-4000-8000-000000000001');
SELECT pg_temp.revision('b_fr1', pg_temp.id('w-b'), 'fr', 'e1000000-0000-4000-8000-000000000001');
SELECT pg_temp.revision('b_ht1', pg_temp.id('w-b'), 'ht', 'e1000000-0000-4000-8000-000000000001');
SELECT pg_temp.revision('c_fr1', pg_temp.id('w-c'), 'fr', 'e1000000-0000-4000-8000-000000000002');
SELECT pg_temp.revision('c_ht1', pg_temp.id('w-c'), 'ht', 'e1000000-0000-4000-8000-000000000002');
SELECT pg_temp.revision('draft_fr', 'f1000000-0000-4000-8000-00000000000d', 'fr', 'e1000000-0000-4000-8000-000000000001', 'draft');
SELECT pg_temp.revision('rejected_fr', 'f1000000-0000-4000-8000-00000000000e', 'fr', 'e1000000-0000-4000-8000-000000000001', 'rejected');
SELECT pg_temp.revision('creole_only_ht', 'f1000000-0000-4000-8000-00000000000f', 'ht', 'e1000000-0000-4000-8000-000000000001');
SELECT pg_temp.revision('in_review_fr', 'f1000000-0000-4000-8000-000000000010', 'fr', 'e1000000-0000-4000-8000-000000000001', 'draft');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000003';
SELECT lives_ok($$SELECT vocab.submit_revision(pg_temp.id('in_review_fr'))$$, 'fixture: one revision is waiting for review');
SET LOCAL edu.actor_id = '';

-- ---- argument bounds --------------------------------------------------------------
SELECT throws_ok($$SELECT * FROM vocab.ensure_assignments(pg_temp.today(), 0)$$, '22023', NULL, 'p_days must be at least 1');
SELECT throws_ok($$SELECT * FROM vocab.ensure_assignments(pg_temp.today(), 63)$$, '22023', NULL, 'p_days is capped at 62');
SELECT throws_ok($$SELECT * FROM vocab.ensure_assignments(NULL, 7)$$, '22023', NULL, 'p_from is required');

-- ---- never back-fills; an unopened-but-empty today is filled once -------------------
SELECT is((SELECT string_agg(haiti_date::text || ':' || locale, ',') FROM vocab.ensure_assignments(pg_temp.today() - 3, 4)),
    pg_temp.today()::text || ':fr', 'a window that starts in the past creates today only (w-a has no Creole yet)');
SELECT is((SELECT count(*)::int FROM vocab.daily_assignments WHERE haiti_date < pg_temp.today()), 0, 'NO PAST DATE is ever back-filled');
SELECT is(pg_temp.slug_on(0), 'w-a', 'today got the first word of the deterministic order');

-- ---- deterministic order: least recently used, then oldest, then id -----------------
SELECT is((SELECT count(*)::int FROM vocab.ensure_assignments(pg_temp.today() + 1, 5)), 9,
    'five future days: 5 French rows + 4 Creole rows (w-b and w-c have a translation, w-a has not)');
SELECT is(pg_temp.slug_on(1) || ',' || pg_temp.slug_on(2) || ',' || pg_temp.slug_on(3) || ',' || pg_temp.slug_on(4) || ',' || pg_temp.slug_on(5),
    'w-b,w-c,w-a,w-b,w-c', 'words rotate least-recently-used first (w-a was used today, so it comes last)');
SELECT is(pg_temp.locales_on(1) || '|' || pg_temp.locales_on(3), 'fr,ht|fr', 'a day carries a Creole row only when the translation is approved');
SELECT is((SELECT count(*)::int FROM vocab.daily_assignments a JOIN vocab.words w ON w.id = a.word_id
           WHERE w.slug IN ('w-draft', 'w-rejected', 'w-creole-only', 'w-in-review')), 0,
    'draft, in-review, rejected and Creole-only words are never scheduled');
SELECT is((SELECT count(*)::int FROM vocab.daily_assignments WHERE assigned_via <> 'auto' OR assigned_by IS NOT NULL), 0,
    'rows created by the fill are marked auto, with no person');
SELECT ok((SELECT bool_and(a.assigned_at < vocab.haiti_day_start(a.haiti_date)) FROM vocab.daily_assignments a WHERE a.haiti_date > pg_temp.today()),
    'every future row was recorded BEFORE its day opens');

-- ---- idempotent ---------------------------------------------------------------------
CREATE TEMP TABLE digest AS SELECT pg_temp.schedule_digest() AS d;
SELECT is((SELECT count(*)::int FROM vocab.ensure_assignments(pg_temp.today() + 1, 5)), 0, 'IDEMPOTENT: a second run creates nothing');
SELECT is((SELECT count(*)::int FROM vocab.ensure_assignments(pg_temp.today() - 10, 16)), 0, 'IDEMPOTENT: a wider overlapping run creates nothing');
SELECT is(pg_temp.schedule_digest(), (SELECT d FROM digest), 'and the schedule is byte-for-byte unchanged (who, when and what)');

-- ---- a person's choice is kept; only unassigned dates are filled ------------------------
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000003';
SELECT throws_ok($$SELECT vocab.schedule_word(pg_temp.today() + 7, pg_temp.id('w-a'))$$, '42501', 'Staff role required', 'an editor cannot schedule (publisher decides)');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000004';
SELECT throws_ok($$SELECT vocab.schedule_word(pg_temp.today() + 7, pg_temp.id('w-a'))$$, '42501', 'Staff role required', 'a reviewer cannot schedule');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000021';
SELECT is(vocab.schedule_word(pg_temp.today() + 7, pg_temp.id('w-a')), 1, 'a publisher schedules w-a on day +7');
SELECT is((SELECT assigned_via || '/' || assigned_by FROM vocab.daily_assignments WHERE haiti_date = pg_temp.today() + 7),
    'staff/a0000000-0000-4000-8000-000000000021', 'the row records who chose it');
SELECT is((SELECT count(*)::int FROM vocab.staff_ensure_assignments(pg_temp.today() + 1, 8)), 4, 'the fill then creates only days +6 and +8');
SELECT is(pg_temp.slug_on(6) || ',' || pg_temp.slug_on(7) || ',' || pg_temp.slug_on(8), 'w-b,w-a,w-c',
    'the staff choice is kept and counts as a use: the fill works around it');
SELECT is((SELECT assigned_via FROM vocab.daily_assignments WHERE haiti_date = pg_temp.today() + 7 AND locale = 'fr'), 'staff', 'day +7 is still the staff row');

-- ---- reschedule the future --------------------------------------------------------------
SELECT is(vocab.schedule_word(pg_temp.today() + 8, pg_temp.id('w-b')), 2, 'FUTURE: day +8 can be rescheduled to another word');
SELECT is(pg_temp.slug_on(8) || '/' || pg_temp.locales_on(8), 'w-b/fr,ht', 'both locale rows moved together');
SELECT is(vocab.schedule_word(pg_temp.today() + 8, pg_temp.id('w-c')), 2, 'and rescheduled back');
SELECT throws_ok($$SELECT vocab.schedule_word(pg_temp.today() + 20, 'f1000000-0000-4000-8000-00000000000d')$$,
    '23514', 'The word has no approved, rights-cleared French revision', 'a draft-only word cannot be scheduled');
SELECT throws_ok($$SELECT vocab.schedule_word(pg_temp.today() + 20, 'f1000000-0000-4000-8000-00000000000e')$$,
    '23514', 'The word has no approved, rights-cleared French revision', 'a rejected word cannot be scheduled');
SELECT throws_ok($$SELECT vocab.schedule_word(pg_temp.today() + 20, 'f1000000-0000-4000-8000-00000000000f')$$,
    '23514', 'The word has no approved, rights-cleared French revision', 'a word without French cannot be scheduled (French is the fallback)');
SELECT throws_ok($$SELECT vocab.schedule_word(pg_temp.today() + 20, gen_random_uuid())$$, 'P0002', 'Word not found', 'unknown word');
SELECT throws_ok($$SELECT vocab.schedule_word(pg_temp.today() + 367, pg_temp.id('w-a'))$$,
    'P0001', 'A day more than 366 days ahead cannot be assigned', 'the horizon is bounded');
SELECT is(vocab.schedule_word(pg_temp.today() + 30, pg_temp.id('w-b')), 2, 'fixture: day +30 scheduled');
SELECT is(vocab.unschedule_date(pg_temp.today() + 30), 2, 'a future day can be cleared');
SELECT is(pg_temp.locales_on(30), '', 'and is empty again');

-- ---- TODAY AND THE PAST ARE IMMUTABLE ---------------------------------------------------
SELECT throws_ok($$SELECT vocab.schedule_word(pg_temp.today(), pg_temp.id('w-b'))$$,
    'P0001', 'The word of a day that has already opened cannot be changed', 'TODAY cannot be rescheduled by staff');
SELECT throws_ok($$SELECT vocab.unschedule_date(pg_temp.today())$$,
    'P0001', 'The word of a day that has already opened cannot be changed', 'TODAY cannot be cleared by staff');
SET LOCAL edu.actor_id = '';
SELECT throws_ok($$UPDATE vocab.daily_assignments SET word_revision_id = pg_temp.id('b_fr1'), word_id = pg_temp.id('w-b') WHERE haiti_date = pg_temp.today()$$,
    'P0001', 'The word of a day that has already opened cannot be changed', 'TODAY cannot be updated, even by the owner role');
SELECT throws_ok($$UPDATE vocab.daily_assignments SET assigned_at = now() WHERE haiti_date = pg_temp.today()$$,
    'P0001', 'The word of a day that has already opened cannot be changed', 'not even its metadata');
SELECT throws_ok($$DELETE FROM vocab.daily_assignments WHERE haiti_date = pg_temp.today()$$,
    'P0001', 'The word of a day that has already opened cannot be changed', 'TODAY cannot be deleted');
SELECT throws_ok($$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (pg_temp.today(), 'fr', pg_temp.id('w-b'), pg_temp.id('b_fr1'), 'auto')$$,
    '23505', NULL, 'a second word for today is impossible');
SELECT throws_ok($$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (pg_temp.today() - 1, 'fr', pg_temp.id('w-b'), pg_temp.id('b_fr1'), 'auto')$$,
    'P0001', 'A past day cannot be assigned', 'YESTERDAY cannot be assigned after the fact');
SELECT throws_ok($$UPDATE vocab.daily_assignments SET haiti_date = pg_temp.today() - 1 WHERE haiti_date = pg_temp.today() + 6$$,
    'P0001', 'An assignment cannot move to another date or locale', 'a future row cannot be moved into the past');
SELECT throws_ok($$UPDATE vocab.daily_assignments SET haiti_date = pg_temp.today() + 40 WHERE haiti_date = pg_temp.today() + 6$$,
    'P0001', 'An assignment cannot move to another date or locale', 'a row cannot change date at all');

-- A row dated YESTERDAY cannot be created legitimately, so this one fixture is
-- placed with the day guard switched off (inside this rolled-back transaction),
-- and the guard is switched on again before the assertions.
ALTER TABLE vocab.daily_assignments DISABLE TRIGGER guard_daily_assignment;
INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via)
VALUES (pg_temp.today() - 1, 'fr', pg_temp.id('w-b'), pg_temp.id('b_fr1'), 'auto');
ALTER TABLE vocab.daily_assignments ENABLE TRIGGER guard_daily_assignment;
SELECT throws_ok($$UPDATE vocab.daily_assignments SET word_revision_id = pg_temp.id('c_fr1'), word_id = pg_temp.id('w-c') WHERE haiti_date = pg_temp.today() - 1$$,
    'P0001', 'The word of a day that has already opened cannot be changed', 'YESTERDAY cannot be updated');
SELECT throws_ok($$DELETE FROM vocab.daily_assignments WHERE haiti_date = pg_temp.today() - 1$$,
    'P0001', 'The word of a day that has already opened cannot be changed', 'YESTERDAY cannot be deleted');
SELECT throws_ok($$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (pg_temp.today() - 1, 'ht', pg_temp.id('w-b'), pg_temp.id('b_ht1'), 'auto')$$,
    'P0001', 'A past day cannot be assigned', 'a translation cannot be added to YESTERDAY');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000021';
SELECT throws_ok($$SELECT vocab.schedule_word(pg_temp.today() - 1, pg_temp.id('w-c'))$$,
    'P0001', 'The word of a day that has already opened cannot be changed', 'YESTERDAY cannot be rescheduled by staff');
SET LOCAL edu.actor_id = '';

-- ---- what can be assigned ------------------------------------------------------------------
SELECT throws_ok($$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (pg_temp.today() + 50, 'fr', 'f1000000-0000-4000-8000-00000000000d', pg_temp.id('draft_fr'), 'auto')$$,
    'P0001', 'Only an approved, rights-cleared word revision can be assigned', 'a DRAFT revision cannot be assigned, even directly');
SELECT throws_ok($$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (pg_temp.today() + 50, 'fr', 'f1000000-0000-4000-8000-000000000010', pg_temp.id('in_review_fr'), 'auto')$$,
    'P0001', 'Only an approved, rights-cleared word revision can be assigned', 'an IN-REVIEW revision cannot be assigned');
SELECT throws_ok($$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (pg_temp.today() + 50, 'fr', 'f1000000-0000-4000-8000-00000000000e', pg_temp.id('rejected_fr'), 'auto')$$,
    'P0001', 'Only an approved, rights-cleared word revision can be assigned', 'a REJECTED revision cannot be assigned');
SELECT throws_ok($$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (pg_temp.today() + 50, 'fr', pg_temp.id('w-a'), pg_temp.id('b_fr1'), 'auto')$$,
    '23503', NULL, 'the revision must belong to the word');
SELECT throws_ok($$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (pg_temp.today() + 50, 'ht', pg_temp.id('w-b'), pg_temp.id('b_fr1'), 'auto')$$,
    '23503', NULL, 'the revision must be in the row''s locale');
SELECT throws_ok($$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (pg_temp.today() + 50, 'fr', pg_temp.id('w-b'), pg_temp.id('b_fr1'), 'staff')$$,
    '23514', NULL, 'a staff row needs the person');
SELECT throws_ok($$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (pg_temp.today() + 50, 'ht', pg_temp.id('w-b'), pg_temp.id('b_ht1'), 'auto')$$,
    'P0001', 'A day needs one word for all its locales, including French', 'a day cannot have a Creole word without the French one');
INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via, assigned_at)
VALUES (pg_temp.today() + 50, 'fr', pg_temp.id('w-b'), pg_temp.id('b_fr1'), 'auto', '1999-01-01');
SELECT ok((SELECT assigned_at > now() - interval '1 minute' FROM vocab.daily_assignments WHERE haiti_date = pg_temp.today() + 50),
    'assigned_at is stamped by the server, not the caller');
SELECT throws_ok($$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (pg_temp.today() + 50, 'ht', pg_temp.id('w-c'), pg_temp.id('c_ht1'), 'auto')$$,
    'P0001', 'A day needs one word for all its locales, including French', 'French and Creole of one day cannot be two different words');
INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via)
VALUES (pg_temp.today() + 50, 'ht', pg_temp.id('w-b'), pg_temp.id('b_ht1'), 'auto');
SELECT throws_ok($$DELETE FROM vocab.daily_assignments WHERE haiti_date = pg_temp.today() + 50 AND locale = 'fr'$$,
    'P0001', 'A day needs one word for all its locales, including French', 'the French row cannot be removed while the Creole one stays');
SELECT lives_ok($$DELETE FROM vocab.daily_assignments WHERE haiti_date = pg_temp.today() + 50$$, 'a future day can be deleted as a whole');

-- ---- a translation approved later completes FUTURE days only --------------------------------
SELECT pg_temp.revision('a_ht1', pg_temp.id('w-a'), 'ht', 'e1000000-0000-4000-8000-000000000001');
SELECT is((SELECT string_agg((haiti_date - pg_temp.today())::text || ':' || locale, ',') FROM vocab.ensure_assignments(pg_temp.today() - 1, 10)),
    '3:ht,7:ht', 'the new Creole translation of w-a is added to its FUTURE days (+3, +7)');
SELECT is(pg_temp.locales_on(0), 'fr', 'TODAY is not touched: it keeps the French row it opened with');
SELECT is(pg_temp.locales_on(-1), 'fr', 'YESTERDAY is not touched either');

-- ---- WORD EDITED AFTER ASSIGNMENT ----------------------------------------------------------------
DROP TABLE digest;
CREATE TEMP TABLE digest AS SELECT pg_temp.schedule_digest() AS d;
SELECT pg_temp.revision('a_fr2', pg_temp.id('w-a'), 'fr', 'e1000000-0000-4000-8000-000000000001');
SELECT is((SELECT revision FROM vocab.word_revisions WHERE id = pg_temp.id('a_fr2')), 2, 'fixture: w-a now has an approved French revision 2');
SELECT is(pg_temp.schedule_digest(), (SELECT d FROM digest), 'EDIT AFTER ASSIGNMENT: approving a new revision changes no recorded date');
SELECT is((SELECT count(*)::int FROM vocab.ensure_assignments(pg_temp.today() - 1, 9)), 0, 'and the fill does not "upgrade" recorded days');
SELECT is((SELECT word_revision_id FROM vocab.daily_assignments WHERE haiti_date = pg_temp.today() AND locale = 'fr'), pg_temp.id('a_fr1'),
    'today still shows the revision it opened with');
SELECT is((SELECT word_revision_id FROM vocab.daily_assignments WHERE haiti_date = pg_temp.today() + 3 AND locale = 'fr'), pg_temp.id('a_fr1'),
    'an already-scheduled future day keeps its pinned revision too');
-- Order now: w-a last on +7, w-b on +6, w-c on +8  ->  +9 = w-b, +10 = w-a (revision 2).
SELECT is((SELECT count(*)::int FROM vocab.ensure_assignments(pg_temp.today() + 9, 2)), 4, 'two new days are filled');
SELECT is(pg_temp.slug_on(9) || ',' || pg_temp.slug_on(10), 'w-b,w-a', 'rotation continues');
SELECT is((SELECT word_revision_id FROM vocab.daily_assignments WHERE haiti_date = pg_temp.today() + 10 AND locale = 'fr'), pg_temp.id('a_fr2'),
    'a NEW day uses the newest approved revision');

-- ---- rights withdrawn: the word leaves the pool ---------------------------------------------------
UPDATE vocab.sources SET rights_status = 'blocked' WHERE id = 'e1000000-0000-4000-8000-000000000002';
SELECT is((SELECT string_agg(DISTINCT w.slug, ',') FROM vocab.ensure_assignments(pg_temp.today() + 11, 4) e JOIN vocab.words w ON w.id = e.word_id),
    'w-a,w-b', 'a word whose rights were withdrawn (w-c) is not chosen for new days');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000021';
SELECT throws_ok($$SELECT vocab.schedule_word(pg_temp.today() + 20, pg_temp.id('w-c'))$$,
    '23514', 'The word has no approved, rights-cleared French revision', 'nor can staff schedule it');
SET LOCAL edu.actor_id = '';
SELECT throws_ok($$INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via) VALUES (pg_temp.today() + 20, 'fr', pg_temp.id('w-c'), pg_temp.id('c_fr1'), 'auto')$$,
    'P0001', 'Only an approved, rights-cleared word revision can be assigned', 'nor can it be assigned directly');

-- ---- WORD RETIRED AFTER ASSIGNMENT ------------------------------------------------------------------
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000003';
SELECT throws_ok($$SELECT vocab.retire_word(pg_temp.id('w-a'))$$, '42501', 'Staff role required', 'an editor cannot retire a word');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000021';
SELECT throws_ok($$SELECT vocab.retire_word(gen_random_uuid())$$, 'P0002', 'Word not found', 'unknown word');
CREATE TEMP TABLE before_retire AS SELECT count(*)::int AS n FROM vocab.daily_assignments WHERE word_id = pg_temp.id('w-a') AND haiti_date > pg_temp.today();
SELECT is(vocab.retire_word(pg_temp.id('w-a')), (SELECT n FROM before_retire), 'retiring w-a removes its rows on days that have not opened');
SELECT is((SELECT is_active::text || '/' || retired_by FROM vocab.words WHERE id = pg_temp.id('w-a')), 'false/a0000000-0000-4000-8000-000000000021', 'the retirement records who did it');
SELECT is((SELECT count(*)::int FROM vocab.daily_assignments WHERE word_id = pg_temp.id('w-a') AND haiti_date > pg_temp.today()), 0, 'no future day shows the retired word');
SELECT is(pg_temp.slug_on(0), 'w-a', 'RETIRED AFTER ASSIGNMENT: today keeps the word it opened with');
SELECT throws_ok($$SELECT vocab.schedule_word(pg_temp.today() + 3, pg_temp.id('w-a'))$$,
    'P0001', 'Only an active word can be assigned', 'a retired word cannot be scheduled again');
SELECT is((SELECT string_agg(DISTINCT w.slug, ',') FROM vocab.ensure_assignments(pg_temp.today() + 1, 14) e JOIN vocab.words w ON w.id = e.word_id),
    'w-b', 'the fill re-covers the freed days with the remaining usable word');
SELECT is((SELECT count(DISTINCT haiti_date)::int FROM vocab.daily_assignments WHERE haiti_date BETWEEN pg_temp.today() + 1 AND pg_temp.today() + 14), 14,
    'no gap is left in the next 14 days');
SELECT is((SELECT count(*)::int FROM vocab.daily_assignments WHERE word_id = pg_temp.id('w-c') AND haiti_date BETWEEN pg_temp.today() + 1 AND pg_temp.today() + 14), 0,
    'future days that held the rights-withdrawn word (w-c) were freed and re-chosen');
SELECT is(pg_temp.slug_on(-1) || ',' || pg_temp.slug_on(0), 'w-b,w-a', 'yesterday and today are exactly as they were');
SELECT is((SELECT count(*)::int FROM vocab.daily_assignments a GROUP BY a.haiti_date HAVING count(DISTINCT a.word_id) > 1 LIMIT 1), NULL,
    'every day still has exactly one word across its locales');

-- ---- calendar ---------------------------------------------------------------------------------------
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000004';
SELECT is((SELECT string_agg((haiti_date - pg_temp.today())::text || locale || ':' || is_locked, ',' ORDER BY haiti_date, locale)
           FROM vocab.calendar(pg_temp.today() - 1, 3)),
    '-1fr:true,0fr:true,1fr:false,1ht:false', 'the calendar shows recorded days and which are locked');
SELECT throws_ok($$SELECT * FROM vocab.calendar(pg_temp.today(), 93)$$, '22023', NULL, 'the calendar window is bounded');
SET LOCAL edu.actor_id = '';

-- ---- audit ------------------------------------------------------------------------------------------
SELECT is((SELECT array_agg(DISTINCT action ORDER BY action) FROM app.audit_events WHERE created_at = now() AND (action LIKE 'vocab.schedule.%' OR action = 'vocab.word.retire')),
    ARRAY['vocab.schedule.clear','vocab.schedule.ensure','vocab.schedule.set','vocab.word.retire'], 'schedule decisions are audited');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE created_at = now() AND action = 'vocab.schedule.set' AND NOT (details ? 'haiti_date')), 0, 'a schedule audit row names the date');

SELECT * FROM finish();
ROLLBACK;
