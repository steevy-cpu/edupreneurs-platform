-- Independent-review fixes (final verification 2026-11-25): LB-1 minimum cohort
-- size and snapshot-only rank/size, LB-5 Haiti week boundaries with explicit
-- instants, LB-6 allow-list, LB-7 frozen Gold for a closed period.
-- (LB-2 needs two real connections: tests/integration/test_leaderboard_review_fixes.py.)
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
CREATE FUNCTION pg_temp.as_role(p_role text, p_actor uuid, p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    PERFORM set_config('edu.actor_id', COALESCE(p_actor::text, ''), true);
    EXECUTE format('SET LOCAL ROLE %I', p_role);
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
CREATE FUNCTION pg_temp.me(p_actor uuid, p_period text, p_path text) RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.as_role('edu_api', p_actor,
        format('SELECT COALESCE(leaderboard.my_standing(%L) #>> %L, ''null'')', p_period, string_to_array(p_path, '.')))
$fn$;
-- '<rank>/<size>' as the learner sees it.
CREATE FUNCTION pg_temp.rs(p_actor uuid, p_period text) RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.me(p_actor, p_period, 'cohort.rank') || '/' || pg_temp.me(p_actor, p_period, 'cohort.size')
$fn$;
-- Test arrangement: a ledger award dated by an explicit instant. Callers run it with
-- session_replication_role = replica (set at top level, like 205's back-dating): no award-path trigger.
CREATE FUNCTION pg_temp.give(p_learner uuid, p_amount int, p_at timestamptz, p_code text) RETURNS void LANGUAGE plpgsql AS $fn$
BEGIN
    INSERT INTO rewards.ledger (learner_id, entry_kind, amount, rule_code, rule_version, source_kind, source_op_id,
                                achievement_code, accepted_at, accepted_day)
    VALUES (p_learner, 'award', p_amount, 'achievement_first_lesson', 1, 'achievement', gen_random_uuid(),
            p_code, p_at, (p_at AT TIME ZONE 'America/Port-au-Prince')::date);
END;
$fn$;
CREATE FUNCTION pg_temp.uid(p_n int) RETURNS uuid LANGUAGE sql AS $$
    SELECT ('3b000000-0000-4000-8000-0000000000' || lpad(p_n::text, 2, '0'))::uuid $$;
-- Enrol learner n in the cohort, refresh 'all', report '<rank>/<size>' of learners 1..n.
CREATE FUNCTION pg_temp.add_and_probe(p_cohort uuid, p_n int) RETURNS text LANGUAGE plpgsql AS $fn$
BEGIN
    PERFORM leaderboard.enroll(p_cohort, pg_temp.uid(p_n));
    PERFORM leaderboard.refresh_snapshot(p_cohort, 'all');
    RETURN (SELECT string_agg(pg_temp.rs(pg_temp.uid(i), 'all'), ' ' ORDER BY i) FROM generate_series(1, p_n) i);
END;
$fn$;

INSERT INTO auth.users (instance_id, id, aud, role, email)
SELECT '00000000-0000-0000-0000-000000000000', pg_temp.uid(n), 'authenticated', 'authenticated', 't210.' || n || '@edupreneur.test'
FROM generate_series(1, 9) n;
INSERT INTO app.learner_profiles (user_id) SELECT pg_temp.uid(n) FROM generate_series(1, 9) n;
INSERT INTO leaderboard.cohorts (id, kind, code) VALUES
    ('3c000000-0000-4000-8000-000000000001', 'class', 'synthetic-k-1'),
    ('3c000000-0000-4000-8000-000000000002', 'class', 'synthetic-k-2');
SET LOCAL session_replication_role = replica;
-- Learner n has 5n Gold, all-time.
SELECT pg_temp.give(pg_temp.uid(n), 5 * n, timestamptz '2026-02-10 12:00+00', 'lbtest_' || n) FROM generate_series(1, 9) n;

SET LOCAL session_replication_role = origin;

-- ---- the setting -------------------------------------------------------------------------
SELECT is((SELECT min_cohort_size FROM leaderboard.config), 5, 'the default minimum cohort size is 5');
SELECT is((SELECT count(*)::int FROM leaderboard.config), 1, 'exactly one settings row');
SELECT throws_ok($$UPDATE leaderboard.config SET min_cohort_size = 0$$, '23514', NULL, 'K cannot be 0 (no way to switch the floor off)');
SELECT throws_ok($$INSERT INTO leaderboard.config (singleton) VALUES (false)$$, '23514', NULL, 'a second settings row cannot exist');
SELECT is(pg_temp.as_role('edu_api', pg_temp.uid(1), 'SELECT min_cohort_size FROM leaderboard.config'), 'ERROR:42501', 'edu_api cannot read the setting');
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants WHERE table_schema = 'leaderboard' AND table_name = 'config'
             AND grantee <> 'postgres'), 0, 'nobody but the owner holds a privilege on the setting');
SELECT is((SELECT relrowsecurity FROM pg_class WHERE oid = 'leaderboard.config'::regclass), true, 'RLS is on for the setting');

-- ---- LB-1: cohorts of 1..4 give no rank and no size, even though the caller keeps own Gold ------
SELECT is(pg_temp.add_and_probe('3c000000-0000-4000-8000-000000000001', 1), 'null/null', 'cohort of 1: no rank, no size');
SELECT is(pg_temp.add_and_probe('3c000000-0000-4000-8000-000000000001', 2), 'null/null null/null', 'cohort of 2: no rank, no size');
SELECT is(pg_temp.add_and_probe('3c000000-0000-4000-8000-000000000001', 3), 'null/null null/null null/null', 'cohort of 3: no rank, no size');
SELECT is(pg_temp.add_and_probe('3c000000-0000-4000-8000-000000000001', 4), 'null/null null/null null/null null/null', 'cohort of 4: no rank, no size');
SELECT is(pg_temp.me(pg_temp.uid(2), 'all', 'gold'), '10', 'below K the caller still gets the own Gold');
SELECT is(pg_temp.me(pg_temp.uid(2), 'all', 'cohort.pseudonym') <> 'null', true, '... and the own pseudonym');
SELECT is((SELECT count(*)::int FROM leaderboard.snapshots WHERE cohort_id = '3c000000-0000-4000-8000-000000000001'), 0,
    'the refresh itself wrote no ranked row for a cohort below K');
SELECT is((SELECT member_count FROM leaderboard.snapshot_runs WHERE cohort_id = '3c000000-0000-4000-8000-000000000001' AND period_key = 'all'), 0,
    '... and no size');
SELECT is((leaderboard.refresh_snapshot('3c000000-0000-4000-8000-000000000001', 'all') ->> 'minimum_cohort_size')::int, 5, 'the refresh reports the floor it applied');

-- ---- the K boundary ------------------------------------------------------------------------------
SELECT is(pg_temp.add_and_probe('3c000000-0000-4000-8000-000000000001', 5), '5/5 4/5 3/5 2/5 1/5', 'cohort of exactly 5: ranks and size appear');

-- ---- LB-1: another member's opt-out is NOT observable before the next refresh -----------------------
SELECT is(leaderboard.withdraw('3c000000-0000-4000-8000-000000000001', pg_temp.uid(5)), true, 'the leader (5) opts out');
SELECT is(pg_temp.rs(pg_temp.uid(1), 'all') || ' ' || pg_temp.rs(pg_temp.uid(4), 'all'), '5/5 2/5',
    'the others'' rank AND size are unchanged (no live re-rank, no size drop)');
SELECT is(pg_temp.me(pg_temp.uid(5), 'all', 'cohort') || '|' || pg_temp.me(pg_temp.uid(5), 'all', 'gold'), 'null|25',
    'the withdrawn learner gets no cohort fields at once, only own Gold');
SELECT is((SELECT count(*)::int FROM leaderboard.snapshots WHERE learner_id = pg_temp.uid(5)), 0, 'and their own snapshot row is gone');
SELECT is(pg_temp.rs(pg_temp.uid(1), 'all'), '5/5', 'still unchanged for the others');
SELECT is((leaderboard.refresh_snapshot('3c000000-0000-4000-8000-000000000001', 'all') ->> 'members')::int, 0, 'refresh: 4 left, below K');
SELECT is(pg_temp.rs(pg_temp.uid(1), 'all') || ' ' || pg_temp.rs(pg_temp.uid(4), 'all'), 'null/null null/null', 'after the refresh the cohort of 4 shows nothing');
SELECT is(left(leaderboard.enroll('3c000000-0000-4000-8000-000000000001', pg_temp.uid(5))::text, 1), '{', 'the leader opts in again');
SELECT is(pg_temp.rs(pg_temp.uid(1), 'all'), 'null/null', 'an opt-in is not observable before the refresh either');
SELECT is((leaderboard.refresh_snapshot('3c000000-0000-4000-8000-000000000001', 'all') ->> 'members')::int, 5, 'refresh: 5 again');
SELECT is(pg_temp.rs(pg_temp.uid(1), 'all'), '5/5', 'ranks are back');

-- A staff grant on another member and an erasure are equally invisible until a refresh.
INSERT INTO app.staff_roles (user_id, role) VALUES (pg_temp.uid(3), 'reviewer');
SELECT is(pg_temp.rs(pg_temp.uid(1), 'all') || ' ' || pg_temp.me(pg_temp.uid(3), 'all', 'cohort'), '5/5 null',
    'another member becoming staff does not change the others'' answer; the staff member''s own standing is gone');
DELETE FROM app.staff_roles WHERE user_id = pg_temp.uid(3);

-- ---- K is enforced at READ time too (fail closed when the owner raises it) ------------------------------
UPDATE leaderboard.config SET min_cohort_size = 6;
SELECT is(pg_temp.rs(pg_temp.uid(1), 'all'), 'null/null', 'K raised above the snapshot size: the read shows nothing, without a refresh');
SELECT is(pg_temp.me(pg_temp.uid(1), 'all', 'cohort.snapshot_gold'), '5', 'the caller''s own snapshot Gold is still its own');
UPDATE leaderboard.config SET min_cohort_size = 5;
SELECT is(pg_temp.rs(pg_temp.uid(1), 'all'), '5/5', 'K back to 5');

-- ---- LB-6: the score uses an allow-list of source kinds ----------------------------------------------------
SELECT is(pg_get_functiondef('leaderboard.period_gold(uuid,date,date)'::regprocedure) ~ 'source_kind IN \(''question_first_correct'', ''lesson_first_completed'', ''achievement'', ''reversal''\)', true,
    'period_gold counts an allow-list of source kinds');
SELECT is(pg_get_functiondef('leaderboard.period_gold(uuid,date,date)'::regprocedure) ~ '<> ''adjustment''', false, '... and no deny-list');
SELECT is(pg_get_functiondef('leaderboard.refresh_snapshot(uuid,text)'::regprocedure) ~ 'source_kind IN \(''question_first_correct'', ''lesson_first_completed'', ''achievement'', ''reversal''\)', true,
    'so does the set-based refresh');

-- ---- LB-5: Haiti week boundaries from explicit instants (no wall clock) -----------------------------------------
UPDATE leaderboard.config SET min_cohort_size = 1;
-- Instants given as Port-au-Prince local time. 2026-03-08 and 2026-11-01 are the DST change Sundays.
SELECT is(rewards.haiti_day(timestamp '2026-03-08 23:59:59' AT TIME ZONE 'America/Port-au-Prince')::text, '2026-03-08', 'Sunday 23:59:59 (DST start) is still Sunday');
SELECT is(rewards.haiti_day(timestamp '2026-03-09 00:00:00' AT TIME ZONE 'America/Port-au-Prince')::text, '2026-03-09', 'Monday 00:00:00 (after DST start) is Monday');
SELECT is(rewards.haiti_day(timestamp '2026-11-01 23:59:59' AT TIME ZONE 'America/Port-au-Prince')::text, '2026-11-01', 'Sunday 23:59:59 (DST end) is still Sunday');
SELECT is(rewards.haiti_day(timestamp '2026-11-02 00:00:00' AT TIME ZONE 'America/Port-au-Prince')::text, '2026-11-02', 'Monday 00:00:00 (after DST end) is Monday');
SELECT is(rewards.haiti_day(timestamptz '2026-03-09 03:59:59+00')::text || rewards.haiti_day(timestamptz '2026-03-09 04:00:00+00')::text, '2026-03-082026-03-09',
    'UTC 03:59:59 / 04:00:00 straddle Haiti midnight in the DST-start week (UTC-4)');
SELECT is(rewards.haiti_day(timestamptz '2026-11-02 04:59:59+00')::text || rewards.haiti_day(timestamptz '2026-11-02 05:00:00+00')::text, '2026-11-012026-11-02',
    'UTC 04:59:59 / 05:00:00 straddle Haiti midnight after DST end (UTC-5)');
SET LOCAL session_replication_role = replica;
-- Learner 6: 1 Gold-unit marks per boundary instant (amounts 1, 2, 4, 8 = Sun, Mon, Sun, Mon).
SELECT pg_temp.give(pg_temp.uid(6), 1, timestamp '2026-03-08 23:59:59' AT TIME ZONE 'America/Port-au-Prince', 'lbtest_b1');
SELECT pg_temp.give(pg_temp.uid(6), 2, timestamp '2026-03-09 00:00:00' AT TIME ZONE 'America/Port-au-Prince', 'lbtest_b2');
SELECT pg_temp.give(pg_temp.uid(6), 4, timestamp '2026-11-01 23:59:59' AT TIME ZONE 'America/Port-au-Prince', 'lbtest_b3');
SELECT pg_temp.give(pg_temp.uid(6), 8, timestamp '2026-11-02 00:00:00' AT TIME ZONE 'America/Port-au-Prince', 'lbtest_b4');
SET LOCAL session_replication_role = origin;
SELECT is(leaderboard.period_gold(pg_temp.uid(6), DATE '2026-03-02', DATE '2026-03-08'), 1::bigint, 'DST-start week (Mon 03-02): Sunday 23:59:59 counts, Monday does not');
SELECT is(leaderboard.period_gold(pg_temp.uid(6), DATE '2026-03-09', DATE '2026-03-15'), 2::bigint, 'the next week starts with Monday 00:00:00');
SELECT is(leaderboard.period_gold(pg_temp.uid(6), DATE '2026-10-26', DATE '2026-11-01'), 4::bigint, 'DST-end week (Mon 10-26): Sunday 23:59:59 counts, Monday does not');
SELECT is(leaderboard.period_gold(pg_temp.uid(6), DATE '2026-11-02', DATE '2026-11-08'), 8::bigint, 'the next week starts with Monday 00:00:00');
SELECT leaderboard.enroll('3c000000-0000-4000-8000-000000000002', pg_temp.uid(6));
SELECT leaderboard.refresh_snapshot('3c000000-0000-4000-8000-000000000002', p) FROM unnest(ARRAY['2026-03-02','2026-03-09','2026-10-26','2026-11-02']) p;
SELECT is((SELECT string_agg(period_key || '=' || gold, ' ' ORDER BY period_key) FROM leaderboard.snapshots
           WHERE learner_id = pg_temp.uid(6) AND period_key <> 'all'),
    '2026-03-02=1 2026-03-09=2 2026-10-26=4 2026-11-02=8', 'the snapshots of the four weeks hold exactly the right Sundays and Mondays');

-- ---- LB-7: a closed period shows the FROZEN Gold, not the live sum -----------------------------------------------
SELECT is(pg_temp.me(pg_temp.uid(6), '2026-03-02', 'closed') || '|' || pg_temp.me(pg_temp.uid(6), '2026-03-02', 'cohort.frozen'), 'true|true', 'the old week is closed and frozen');
SET LOCAL session_replication_role = replica;
SELECT pg_temp.give(pg_temp.uid(6), 50, timestamptz '2026-03-04 15:00+00', 'lbtest_late');
SET LOCAL session_replication_role = origin;
SELECT is(leaderboard.period_gold(pg_temp.uid(6), DATE '2026-03-02', DATE '2026-03-08'), 51::bigint, 'a late ledger row lands in the closed week (live sum 51)');
SELECT is(pg_temp.me(pg_temp.uid(6), '2026-03-02', 'gold') || '|' || pg_temp.me(pg_temp.uid(6), '2026-03-02', 'cohort.snapshot_gold'), '1|1',
    'the answer carries the frozen snapshot Gold (1), not the live sum');
SELECT is(pg_temp.me(pg_temp.uid(6), 'all', 'gold'), '95', 'an open period (all-time) is still the live sum');

SELECT * FROM finish();
ROLLBACK;
