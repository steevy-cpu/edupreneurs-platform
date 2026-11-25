-- Deletion / export requests and account.export_own_data(): own rows only, idempotent,
-- no retention rule, nothing deleted by a request. Synthetic users only.
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

-- Exact starting point (rolled back with the transaction).
TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;
DELETE FROM account.deletion_requests;
DELETE FROM account.export_requests;
DELETE FROM account.onboarding_state;

CREATE TEMP TABLE seam_calls (n serial, actor uuid, action text, target_kind text, target_id uuid, details jsonb);
CREATE OR REPLACE FUNCTION account.audit_seam(
    p_action text, p_target_kind text, p_target_id uuid, p_outcome text, p_details jsonb DEFAULT '{}'::jsonb)
RETURNS uuid LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
    INSERT INTO pg_temp.seam_calls (actor, action, target_kind, target_id, details)
    VALUES (app.current_actor_id(), p_action, p_target_kind, p_target_id, p_details);
    RETURN NULL;
END;
$fn$;

-- Both learners have real learning data, written through the only write path.
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT app.sync_apply_operation('11111111-1111-4111-8111-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}', sha256('a1'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'A answers');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT app.sync_apply_operation('11111111-1111-4111-8111-000000000002','lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000001"}', sha256('a2'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'A completes');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT app.sync_apply_operation('22222222-2222-4222-8222-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000201","response":{"choice_id":"a"}}', sha256('b1'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'B answers');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT account.advance_onboarding('ready', 3, 2, true) ->> 'state'$$), 'ready', 'B has an onboarding row');

-- ---- structure and privileges ------------------------------------------------------
SELECT has_table('account', 'deletion_requests', 'deletion_requests exists');
SELECT has_table('account', 'export_requests', 'export_requests exists');
SELECT has_table('account', 'erasure_hooks', 'erasure_hooks exists');
SELECT policies_are('account', 'deletion_requests', ARRAY['deletion_requests_select_own'], 'deletion requests: own-row read only');
SELECT policies_are('account', 'export_requests', ARRAY['export_requests_select_own'], 'export requests: own-row read only');
SELECT policies_are('account', 'erasure_hooks', ARRAY[]::name[], 'the hook registry has no policy at all');
SELECT is(has_table_privilege('edu_api', 'account.erasure_hooks', 'SELECT'), false, 'edu_api cannot read the hook registry');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'account'::regnamespace AND has_function_privilege('edu_api', p.oid, 'EXECUTE')),
    ARRAY['advance_onboarding', 'cancel_deletion_request', 'export_own_data', 'get_own_onboarding',
          'get_own_requests', 'request_deletion', 'update_own_profile'],
    'edu_api may execute exactly the seven self-service functions');
SELECT is((SELECT count(*)::int FROM information_schema.columns
           WHERE table_schema = 'account' AND table_name IN ('deletion_requests', 'export_requests')
             AND column_name ~ 'retention|retain|expires|purge|deadline|due|grace|scheduled'), 0,
    'no retention, grace or deadline column exists (none has been decided: PO-04)');

-- ---- deletion requests ---------------------------------------------------------------
SELECT is(pg_temp.as_api(NULL, 'SELECT account.request_deletion()'), 'ERROR:42501', 'no actor: request refused');
SELECT is(pg_temp.as_api(NULL, 'SELECT account.cancel_deletion_request()'), 'ERROR:42501', 'no actor: cancel refused');
SELECT is(pg_temp.as_api(NULL, 'SELECT account.get_own_requests()'), 'ERROR:42501', 'no actor: read refused');
SELECT is(pg_temp.as_api(NULL, 'SELECT account.export_own_data()'), 'ERROR:42501', 'no actor: export refused');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-0000000000ee', 'SELECT account.request_deletion()'), 'ERROR:42501', 'an actor without a profile cannot request deletion');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-0000000000ee', 'SELECT account.export_own_data()'), 'ERROR:42501', 'an actor without a profile has nothing to export');

SELECT is(pg_temp.as_api(:A::uuid, 'SELECT account.get_own_requests()')::jsonb,
    '{"deletion_request":null,"last_export":null}'::jsonb, 'A starts with no request');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.cancel_deletion_request()$$)::jsonb,
    '{"cancelled":false,"deletion_request":null}'::jsonb, 'cancelling with nothing open changes nothing');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.request_deletion() #>> '{deletion_request,status}'$$), 'requested', 'A requests deletion');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.request_deletion() ->> 'created'$$), 'false', 'asking again returns the same open request');
SELECT is((SELECT count(*)::int FROM account.deletion_requests WHERE user_id = :A::uuid), 1, 'exactly one request row');
SELECT throws_ok($$INSERT INTO account.deletion_requests (user_id) VALUES ('a0000000-0000-4000-8000-000000000001')$$, '23505', NULL,
    'the table itself allows one open request per learner');

-- A request deletes nothing.
SELECT is((SELECT count(*)::int FROM app.practice_attempts WHERE learner_id = :A::uuid), 1, 'request: attempts untouched');
SELECT is((SELECT count(*)::int FROM app.lesson_progress WHERE learner_id = :A::uuid), 1, 'request: progress untouched');
SELECT is((SELECT count(*)::int FROM app.learner_profiles WHERE user_id = :A::uuid), 1, 'request: profile untouched');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT app.sync_apply_operation('11111111-1111-4111-8111-000000000003','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000102","response":{"choice_id":"a"}}', sha256('a3'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'A can keep learning while a request is open');

-- Isolation.
SELECT is(pg_temp.as_api(:B::uuid, 'SELECT account.get_own_requests()')::jsonb,
    '{"deletion_request":null,"last_export":null}'::jsonb, 'B sees none of A requests');
SELECT is(pg_temp.as_api(:B::uuid, 'SELECT count(*) FROM account.deletion_requests'), '0', 'B reads no deletion request rows');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT account.cancel_deletion_request() ->> 'cancelled'$$), 'false', 'B cannot cancel A request');
SELECT is((SELECT status FROM account.deletion_requests WHERE user_id = :A::uuid), 'requested', 'A request is still open');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE user_id <> app.current_actor_id()) FROM account.deletion_requests'), '1/0', 'A reads only own request');

-- Cancel, then a new request is a new row.
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.cancel_deletion_request() #>> '{deletion_request,status}'$$), 'cancelled', 'A cancels');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.cancel_deletion_request() ->> 'cancelled'$$), 'false', 'cancelling twice changes nothing');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.request_deletion() ->> 'created'$$), 'true', 'A may ask again later');
SELECT is((SELECT array_agg(status ORDER BY status) FROM account.deletion_requests WHERE user_id = :A::uuid),
    ARRAY['cancelled', 'requested'], 'history: one cancelled, one open');

-- No way around the functions.
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO account.deletion_requests (user_id) VALUES ('a0000000-0000-4000-8000-000000000002') RETURNING 1$$), 'ERROR:42501', 'A cannot file a deletion request for B');
SELECT is(pg_temp.as_api(:A::uuid, $$UPDATE account.deletion_requests SET status = 'processed', processed_at = now(), user_id = NULL RETURNING 1$$), 'ERROR:42501', 'A cannot mark a request processed');
SELECT is(pg_temp.as_api(:A::uuid, 'DELETE FROM account.deletion_requests RETURNING 1'), 'ERROR:42501', 'A cannot delete requests');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.erase_learner('a0000000-0000-4000-8000-000000000002')$$), 'ERROR:42501', 'A cannot call the erasure orchestrator');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.erase_learner('a0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'not even on their own account (a request is processed by the worker)');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.find_learner_references('a0000000-0000-4000-8000-000000000002')$$), 'ERROR:42501', 'A cannot call the reference scanner');
SELECT throws_ok($$UPDATE account.deletion_requests SET status = 'processed', processed_at = now() WHERE status = 'requested'$$, '23514', NULL,
    'a processed deletion request cannot keep the user id (table constraint)');
SELECT throws_ok($$UPDATE account.deletion_requests SET user_id = NULL WHERE status = 'requested'$$, '23514', NULL,
    'an open request must name its user (table constraint)');

-- ---- export ---------------------------------------------------------------------------
CREATE TEMP TABLE export_a AS
    SELECT pg_temp.as_api(:A::uuid, 'SELECT account.export_own_data()')::jsonb AS doc;
SELECT is((SELECT doc ->> 'format' FROM export_a), 'mep-account-export-1', 'export has a format tag');
SELECT is((SELECT doc ->> 'user_id' FROM export_a), 'a0000000-0000-4000-8000-000000000001', 'export is for the caller');
SELECT is((SELECT doc -> 'profile' FROM export_a) - 'created_at' - 'updated_at',
    '{"grade_code":"9AF","preferred_locale":"fr","display_name":"Élève A (synthétique)"}'::jsonb, 'export contains the caller profile');
SELECT is((SELECT doc -> 'onboarding' FROM export_a), 'null'::jsonb, 'A has no onboarding row: null');
SELECT is((SELECT jsonb_array_length(doc -> 'practice_attempts') FROM export_a), 2, 'both of A attempts');
SELECT is((SELECT jsonb_array_length(doc -> 'lesson_progress') FROM export_a), 1, 'A progress');
SELECT is((SELECT doc -> 'counts' FROM export_a), '{"lesson_progress":1,"practice_attempts":2}'::jsonb, 'true totals');
SELECT is((SELECT doc -> 'truncated' FROM export_a), '{"lesson_progress":false,"practice_attempts":false}'::jsonb, 'nothing truncated');
SELECT is((SELECT count(*)::int FROM export_a, jsonb_array_elements(doc -> 'practice_attempts') a
           WHERE NOT EXISTS (SELECT 1 FROM app.practice_attempts p
                             WHERE p.id = (a ->> 'id')::uuid AND p.learner_id = :A::uuid)), 0,
    'every exported attempt is one of A own attempts');
SELECT is((SELECT position('a0000000-0000-4000-8000-000000000002' IN doc::text) FROM export_a), 0, 'B id appears nowhere in A export');
SELECT is((SELECT position('d0000000-0000-4000-8000-000000000201' IN doc::text) FROM export_a), 0, 'B answered question appears nowhere in A export');
SELECT is((SELECT position('sentetik' IN doc::text) FROM export_a), 0, 'B display name appears nowhere in A export');
SELECT is((SELECT count(*)::int FROM export_a, jsonb_object_keys(doc) k
           WHERE k NOT IN ('format', 'export_id', 'generated_at', 'user_id', 'profile', 'onboarding',
                           'lesson_progress', 'practice_attempts', 'counts', 'limits', 'truncated')), 0,
    'the export has exactly the documented sections');

SELECT is(pg_temp.as_api(:B::uuid, $$SELECT account.export_own_data() #>> '{onboarding,state}'$$), 'ready', 'B export contains B onboarding');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT jsonb_array_length(account.export_own_data() -> 'practice_attempts')$$), '1', 'B export contains only B attempt');
SELECT is((SELECT count(*)::int FROM account.export_requests WHERE user_id = :A::uuid AND status = 'processed'), 1, 'A export was recorded');
SELECT is((SELECT count(*)::int FROM account.export_requests WHERE user_id = :B::uuid AND status = 'processed'), 2, 'B exports were recorded');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE user_id <> app.current_actor_id()) FROM account.export_requests'), '1/0', 'A reads only own export records');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.get_own_requests() #>> '{last_export,status}'$$), 'processed', 'A sees the last export');

-- Bounded size: 2000 rows per list, with honest totals.
-- (fixture rows inserted by the owner; the API role could not do this)
INSERT INTO app.practice_attempts (learner_id, op_id, lesson_revision_id, question_revision_id, response, score, scoring_version)
SELECT :A::uuid, gen_random_uuid(), 'c0000000-0000-4000-8000-000000000001', 'd0000000-0000-4000-8000-000000000103',
       '{"choice_id":"c"}'::jsonb, 1, 'mcq-v1'
FROM generate_series(1, 2100);
CREATE TEMP TABLE export_big AS
    SELECT pg_temp.as_api(:A::uuid, 'SELECT account.export_own_data()')::jsonb AS doc;
SELECT is((SELECT jsonb_array_length(doc -> 'practice_attempts') FROM export_big), 2000, 'the attempt list is capped at 2000');
SELECT is((SELECT doc #>> '{counts,practice_attempts}' FROM export_big), '2102', 'the true total is still reported');
SELECT is((SELECT doc #>> '{truncated,practice_attempts}' FROM export_big), 'true', 'and the export says it was truncated');
SELECT ok((SELECT octet_length(doc::text) < 1500000 FROM export_big), 'a capped export stays under 1.5 MB');

-- ---- audit seam ------------------------------------------------------------------------
SELECT is((SELECT array_agg(action ORDER BY n) FROM seam_calls WHERE actor = :A::uuid),
    ARRAY['account.deletion_requested', 'account.deletion_cancelled', 'account.deletion_requested',
          'account.data_exported', 'account.data_exported'],
    'each lifecycle action of A went through the audit seam once (idempotent repeats did not)');
SELECT is((SELECT count(*)::int FROM seam_calls WHERE details::text ~ 'synth|choice_id|a0000000'), 0, 'audit details carry no personal value');

SELECT * FROM finish();
ROLLBACK;
