-- Who can read and write what: anonymous, Student A, Student B, staff.
BEGIN;
SELECT * FROM no_plan();
-- Run one statement AS THE STUDENT API ROLE with the given actor, then switch
-- back. Returns the first column of the first row as text, or 'ERROR:<sqlstate>'.
-- A failing statement is rolled back (the inner block is a savepoint).
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

-- Start from empty learner state so counts are exact. This runs inside the
-- test transaction and is rolled back at the end: nothing is really deleted.
TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''

-- Both students create real data through the only write path.
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT app.sync_apply_operation('11111111-1111-4111-8111-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}', sha256('a1'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'A submits an answer');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT app.sync_apply_operation('11111111-1111-4111-8111-000000000002','lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000001"}', sha256('a2'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'A completes the lesson');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT app.sync_apply_operation('22222222-2222-4222-8222-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000201","response":{"choice_id":"a"}}', sha256('b1'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'B submits an answer');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT app.sync_apply_operation('22222222-2222-4222-8222-000000000002','lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000002"}', sha256('b2'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'B completes the lesson');

-- ---- no actor (a connection that never set a verified identity) ---------------
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM app.learner_profiles'), '0', 'no actor: no profiles');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM app.practice_attempts'), '0', 'no actor: no attempts');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM app.lesson_progress'), '0', 'no actor: no progress');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM app.sync_receipts'), '0', 'no actor: no receipts');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM app.account_change_feed'), '0', 'no actor: no feed');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM app.account_sync_state'), '0', 'no actor: no sync state');
SELECT is(pg_temp.as_api(NULL, $$SELECT app.sync_apply_operation(gen_random_uuid(),'lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000001"}', sha256('x'), 'mep-canon-1')$$), 'ERROR:42501', 'no actor: sync write refused');
SELECT is(pg_temp.as_api(NULL, $$INSERT INTO app.learner_profiles (user_id) VALUES ('a0000000-0000-4000-8000-000000000003') RETURNING 1$$), 'ERROR:42501', 'no actor: cannot create a profile');

-- ---- Student A sees only A ---------------------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT string_agg(user_id::text, $$,$$) FROM app.learner_profiles'), 'a0000000-0000-4000-8000-000000000001', 'A reads only own profile');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM app.learner_profiles WHERE user_id = 'a0000000-0000-4000-8000-000000000002'$$), '0', 'A cannot read B profile by id');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM app.practice_attempts'), '1/0', 'A reads only own attempts');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM app.lesson_progress'), '1/0', 'A reads only own progress');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM app.sync_receipts'), '2/0', 'A reads only own receipts');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM app.account_change_feed'), '2/0', 'A reads only own change feed');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM app.account_sync_state'), '1/0', 'A reads only own sync state');
SELECT is(pg_temp.as_api(:B::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM app.account_change_feed'), '2/0', 'B reads only own change feed');

-- ---- Student A cannot write around the sync function -------------------------
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO app.practice_attempts (learner_id, op_id, lesson_revision_id, question_revision_id, response, score) VALUES ('a0000000-0000-4000-8000-000000000001', gen_random_uuid(), 'c0000000-0000-4000-8000-000000000001', 'd0000000-0000-4000-8000-000000000102', '{"choice_id":"a"}', 1) RETURNING 1$$), 'ERROR:42501', 'A cannot insert a self-scored attempt');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO app.practice_attempts (learner_id, op_id, lesson_revision_id, question_revision_id, response, score) VALUES ('a0000000-0000-4000-8000-000000000002', gen_random_uuid(), 'c0000000-0000-4000-8000-000000000001', 'd0000000-0000-4000-8000-000000000102', '{"choice_id":"a"}', 1) RETURNING 1$$), 'ERROR:42501', 'A cannot insert an attempt for B');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO app.lesson_progress (learner_id, lesson_id, completed_at) VALUES ('a0000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000005', now()) RETURNING 1$$), 'ERROR:42501', 'A cannot insert progress directly');
SELECT is(pg_temp.as_api(:A::uuid, 'UPDATE app.lesson_progress SET completed_at = NULL RETURNING 1'), 'ERROR:42501', 'A cannot update progress directly');
SELECT is(pg_temp.as_api(:A::uuid, $$UPDATE app.lesson_progress SET completed_at = now() WHERE learner_id = 'a0000000-0000-4000-8000-000000000002' RETURNING 1$$), 'ERROR:42501', 'A cannot update B progress');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO app.sync_receipts (learner_id, op_id, op_kind, canon_version, payload_sha256, result_code, result) VALUES ('a0000000-0000-4000-8000-000000000001', gen_random_uuid(), 'practice_answer', 'mep-canon-1', sha256('z'), 'accepted', '{}') RETURNING 1$$), 'ERROR:42501', 'A cannot forge a receipt');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO app.account_change_feed (learner_id, version, entity_type, entity_id, change_data) VALUES ('a0000000-0000-4000-8000-000000000001', 99, 'practice_attempt', gen_random_uuid(), '{}') RETURNING 1$$), 'ERROR:42501', 'A cannot forge a change-feed entry');
SELECT is(pg_temp.as_api(:A::uuid, 'UPDATE app.account_sync_state SET current_version = 0 RETURNING 1'), 'ERROR:42501', 'A cannot rewind the change version');
SELECT is(pg_temp.as_api(:A::uuid, 'DELETE FROM app.practice_attempts RETURNING 1'), 'ERROR:42501', 'A cannot delete attempts');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO app.audit_events (actor_id, actor_kind, action, outcome) VALUES ('a0000000-0000-4000-8000-000000000001', 'user', 'forged.event', 'allowed') RETURNING 1$$), 'ERROR:42501', 'A cannot forge an audit event');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM app.audit_events'), 'ERROR:42501', 'A cannot read audit events');
SELECT is(pg_temp.as_api(:A::uuid, $$UPDATE app.learner_profiles SET display_name = 'x' RETURNING 1$$), 'ERROR:42501', 'A cannot update profiles (no endpoint needs it yet)');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO app.learner_profiles (user_id) VALUES ('a0000000-0000-4000-8000-000000000003') RETURNING 1$$), 'ERROR:42501', 'A cannot create a profile for another user');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO app.learner_profiles (user_id, display_name) VALUES ('a0000000-0000-4000-8000-000000000001', 'x') RETURNING 1$$), 'ERROR:42501', 'A cannot set profile columns other than user_id');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT app.revision_is_syncable('c0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'A cannot call internal functions');

-- ---- staff surface is closed to the student API role -------------------------
SELECT is(pg_temp.as_api(:EDITOR::uuid, 'SELECT count(*) FROM app.staff_roles'), 'ERROR:42501', 'student API cannot read staff roles, even as a staff user');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$INSERT INTO app.staff_roles (user_id, role) VALUES ('a0000000-0000-4000-8000-000000000003', 'admin') RETURNING 1$$), 'ERROR:42501', 'student API cannot grant staff roles');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$UPDATE app.lesson_revisions SET title = 'x' RETURNING 1$$), 'ERROR:42501', 'student API cannot edit lessons, even as a staff user');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$UPDATE app.courses SET visibility = 'published' RETURNING 1$$), 'ERROR:42501', 'student API cannot publish courses');
SELECT is(pg_temp.as_api(:EDITOR::uuid, 'SELECT count(*) FROM app.practice_attempts'), '0', 'a staff user sees no learner attempts through the student API');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM app.background_jobs'), 'ERROR:42501', 'student API cannot read the job queue');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM auth.users'), 'ERROR:42501', 'student API cannot read auth.users');

-- ---- Supabase Data API roles cannot reach the schema at all -------------------
SET LOCAL ROLE anon;
SELECT throws_ok('SELECT count(*) FROM app.learner_profiles', '42501', NULL, 'anon: schema app is unreachable');
SELECT throws_ok('SELECT app.current_actor_id()', '42501', NULL, 'anon: cannot call app functions');
RESET ROLE;
SET LOCAL ROLE authenticated;
SELECT throws_ok('SELECT count(*) FROM app.practice_attempts', '42501', NULL, 'authenticated (Data API): schema app is unreachable');
SELECT throws_ok('SELECT count(*) FROM app.lesson_revisions', '42501', NULL, 'authenticated (Data API): cannot read lessons directly');
RESET ROLE;

-- ---- account deletion is restricted ------------------------------------------
SELECT throws_ok($$DELETE FROM auth.users WHERE id = 'a0000000-0000-4000-8000-000000000001'$$, '23503', NULL,
    'deleting an auth user with learning data is blocked (needs the future deletion procedure)');

SELECT * FROM finish();
ROLLBACK;
