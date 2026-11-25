-- Streaks: a "day" is the America/Port-au-Prince date of SERVER acceptance.
-- Every instant below is explicit (UTC), so the test does not depend on when it runs.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
CREATE FUNCTION pg_temp.as_api(p_actor uuid, p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    PERFORM set_config('edu.actor_id', COALESCE(p_actor::text, ''), true);
    EXECUTE 'SET LOCAL ROLE edu_api';
    BEGIN
        EXECUTE p_sql INTO v_out;
    EXCEPTION WHEN OTHERS THEN
        v_out := 'ERROR:' || SQLSTATE;
    END;
    EXECUTE 'RESET ROLE';
    PERFORM set_config('edu.actor_id', '', true);
    RETURN v_out;
END;
$fn$;

-- An operation the server accepted at an exact instant (what sync_apply_operation
-- writes, with the clock pinned). p_correct NULL = a lesson completion is not
-- needed here; a wrong answer is enough to make a day active.
CREATE FUNCTION pg_temp.accepted_at(p_learner uuid, p_instant timestamptz, p_result text DEFAULT 'accepted',
                                    p_client_clock timestamptz DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql AS $fn$
DECLARE v_op uuid := gen_random_uuid();
BEGIN
    INSERT INTO app.sync_receipts (learner_id, op_id, op_kind, canon_version, payload_sha256, result_code, result, created_at)
    VALUES (p_learner, v_op, 'practice_answer', 'mep-canon-1', sha256(v_op::text::bytea), p_result, '{}', p_instant);
    IF p_result = 'accepted' THEN
        INSERT INTO app.practice_attempts (learner_id, op_id, lesson_revision_id, question_revision_id, response, score,
                                           scoring_version, client_recorded_at, accepted_at)
        VALUES (p_learner, v_op, 'c0000000-0000-4000-8000-000000000001', 'd0000000-0000-4000-8000-000000000102',
                '{"choice_id":"d"}', 0, 'mcq-v1', p_client_clock, p_instant);
    END IF;
    RETURN v_op;
END;
$fn$;
CREATE FUNCTION pg_temp.reconcile(p_learner uuid) RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.as_api(p_learner, $$SELECT rewards.reconcile_learner(500) ->> 'examined'$$)
$fn$;
CREATE FUNCTION pg_temp.streak(p_learner uuid) RETURNS text LANGUAGE sql AS $fn$
    SELECT latest_run_days || ' from ' || latest_run_start || ' to ' || last_active_day
           || ' / longest ' || longest_run_days || ' ending ' || longest_run_end
    FROM rewards.streak_state WHERE learner_id = p_learner
$fn$;
CREATE FUNCTION pg_temp.days(p_learner uuid) RETURNS text LANGUAGE sql AS $fn$
    SELECT string_agg(day::text, ',' ORDER BY day) FROM rewards.activity_days WHERE learner_id = p_learner
$fn$;

TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;
TRUNCATE rewards.achievement_awards, rewards.ledger, rewards.processed_operations,
         rewards.activity_days, rewards.streak_state, rewards.balances;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''

-- ---- the day function: Haiti midnight, winter (UTC-5) and summer (UTC-4) -----------
SELECT is(rewards.haiti_day('2026-01-15T04:59:59Z'), '2026-01-14'::date, 'winter: 23:59:59 local is still the previous day');
SELECT is(rewards.haiti_day('2026-01-15T05:00:00Z'), '2026-01-15'::date, 'winter: local midnight starts the new day (05:00 UTC)');
SELECT is(rewards.haiti_day('2026-07-15T03:59:59Z'), '2026-07-14'::date, 'summer: 23:59:59 local is still the previous day');
SELECT is(rewards.haiti_day('2026-07-15T04:00:00Z'), '2026-07-15'::date, 'summer: local midnight starts the new day (04:00 UTC)');
-- DST starts Sunday 2026-03-08 at 02:00 local (a 23-hour day).
SELECT is(rewards.haiti_day('2026-03-08T04:59:59Z'), '2026-03-07'::date, 'spring forward: the last second of Saturday (UTC-5)');
SELECT is(rewards.haiti_day('2026-03-08T05:00:00Z'), '2026-03-08'::date, 'spring forward: Sunday starts at 05:00 UTC');
SELECT is(rewards.haiti_day('2026-03-09T03:59:59Z'), '2026-03-08'::date, 'spring forward: Sunday ends at 03:59:59 UTC (now UTC-4)');
SELECT is(rewards.haiti_day('2026-03-09T04:00:00Z'), '2026-03-09'::date, 'spring forward: Monday starts at 04:00 UTC');
-- DST ends Sunday 2026-11-01 at 02:00 local (a 25-hour day).
SELECT is(rewards.haiti_day('2026-11-01T03:59:59Z'), '2026-10-31'::date, 'fall back: the last second of Saturday (UTC-4)');
SELECT is(rewards.haiti_day('2026-11-01T04:00:00Z'), '2026-11-01'::date, 'fall back: Sunday starts at 04:00 UTC');
SELECT is(rewards.haiti_day('2026-11-02T04:59:59Z'), '2026-11-01'::date, 'fall back: Sunday ends at 04:59:59 UTC (now UTC-5)');
SELECT is(rewards.haiti_day('2026-11-02T05:00:00Z'), '2026-11-02'::date, 'fall back: Monday starts at 05:00 UTC');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.haiti_day('2026-03-08T04:59:59Z')$$), '2026-03-07', 'the API role can compute the product day');

-- ---- one second either side of midnight is two different days ----------------------
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000001', '2026-03-08T04:59:59Z')$$, 'accepted Sat 23:59:59 local');
SELECT is(pg_temp.reconcile(:A), '1', 'examined');
SELECT is(pg_temp.streak(:A), '1 from 2026-03-07 to 2026-03-07 / longest 1 ending 2026-03-07', 'a first active day is a run of 1');
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000001', '2026-03-08T05:00:00Z')$$, 'accepted one second later: Sun 00:00:00 local');
SELECT is(pg_temp.reconcile(:A), '1', 'examined');
SELECT is(pg_temp.streak(:A), '2 from 2026-03-07 to 2026-03-08 / longest 2 ending 2026-03-08', 'crossing local midnight extends the run to 2 days');
-- Same Haiti day, 22h59m later in UTC terms, across the DST change: still Sunday.
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000001', '2026-03-09T03:59:59Z')$$, 'accepted Sun 23:59:59 local (after the clock change)');
SELECT is(pg_temp.reconcile(:A), '1', 'examined');
SELECT is(pg_temp.streak(:A), '2 from 2026-03-07 to 2026-03-08 / longest 2 ending 2026-03-08', 'a second operation on the same Haiti day changes nothing');
SELECT is((SELECT count(*)::int FROM rewards.achievement_awards WHERE learner_id = :A::uuid AND achievement_code = 'three_day_streak'), 0, 'two days: no three-day achievement yet');
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000001', '2026-03-09T04:00:00Z')$$, 'accepted Mon 00:00:00 local');
SELECT is(pg_temp.reconcile(:A), '1', 'examined');
SELECT is(pg_temp.streak(:A), '3 from 2026-03-07 to 2026-03-09 / longest 3 ending 2026-03-09', 'three consecutive Haiti days across the DST start');
SELECT is(pg_temp.days(:A), '2026-03-07,2026-03-08,2026-03-09', 'the activity days are Haiti dates');
SELECT is((SELECT awarded_day::text || '|' || (ledger_id IS NULL) FROM rewards.achievement_awards WHERE learner_id = :A::uuid AND achievement_code = 'three_day_streak'),
    '2026-03-09|true', 'the three-day achievement is earned on the third day and carries no Gold');
SELECT is((SELECT count(*)::int FROM rewards.ledger WHERE learner_id = :A::uuid), 0, 'wrong answers kept the streak alive without earning Gold');

-- ---- a gap is not a punishment ---------------------------------------------------------
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000001', '2026-03-12T18:00:00Z')$$, 'accepted three days later (Thu)');
SELECT is(pg_temp.reconcile(:A), '1', 'examined');
SELECT is(pg_temp.streak(:A), '1 from 2026-03-12 to 2026-03-12 / longest 3 ending 2026-03-09', 'after a gap a new run starts at 1 and the longest run is kept');
SELECT is((SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns
           WHERE table_schema = 'rewards' AND table_name = 'streak_state'),
    ARRAY['learner_id','latest_run_days','latest_run_start','last_active_day','longest_run_days','longest_run_end','updated_at'],
    'non-punitive by construction: the streak state has no lost / broken / frozen / penalty column');
SELECT is((SELECT count(*)::int FROM rewards.ledger WHERE learner_id = :A::uuid AND amount < 0), 0, 'a gap never costs Gold');

-- ---- offline work synced late counts on the day the SERVER accepted it -------------------
-- The phone says the work was done on Tue/Wed (which would close the gap); the
-- server accepted it on Friday. The phone's clock is display metadata only.
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000001', '2026-03-13T16:00:00Z', 'accepted', '2026-03-10T16:00:00Z')$$, 'accepted Fri, device clock says Tue');
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000001', '2026-03-13T16:00:01Z', 'accepted', '2026-03-11T16:00:00Z')$$, 'accepted Fri, device clock says Wed');
SELECT is(pg_temp.reconcile(:A), '2', 'examined');
SELECT is(pg_temp.days(:A), '2026-03-07,2026-03-08,2026-03-09,2026-03-12,2026-03-13', 'no back-dating: the device clock created no day');
SELECT is(pg_temp.streak(:A), '2 from 2026-03-12 to 2026-03-13 / longest 3 ending 2026-03-09', 'the late sync counts on the acceptance day only');

-- ---- reconciliation in any order gives the same streak ------------------------------------
-- Receipts whose SERVER acceptance was Tue and Wed, but which the rewards engine
-- only examines now (the hook was off then). They fill the gap.
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000001', '2026-03-11T16:00:00Z')$$, 'accepted Wed, examined late');
SELECT is(pg_temp.reconcile(:A), '1', 'examined');
SELECT is(pg_temp.streak(:A), '3 from 2026-03-11 to 2026-03-13 / longest 3 ending 2026-03-13', 'an older accepted day examined late joins the run it belongs to');
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000001', '2026-03-10T16:00:00Z')$$, 'accepted Tue, examined late');
SELECT is(pg_temp.reconcile(:A), '1', 'examined');
SELECT is(pg_temp.streak(:A), '7 from 2026-03-07 to 2026-03-13 / longest 7 ending 2026-03-13', 'the two runs merge into one of 7 days');
SELECT lives_ok($$SELECT rewards.rebuild_streak('a0000000-0000-4000-8000-000000000001')$$, 'rebuild_streak runs');
SELECT is(pg_temp.streak(:A), '7 from 2026-03-07 to 2026-03-13 / longest 7 ending 2026-03-13', 'a rebuild from the activity days gives the same state');

-- ---- rejected operations and other learners -------------------------------------------------
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000001', '2026-03-14T16:00:00Z', 'rejected')$$, 'a REJECTED operation on Sat');
SELECT is(pg_temp.reconcile(:A), '0', 'a rejected operation is never examined');
SELECT is(pg_temp.streak(:A), '7 from 2026-03-07 to 2026-03-13 / longest 7 ending 2026-03-13', 'a rejected operation does not make a day active');
SELECT is((SELECT count(*)::int FROM rewards.streak_state WHERE learner_id = :B::uuid), 0, 'B has no streak from A''s activity');

-- ---- the 25-hour day in November ---------------------------------------------------------------
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000002', '2026-11-01T03:59:59Z')$$, 'B: Sat 23:59:59 local (UTC-4)');
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000002', '2026-11-01T04:00:00Z')$$, 'B: Sun 00:00:00 local');
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000002', '2026-11-02T04:59:59Z')$$, 'B: Sun 23:59:59 local (UTC-5, 25 hours later)');
SELECT lives_ok($$SELECT pg_temp.accepted_at('a0000000-0000-4000-8000-000000000002', '2026-11-02T05:00:00Z')$$, 'B: Mon 00:00:00 local');
SELECT is(pg_temp.reconcile(:B), '4', 'examined');
SELECT is(pg_temp.days(:B), '2026-10-31,2026-11-01,2026-11-02', 'four instants, three Haiti days across the DST end');
SELECT is(pg_temp.streak(:B), '3 from 2026-10-31 to 2026-11-02 / longest 3 ending 2026-11-02', 'the long Sunday counts once');
SELECT is(pg_temp.streak(:A), '7 from 2026-03-07 to 2026-03-13 / longest 7 ending 2026-03-13', 'A is unaffected by B');

-- ---- erasure removes streak data too -------------------------------------------------------------
SELECT is((rewards.erase_learner(:B) #>> '{deleted,activity_days}')::int, 3, 'the erasure hook removes the activity days');
SELECT is((SELECT count(*)::int FROM rewards.streak_state WHERE learner_id = :B::uuid), 0, '... and the streak state');

SELECT * FROM finish();
ROLLBACK;
