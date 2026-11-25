-- Ranking rules: computed from the ledger only, ties, exclusions, clamping,
-- recomputation, immediate opt-out / erasure, isolation, frozen closed weeks.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api, edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
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
-- One pushed answer, exactly as the API does it: apply, then ask for the award.
CREATE FUNCTION pg_temp.answer(p_actor uuid, p_n integer, p_choice text, p_op uuid DEFAULT gen_random_uuid(),
                               p_award boolean DEFAULT true)
RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.as_role('edu_api', p_actor, format(
        $q$WITH s AS MATERIALIZED (
               SELECT app.sync_apply_operation(%L, 'practice_answer', %L::jsonb, sha256(convert_to(%L, 'UTF8')), 'mep-canon-1') AS o)
           SELECT (s.o ->> 'status') || CASE WHEN %L::boolean THEN
                      (SELECT '/' || (a.o ->> 'status') FROM (SELECT rewards.award_for_operation(%L) AS o) a)
                  ELSE '' END
           FROM s$q$,
        p_op,
        jsonb_build_object('question_revision_id', 'd0000000-0000-4000-8000-00000000010' || p_n,
                           'response', jsonb_build_object('choice_id', p_choice))::text,
        p_n::text || p_choice, p_award, p_op))
$fn$;
-- The caller's own view, through the one function the API may call.
CREATE FUNCTION pg_temp.me(p_actor uuid, p_period text, p_path text) RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.as_role('edu_api', p_actor,
        format('SELECT COALESCE(leaderboard.my_standing(%L) #>> %L, ''null'')', p_period, string_to_array(p_path, '.')))
$fn$;
-- '<rank>/<size>/<snapshot gold>' of the caller.
CREATE FUNCTION pg_temp.standing(p_actor uuid, p_period text) RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.me(p_actor, p_period, 'cohort.rank') || '/' || pg_temp.me(p_actor, p_period, 'cohort.size')
           || '/' || pg_temp.me(p_actor, p_period, 'cohort.snapshot_gold')
$fn$;
CREATE FUNCTION pg_temp.snapshot_state(p_cohort uuid, p_period text) RETURNS text LANGUAGE sql AS $fn$
    SELECT string_agg(right(learner_id::text, 2) || ':' || gold || ':' || rank || ':' || tie_order, ' ' ORDER BY tie_order)
    FROM leaderboard.snapshots WHERE cohort_id = p_cohort AND period_key = p_period
$fn$;

TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;
TRUNCATE rewards.achievement_awards, rewards.ledger, rewards.processed_operations,
         rewards.activity_days, rewards.streak_state, rewards.balances;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set C '''a0000000-0000-4000-8000-0000000002c3'''
\set D '''a0000000-0000-4000-8000-0000000002d4'''
\set E '''a0000000-0000-4000-8000-0000000002e5'''
\set F '''a0000000-0000-4000-8000-0000000002f6'''
\set S '''a0000000-0000-4000-8000-0000000002a7'''
\set G '''a0000000-0000-4000-8000-0000000002b8'''
\set ADMIN '''a0000000-0000-4000-8000-0000000002a9'''
\set GONE '''a0000000-0000-4000-8000-0000000002aa'''
\set K1 '''1b000000-0000-4000-8000-000000000001'''
\set K2 '''1b000000-0000-4000-8000-000000000002'''

INSERT INTO auth.users (instance_id, id, aud, role, email)
SELECT '00000000-0000-0000-0000-000000000000', id, 'authenticated', 'authenticated', 't205.' || right(id::text, 2) || '@edupreneur.test'
FROM unnest(ARRAY[:C, :D, :E, :F, :S, :G, :ADMIN, :GONE]::uuid[]) AS u(id);
INSERT INTO app.learner_profiles (user_id)
SELECT id FROM unnest(ARRAY[:C, :D, :E, :F, :S, :G, :ADMIN, :GONE]::uuid[]) AS u(id);
INSERT INTO app.staff_roles (user_id, role) VALUES (:ADMIN, 'admin');
INSERT INTO leaderboard.cohorts (id, kind, code) VALUES (:K1, 'class', 'synthetic-class-1'), (:K2, 'school', 'synthetic-school-2');
SELECT is((SELECT (starts_on - 14)::text FROM leaderboard.resolve_period('week')) IS NOT NULL, true, 'setup: the current week resolves');
CREATE TEMP TABLE wk AS SELECT to_char(starts_on - 14, 'YYYY-MM-DD') AS old_week, period_key AS this_week
                        FROM leaderboard.resolve_period('week');

-- ---- Gold, earned the real way ---------------------------------------------------
-- A 15, B 10, C 10, D (see below), E 0, F 5, S 20, G 5, GONE 5
SELECT is(pg_temp.answer(:A, 1, 'b') || pg_temp.answer(:A, 2, 'a') || pg_temp.answer(:A, 3, 'c'),
    'accepted/awardedaccepted/awardedaccepted/awarded', 'A earns 15');
SELECT is(pg_temp.answer(:B, 1, 'b') || pg_temp.answer(:B, 2, 'a'), 'accepted/awardedaccepted/awarded', 'B earns 10');
SELECT is(pg_temp.answer(:C, 1, 'b') || pg_temp.answer(:C, 2, 'a'), 'accepted/awardedaccepted/awarded', 'C earns 10');
SELECT is(pg_temp.answer(:F, 1, 'b'), 'accepted/awarded', 'F earns 5');
SELECT is(pg_temp.answer(:G, 1, 'b'), 'accepted/awarded', 'G earns 5');
SELECT is(pg_temp.answer(:GONE, 1, 'b'), 'accepted/awarded', 'GONE earns 5');
SELECT is(pg_temp.answer(:S, 1, 'b') || pg_temp.answer(:S, 2, 'a') || pg_temp.answer(:S, 3, 'c') || pg_temp.answer(:S, 4, 'd'),
    'accepted/awardedaccepted/awardedaccepted/awardedaccepted/awarded', 'S (future staff) earns 20');
-- D: one answer accepted 14 days ago (test-only arrangement: the receipt instant
-- is moved back BEFORE the award is computed, so the ledger row is dated then).
SELECT is(pg_temp.answer(:D, 1, 'b', '1d000000-0000-4000-8000-000000000001', false), 'accepted', 'D answers (award not computed yet)');
SET LOCAL session_replication_role = replica;
UPDATE app.sync_receipts SET created_at = created_at - interval '14 days' WHERE op_id = '1d000000-0000-4000-8000-000000000001';
SET LOCAL session_replication_role = origin;
SELECT is(pg_temp.as_role('edu_api', :D, $$SELECT rewards.award_for_operation('1d000000-0000-4000-8000-000000000001') ->> 'status'$$),
    'awarded', 'D''s old operation is healed and awarded');
SELECT is((SELECT accepted_day FROM rewards.ledger WHERE learner_id = :D::uuid),
    (SELECT starts_on - 14 + (rewards.haiti_day(now()) - starts_on) FROM leaderboard.resolve_period('week')),
    'D''s Gold is dated 14 days ago');

-- ---- before anyone opts in ----------------------------------------------------------
SELECT is(pg_temp.me(:A, 'week', 'gold'), '15', 'not a member: own Gold for the week is shown');
SELECT is(pg_temp.me(:A, 'week', 'cohort'), 'null', 'not a member: no cohort, no rank, no size');
SELECT is(pg_temp.me(:E, 'all', 'gold'), '0', 'no ledger row: Gold is 0');
SELECT is(pg_temp.as_role('edu_api', NULL, $$SELECT leaderboard.my_standing('week')$$), 'ERROR:42501', 'no actor: refused');
SELECT is(pg_temp.as_role('edu_api', :A, $$SELECT leaderboard.my_standing('nonsense')$$), 'ERROR:22023', 'an unknown period is refused');
SELECT is(pg_temp.as_role('edu_api', :A, $$SELECT (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(leaderboard.my_standing('week')) k)$$),
    'closed,cohort,ends_on,gold,kind,period,starts_on', 'the answer has exactly the documented keys');

-- ---- edu_api reaches nothing but its own standing -------------------------------------
SELECT is(pg_temp.as_role('edu_api', :A, 'SELECT count(*) FROM leaderboard.snapshots'), 'ERROR:42501', 'edu_api cannot read snapshots');
SELECT is(pg_temp.as_role('edu_api', :A, 'SELECT count(*) FROM leaderboard.memberships'), 'ERROR:42501', 'edu_api cannot read memberships');
SELECT is(pg_temp.as_role('edu_api', :A, 'SELECT count(*) FROM leaderboard.cohorts'), 'ERROR:42501', 'edu_api cannot list cohorts');
SELECT is(pg_temp.as_role('edu_api', :A, 'SELECT count(*) FROM leaderboard.pseudonym_pool'), 'ERROR:42501', 'edu_api cannot read the pseudonym pool');
SELECT is(pg_temp.as_role('edu_api', :A, format('SELECT leaderboard.enroll(%L, %L)', :K1, :A)), 'ERROR:42501', 'edu_api cannot enroll anyone');
SELECT is(pg_temp.as_role('edu_api', :A, format('SELECT leaderboard.refresh_snapshot(%L, %L)', :K1, 'week')), 'ERROR:42501', 'edu_api cannot refresh');
SELECT is(pg_temp.as_role('edu_api', :A, format('SELECT leaderboard.erase_learner(%L)', :B)), 'ERROR:42501', 'edu_api cannot erase');
SELECT is(pg_temp.as_role('edu_api', :A, format('SELECT leaderboard.period_gold(%L, NULL, NULL)', :B)), 'ERROR:42501', 'edu_api cannot ask for someone else''s Gold');
SELECT is(pg_temp.as_role('edu_api', :A, format('SELECT count(*) FROM leaderboard.visible_rows(%L, %L)', :K1, 'all')), 'ERROR:42501', 'edu_api cannot list a cohort');

-- ---- opt-in: pseudonyms come from the server ------------------------------------------
SELECT is(left(leaderboard.enroll(:K1, :A)::text, 1), '{', 'A opts in');
SELECT lives_ok(format('SELECT leaderboard.enroll(%L, u) FROM unnest(ARRAY[%L,%L,%L,%L,%L,%L,%L]::uuid[]) u', :K1, :B, :C, :D, :E, :F, :S, :GONE), 'B, C, D, E, F, S, GONE opt in');
SELECT lives_ok(format('SELECT leaderboard.enroll(%L, %L)', :K2, :G), 'G opts in to the other cohort');
SELECT is((SELECT count(*)::int FROM leaderboard.memberships m JOIN leaderboard.pseudonym_pool p ON p.id = m.pseudonym_id WHERE m.cohort_id = :K1), 8,
    'every member has a pseudonym from the allow-list');
SELECT is((SELECT count(DISTINCT leaderboard.display_pseudonym(pseudonym_id, pseudonym_suffix))::int FROM leaderboard.memberships WHERE cohort_id = :K1), 8,
    'pseudonyms are unique within the cohort');
SELECT is((SELECT leaderboard.enroll(:K1, :A) ->> 'pseudonym'),
    (SELECT leaderboard.display_pseudonym(pseudonym_id, pseudonym_suffix) FROM leaderboard.memberships WHERE cohort_id = :K1 AND learner_id = :A),
    'opting in twice is idempotent and keeps the pseudonym');
SELECT throws_ok(format('SELECT leaderboard.enroll(%L, %L)', :K2, :A), '23505', NULL, 'a learner cannot be an active member of two cohorts');
SELECT throws_ok(format('SELECT leaderboard.enroll(%L, %L)', :K1, :ADMIN), '22023', 'Account cannot join a cohort', 'a staff account cannot opt in');
SELECT throws_ok(format('SELECT leaderboard.enroll(%L, %L)', :K1, gen_random_uuid()), '22023', 'Account cannot join a cohort', 'an unknown account cannot opt in');
SELECT throws_ok(format('SELECT leaderboard.enroll(%L, %L)', gen_random_uuid(), :A), '22023', 'Unknown cohort', 'an unknown cohort cannot be joined');
SELECT is(pg_temp.me(:A, 'week', 'cohort.rank'), 'null', 'opted in, but no snapshot yet: no rank is invented');
SELECT is(pg_temp.me(:A, 'week', 'cohort.computed_at'), 'null', '... and the missing snapshot is visible as computed_at = null');
SELECT is(pg_temp.me(:A, 'week', 'cohort.pseudonym'),
    (SELECT leaderboard.display_pseudonym(pseudonym_id, pseudonym_suffix) FROM leaderboard.memberships WHERE learner_id = :A),
    'the caller sees its own pseudonym');

-- S becomes staff and GONE's auth account is soft-deleted AFTER opting in; F opts out.
INSERT INTO app.staff_roles (user_id, role, is_active) VALUES (:S, 'editor', false);
UPDATE auth.users SET deleted_at = now() WHERE id = :GONE;
SELECT is(leaderboard.withdraw(:K1, :F), true, 'F opts out');

-- ---- refresh: ranks, ties, exclusions ---------------------------------------------------
SELECT is((leaderboard.refresh_snapshot(:K1, 'week') ->> 'members')::int, 5, 'the snapshot holds the 5 rankable opted-in members (not F, S, GONE)');
SELECT is((leaderboard.refresh_snapshot(:K1, 'all') ->> 'members')::int, 5, 'the all-time snapshot too');
SELECT is((SELECT count(*)::int FROM leaderboard.snapshots WHERE learner_id IN (:S, :F, :GONE, :ADMIN)), 0,
    'a staff account (even an inactive role), an opted-out learner and a deleted account are never in a snapshot');
SELECT is((SELECT string_agg(right(learner_id::text, 2) || '=' || gold || '#' || rank, ' ' ORDER BY rank, right(learner_id::text, 2))
           FROM leaderboard.snapshots WHERE cohort_id = :K1 AND period_key = 'all'),
    '01=15#1 02=10#2 c3=10#2 d4=5#4 e5=0#5', 'all-time: competition ranking 1, 2, 2, 4, 5');
SELECT is((SELECT string_agg(right(learner_id::text, 2) || '=' || gold || '#' || rank, ' ' ORDER BY rank, right(learner_id::text, 2))
           FROM leaderboard.snapshots WHERE cohort_id = :K1 AND period_key = (SELECT this_week FROM wk)),
    '01=15#1 02=10#2 c3=10#2 d4=0#4 e5=0#4', 'this week: D''s Gold from 14 days ago does not count');
SELECT is((SELECT array_agg(tie_order ORDER BY tie_order) FROM leaderboard.snapshots WHERE cohort_id = :K1 AND period_key = 'all'),
    ARRAY[1,2,3,4,5], 'the display order is a gap-free 1..n');
SELECT is((SELECT array_agg(learner_id ORDER BY tie_order) FROM leaderboard.snapshots
           WHERE cohort_id = :K1 AND period_key = 'all' AND gold = 10),
    (SELECT array_agg(u ORDER BY sha256(convert_to(:K1 || ':all:' || u::text, 'UTF8'))) FROM unnest(ARRAY[:B, :C]::uuid[]) u),
    'inside a tie the order follows a hash of (cohort, period, learner): deterministic, not an identity or a name');
SELECT is(pg_temp.standing(:A, 'all'), '1/5/15', 'A: rank 1 of 5');
SELECT is(pg_temp.standing(:B, 'all'), '2/5/10', 'B: rank 2 of 5');
SELECT is(pg_temp.standing(:C, 'all'), '2/5/10', 'C: the same rank 2 (tie)');
SELECT is(pg_temp.standing(:D, 'all'), '4/5/5', 'D: rank 4 (3 is skipped after a tie)');
SELECT is(pg_temp.standing(:E, 'week'), '4/5/0', 'E: 0 Gold ties with D this week');
SELECT is(pg_temp.me(:S, 'all', 'cohort') || '|' || pg_temp.me(:S, 'all', 'gold'), 'null|20', 'a staff account sees its own Gold but never a cohort or rank');
SELECT is(pg_temp.me(:F, 'all', 'cohort') || '|' || pg_temp.me(:F, 'all', 'gold'), 'null|5', 'an opted-out learner sees own Gold only');
SELECT is(pg_temp.me(:ADMIN, 'all', 'cohort'), 'null', 'an admin has no standing');

-- The review fixes (210_) test the minimum cohort size K; from here on this file
-- exercises ranking on cohorts of 1 to 6, so K is lowered to 1 (rolled back at the end).
UPDATE leaderboard.config SET min_cohort_size = 1;

-- ---- cross-cohort isolation -----------------------------------------------------------
SELECT is((leaderboard.refresh_snapshot(:K2, 'all') ->> 'members')::int, 1, 'the other cohort has its own snapshot');
SELECT is(pg_temp.standing(:G, 'all'), '1/1/5', 'G is ranked only inside its own cohort (size 1)');
SELECT is(pg_temp.me(:G, 'all', 'cohort.cohort_id'), '1b000000-0000-4000-8000-000000000002',
    'G''s standing names its own cohort only');
SELECT is(pg_temp.standing(:A, 'all'), '1/5/15', 'cohort 1 is unaffected by cohort 2');

-- ---- recomputation equality; duplicates do not move a rank ------------------------------
CREATE TEMP TABLE before_all AS SELECT pg_temp.snapshot_state(:K1, 'all') AS s;
SELECT is((leaderboard.refresh_snapshot(:K1, 'all') ->> 'recomputed'), 'true', 'refresh again');
SELECT is(pg_temp.snapshot_state(:K1, 'all'), (SELECT s FROM before_all), 'recomputation rebuilds exactly the same rows');
SELECT is(pg_temp.answer(:B, 1, 'b') || '|' || pg_temp.answer(:B, 2, 'a') || '|' || pg_temp.answer(:D, 1, 'b'),
    'accepted/duplicate|accepted/duplicate|accepted/duplicate', 'B and D re-send answers already rewarded (new op ids)');
SELECT lives_ok(format('SELECT leaderboard.refresh_snapshot(%L, %L)', :K1, 'all'), 'refresh after the duplicates');
SELECT is(pg_temp.snapshot_state(:K1, 'all'), (SELECT s FROM before_all), 'duplicated events move no score and no rank');

-- ---- staleness is honest -------------------------------------------------------------
SELECT is(pg_temp.answer(:E, 1, 'b') || pg_temp.answer(:E, 2, 'a') || pg_temp.answer(:E, 3, 'c') || pg_temp.answer(:E, 4, 'd'),
    'accepted/awardedaccepted/awardedaccepted/awardedaccepted/awarded', 'E earns 20 after the snapshot');
SELECT is(pg_temp.me(:E, 'all', 'gold') || '|' || pg_temp.standing(:E, 'all'), '20|5/5/0',
    'own Gold is live (20); the rank still comes from the snapshot, with its snapshot_gold (0)');
SELECT is(pg_temp.me(:E, 'all', 'cohort.computed_at') <> 'null', true, '... and computed_at says when that snapshot was taken');
SELECT lives_ok(format('SELECT leaderboard.refresh_snapshot(%L, %L)', :K1, 'all'), 'refresh');
SELECT is(pg_temp.standing(:E, 'all') || '|' || pg_temp.standing(:A, 'all'), '1/5/20|2/5/15', 'after the refresh E is first and A second');

-- ---- staff adjustments do not count -----------------------------------------------------
SELECT is(left(pg_temp.as_role('edu_staff', :ADMIN, format('SELECT rewards.staff_adjust(%L, 100, %L, gen_random_uuid())', :B, 'support_goodwill')), 1), '{',
    'an admin credits B 100 Gold (audited adjustment)');
SELECT is((SELECT balance::int FROM rewards.balances WHERE learner_id = :B::uuid), 110, 'B''s balance includes the adjustment');
SELECT lives_ok(format('SELECT leaderboard.refresh_snapshot(%L, %L)', :K1, 'all'), 'refresh');
SELECT is(pg_temp.me(:B, 'all', 'gold') || '|' || pg_temp.standing(:B, 'all'), '10|3/5/10', 'an adjustment is not Gold earned by learning: score and rank unchanged');

-- ---- reversals; a negative period sum is clamped ------------------------------------------
SELECT isnt(rewards.reverse_entry((SELECT id FROM rewards.ledger WHERE learner_id = :A::uuid AND question_key = 'addition'), 'scoring_error'), NULL,
    'one of A''s awards is reversed');
SELECT isnt(rewards.reverse_entry((SELECT id FROM rewards.ledger WHERE learner_id = :D::uuid), 'scoring_error'), NULL,
    'D''s award of 14 days ago is reversed TODAY');
SELECT is((SELECT sum(amount)::int FROM rewards.ledger WHERE learner_id = :D::uuid AND accepted_day >= (SELECT starts_on FROM leaderboard.resolve_period('week'))), -5,
    'D''s raw ledger sum for this week is negative');
SELECT lives_ok(format('SELECT leaderboard.refresh_snapshot(%L, p) FROM unnest(ARRAY[%L, %L]) p', :K1, 'all', 'week'), 'refresh both periods');
SELECT is(pg_temp.me(:D, 'week', 'gold') || '|' || pg_temp.me(:D, 'week', 'cohort.snapshot_gold'), '0|0', 'a negative week is shown as 0, never below');
SELECT is(pg_temp.me(:D, 'all', 'gold'), '0', 'all-time: the award and its reversal cancel out');
SELECT is(pg_temp.standing(:A, 'all') || '|' || pg_temp.standing(:C, 'all') || '|' || pg_temp.standing(:B, 'all'), '2/5/10|2/5/10|2/5/10',
    'after the reversal A, B and C tie at 10: all rank 2');
SELECT is((SELECT min(gold)::int FROM leaderboard.snapshots), 0, 'no snapshot row is negative');

-- ---- a closed week is computed once and frozen ---------------------------------------------
SELECT is((SELECT leaderboard.refresh_snapshot(:K1, old_week) ->> 'frozen' FROM wk), 'true', 'the week of 14 days ago is closed: its snapshot is the closing one');
SELECT is((SELECT gold::int FROM leaderboard.snapshots, wk WHERE period_key = old_week AND learner_id = :D), 5,
    'the old week keeps D''s 5 Gold: a reversal is dated the day it is made');
CREATE TEMP TABLE frozen AS SELECT pg_temp.snapshot_state(:K1, old_week) AS s,
    (SELECT computed_at FROM leaderboard.snapshot_runs r WHERE r.period_key = old_week AND r.cohort_id = :K1) AS at FROM wk;
SELECT lives_ok(format('SELECT leaderboard.enroll(%L, %L)', :K1, :F), 'F opts in again after the closing snapshot');
SELECT is((SELECT leaderboard.refresh_snapshot(:K1, old_week) ->> 'recomputed' FROM wk), 'false', 'refreshing a frozen period recomputes nothing');
SELECT is((SELECT pg_temp.snapshot_state(:K1, old_week) FROM wk), (SELECT s FROM frozen), 'the frozen rows are unchanged');
SELECT is((SELECT r.computed_at FROM leaderboard.snapshot_runs r, wk WHERE r.period_key = old_week AND r.cohort_id = :K1), (SELECT at FROM frozen),
    'and so is its computed_at');
SELECT is((SELECT pg_temp.me(:D, old_week, 'cohort.frozen') || '|' || pg_temp.me(:D, old_week, 'closed') FROM wk), 'true|true', 'the reader is told the period is closed and frozen');
SELECT is((SELECT pg_temp.me(:F, old_week, 'cohort.rank') FROM wk), 'null', 'a member who joined after the closing snapshot has no rank in it');

-- ---- opt-out is immediate (no refresh) -----------------------------------------------------
SELECT lives_ok(format('SELECT leaderboard.refresh_snapshot(%L, %L)', :K1, 'all'), 'refresh (F is a member again: 6 members)');
SELECT is(pg_temp.standing(:F, 'all') || '|' || pg_temp.standing(:E, 'all'), '5/6/5|1/6/20', 'F is ranked 5th of 6');
SELECT is(leaderboard.withdraw(:K1, :E), true, 'E (the leader) opts out');
SELECT is(pg_temp.me(:E, 'all', 'cohort') || '|' || pg_temp.me(:E, 'all', 'gold'), 'null|20', 'E: no cohort at once, own Gold still shown');
SELECT is(pg_temp.standing(:A, 'all') || '|' || pg_temp.standing(:F, 'all'), '2/6/10|5/6/5', 'the others keep rank and size of the snapshot until the next refresh (no live re-rank)');
SELECT is((SELECT count(*)::int FROM leaderboard.snapshots WHERE learner_id = :E), 0, 'E''s snapshot rows are gone from every period');
SELECT is((SELECT (opted_out_at IS NOT NULL)::text FROM leaderboard.memberships WHERE learner_id = :E), 'true', 'the consent row records the opt-out instant');
SELECT is(leaderboard.withdraw(:K1, :E), false, 'opting out twice changes nothing');

-- ---- a staff grant is immediate ----------------------------------------------------------------
INSERT INTO app.staff_roles (user_id, role) VALUES (:F, 'reviewer');
SELECT is(pg_temp.me(:F, 'all', 'cohort'), 'null', 'a member who becomes staff loses the standing at once');
SELECT is(pg_temp.standing(:A, 'all'), '2/6/10', 'and the others'' standing stays as of the snapshot until the next refresh');

-- ---- erasure is immediate -------------------------------------------------------------------------
SELECT is(leaderboard.erase_learner(:C)::text, '{"schema": "leaderboard", "deleted": {"snapshots": 3, "memberships": 1}}',
    'the erasure hook reports what it removed');
SELECT is((SELECT count(*)::int FROM leaderboard.snapshots WHERE learner_id = :C) + (SELECT count(*)::int FROM leaderboard.memberships WHERE learner_id = :C), 0,
    'nothing of C is left in the schema');
SELECT is(pg_temp.me(:C, 'all', 'cohort'), 'null', 'C has no standing');
SELECT is(pg_temp.standing(:A, 'all') || '|' || pg_temp.standing(:D, 'all'), '2/6/10|6/6/0', 'the others'' rank and size stay as of the snapshot (erasure is not observable before a refresh)');
SELECT is(leaderboard.erase_learner(:C)::text, '{"schema": "leaderboard", "deleted": {"snapshots": 0, "memberships": 0}}', 'erasing again is a no-op');
SELECT throws_ok('SELECT leaderboard.erase_learner(NULL)', '22023', NULL, 'a NULL learner id is refused');
SELECT lives_ok(format('SELECT rewards.erase_learner(%L)', :C), 'the rewards hook can run after ours (no leaderboard row blocks it)');
SELECT lives_ok(format('SELECT leaderboard.refresh_snapshot(%L, %L)', :K1, 'all'), 'a refresh after erasure works');
SELECT is(pg_temp.snapshot_state(:K1, 'all') ~ 'c3', false, 'and does not bring C back');

-- ---- refresh input checks ---------------------------------------------------------------------------
SELECT throws_ok($$SELECT leaderboard.refresh_snapshot(gen_random_uuid(), 'all')$$, '22023', 'Unknown cohort', 'an unknown cohort cannot be refreshed');
SELECT throws_ok(format('SELECT leaderboard.refresh_snapshot(%L, %L)', :K1, 'global'), '22023', 'Unknown period', 'there is no global period');
SELECT throws_ok($$SELECT leaderboard.refresh_snapshot(NULL, 'all')$$, '22023', NULL, 'there is no cohort-less (global) snapshot');

SELECT * FROM finish();
ROLLBACK;
