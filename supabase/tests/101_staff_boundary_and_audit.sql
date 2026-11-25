-- Behaviour of the shared platform interface: who may call it, role checks,
-- audit attribution, audit input limits, append-only audit.
BEGIN;
SELECT * FROM no_plan();

-- Run one statement AS THE GIVEN ROLE with the given actor, then switch back.
-- Returns the first column of the first row as text, or 'ERROR:<sqlstate>'.
GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_worker TO postgres WITH INHERIT FALSE, SET TRUE;
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

\set A '''a0000000-0000-4000-8000-000000000001'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
\set REVIEWER '''a0000000-0000-4000-8000-000000000004'''

-- ---- the student API role is shut out of both schemas ------------------------------
SELECT is(pg_temp.as_role('edu_api', :EDITOR::uuid, $$SELECT ops.audit_write('staff.access', NULL, NULL, 'allowed')$$), 'ERROR:42501', 'edu_api cannot write audit events, even as a staff user');
SELECT is(pg_temp.as_role('edu_api', :EDITOR::uuid, $$SELECT staff.actor_roles()$$), 'ERROR:42501', 'edu_api cannot read staff roles');
SELECT is(pg_temp.as_role('edu_api', :EDITOR::uuid, $$SELECT staff.actor_has_role('editor')$$), 'ERROR:42501', 'edu_api cannot test a staff role');
SELECT is(pg_temp.as_role('edu_api', :EDITOR::uuid, $$SELECT staff.require_role('editor')$$), 'ERROR:42501', 'edu_api cannot call require_role');
SELECT is(pg_temp.as_role('edu_api', :A::uuid, $$SELECT ops.actor_kind_for('postgres')$$), 'ERROR:42501', 'edu_api cannot call ops helpers');
SELECT is(pg_temp.as_role('edu_api', :A::uuid, $$SELECT ops.check_audit_details('{}')$$), 'ERROR:42501', 'edu_api cannot call the audit detail check');
SELECT is(pg_temp.as_role('edu_api', :A::uuid, $$SELECT staff.check_role_names(ARRAY['admin'])$$), 'ERROR:42501', 'edu_api cannot call staff helpers');
SELECT is(pg_temp.as_role('edu_api', :A::uuid, $$SELECT count(*) FROM pg_proc WHERE pronamespace = 'ops'::regnamespace AND has_function_privilege(oid, 'EXECUTE')$$), '0', 'edu_api can execute nothing in ops');
SELECT is(pg_temp.as_role('edu_api', :A::uuid, $$SELECT count(*) FROM pg_proc WHERE pronamespace = 'staff'::regnamespace AND has_function_privilege(oid, 'EXECUTE')$$), '0', 'edu_api can execute nothing in staff');
SELECT is(pg_temp.as_role('edu_api', :A::uuid, $$SELECT has_schema_privilege('ops', 'USAGE') OR has_schema_privilege('staff', 'USAGE')$$), 'false', 'edu_api sees neither schema');

-- ---- Supabase Data API roles cannot reach either schema ----------------------------
SET LOCAL ROLE anon;
SELECT throws_ok($$SELECT ops.audit_write('staff.access', NULL, NULL, 'allowed')$$, '42501', NULL, 'anon: schema ops is unreachable');
SELECT throws_ok($$SELECT staff.actor_roles()$$, '42501', NULL, 'anon: schema staff is unreachable');
RESET ROLE;
SET LOCAL ROLE authenticated;
SELECT throws_ok($$SELECT ops.audit_write('staff.access', NULL, NULL, 'allowed')$$, '42501', NULL, 'authenticated (Data API): schema ops is unreachable');
SELECT throws_ok($$SELECT staff.require_role('admin')$$, '42501', NULL, 'authenticated (Data API): schema staff is unreachable');
RESET ROLE;
SET LOCAL ROLE service_role;
SELECT throws_ok($$SELECT ops.audit_write('staff.access', NULL, NULL, 'allowed')$$, '42501', NULL, 'service_role (Data API secret key): schema ops is unreachable');
SELECT throws_ok($$SELECT staff.actor_roles()$$, '42501', NULL, 'service_role (Data API secret key): schema staff is unreachable');
RESET ROLE;

-- ---- role checks: the actor's ACTIVE roles ------------------------------------------
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.actor_roles()::text$$), '{editor}', 'editor: actor_roles');
SELECT is(pg_temp.as_role('edu_staff', :REVIEWER::uuid, $$SELECT staff.actor_roles()::text$$), '{reviewer}', 'reviewer: actor_roles');
SELECT is(pg_temp.as_role('edu_staff', :A::uuid, $$SELECT staff.actor_roles()::text$$), '{}', 'a learner has no staff role');
SELECT is(pg_temp.as_role('edu_staff', NULL, $$SELECT staff.actor_roles()::text$$), '{}', 'no actor: no staff role');

SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.actor_has_role('editor')$$), 'true', 'editor has editor');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.actor_has_role('reviewer')$$), 'false', 'editor does not have reviewer');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.actor_has_role('reviewer', 'editor', 'admin')$$), 'true', 'any one of several roles is enough');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.actor_has_role(VARIADIC ARRAY['publisher','admin'])$$), 'false', 'explicit VARIADIC array form');
SELECT is(pg_temp.as_role('edu_staff', :A::uuid, $$SELECT staff.actor_has_role('editor', 'reviewer', 'publisher', 'admin')$$), 'false', 'a learner has none of the roles');
SELECT is(pg_temp.as_role('edu_staff', NULL, $$SELECT staff.actor_has_role('editor')$$), 'false', 'no actor: actor_has_role is false');

SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.require_role('editor')$$), 'a0000000-0000-4000-8000-000000000003', 'require_role returns the actor id');
SELECT is(pg_temp.as_role('edu_staff', :REVIEWER::uuid, $$SELECT staff.require_role('admin', 'reviewer')$$), 'a0000000-0000-4000-8000-000000000004', 'require_role accepts any one of several roles');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.require_role('publisher')$$), 'ERROR:42501', 'editor is refused a publisher action');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.require_role('reviewer', 'publisher', 'admin')$$), 'ERROR:42501', 'editor is refused when none of the roles match');
SELECT is(pg_temp.as_role('edu_staff', :A::uuid, $$SELECT staff.require_role('editor', 'reviewer', 'publisher', 'admin')$$), 'ERROR:42501', 'a learner is refused every staff action');
SELECT is(pg_temp.as_role('edu_staff', NULL, $$SELECT staff.require_role('editor')$$), 'ERROR:42501', 'no actor: refused');
SELECT throws_ok($$SELECT staff.require_role('publisher')$$, '42501', 'A staff role is required for this action',
    'the refusal does not say which role was needed');

-- unknown or missing role names fail loudly instead of silently never matching
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.actor_has_role('Editor')$$), 'ERROR:22023', 'role names are case-sensitive: a misspelt role is an error');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.require_role('editor', 'superuser')$$), 'ERROR:22023', 'an unknown role next to a held one is still an error');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.require_role(VARIADIC ARRAY[]::text[])$$), 'ERROR:22023', 'an empty role list is an error, not "anyone"');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.require_role(VARIADIC NULL::text[])$$), 'ERROR:22023', 'a NULL role list is an error');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.actor_has_role('editor', NULL)$$), 'ERROR:22023', 'a NULL role name is an error');

-- an INACTIVE role row grants nothing
UPDATE app.staff_roles SET is_active = false WHERE user_id = :EDITOR AND role = 'editor';
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.actor_roles()::text$$), '{}', 'inactive role: not listed');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.actor_has_role('editor')$$), 'false', 'inactive role: actor_has_role is false');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.require_role('editor')$$), 'ERROR:42501', 'inactive role: refused');
INSERT INTO app.staff_roles (user_id, role, is_active) VALUES (:EDITOR, 'publisher', true), (:EDITOR, 'admin', false);
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.actor_roles()::text$$), '{publisher}', 'only the active roles of a person count');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.require_role('editor', 'admin')$$), 'ERROR:42501', 'two inactive roles do not add up to one');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.require_role('publisher')$$), 'a0000000-0000-4000-8000-000000000003', 'the active role works');
DELETE FROM app.staff_roles WHERE user_id = :EDITOR AND role IN ('publisher', 'admin');
UPDATE app.staff_roles SET is_active = true WHERE user_id = :EDITOR AND role = 'editor';

-- ---- the staff and worker roles have NO direct access to any table --------------------
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, 'SELECT count(*) FROM app.staff_roles'), 'ERROR:42501', 'edu_staff cannot read staff_roles directly');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$INSERT INTO app.staff_roles (user_id, role) VALUES ('a0000000-0000-4000-8000-000000000003', 'admin') RETURNING 1$$), 'ERROR:42501', 'edu_staff cannot grant itself a role');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$UPDATE app.staff_roles SET is_active = true RETURNING 1$$), 'ERROR:42501', 'edu_staff cannot reactivate a role');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, 'SELECT count(*) FROM app.audit_events'), 'ERROR:42501', 'edu_staff cannot read audit events');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$INSERT INTO app.audit_events (actor_id, actor_kind, action, outcome) VALUES (NULL, 'system', 'forged.event', 'allowed') RETURNING 1$$), 'ERROR:42501', 'edu_staff cannot insert audit events around audit_write');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$UPDATE app.audit_events SET outcome = 'allowed' RETURNING 1$$), 'ERROR:42501', 'edu_staff cannot edit audit events');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, 'DELETE FROM app.audit_events RETURNING 1'), 'ERROR:42501', 'edu_staff cannot delete audit events');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$UPDATE app.lesson_revisions SET title = 'x' RETURNING 1$$), 'ERROR:42501', 'edu_staff cannot edit lessons directly (only through staff.* functions)');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, 'SELECT count(*) FROM app.practice_attempts'), 'ERROR:42501', 'edu_staff cannot read learner attempts');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, 'SELECT count(*) FROM app.learner_profiles'), 'ERROR:42501', 'edu_staff cannot read learner profiles');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, 'SELECT app.current_actor_id()'), 'ERROR:42501', 'edu_staff cannot call app functions');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, 'SELECT count(*) FROM auth.users'), 'ERROR:42501', 'edu_staff cannot read auth.users');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT ops.actor_kind_for('postgres')$$), 'ERROR:42501', 'edu_staff cannot call internal ops helpers');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT staff.check_role_names(ARRAY['admin'])$$), 'ERROR:42501', 'edu_staff cannot call internal staff helpers');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, 'CREATE TABLE staff.exfil (x int)'), 'ERROR:42501', 'edu_staff cannot create objects in staff');

SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT staff.actor_roles()$$), 'ERROR:42501', 'edu_worker cannot use schema staff');
SELECT is(pg_temp.as_role('edu_worker', :EDITOR::uuid, $$SELECT staff.require_role('editor')$$), 'ERROR:42501', 'edu_worker cannot pass a staff role check');
SELECT is(pg_temp.as_role('edu_worker', NULL, 'SELECT count(*) FROM app.background_jobs'), 'ERROR:42501', 'edu_worker cannot read the job table directly');
SELECT is(pg_temp.as_role('edu_worker', NULL, 'SELECT count(*) FROM app.audit_events'), 'ERROR:42501', 'edu_worker cannot read audit events');
SELECT is(pg_temp.as_role('edu_worker', NULL, 'SELECT count(*) FROM app.practice_attempts'), 'ERROR:42501', 'edu_worker cannot read learner attempts');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$INSERT INTO app.audit_events (actor_kind, action, outcome) VALUES ('worker', 'forged.event', 'allowed') RETURNING 1$$), 'ERROR:42501', 'edu_worker cannot insert audit events around audit_write');

-- ---- audit_write: attribution ---------------------------------------------------------
-- actor_id is the transaction's verified actor; nothing in the call can change it.
CREATE TEMP TABLE written (label text PRIMARY KEY, id uuid);
GRANT SELECT ON written TO edu_staff, edu_worker;
INSERT INTO written VALUES ('editor', pg_temp.as_role('edu_staff', :EDITOR::uuid,
    $$SELECT ops.audit_write('lesson_revision.submit', 'lesson_revision', 'c0000000-0000-4000-8000-000000000001', 'allowed', '{"from_status":"draft","to_status":"in_review","revision":1}')$$)::uuid);
INSERT INTO written VALUES ('learner', pg_temp.as_role('edu_staff', :A::uuid,
    $$SELECT ops.audit_write('staff.access', NULL, NULL, 'denied', '{"method":"GET","route":"/v1/staff/things/{thing_id}","required_roles":["editor","admin"]}')$$)::uuid);
INSERT INTO written VALUES ('worker', pg_temp.as_role('edu_worker', NULL,
    $$SELECT ops.audit_write('job.dead', 'background_job', gen_random_uuid(), 'error', '{"error_class":"TimeoutError","attempts":5}')$$)::uuid);
INSERT INTO written VALUES ('defaults', pg_temp.as_role('edu_worker', NULL,
    $$SELECT ops.audit_write('job.swept', NULL, NULL, 'allowed')$$)::uuid);

SELECT is((SELECT count(*)::int FROM written WHERE id IS NOT NULL), 4, 'audit_write returns the id of the new event');
SELECT is((SELECT row(e.actor_id, e.action, e.target_kind, e.target_id, e.outcome, e.details)::text
           FROM app.audit_events e JOIN written w ON w.id = e.id WHERE w.label = 'editor'),
    row('a0000000-0000-4000-8000-000000000003'::uuid, 'lesson_revision.submit', 'lesson_revision',
        'c0000000-0000-4000-8000-000000000001'::uuid, 'allowed',
        '{"from_status":"draft","to_status":"in_review","revision":1}'::jsonb)::text,
    'the event is stored as given, attributed to the transaction actor');
SELECT is((SELECT row(e.actor_id, e.outcome)::text FROM app.audit_events e JOIN written w ON w.id = e.id WHERE w.label = 'learner'),
    row('a0000000-0000-4000-8000-000000000001'::uuid, 'denied')::text,
    'a refusal is attributed to the account that was refused');
SELECT is((SELECT row(e.actor_id, e.outcome, e.details)::text FROM app.audit_events e JOIN written w ON w.id = e.id WHERE w.label = 'worker'),
    row(NULL::uuid, 'error', '{"error_class":"TimeoutError","attempts":5}'::jsonb)::text,
    'a worker event has no actor');
SELECT is((SELECT row(e.target_kind, e.target_id, e.details)::text FROM app.audit_events e JOIN written w ON w.id = e.id WHERE w.label = 'defaults'),
    row(NULL::text, NULL::uuid, '{}'::jsonb)::text, 'details default to an empty object');
SELECT is((SELECT count(*)::int FROM app.audit_events e JOIN written w ON w.id = e.id
           WHERE e.created_at IS DISTINCT FROM now()), 0, 'created_at is the server transaction time');
-- This test session is logged in as postgres, which USES none of the three group roles.
SELECT is((SELECT array_agg(DISTINCT e.actor_kind) FROM app.audit_events e JOIN written w ON w.id = e.id),
    ARRAY['system'], 'actor_kind follows the session login, not the current role (SET ROLE cannot fake it)');

-- actor_kind per database login (real logins are exercised by the API tests)
CREATE ROLE t_staff_login LOGIN;   GRANT edu_staff TO t_staff_login;
CREATE ROLE t_worker_login LOGIN;  GRANT edu_worker TO t_worker_login;
CREATE ROLE t_api_login LOGIN;     GRANT edu_api TO t_api_login;
CREATE ROLE t_other_login LOGIN;
CREATE ROLE t_mixed_login LOGIN;   GRANT edu_api, edu_staff TO t_mixed_login;
SELECT is(ops.actor_kind_for('t_staff_login'), 'staff', 'a login that uses edu_staff writes as staff');
SELECT is(ops.actor_kind_for('t_worker_login'), 'worker', 'a login that uses edu_worker writes as worker');
SELECT is(ops.actor_kind_for('t_api_login'), 'user', 'a login that uses edu_api writes as user');
SELECT is(ops.actor_kind_for('t_other_login'), 'system', 'any other login writes as system');
SELECT is(ops.actor_kind_for('postgres'), 'system', 'the owner (ADMIN-only membership in the groups) writes as system');
SELECT is(ops.actor_kind_for('t_mixed_login'), 'staff', 'a wrongly mixed login is recorded with the stronger kind');
SELECT is(ops.actor_kind_for('authenticator'), 'system', 'the Data API login is not a staff, worker or user login');
SELECT is(ops.actor_kind_for('supabase_admin'), 'system', 'a superuser session is system, never staff (pg_has_role is true for superusers)');
SELECT is((SELECT count(*)::int FROM pg_roles WHERE rolsuper AND ops.actor_kind_for(rolname) <> 'system'), 0, 'no superuser is labelled staff, worker or user');
SELECT is(pg_temp.as_role('edu_staff', NULL, 'SELECT ops.session_kind()'), 'system', 'session_kind reports the login of the session (postgres here), whatever the current role');
SELECT is(pg_temp.as_role('edu_worker', NULL, 'SELECT ops.session_kind()'), 'system', 'edu_worker may ask for its session kind');
SELECT is(pg_temp.as_role('edu_api', NULL, 'SELECT ops.session_kind()'), 'ERROR:42501', 'edu_api cannot call session_kind');

-- ---- audit_write: input limits (no free text) -----------------------------------------
CREATE FUNCTION pg_temp.audit_try(p_action text, p_kind text, p_id uuid, p_outcome text, p_details jsonb) RETURNS text
LANGUAGE plpgsql AS $fn$
BEGIN
    PERFORM ops.audit_write(p_action, p_kind, p_id, p_outcome, p_details);
    RETURN 'ok';
EXCEPTION WHEN OTHERS THEN
    RETURN 'ERROR:' || SQLSTATE;
END;
$fn$;
SELECT is(pg_temp.audit_try('pack_release.activate', 'pack_release', gen_random_uuid(), 'allowed', '{}'), 'ok', 'a well-formed event is accepted');
SELECT is(pg_temp.audit_try(NULL, NULL, NULL, 'allowed', '{}'), 'ERROR:22023', 'action is required');
SELECT is(pg_temp.audit_try('login', NULL, NULL, 'allowed', '{}'), 'ERROR:22023', 'action must be a dotted code');
SELECT is(pg_temp.audit_try('Staff.Access', NULL, NULL, 'allowed', '{}'), 'ERROR:22023', 'action must be lower-case');
SELECT is(pg_temp.audit_try('staff.access denied for Jean', NULL, NULL, 'allowed', '{}'), 'ERROR:22023', 'action cannot carry free text');
SELECT is(pg_temp.audit_try('a.' || repeat('b', 99), NULL, NULL, 'allowed', '{}'), 'ERROR:22023', 'action is limited to 100 characters');
SELECT is(pg_temp.audit_try('staff.access', 'Lesson Revision', NULL, 'allowed', '{}'), 'ERROR:22023', 'target kind must be a snake_case name');
SELECT is(pg_temp.audit_try('staff.access', NULL, gen_random_uuid(), 'allowed', '{}'), 'ERROR:22023', 'a target id needs a target kind');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'maybe', '{}'), 'ERROR:22023', 'outcome must be allowed, denied or error');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, NULL, '{}'), 'ERROR:22023', 'outcome is required');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', NULL), 'ok', 'NULL details are stored as {}');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', '["a"]'), 'ERROR:22023', 'details must be an object');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', '"text"'), 'ERROR:22023', 'details cannot be a bare string');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', '{"note":"the learner wrote this sentence"}'), 'ERROR:22023', 'a sentence is refused (no whitespace in values)');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', '{"name":"Élève"}'), 'ERROR:22023', 'non-ASCII text is refused');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', '{"email":"someone@example.test"}'), 'ERROR:22023', 'an e-mail address is refused');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', jsonb_build_object('code', repeat('x', 65))), 'ERROR:22023', 'strings are limited to 64 characters');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', jsonb_build_object('code', repeat('x', 64))), 'ok', 'a 64-character code is accepted');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', jsonb_build_object('route', '/' || repeat('x', 119))), 'ok', 'only the key "route" may hold up to 120 characters');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', jsonb_build_object('route', '/' || repeat('x', 120))), 'ERROR:22023', 'a route is limited to 120 characters');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', jsonb_build_object('routes', jsonb_build_array(repeat('x', 65)))), 'ERROR:22023', 'array items are limited to 64 characters');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', jsonb_build_object('blob', jsonb_build_array(repeat('A', 64), repeat('B', 64), repeat('C', 64)))), 'ok', 'KNOWN LIMIT: short machine-looking chunks pass; the check is structural');
-- Pinned on purpose (review finding M2): these personal-data-shaped values are
-- ACCEPTED by the structural check. Callers must never pass learner-typed values.
SELECT is((SELECT array_agg(v ORDER BY v) FROM unnest(ARRAY[
        '{"answer":"Paris"}', '{"name":"Jean-Pierre.Dupont"}', '{"phone":"+50937123456"}',
        '{"dob":"2014-03-09"}', '{"ip":"192.168.1.20"}', '{"note":"my_teacher_hits_me_at_school"}']) AS v
     WHERE pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', v::jsonb) <> 'ok'),
    NULL, 'KNOWN LIMIT: one-word answers, names, phone numbers, dates and addresses are not recognised as personal data');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', '{"response":{"choice_id":"b"}}'), 'ERROR:22023', 'nested objects are refused (no payload dumps)');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', '{"items":[["a"]]}'), 'ERROR:22023', 'nested arrays are refused');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', '{"items":["ok","not ok"]}'), 'ERROR:22023', 'array items follow the same string rule');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', '{"items":[null]}'), 'ERROR:22023', 'array items cannot be null');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed', '{"Bad Key":1}'), 'ERROR:22023', 'keys must be snake_case names');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed',
    (SELECT jsonb_object_agg('k' || n, n) FROM generate_series(1, 25) AS n)), 'ERROR:22023', 'at most 24 keys');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed',
    (SELECT jsonb_object_agg('k' || n, n) FROM generate_series(1, 24) AS n)), 'ok', '24 keys are accepted');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed',
    jsonb_build_object('items', (SELECT jsonb_agg(n) FROM generate_series(1, 25) AS n))), 'ERROR:22023', 'at most 24 array items');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed',
    (SELECT jsonb_object_agg('k' || n, repeat('x', 110)) FROM generate_series(1, 20) AS n)), 'ERROR:22023', 'details are limited to 2048 bytes in total');
SELECT is(pg_temp.audit_try('staff.access', NULL, NULL, 'allowed',
    '{"at":"2026-11-24T10:00:00.000+00:00","id":"c0000000-0000-4000-8000-000000000001","n":3,"ok":true,"none":null,"roles":["editor","admin"],"ratio":0.5}'), 'ok',
    'timestamps, uuids, numbers, booleans, null and lists of codes are accepted');
SELECT throws_ok($$SELECT ops.audit_write('staff.access', NULL, NULL, 'allowed', '{"note":"secret words here"}')$$, '22023',
    'Audit detail strings must be short machine values (no free text)', 'the error does not echo the rejected value');

-- ---- audit events stay append-only -------------------------------------------------------
SELECT throws_ok($$UPDATE app.audit_events SET outcome = 'allowed' WHERE id = (SELECT id FROM written WHERE label = 'learner')$$,
    'P0001', 'Append-only records cannot be updated or deleted', 'even the owner cannot rewrite an audit event');
SELECT throws_ok($$DELETE FROM app.audit_events WHERE id = (SELECT id FROM written WHERE label = 'learner')$$,
    'P0001', 'Append-only records cannot be updated or deleted', 'even the owner cannot delete an audit event');
SELECT is((SELECT outcome FROM app.audit_events WHERE id = (SELECT id FROM written WHERE label = 'learner')), 'denied',
    'the event is unchanged');

SELECT * FROM finish();
ROLLBACK;
