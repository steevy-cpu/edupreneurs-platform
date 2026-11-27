-- Fixes from the independent review of the identity lane (migration 20261124020500).
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_worker TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
-- Run one statement as a role with an optional actor; errors come back as text.
CREATE FUNCTION pg_temp.run_as(p_role text, p_actor uuid, p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    PERFORM set_config('edu.actor_id', COALESCE(p_actor::text, ''), true);
    IF p_role IS NOT NULL THEN EXECUTE format('SET LOCAL ROLE %I', p_role); END IF;
    BEGIN
        EXECUTE p_sql INTO v_out;
    EXCEPTION WHEN OTHERS THEN
        v_out := 'ERROR:' || SQLSTATE || ':' || SQLERRM;
    END;
    EXECUTE 'RESET ROLE';
    PERFORM set_config('edu.actor_id', '', true);
    RETURN v_out;
END;
$fn$;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''

TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;
TRUNCATE app.audit_events;
DELETE FROM account.deletion_requests;
DELETE FROM account.export_requests;
DELETE FROM account.onboarding_state;

SELECT is(pg_temp.run_as('edu_api', :A::uuid, $$SELECT app.sync_apply_operation('11111111-1111-4111-8111-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}', sha256('a1'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'A has learning data');
SELECT is(pg_temp.run_as('edu_api', :B::uuid, $$SELECT app.sync_apply_operation('22222222-2222-4222-8222-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000201","response":{"choice_id":"a"}}', sha256('b1'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'B has learning data');
SELECT is(pg_temp.run_as('edu_api', :A::uuid, $$SELECT account.request_deletion() ->> 'created'$$), 'true', 'A files a deletion request');
SELECT is(pg_temp.run_as('edu_api', :B::uuid, $$SELECT account.request_deletion() ->> 'created'$$), 'true', 'B files one');
SELECT is(pg_temp.run_as('edu_api', :B::uuid, $$SELECT account.cancel_deletion_request() ->> 'cancelled'$$), 'true', 'and withdraws it');
CREATE TEMP TABLE req AS
    SELECT (SELECT id FROM account.deletion_requests WHERE user_id = :A::uuid AND status = 'requested') AS a_open,
           (SELECT id FROM account.deletion_requests WHERE user_id = :B::uuid AND status = 'cancelled') AS b_cancelled;
CREATE TEMP TABLE audit_n AS SELECT count(*)::int AS n FROM app.audit_events;

-- ---- M-2: the worker never names a user ------------------------------------------------
SELECT matches(pg_temp.run_as('edu_worker', NULL, $$SELECT account.erase_learner('a0000000-0000-4000-8000-000000000001')$$), '^ERROR:42501', 'the worker cannot call the orchestrator with a user id');
SELECT matches(pg_temp.run_as('edu_worker', NULL, 'SELECT account.worker_process_deletion(NULL)'), '^ERROR:22023', 'a NULL request id is refused');
SELECT matches(pg_temp.run_as('edu_worker', NULL, $$SELECT account.worker_process_deletion('99999999-9999-4999-8999-999999999999')$$), '^ERROR:P0002', 'an unknown request id is an error, not "erased"');
SELECT matches(pg_temp.run_as('edu_worker', NULL, $$SELECT account.worker_process_deletion('a0000000-0000-4000-8000-000000000001')$$), '^ERROR:P0002', 'a USER id is not a request id');
SELECT matches(pg_temp.run_as('edu_worker', NULL, format('SELECT account.worker_process_deletion(%L)', (SELECT b_cancelled FROM req))), '^ERROR:P0002', 'a cancelled request cannot be processed');
SELECT is((SELECT count(*)::int FROM app.audit_events), (SELECT n FROM audit_n), 'none of those refusals wrote an audit event');
SELECT is((SELECT count(*)::int FROM app.practice_attempts), 2, 'and nothing was erased');
SELECT matches(pg_temp.run_as('edu_api', :A::uuid, format('SELECT account.worker_process_deletion(%L)', (SELECT a_open FROM req))), '^ERROR:42501', 'a learner cannot process their own request');
SELECT matches(pg_temp.run_as('edu_staff', 'a0000000-0000-4000-8000-000000000003', format('SELECT account.worker_process_deletion(%L)', (SELECT a_open FROM req))), '^ERROR:42501', 'staff cannot use the worker path');
INSERT INTO app.staff_roles (user_id, role) VALUES ('a0000000-0000-4000-8000-000000000004', 'admin');
SELECT matches(pg_temp.run_as('edu_staff', 'a0000000-0000-4000-8000-000000000004', $$SELECT account.staff_erase_learner('99999999-9999-4999-8999-999999999999')$$), '^ERROR:P0002', 'staff path: an id with no learner is "not found", not "erased"');
SELECT is((SELECT count(*)::int FROM app.audit_events), (SELECT n FROM audit_n), 'still no audit event');

-- ---- M-1: the erased learner must not be the session actor -----------------------------
SELECT matches(pg_temp.run_as('edu_worker', :A::uuid, format('SELECT account.worker_process_deletion(%L)', (SELECT a_open FROM req))), '^ERROR:55000.*session actor', 'refused when the session actor is the learner being erased');
SELECT matches(pg_temp.run_as(NULL, :A::uuid, $$SELECT account.erase_learner('a0000000-0000-4000-8000-000000000001')$$), '^ERROR:55000.*session actor', 'also for the owner');
SELECT is((SELECT count(*)::int FROM app.learner_profiles WHERE user_id = :A::uuid), 1, 'A is untouched by the refused calls');
SELECT ok((SELECT position('find_learner_references' IN prosrc) > position('account.learner_erased' IN prosrc) FROM pg_proc WHERE oid = 'account.erase_learner(uuid)'::regprocedure),
    'the "id is nowhere" check runs after the audit record is written');

-- ---- L-1: a temporary function named erase_learner is not a module ---------------------
CREATE FUNCTION pg_temp.erase_learner(p_user_id uuid) RETURNS jsonb LANGUAGE sql AS $fn$ SELECT '{}'::jsonb $fn$;

-- ---- L-2: hook contract ---------------------------------------------------------------
CREATE SCHEMA zz_sig;
INSERT INTO account.erasure_hooks (schema_name, position) VALUES ('zz_sig', 1);
CREATE FUNCTION zz_sig.erase_learner(p_user_id text) RETURNS jsonb LANGUAGE sql AS $fn$ SELECT '{}'::jsonb $fn$;
SELECT matches(pg_temp.run_as('edu_worker', NULL, format('SELECT account.worker_process_deletion(%L)', (SELECT a_open FROM req))), '^ERROR:55000.*zz_sig.*signature', 'a registered hook with the wrong signature blocks (and the temporary function did not)');
DROP FUNCTION zz_sig.erase_learner(text);
CREATE FUNCTION zz_sig.erase_learner(p_user_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
    SET LOCAL session_replication_role = replica;  -- a hook that forgets to switch triggers back on
    RETURN '{}'::jsonb;
END;
$fn$;
SELECT matches(pg_temp.run_as('edu_worker', NULL, format('SELECT account.worker_process_deletion(%L)', (SELECT a_open FROM req))), '^ERROR:55000.*zz_sig.*session_replication_role', 'a hook that leaves triggers off blocks the erasure');
SELECT is(current_setting('session_replication_role'), 'origin', 'and triggers are ON in the caller''s transaction afterwards');
SELECT throws_ok('DELETE FROM app.practice_attempts', 'P0001', 'Append-only records cannot be updated or deleted', 'attempts are protected');
SELECT is((SELECT count(*)::int FROM app.learner_profiles WHERE user_id = :A::uuid), 1, 'A is still untouched');
DROP FUNCTION zz_sig.erase_learner(uuid);

-- ---- L-3 (part): unlogged tables and uuid[] columns are covered --------------------------
CREATE UNLOGGED TABLE zz_sig.cache (learner uuid);
CREATE TABLE zz_sig.groups (members uuid[]);
INSERT INTO zz_sig.cache VALUES (:A::uuid);
INSERT INTO zz_sig.groups VALUES (ARRAY[:B::uuid, :A::uuid]);
SELECT ok(account.find_learner_references(:A::uuid) @> ARRAY['zz_sig.cache.learner', 'zz_sig.groups.members'], 'the scanner finds the id in an unlogged table and inside a uuid[] column');
SELECT matches(pg_temp.run_as('edu_worker', NULL, format('SELECT account.worker_process_deletion(%L)', (SELECT a_open FROM req))), '^ERROR:55000.*erasure incomplete.*zz_sig', 'so the erasure refuses to report success');
DROP TABLE zz_sig.cache, zz_sig.groups;

-- ---- the worker path, when everything is in order ------------------------------------------
SELECT is((pg_temp.run_as('edu_worker', NULL, format('SELECT account.worker_process_deletion(%L)', (SELECT a_open FROM req)))::jsonb) ->> 'erased', 'true', 'the worker processes A open request');
SELECT is(account.find_learner_references(:A::uuid), ARRAY[]::text[], 'A id is nowhere');
SELECT is((SELECT status || '/' || (user_id IS NULL) FROM account.deletion_requests WHERE id = (SELECT a_open FROM req)), 'processed/true', 'the request is processed and de-identified');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE action = 'account.learner_erased' AND actor_id IS NULL AND target_id IS NULL), 1, 'one erasure record, naming nobody');
SELECT matches(pg_temp.run_as('edu_worker', NULL, format('SELECT account.worker_process_deletion(%L)', (SELECT a_open FROM req))), '^ERROR:P0002', 'the same request cannot be processed twice');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE action = 'account.learner_erased'), 1, 'and no second erasure record appears');
SELECT is((SELECT count(*)::int FROM app.practice_attempts WHERE learner_id = :B::uuid), 1, 'B is untouched');

-- ---- H-1 (structure; the race itself is tested with two connections in pytest) ---------------
SELECT ok((SELECT prosrc ~ 'FROM app\.learner_profiles p WHERE p\.user_id = v_actor FOR KEY SHARE' FROM pg_proc WHERE oid = 'account.advance_onboarding(text, integer, integer, boolean)'::regprocedure), 'advance_onboarding locks the caller profile');
SELECT ok((SELECT prosrc ~ 'FROM app\.learner_profiles p WHERE p\.user_id = v_actor FOR KEY SHARE' FROM pg_proc WHERE oid = 'account.export_own_data()'::regprocedure), 'export_own_data locks the caller profile');
SELECT is(pg_temp.run_as('edu_api', :A::uuid, $$SELECT account.advance_onboarding('ready', 1)$$), 'ERROR:42501:Learner profile required', 'after the erasure, onboarding for A is refused');
SELECT is(pg_temp.run_as('edu_api', :A::uuid, 'SELECT account.export_own_data()'), 'ERROR:42501:Learner profile required', 'and so is an export');

SELECT * FROM finish();
ROLLBACK;
