-- account.erase_learner(): one SYNTHETIC learner is fully erased, another is untouched,
-- the append-only triggers are never changed and keep protecting everyone else.
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

-- Stand-in for the future executor (edu_worker arrives with the staff lane):
-- a role with no attribute and exactly one privilege, EXECUTE on the orchestrator.
-- It exists only inside this transaction.
CREATE ROLE zz_erasure_executor NOLOGIN NOSUPERUSER NOBYPASSRLS;
GRANT zz_erasure_executor TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT USAGE ON SCHEMA account TO zz_erasure_executor;
GRANT EXECUTE ON FUNCTION account.erase_learner(uuid) TO zz_erasure_executor;
CREATE FUNCTION pg_temp.as_executor(p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    EXECUTE 'SET LOCAL ROLE zz_erasure_executor';
    BEGIN
        EXECUTE p_sql INTO v_out;
    EXCEPTION WHEN OTHERS THEN
        v_out := 'ERROR:' || SQLSTATE || ':' || SQLERRM;
    END;
    EXECUTE 'RESET ROLE';
    RETURN v_out;
END;
$fn$;

-- Does the id appear ANYWHERE in the application schemas — in any uuid, text or
-- JSON column? (Deeper than the orchestrator's own postcondition, which checks
-- uuid columns.) Returns the list of schema.table.column places.
CREATE FUNCTION pg_temp.anywhere(p_id uuid) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_col record; v_hit boolean; v_out text[] := ARRAY[]::text[];
BEGIN
    FOR v_col IN
        SELECT n.nspname, c.relname, a.attname
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('app', 'account', 'zz_lane', 'public') AND c.relkind = 'r'
          AND a.attnum > 0 AND NOT a.attisdropped
          AND a.atttypid IN ('uuid'::regtype, 'text'::regtype, 'jsonb'::regtype, 'json'::regtype, 'uuid[]'::regtype)
    LOOP
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.%I WHERE position(%L IN %I::text) > 0)',
                       v_col.nspname, v_col.relname, p_id::text, v_col.attname) INTO v_hit;
        IF v_hit THEN v_out := v_out || format('%s.%s.%s', v_col.nspname, v_col.relname, v_col.attname); END IF;
    END LOOP;
    RETURN array_to_string(v_out, ',');
END;
$fn$;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''

-- Exact starting point (rolled back with the transaction; nothing is really removed).
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

-- ---- two learners with attempts, progress, receipts, feed, onboarding, requests ---------
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT app.sync_apply_operation('11111111-1111-4111-8111-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}', sha256('a1'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'A answers');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT app.sync_apply_operation('11111111-1111-4111-8111-000000000002','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000102","response":{"choice_id":"c"}}', sha256('a2'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'A answers again');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT app.sync_apply_operation('11111111-1111-4111-8111-000000000003','lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000001"}', sha256('a3'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'A completes the lesson');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT app.sync_apply_operation('11111111-1111-4111-8111-000000000004','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-0000000009ff","response":{"choice_id":"a"}}', sha256('a4'), 'mep-canon-1') ->> 'status'$$), 'rejected', 'A has a rejected receipt too');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT app.sync_apply_operation('22222222-2222-4222-8222-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000201","response":{"choice_id":"a"}}', sha256('b1'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'B answers');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT app.sync_apply_operation('22222222-2222-4222-8222-000000000002','lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000002"}', sha256('b2'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'B completes the lesson');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.advance_onboarding('ready', 2, 1, true) ->> 'state'$$), 'ready', 'A onboarding');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT account.advance_onboarding('downloads_informed', 1, 4, false) ->> 'state'$$), 'ready', 'B onboarding');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.update_own_profile('{"display_name":"Synthetic learner to erase"}') ->> 'status'$$), 'ok', 'A edits the profile');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.request_deletion() ->> 'created'$$), 'true', 'A requests deletion');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.cancel_deletion_request() ->> 'cancelled'$$), 'true', 'A cancels');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.request_deletion() ->> 'created'$$), 'true', 'A requests deletion again');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT account.export_own_data() ->> 'format'$$), 'mep-account-export-1', 'A exports');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT account.request_deletion() ->> 'created'$$), 'true', 'B has an open deletion request of their own');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT account.export_own_data() ->> 'format'$$), 'mep-account-export-1', 'B exports');

-- Audit rows as the future audit writer would leave them (fixture rows by the owner).
INSERT INTO app.audit_events (actor_id, actor_kind, action, target_kind, target_id, outcome, details) VALUES
    (:A::uuid, 'user', 'account.profile_updated', 'learner_profile', :A::uuid, 'allowed', '{"fields":["display_name"]}'),
    (:EDITOR::uuid, 'staff', 'support.note_added', 'learner', :A::uuid, 'allowed', '{"note":"kept, de-identified"}'),
    (:EDITOR::uuid, 'staff', 'support.lookup', 'learner', NULL, 'allowed', '{"looked_up":"a0000000-0000-4000-8000-000000000001"}'),
    (:B::uuid, 'user', 'account.profile_updated', 'learner_profile', :B::uuid, 'allowed', '{"fields":["grade_code"]}'),
    (NULL, 'system', 'pack.released', 'pack', NULL, 'allowed', '{}');

SELECT is((SELECT count(*)::int FROM app.practice_attempts WHERE learner_id = :A::uuid), 2, 'before: A has 2 attempts');
SELECT is((SELECT count(*)::int FROM app.sync_receipts WHERE learner_id = :A::uuid), 4, 'before: A has 4 receipts');
SELECT is((SELECT count(*)::int FROM app.account_change_feed WHERE learner_id = :A::uuid), 3, 'before: A has 3 feed entries');
SELECT is((SELECT count(*)::int FROM app.lesson_progress WHERE learner_id = :A::uuid), 1, 'before: A has progress');
SELECT isnt(pg_temp.anywhere(:A::uuid), '', 'before: the id is stored in many places');

-- Snapshots of everything that is NOT A.
CREATE TEMP TABLE keep_profiles AS SELECT * FROM app.learner_profiles WHERE user_id <> :A::uuid;
CREATE TEMP TABLE keep_attempts AS SELECT * FROM app.practice_attempts WHERE learner_id <> :A::uuid;
CREATE TEMP TABLE keep_receipts AS SELECT * FROM app.sync_receipts WHERE learner_id <> :A::uuid;
CREATE TEMP TABLE keep_feed AS SELECT * FROM app.account_change_feed WHERE learner_id <> :A::uuid;
CREATE TEMP TABLE keep_progress AS SELECT * FROM app.lesson_progress WHERE learner_id <> :A::uuid;
CREATE TEMP TABLE keep_state AS SELECT * FROM app.account_sync_state WHERE learner_id <> :A::uuid;
CREATE TEMP TABLE keep_onboarding AS SELECT * FROM account.onboarding_state WHERE user_id <> :A::uuid;
CREATE TEMP TABLE keep_deletion AS SELECT * FROM account.deletion_requests WHERE user_id <> :A::uuid;
CREATE TEMP TABLE keep_export AS SELECT * FROM account.export_requests WHERE user_id <> :A::uuid;
CREATE TEMP TABLE keep_audit AS SELECT * FROM app.audit_events
    WHERE actor_id IS DISTINCT FROM :A::uuid AND target_id IS DISTINCT FROM :A::uuid
      AND position('a0000000-0000-4000-8000-000000000001' IN details::text) = 0;
CREATE TEMP TABLE triggers_before AS
    SELECT t.oid, t.tgname, t.tgenabled, t.tgfoid, t.tgtype, pg_get_triggerdef(t.oid) AS def
    FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
    WHERE c.relnamespace = 'app'::regnamespace;
CREATE TEMP TABLE functions_before AS
    SELECT p.oid, p.proname, p.prosrc, p.proconfig, p.prosecdef, p.proacl::text AS acl
    FROM pg_proc p WHERE p.pronamespace = 'app'::regnamespace;

-- ---- who may run it ------------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_proc p, aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) a
           WHERE p.oid = 'account.erase_learner(uuid)'::regprocedure
             AND a.grantee NOT IN (p.proowner, 'zz_erasure_executor'::regrole)), 0,
    'as migrated, EXECUTE on erase_learner is granted to nobody but its owner (the test role was added above)');
SELECT is(has_function_privilege('edu_api', 'account.erase_learner(uuid)', 'EXECUTE'), false, 'edu_api cannot execute erase_learner');
SELECT is(has_function_privilege('anon', 'account.erase_learner(uuid)', 'EXECUTE'), false, 'anon cannot');
SELECT is(has_function_privilege('authenticated', 'account.erase_learner(uuid)', 'EXECUTE'), false, 'authenticated cannot');
SELECT is(has_function_privilege('service_role', 'account.erase_learner(uuid)', 'EXECUTE'), false, 'service_role cannot');
SELECT is((SELECT prosecdef FROM pg_proc WHERE oid = 'account.erase_learner(uuid)'::regprocedure), true, 'erase_learner is SECURITY DEFINER');

-- The executor can do NOTHING by itself: not delete, not lift the protection.
SELECT matches(pg_temp.as_executor($$DELETE FROM app.practice_attempts WHERE learner_id = 'a0000000-0000-4000-8000-000000000001' RETURNING 1$$), '^ERROR:42501', 'executor cannot delete attempts directly');
SELECT matches(pg_temp.as_executor('SET LOCAL session_replication_role = replica'), '^ERROR:42501', 'executor cannot switch off triggers for itself');
SELECT matches(pg_temp.as_executor($$SELECT set_config('session_replication_role', 'replica', true)$$), '^ERROR:42501', 'executor cannot switch off triggers through set_config either');
SELECT matches(pg_temp.as_executor('SELECT count(*) FROM app.learner_profiles'), '^ERROR:42501', 'executor cannot even read learner data');
SELECT matches(pg_temp.as_executor($$SELECT account.find_learner_references('a0000000-0000-4000-8000-000000000001')$$), '^ERROR:42501', 'executor cannot call the internal scanner');

-- ---- refusals (each leaves everything in place) -----------------------------------------
SELECT matches(pg_temp.as_executor('SELECT account.erase_learner(NULL)'), '^ERROR:22023', 'a NULL id is refused');
SELECT matches(pg_temp.as_executor($$SELECT account.erase_learner('a0000000-0000-4000-8000-000000000003')$$), '^ERROR:55000.*staff', 'an account with staff records is refused');
SET LOCAL session_replication_role = replica;
SELECT throws_ok($$SELECT account.erase_learner('a0000000-0000-4000-8000-000000000001')$$, '55000', NULL, 'refuses to start when triggers are already off in the session');
SET LOCAL session_replication_role = origin;

-- A module that stores learner rows but has no hook / is not registered.
CREATE SCHEMA zz_lane;
CREATE TABLE zz_lane.notes (id serial PRIMARY KEY, learner uuid NOT NULL, body text);
INSERT INTO zz_lane.notes (learner, body) VALUES (:A::uuid, 'synthetic'), (:B::uuid, 'synthetic');
SELECT matches(pg_temp.as_executor($$SELECT account.erase_learner('a0000000-0000-4000-8000-000000000001')$$),
    '^ERROR:55000.*erasure incomplete.*zz_lane\.notes\.learner', 'a leftover reference in an unknown module aborts the erasure and names the place');
SELECT is((SELECT count(*)::int FROM app.practice_attempts WHERE learner_id = :A::uuid), 2, 'aborted erasure: attempts all still there');
SELECT is((SELECT count(*)::int FROM app.sync_receipts WHERE learner_id = :A::uuid), 4, 'aborted erasure: receipts all still there');
SELECT is((SELECT count(*)::int FROM app.learner_profiles WHERE user_id = :A::uuid), 1, 'aborted erasure: profile still there');
SELECT is((SELECT status FROM account.deletion_requests WHERE user_id = :A::uuid AND status = 'requested'), 'requested', 'aborted erasure: the request is still open');
SELECT is(current_setting('session_replication_role'), 'origin', 'aborted erasure: triggers are on in this session');

-- An unregistered hook is never run and blocks the erasure.
CREATE FUNCTION zz_lane.erase_learner(p_user_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE n bigint;
BEGIN
    DELETE FROM zz_lane.notes WHERE learner = p_user_id;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN jsonb_build_object('notes', n);
END;
$fn$;
REVOKE ALL ON FUNCTION zz_lane.erase_learner(uuid) FROM PUBLIC;
SELECT matches(pg_temp.as_executor($$SELECT account.erase_learner('a0000000-0000-4000-8000-000000000001')$$),
    '^ERROR:55000.*not registered', 'a hook in an unregistered schema blocks the erasure');
SELECT is((SELECT count(*)::int FROM zz_lane.notes), 2, 'the unregistered hook was not run');
INSERT INTO account.erasure_hooks (schema_name, position, note) VALUES ('zz_lane', 5, 'test module');

-- A module that references an append-only row by foreign key but whose hook forgets it.
CREATE TABLE zz_lane.attempt_bonus (attempt_id uuid PRIMARY KEY REFERENCES app.practice_attempts(id), points integer NOT NULL);
INSERT INTO zz_lane.attempt_bonus (attempt_id, points)
    SELECT id, 1 FROM app.practice_attempts;
SELECT matches(pg_temp.as_executor($$SELECT account.erase_learner('a0000000-0000-4000-8000-000000000001')$$),
    '^ERROR:55000.*zz_lane\.attempt_bonus still references', 'a foreign key onto the learner''s append-only rows blocks the erasure BEFORE triggers are suspended');
SELECT is((SELECT count(*)::int FROM zz_lane.notes), 2, 'that failed run rolled the hook''s own deletes back too');
SELECT is((SELECT count(*)::int FROM app.practice_attempts WHERE learner_id = :A::uuid), 2, 'and A attempts are still there');
CREATE OR REPLACE FUNCTION zz_lane.erase_learner(p_user_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE n bigint; m bigint;
BEGIN
    DELETE FROM zz_lane.attempt_bonus b USING app.practice_attempts a
     WHERE a.id = b.attempt_id AND a.learner_id = p_user_id;
    GET DIAGNOSTICS m = ROW_COUNT;
    DELETE FROM zz_lane.notes WHERE learner = p_user_id;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN jsonb_build_object('notes', n, 'attempt_bonus', m);
END;
$fn$;
CREATE TEMP TABLE keep_lane_notes AS SELECT * FROM zz_lane.notes WHERE learner <> :A::uuid;
CREATE TEMP TABLE keep_lane_bonus AS SELECT b.* FROM zz_lane.attempt_bonus b JOIN app.practice_attempts a ON a.id = b.attempt_id WHERE a.learner_id <> :A::uuid;

-- ---- THE ERASURE ----------------------------------------------------------------------
CREATE TEMP TABLE report AS
    SELECT pg_temp.as_executor($$SELECT account.erase_learner('a0000000-0000-4000-8000-000000000001')$$) AS raw;
SELECT doesnt_match((SELECT raw FROM report), '^ERROR', 'erase_learner succeeds when called by the executor role');
SELECT is((SELECT (raw::jsonb) -> 'counts' FROM report),
    '{"account.onboarding_state":1,"account.export_requests":1,"account.deletion_requests_cancelled":1,
      "account.deletion_requests_processed":1,"app.account_change_feed":3,"app.sync_receipts":4,
      "app.practice_attempts":2,"app.audit_events_deidentified":3,"app.lesson_progress":1,
      "app.account_sync_state":1,"app.learner_profiles":1}'::jsonb,
    'the report counts every row that was removed');
SELECT is((SELECT (raw::jsonb) #> '{hooks,zz_lane}' FROM report), '{"notes":1,"attempt_bonus":2}'::jsonb, 'the registered hook was called and its result is in the report');
SELECT is((SELECT (raw::jsonb) #>> '{hooks,rewards}' FROM report), 'absent', 'registered schemas without a hook are reported as absent');
SELECT is((SELECT position('a0000000-0000-4000-8000-000000000001' IN raw) FROM report), 0, 'the report does not contain the erased id');

-- No row in any application schema references the id — in any uuid, text or JSON column.
SELECT is(pg_temp.anywhere(:A::uuid), '', 'the erased id appears NOWHERE in app, account, public or the test module');
SELECT is(account.find_learner_references(:A::uuid), ARRAY[]::text[], 'the orchestrator''s own scanner agrees');
SELECT is((SELECT count(*)::int FROM app.learner_profiles WHERE user_id = :A::uuid), 0, 'profile gone');
SELECT is((SELECT count(*)::int FROM app.practice_attempts WHERE learner_id = :A::uuid), 0, 'attempts gone');
SELECT is((SELECT count(*)::int FROM app.sync_receipts WHERE learner_id = :A::uuid), 0, 'receipts gone');
SELECT is((SELECT count(*)::int FROM app.account_change_feed WHERE learner_id = :A::uuid), 0, 'change feed gone');
SELECT is((SELECT count(*)::int FROM app.lesson_progress WHERE learner_id = :A::uuid), 0, 'progress gone');
SELECT is((SELECT count(*)::int FROM app.account_sync_state WHERE learner_id = :A::uuid), 0, 'sync state gone');
SELECT is((SELECT count(*)::int FROM account.onboarding_state WHERE user_id = :A::uuid), 0, 'onboarding gone');
SELECT is((SELECT count(*)::int FROM account.export_requests WHERE user_id = :A::uuid), 0, 'export records gone');
SELECT is((SELECT count(*)::int FROM account.deletion_requests WHERE user_id = :A::uuid), 0, 'no deletion request names the learner any more');
SELECT is((SELECT count(*)::int FROM account.deletion_requests WHERE status = 'processed' AND user_id IS NULL AND processed_at IS NOT NULL), 1,
    'one de-identified "processed" request remains as the record that it was carried out');
SELECT is((SELECT count(*)::int FROM app.audit_events), 5, 'no audit event was deleted');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE details = '{"redacted":true}'::jsonb), 1, 'the audit detail that contained the id was redacted');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE action = 'support.note_added' AND target_id IS NULL AND actor_id = :EDITOR::uuid), 1,
    'a staff action about the learner keeps its staff actor and loses only the learner id');

-- The Auth account itself is out of scope, but nothing of ours blocks its removal any more.
SELECT lives_ok($$DELETE FROM auth.users WHERE id = 'a0000000-0000-4000-8000-000000000001'$$,
    'after erasure the auth.users row can be deleted (it was blocked by foreign keys before)');

-- ---- the other learner is untouched ------------------------------------------------------
SELECT is((SELECT count(*)::int FROM ((SELECT * FROM app.learner_profiles EXCEPT SELECT * FROM keep_profiles) UNION ALL (SELECT * FROM keep_profiles EXCEPT SELECT * FROM app.learner_profiles)) d), 0, 'other profiles byte-identical');
SELECT is((SELECT count(*)::int FROM ((SELECT * FROM app.practice_attempts EXCEPT SELECT * FROM keep_attempts) UNION ALL (SELECT * FROM keep_attempts EXCEPT SELECT * FROM app.practice_attempts)) d), 0, 'other attempts byte-identical');
SELECT is((SELECT count(*)::int FROM ((SELECT * FROM app.sync_receipts EXCEPT SELECT * FROM keep_receipts) UNION ALL (SELECT * FROM keep_receipts EXCEPT SELECT * FROM app.sync_receipts)) d), 0, 'other receipts byte-identical');
SELECT is((SELECT count(*)::int FROM ((SELECT * FROM app.account_change_feed EXCEPT SELECT * FROM keep_feed) UNION ALL (SELECT * FROM keep_feed EXCEPT SELECT * FROM app.account_change_feed)) d), 0, 'other change feeds byte-identical');
SELECT is((SELECT count(*)::int FROM ((SELECT * FROM app.lesson_progress EXCEPT SELECT * FROM keep_progress) UNION ALL (SELECT * FROM keep_progress EXCEPT SELECT * FROM app.lesson_progress)) d), 0, 'other progress byte-identical');
SELECT is((SELECT count(*)::int FROM ((SELECT * FROM app.account_sync_state EXCEPT SELECT * FROM keep_state) UNION ALL (SELECT * FROM keep_state EXCEPT SELECT * FROM app.account_sync_state)) d), 0, 'other sync states byte-identical');
SELECT is((SELECT count(*)::int FROM ((SELECT * FROM account.onboarding_state EXCEPT SELECT * FROM keep_onboarding) UNION ALL (SELECT * FROM keep_onboarding EXCEPT SELECT * FROM account.onboarding_state)) d), 0, 'other onboarding rows byte-identical');
SELECT is((SELECT count(*)::int FROM ((SELECT * FROM account.deletion_requests WHERE user_id IS NOT NULL EXCEPT SELECT * FROM keep_deletion) UNION ALL (SELECT * FROM keep_deletion EXCEPT SELECT * FROM account.deletion_requests)) d), 0, 'other deletion requests byte-identical (B request is still open)');
SELECT is((SELECT count(*)::int FROM ((SELECT * FROM account.export_requests EXCEPT SELECT * FROM keep_export) UNION ALL (SELECT * FROM keep_export EXCEPT SELECT * FROM account.export_requests)) d), 0, 'other export records byte-identical');
SELECT is((SELECT count(*)::int FROM (SELECT * FROM keep_audit EXCEPT SELECT * FROM app.audit_events) d), 0, 'audit events that did not concern the learner are byte-identical');
SELECT is((SELECT count(*)::int FROM (SELECT * FROM keep_lane_notes EXCEPT SELECT * FROM zz_lane.notes) d) + (SELECT count(*)::int FROM zz_lane.notes) - (SELECT count(*)::int FROM keep_lane_notes), 0, 'the test module kept the other learner''s rows');
SELECT is((SELECT count(*)::int FROM zz_lane.attempt_bonus), (SELECT count(*)::int FROM keep_lane_bonus), 'and the other learner''s rows that reference attempts');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT app.sync_apply_operation('22222222-2222-4222-8222-000000000003','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000202","response":{"choice_id":"a"}}', sha256('b3'), 'mep-canon-1') #>> '{result,change_version}'$$), '3', 'B keeps syncing and the change version is still gap-free');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT account.get_own_requests() #>> '{deletion_request,status}'$$), 'requested', 'B still sees their own open request');

-- ---- the protections were never changed and still apply to everyone -------------------------
SELECT is(current_setting('session_replication_role'), 'origin', 'triggers are on in this session after the erasure');
SELECT is((SELECT count(*)::int FROM ((SELECT t.oid, t.tgname, t.tgenabled, t.tgfoid, t.tgtype, pg_get_triggerdef(t.oid) AS def
                                       FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
                                       WHERE c.relnamespace = 'app'::regnamespace AND NOT t.tgisinternal
                                       EXCEPT SELECT * FROM triggers_before)
                                      UNION ALL
                                      (SELECT * FROM triggers_before b WHERE NOT (SELECT tgisinternal FROM pg_trigger WHERE oid = b.oid)
                                       EXCEPT SELECT t.oid, t.tgname, t.tgenabled, t.tgfoid, t.tgtype, pg_get_triggerdef(t.oid)
                                       FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
                                       WHERE c.relnamespace = 'app'::regnamespace)) d), 0,
    'every app trigger is the same catalog row, same definition, same enabled state as before');
SELECT is((SELECT count(*)::int FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
           WHERE c.relnamespace = 'app'::regnamespace AND NOT t.tgisinternal AND t.tgenabled = 'O'), 16,
    'all 16 integrity triggers are enabled');
SELECT is((SELECT count(*)::int FROM ((SELECT p.oid, p.proname, p.prosrc, p.proconfig, p.prosecdef, p.proacl::text FROM pg_proc p WHERE p.pronamespace = 'app'::regnamespace
                                       EXCEPT SELECT * FROM functions_before)
                                      UNION ALL
                                      (SELECT * FROM functions_before
                                       EXCEPT SELECT p.oid, p.proname, p.prosrc, p.proconfig, p.prosecdef, p.proacl::text FROM pg_proc p WHERE p.pronamespace = 'app'::regnamespace)) d), 0,
    'every app function is unchanged (source, settings, privileges)');
SELECT throws_ok($$DELETE FROM app.practice_attempts WHERE learner_id = 'a0000000-0000-4000-8000-000000000002'$$, 'P0001', 'Append-only records cannot be updated or deleted', 'attempts are still append-only, even for the owner');
SELECT throws_ok($$UPDATE app.practice_attempts SET score = 1$$, 'P0001', 'Append-only records cannot be updated or deleted', 'attempts still cannot be rescored');
SELECT throws_ok($$DELETE FROM app.sync_receipts$$, 'P0001', 'Append-only records cannot be updated or deleted', 'receipts are still append-only');
SELECT throws_ok($$DELETE FROM app.account_change_feed$$, 'P0001', 'Append-only records cannot be updated or deleted', 'the change feed is still append-only');
SELECT throws_ok($$UPDATE app.audit_events SET action = 'tampered.event'$$, 'P0001', 'Append-only records cannot be updated or deleted', 'audit events are still append-only');
SELECT throws_ok($$DELETE FROM app.learner_profiles WHERE user_id = 'a0000000-0000-4000-8000-000000000002'$$, '23503', NULL, 'foreign keys are enforced again: a profile with learning data cannot be deleted directly');
SELECT matches(pg_temp.as_executor($$DELETE FROM app.sync_receipts RETURNING 1$$), '^ERROR:42501', 'the executor still cannot delete anything directly');

-- ---- audit record of the erasure: counts only ---------------------------------------------
SELECT is((SELECT count(*)::int FROM seam_calls WHERE action = 'account.learner_erased'), 1, 'exactly one erasure audit call (failed attempts left none)');
SELECT is((SELECT target_id FROM seam_calls WHERE action = 'account.learner_erased'), NULL, 'the erasure audit call has no target id');
SELECT is((SELECT position('a0000000-0000-4000-8000-000000000001' IN details::text) FROM seam_calls WHERE action = 'account.learner_erased'), 0, 'and its details do not contain the id');
SELECT is((SELECT details #>> '{counts,app.practice_attempts}' FROM seam_calls WHERE action = 'account.learner_erased'), '2', 'it records how much was erased');

-- ---- idempotent / unknown ids ----------------------------------------------------------
SELECT is((pg_temp.as_executor($$SELECT account.erase_learner('a0000000-0000-4000-8000-000000000001')$$)::jsonb) #>> '{counts,app.learner_profiles}', '0', 'erasing again finds nothing and succeeds');
SELECT is((pg_temp.as_executor($$SELECT account.erase_learner('99999999-9999-4999-8999-999999999999')$$)::jsonb) ->> 'erased', 'true', 'an id that was never here is not an error');
SELECT is((SELECT count(*)::int FROM app.practice_attempts WHERE learner_id = :B::uuid), 2, 'B attempts are all still there at the end');

SELECT * FROM finish();
ROLLBACK;
