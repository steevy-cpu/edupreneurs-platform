-- Onboarding state: own row only, forward-only, monotonic merges, returning-learner rule.
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

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''

-- Exact starting point (rolled back with the transaction; nothing is really removed).
TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;
DELETE FROM account.onboarding_state;
DELETE FROM app.learner_profiles WHERE user_id = :EDITOR::uuid;  -- the API tests may have created it
UPDATE app.learner_profiles SET grade_id = NULL WHERE user_id = :A::uuid;  -- A: no grade; B keeps the seed grade

-- ---- reading ----------------------------------------------------------------------
SELECT is(pg_temp.as_api(NULL, 'SELECT account.get_own_onboarding()'), 'ERROR:42501', 'no actor: read refused');
SELECT is(pg_temp.as_api(NULL, $$SELECT account.advance_onboarding('ready', 1)$$), 'ERROR:42501', 'no actor: write refused');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM account.onboarding_state'), '0', 'no actor: no rows');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT account.get_own_onboarding()')::jsonb,
    '{"state":"new","onboarding_version":0,"tour_version_seen":0,"tour_dismissed":false,"completed_at":null,"updated_at":null}'::jsonb,
    'A (no grade, no work, no row) is new');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT account.get_own_onboarding() ->> 'state'$$), 'profile_selected', 'B already has a grade: at least profile_selected');
SELECT is((SELECT count(*)::int FROM account.onboarding_state), 0, 'reading creates no row');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-0000000000ee', $$SELECT account.advance_onboarding('ready', 1)$$), 'ERROR:42501', 'an actor without a profile cannot write onboarding');

-- ---- forward only -----------------------------------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('profile_selected', 1) ->> 'state'$$), 'profile_selected', 'A: new -> profile_selected');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('downloads_informed', 1) ->> 'state'$$), 'downloads_informed', 'A: -> downloads_informed');
CREATE TEMP TABLE a_mid AS SELECT * FROM account.onboarding_state WHERE user_id = :A::uuid;
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('new', 1) ->> 'state'$$), 'downloads_informed', 'stale "new" is accepted and ignored');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('profile_selected', 1) ->> 'changed'$$), 'false', 'stale "profile_selected" reports changed=false');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('downloads_informed', 1) ->> 'changed'$$), 'false', 'a repeat reports changed=false');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding(NULL, 1) ->> 'state'$$), 'downloads_informed', 'no state reported: unchanged');
SELECT is((SELECT count(*)::int FROM (SELECT * FROM account.onboarding_state WHERE user_id = :A::uuid EXCEPT SELECT * FROM a_mid) d), 0,
    'stale and repeated requests did not touch the row (not even updated_at)');
SELECT is((SELECT completed_at FROM account.onboarding_state WHERE user_id = :A::uuid), NULL, 'not completed yet');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('ready', 1) ->> 'state'$$), 'ready', 'A: -> ready');
SELECT isnt((SELECT completed_at FROM account.onboarding_state WHERE user_id = :A::uuid), NULL, 'completed_at stamped by the server');
CREATE TEMP TABLE a_done AS SELECT * FROM account.onboarding_state WHERE user_id = :A::uuid;

-- ---- version rule -----------------------------------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('new', 5)$$)::jsonb - 'updated_at' - 'completed_at',
    '{"state":"ready","onboarding_version":5,"tour_version_seen":0,"tour_dismissed":false,"changed":true}'::jsonb,
    'a newer app version raises the version and does NOT send a ready learner back');
SELECT is((SELECT completed_at FROM account.onboarding_state WHERE user_id = :A::uuid), (SELECT completed_at FROM a_done), 'completed_at is kept');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('profile_selected', 2) ->> 'onboarding_version'$$), '5', 'an older app cannot lower the version');

-- ---- tour fields ------------------------------------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding(NULL, 1, 3, NULL) ->> 'tour_version_seen'$$), '3', 'tour version recorded');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding(NULL, 1, 1, true) ->> 'tour_version_seen'$$), '3', 'tour version never decreases');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding(NULL, 1, 4, false) ->> 'tour_dismissed'$$), 'true', 'tour_dismissed stays true once set');

-- ---- validation -------------------------------------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('done', 1)$$), 'ERROR:22023', 'unknown state');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('ready', NULL)$$), 'ERROR:22023', 'version required');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('ready', 0)$$), 'ERROR:22023', 'version must be positive');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('ready', 10001)$$), 'ERROR:22023', 'version bounded');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('ready', 1, -1)$$), 'ERROR:22023', 'tour version bounded below');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('ready', 1, 10001)$$), 'ERROR:22023', 'tour version bounded above');

-- ---- isolation --------------------------------------------------------------------
SELECT is(pg_temp.as_api(:B::uuid, 'SELECT count(*) FROM account.onboarding_state'), '0', 'B sees no onboarding row (A has one)');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT count(*) FROM account.onboarding_state WHERE user_id = 'a0000000-0000-4000-8000-000000000001'$$), '0', 'B cannot read A row by id');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT account.advance_onboarding('new', 1) ->> 'state'$$), 'profile_selected', 'B first write merges with what the server knows (has a grade)');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE user_id <> app.current_actor_id()) FROM account.onboarding_state'), '1/0', 'A reads only own row');
SELECT is(pg_temp.as_api(:B::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE user_id <> app.current_actor_id()) FROM account.onboarding_state'), '1/0', 'B reads only own row');
SELECT is((SELECT state || '/' || onboarding_version FROM account.onboarding_state WHERE user_id = :A::uuid), 'ready/5', 'A row unaffected by B');
SELECT is(pg_temp.as_api(:EDITOR::uuid, 'SELECT count(*) FROM account.onboarding_state'), '0', 'a staff user sees no learner onboarding through the student API');

-- ---- no way around the function -----------------------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, $$UPDATE account.onboarding_state SET state = 'new' RETURNING 1$$), 'ERROR:42501', 'A cannot UPDATE onboarding directly');
SELECT is(pg_temp.as_api(:A::uuid, 'DELETE FROM account.onboarding_state RETURNING 1'), 'ERROR:42501', 'A cannot DELETE onboarding');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO account.onboarding_state (user_id, onboarding_version) VALUES ('a0000000-0000-4000-8000-000000000003', 1) RETURNING 1$$), 'ERROR:42501', 'A cannot INSERT onboarding rows');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.onboarding_floor('a0000000-0000-4000-8000-000000000002')$$), 'ERROR:42501', 'A cannot call the internal floor function for another user');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.audit_seam('x.y', 'z', NULL, 'allowed')$$), 'ERROR:42501', 'A cannot call the audit seam');
SELECT throws_ok($$UPDATE account.onboarding_state SET completed_at = now() WHERE state <> 'ready'$$, '23514', NULL, 'completed_at requires state ready (table constraint)');
SELECT throws_ok($$UPDATE account.onboarding_state SET state = 'finished'$$, '23514', NULL, 'state values are constrained');

-- ---- returning learner: accepted work means ready -----------------------------------
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$INSERT INTO app.learner_profiles (user_id) VALUES ('a0000000-0000-4000-8000-000000000003') RETURNING 1$$), '1', 'a third learner profile (first contact)');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$SELECT account.get_own_onboarding() ->> 'state'$$), 'new', 'no grade, no work: new');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$SELECT app.sync_apply_operation('33333333-3333-4333-8333-000000000001','lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000001"}', sha256('e1'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'the learner completes a lesson');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$SELECT account.get_own_onboarding() ->> 'state'$$), 'ready', 'accepted work: reported ready without any onboarding row');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$SELECT account.advance_onboarding('new', 1) ->> 'state'$$), 'ready', 'and stored as ready on the first write');
SELECT isnt((SELECT completed_at FROM account.onboarding_state WHERE user_id = :EDITOR::uuid), NULL, 'completed_at set for the returning learner');

-- ---- onboarding never touches learning data ----------------------------------------
SELECT is((SELECT count(*)::int FROM app.lesson_progress), 1, 'progress row count unchanged by onboarding calls');
SELECT is((SELECT count(*)::int FROM app.sync_receipts), 1, 'receipt count unchanged by onboarding calls');
SELECT is((SELECT count(*)::int FROM app.account_change_feed), 1, 'change feed unchanged by onboarding calls');

-- ---- Data API roles -----------------------------------------------------------------
SET LOCAL ROLE anon;
SELECT throws_ok('SELECT count(*) FROM account.onboarding_state', '42501', NULL, 'anon: schema account is unreachable');
SELECT throws_ok('SELECT account.get_own_onboarding()', '42501', NULL, 'anon: cannot call account functions');
RESET ROLE;
SET LOCAL ROLE authenticated;
SELECT throws_ok('SELECT count(*) FROM account.onboarding_state', '42501', NULL, 'authenticated (Data API): schema account is unreachable');
SELECT throws_ok($$SELECT account.update_own_profile('{"display_name":"x"}')$$, '42501', NULL, 'authenticated (Data API): cannot call update_own_profile');
RESET ROLE;
SET LOCAL ROLE service_role;
SELECT throws_ok('SELECT count(*) FROM account.onboarding_state', '42501', NULL, 'service_role: schema account is unreachable');
RESET ROLE;

SELECT * FROM finish();
ROLLBACK;
