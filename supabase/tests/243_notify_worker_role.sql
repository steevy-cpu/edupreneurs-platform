-- The worker role in schema notify: what edu_worker can do, and that edu_api and
-- edu_staff still cannot create, claim or report a notification.
BEGIN;
SELECT * FROM no_plan();
GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_worker TO postgres WITH INHERIT FALSE, SET TRUE;
-- Run one statement AS p_role with the given actor. Returns the first column of
-- the first row as text, or 'ERROR:<sqlstate>'.
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

TRUNCATE notify.delivery_attempts, notify.deliveries, notify.outbox, notify.preferences;
-- Quiet hours depend on the hour this test runs at; move the platform window
-- away from "now" (rolled back). Exact instants are tested in 242.
UPDATE notify.policy SET
    quiet_start = ((now() AT TIME ZONE 'America/Port-au-Prince') + interval '6 hours')::time,
    quiet_end = ((now() AT TIME ZONE 'America/Port-au-Prince') + interval '7 hours')::time;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''

-- ---- structure ------------------------------------------------------------------
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'notify'::regnamespace AND has_function_privilege('edu_worker', p.oid, 'EXECUTE')),
    ARRAY['claim_due','enqueue','recheck_lease','record_attempt'],
    'edu_worker may execute exactly claim_due, enqueue, recheck_lease and record_attempt');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'notify'::regnamespace
           AND has_function_privilege('edu_staff', p.oid, 'EXECUTE')), 0,
    'edu_staff may execute nothing in notify');
SELECT is(has_schema_privilege('edu_worker', 'notify', 'USAGE'), true, 'edu_worker can use schema notify');
SELECT is(has_schema_privilege('edu_worker', 'notify', 'CREATE'), false, 'edu_worker cannot create objects in notify');
SELECT is(has_schema_privilege('edu_staff', 'notify', 'USAGE'), false, 'edu_staff cannot use schema notify');
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'notify' AND grantee IN ('edu_worker','edu_staff')), 0,
    'edu_worker and edu_staff hold no table privilege in notify');
SELECT is((SELECT count(*)::int FROM information_schema.column_privileges
           WHERE table_schema = 'notify' AND grantee IN ('edu_worker','edu_staff')), 0,
    '... and no column privilege');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'notify'
           AND roles && ARRAY['edu_worker','edu_staff']::name[]), 0,
    'no notify policy mentions edu_worker or edu_staff');

-- ---- edu_api and edu_staff still cannot create, claim or report -------------------
SELECT is(pg_temp.as_role('edu_api', :A::uuid, $$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}','k')$$), 'ERROR:42501', 'edu_api cannot enqueue');
SELECT is(pg_temp.as_role('edu_api', :A::uuid, $$SELECT count(*) FROM notify.claim_due('push')$$), 'ERROR:42501', 'edu_api cannot claim');
SELECT is(pg_temp.as_role('edu_api', :A::uuid, $$SELECT notify.record_attempt(gen_random_uuid(),'push',gen_random_uuid(),'delivered')$$), 'ERROR:42501', 'edu_api cannot report');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}','k')$$), 'ERROR:42501', 'edu_staff cannot enqueue, even as a real staff member');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT count(*) FROM notify.claim_due('push')$$), 'ERROR:42501', 'edu_staff cannot claim');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT notify.record_attempt(gen_random_uuid(),'push',gen_random_uuid(),'delivered')$$), 'ERROR:42501', 'edu_staff cannot report');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, 'SELECT count(*) FROM notify.outbox'), 'ERROR:42501', 'edu_staff cannot read learner notifications');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, 'SELECT count(*) FROM notify.preferences'), 'ERROR:42501', 'edu_staff cannot read learner preferences');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT notify.set_preferences(true, '{}', NULL, NULL)$$), 'ERROR:42501', 'edu_staff cannot set preferences');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT notify.erase_learner('a0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'edu_staff cannot erase through notify directly');
SELECT is((SELECT count(*)::int FROM notify.outbox), 0, 'nothing was created by any of the refused calls');

-- ---- what the worker can do --------------------------------------------------------
INSERT INTO notify.preferences (learner_id, push_enabled) VALUES (:A, true);
SELECT isnt(pg_temp.as_role('edu_worker', NULL, $$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}','job-1', ARRAY['push','in_app'])$$), 'ERROR:42501', 'edu_worker can enqueue (a scheduled job)');
SELECT is((SELECT count(*)::int FROM notify.outbox WHERE recipient_id = :A), 1, '... one event exists');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{"word_id":"Bonjour"}','job-2')$$), 'ERROR:22023', 'the worker is bound by the same "ids only" rule');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','marketing_blast','{}','job-3')$$), 'ERROR:22023', 'the worker is bound by the kind allow-list');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000002','sync_reminder','{}','job-4', ARRAY['push'])$$) ~ '^[0-9a-f-]{36}$', true, 'edu_worker enqueues a push for B, who never opted in');

SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT attempt_no || '|' || kind || '|' || channel FROM notify.claim_due('push', 20, 60)$$), '1|sync_reminder|push', 'edu_worker claims the one delivery that may be pushed');
SELECT is((SELECT string_agg(d.state || ':' || COALESCE(d.last_error_code, '-'), ',' ORDER BY o.recipient_id)
           FROM notify.deliveries d JOIN notify.outbox o ON o.id = d.outbox_id),
    'leased:-,suppressed:push_not_enabled',
    'the opt-in rule is applied inside claim_due: the worker never receives B''s delivery');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT count(*) FROM notify.claim_due('push')$$), '0', 'a leased delivery is not handed out twice');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT notify.record_attempt((SELECT gen_random_uuid()), 'push', gen_random_uuid(), 'delivered')$$), 'stale', 'a report without a valid lease is stale');
SELECT lease_token AS token, outbox_id AS event FROM notify.deliveries WHERE state = 'leased' \gset
SELECT is(pg_temp.as_role('edu_worker', NULL, format($$SELECT notify.record_attempt(%L, 'push', %L, 'delivered')$$, :'event', :'token')), 'delivered', 'edu_worker reports the delivery');
SELECT is((SELECT state FROM notify.outbox WHERE id = :'event'), 'settled', '... and the event is settled');

-- ---- what the worker cannot do -------------------------------------------------------
SELECT is(pg_temp.as_role('edu_worker', NULL, 'SELECT count(*) FROM notify.outbox'), 'ERROR:42501', 'edu_worker cannot read the outbox table');
SELECT is(pg_temp.as_role('edu_worker', NULL, 'SELECT count(*) FROM notify.deliveries'), 'ERROR:42501', 'edu_worker cannot read delivery state directly');
SELECT is(pg_temp.as_role('edu_worker', NULL, 'SELECT count(*) FROM notify.preferences'), 'ERROR:42501', 'edu_worker cannot read learner preferences');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$UPDATE notify.policy SET quiet_start = '00:00' RETURNING 1$$), 'ERROR:42501', 'edu_worker cannot change quiet hours');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$UPDATE notify.deliveries SET state = 'delivered' RETURNING 1$$), 'ERROR:42501', 'edu_worker cannot mark deliveries around the function');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT count(*) FROM notify._claim_due_at('push', 20, 60, now() + interval '12 hours')$$), 'ERROR:42501', 'edu_worker cannot choose the clock (no way around quiet hours)');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT notify._record_attempt_at(gen_random_uuid(), 'push', gen_random_uuid(), 'delivered', NULL, now())$$), 'ERROR:42501', 'edu_worker cannot call the internal report');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT notify._settle(gen_random_uuid())$$), 'ERROR:42501', 'edu_worker cannot call _settle');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT notify.erase_learner('a0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'edu_worker cannot erase a learner');
SELECT is(pg_temp.as_role('edu_worker', :A::uuid, $$SELECT notify.set_preferences(true, '{}', NULL, NULL)$$), 'ERROR:42501', 'edu_worker cannot opt a learner in, even with the actor set');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT notify.quiet_until(now(), 'a0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'edu_worker cannot call the quiet-hours helper');

-- Quiet hours hold for the worker too (real clock: make "now" quiet).
UPDATE notify.policy SET
    quiet_start = ((now() AT TIME ZONE 'America/Port-au-Prince') - interval '1 hour')::time,
    quiet_end = ((now() AT TIME ZONE 'America/Port-au-Prince') + interval '2 hours')::time;
SELECT isnt(pg_temp.as_role('edu_worker', NULL, $$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}','job-night', ARRAY['push'])$$), NULL, 'another push for A, enqueued during quiet hours');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT count(*) FROM notify.claim_due('push')$$), '0', 'during quiet hours the worker is handed nothing');
SELECT is((SELECT d.state || '/' || d.attempt_count FROM notify.deliveries d JOIN notify.outbox o ON o.id = d.outbox_id
           WHERE o.recipient_id = :A AND d.state <> 'delivered'), 'pending/0', '... and no attempt is spent');

-- ---- recheck_lease (review finding L-2): the last question before an adapter call ----
UPDATE notify.policy SET
    quiet_start = ((now() AT TIME ZONE 'America/Port-au-Prince') + interval '6 hours')::time,
    quiet_end = ((now() AT TIME ZONE 'America/Port-au-Prince') + interval '7 hours')::time;
UPDATE notify.deliveries SET next_attempt_at = now() WHERE state = 'pending';
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT count(*) FROM notify.claim_due('push')$$), '1', 'outside quiet hours the night job is leased');
SELECT lease_token AS ltoken, outbox_id AS levent FROM notify.deliveries WHERE state = 'leased' \gset
SELECT is(pg_temp.as_role('edu_worker', NULL, format($$SELECT notify.recheck_lease(%L, 'push', gen_random_uuid())$$, :'levent')), 'stale', 'recheck with a foreign lease token is stale');
SELECT is(pg_temp.as_role('edu_worker', NULL, format($$SELECT notify.recheck_lease(%L, 'push', %L)$$, :'levent', :'ltoken')), 'send', 'recheck of a live lease outside quiet hours says send');
SELECT is(pg_temp.as_role('edu_api', :A::uuid, format($$SELECT notify.recheck_lease(%L, 'push', %L)$$, :'levent', :'ltoken')), 'ERROR:42501', 'edu_api cannot recheck leases');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, format($$SELECT notify.recheck_lease(%L, 'push', %L)$$, :'levent', :'ltoken')), 'ERROR:42501', 'edu_staff cannot recheck leases');
UPDATE notify.policy SET
    quiet_start = ((now() AT TIME ZONE 'America/Port-au-Prince') - interval '1 hour')::time,
    quiet_end = ((now() AT TIME ZONE 'America/Port-au-Prince') + interval '2 hours')::time;
SELECT is(pg_temp.as_role('edu_worker', NULL, format($$SELECT notify.recheck_lease(%L, 'push', %L)$$, :'levent', :'ltoken')), 'deferred', 'quiet hours began after the claim: deferred');
SELECT is((SELECT d.state || '/' || d.attempt_count || '/' || (d.lease_token IS NULL) || '/' || (d.next_attempt_at > now())
           FROM notify.deliveries d WHERE d.outbox_id = :'levent'), 'pending/0/true/true', '... back to pending, attempt given back, due after the window');
SELECT is(pg_temp.as_role('edu_worker', NULL, format($$SELECT notify.recheck_lease(%L, 'push', %L)$$, :'levent', :'ltoken')), 'stale', 'the old token is stale after a deferral');
UPDATE notify.deliveries SET state = 'leased', lease_token = :'ltoken', next_attempt_at = now() - interval '1 second', attempt_count = 1
WHERE outbox_id = :'levent';
SELECT is(pg_temp.as_role('edu_worker', NULL, format($$SELECT notify.recheck_lease(%L, 'push', %L)$$, :'levent', :'ltoken')), 'stale', 'a lease that has run out is stale');

SELECT * FROM finish();
ROLLBACK;
