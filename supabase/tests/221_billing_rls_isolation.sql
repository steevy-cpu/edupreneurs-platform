-- billing: who can read and write what — anonymous, Student A, Student B, a staff
-- user arriving through the student API — and proof that learning does not
-- depend on billing at all.
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

-- Start from empty state so counts are exact (rolled back at the end).
TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;
TRUNCATE billing.refunds, billing.entitlement_revocations, billing.entitlements,
         billing.provider_events, billing.orders, billing.plan_prices, billing.plans,
         billing.providers;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
\set COURSE '''b0000000-0000-4000-8000-000000000003'''

-- Fixture (as the owner): A holds an active 'all' grant and a course grant that
-- starts tomorrow; B holds an 'all' grant and a second one that was revoked.
SELECT is(billing.grant_entitlement(:A, 'all', NULL, now(), now() + interval '30 days', 'gift', NULL, 'rls-fixture-a-all', NULL) ->> 'status', 'granted', 'fixture: A all');
SELECT is(billing.grant_entitlement(:A, 'course', :COURSE, now() + interval '1 day', now() + interval '31 days', 'promo', NULL, 'rls-fixture-a-course', NULL) ->> 'status', 'granted', 'fixture: A course, future');
SELECT is(billing.grant_entitlement(:B, 'all', NULL, now(), now() + interval '30 days', 'gift', 'internal-ref-b', 'rls-fixture-b-all', :EDITOR) ->> 'status', 'granted', 'fixture: B all');
SELECT is(billing.grant_entitlement(:B, 'course', :COURSE, now(), now() + interval '30 days', 'trial', NULL, 'rls-fixture-b-revoked', NULL) ->> 'status', 'granted', 'fixture: B course');
SELECT is(billing.revoke_entitlement((SELECT id FROM billing.entitlements WHERE idempotency_key = 'rls-fixture-b-revoked'), 'staff_revoke', :EDITOR) ->> 'status', 'revoked', 'fixture: B course revoked');
INSERT INTO billing.providers (code, is_simulated, is_enabled) VALUES ('mock', true, true);
INSERT INTO billing.plans (id, code, scope_kind, duration_days) VALUES ('f0000000-0000-4000-8000-000000000001', 'synthetic-all-30', 'all', 30);
INSERT INTO billing.plan_prices (plan_id, currency, amount_minor) VALUES ('f0000000-0000-4000-8000-000000000001', 'HTG', 12345);

-- ---- no actor ---------------------------------------------------------------------
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM billing.entitlements'), '0', 'no actor: no grants');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM billing.entitlement_revocations'), '0', 'no actor: no revocations');
SELECT is(pg_temp.as_api(NULL, 'SELECT billing.is_entitled()'), 'false', 'no actor: not entitled');

-- ---- Student A sees only A ---------------------------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM billing.entitlements'), '2/0', 'A reads only own grants');
SELECT is(pg_temp.as_api(:B::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM billing.entitlements'), '2/0', 'B reads only own grants');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM billing.entitlements WHERE learner_id = 'a0000000-0000-4000-8000-000000000002'$$), '0', 'A cannot read B grants by learner id');
SELECT is(pg_temp.as_api(:A::uuid, format('SELECT count(*) FROM billing.entitlements WHERE id = %L', (SELECT id FROM billing.entitlements WHERE idempotency_key = 'rls-fixture-b-all'))), '0', 'A cannot read a B grant by its id');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM billing.entitlement_revocations'), '0', 'A sees no revocation (B''s is hidden)');
SELECT is(pg_temp.as_api(:B::uuid, 'SELECT count(*) FROM billing.entitlement_revocations'), '1', 'B sees own revocation');
SELECT is(pg_temp.as_api(:EDITOR::uuid, 'SELECT count(*) FROM billing.entitlements'), '0', 'a staff user sees no learner grants through the student API');

-- ---- internal columns are not readable at all ----------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT idempotency_key FROM billing.entitlements LIMIT 1'), 'ERROR:42501', 'A cannot read idempotency keys');
SELECT is(pg_temp.as_api(:B::uuid, 'SELECT granted_by FROM billing.entitlements LIMIT 1'), 'ERROR:42501', 'B cannot read which staff member granted');
SELECT is(pg_temp.as_api(:B::uuid, 'SELECT source_ref FROM billing.entitlements LIMIT 1'), 'ERROR:42501', 'B cannot read internal source references');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT order_id FROM billing.entitlements LIMIT 1'), 'ERROR:42501', 'A cannot read order ids');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT * FROM billing.entitlements LIMIT 1'), 'ERROR:42501', 'A cannot SELECT * from grants');
SELECT is(pg_temp.as_api(:B::uuid, 'SELECT revoked_by FROM billing.entitlement_revocations LIMIT 1'), 'ERROR:42501', 'B cannot read who revoked');

-- ---- the caller's own entitlement answer ----------------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT billing.is_entitled()'), 'true', 'A is entitled to all');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT billing.is_entitled('course', 'b0000000-0000-4000-8000-000000000003')$$), 'true', 'A is entitled to the course through the all grant');
SELECT is(pg_temp.as_api(:EDITOR::uuid, 'SELECT billing.is_entitled()'), 'false', 'an account with no grant is not entitled');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT billing.is_entitled('bogus', NULL)$$), 'false', 'an unknown scope kind is simply not entitled');

-- ---- no client request can create or extend a grant -------------------------------------
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO billing.entitlements (learner_id, scope_kind, starts_at, ends_at, source, idempotency_key) VALUES ('a0000000-0000-4000-8000-000000000001', 'all', now(), now() + interval '10 years', 'gift', 'self-grant-attempt') RETURNING 1$$), 'ERROR:42501', 'A cannot insert a grant for themselves');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$INSERT INTO billing.entitlements (learner_id, scope_kind, starts_at, ends_at, source, idempotency_key) VALUES ('a0000000-0000-4000-8000-000000000003', 'all', now(), now() + interval '1 year', 'staff_grant', 'staff-self-grant-attempt') RETURNING 1$$), 'ERROR:42501', 'a staff user cannot insert a grant through the student API');
SELECT is(pg_temp.as_api(:A::uuid, $$UPDATE billing.entitlements SET ends_at = ends_at + interval '10 years' RETURNING 1$$), 'ERROR:42501', 'A cannot extend a grant');
SELECT is(pg_temp.as_api(:A::uuid, $$UPDATE billing.entitlements SET starts_at = now() - interval '1 day' RETURNING 1$$), 'ERROR:42501', 'A cannot bring a future grant forward');
SELECT is(pg_temp.as_api(:A::uuid, 'DELETE FROM billing.entitlements RETURNING 1'), 'ERROR:42501', 'A cannot delete grants');
SELECT is(pg_temp.as_api(:B::uuid, 'DELETE FROM billing.entitlement_revocations RETURNING 1'), 'ERROR:42501', 'B cannot delete a revocation (un-revoke)');
SELECT is(pg_temp.as_api(:B::uuid, $$UPDATE billing.entitlement_revocations SET revoked_at = now() + interval '10 years' RETURNING 1$$), 'ERROR:42501', 'B cannot postpone a revocation');
SELECT is(pg_temp.as_api(:A::uuid, format('INSERT INTO billing.entitlement_revocations (entitlement_id, reason_code) VALUES (%L, $$staff_revoke$$) RETURNING 1', (SELECT id FROM billing.entitlements WHERE idempotency_key = 'rls-fixture-b-all'))), 'ERROR:42501', 'A cannot revoke B''s grant');

SELECT is(pg_temp.as_api(:A::uuid, $$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, now(), now() + interval '30 days', 'gift', NULL, 'self-grant-by-function', NULL)$$), 'ERROR:42501', 'A cannot call the grant function');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, 30, 'gift', 'goodwill', 'self-grant-by-staff-function')$$), 'ERROR:42501', 'A cannot call the staff grant function');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, 30, 'gift', 'goodwill', 'staff-grant-through-student-api')$$), 'ERROR:42501', 'a staff user cannot call the staff grant function through the student API');
SELECT is(pg_temp.as_api(:A::uuid, format('SELECT billing.staff_revoke_entitlement(%L, $$correction$$)', (SELECT id FROM billing.entitlements WHERE idempotency_key = 'rls-fixture-b-all'))), 'ERROR:42501', 'A cannot call the staff revoke function');
SELECT is(pg_temp.as_api(:A::uuid, format('SELECT billing.revoke_entitlement(%L, $$staff_revoke$$, NULL)', (SELECT id FROM billing.entitlements WHERE idempotency_key = 'rls-fixture-b-all'))), 'ERROR:42501', 'A cannot call the revoke function');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT billing.staff_list_entitlements('a0000000-0000-4000-8000-000000000002')$$), 'ERROR:42501', 'A cannot list B''s grants through the staff function');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT billing.learner_is_entitled_at('a0000000-0000-4000-8000-000000000002', 'all', NULL, now())$$), 'ERROR:42501', 'A cannot ask whether B is entitled');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT billing.create_order('synthetic-all-30', 'HTG', 'mock', 'client-made-order-1')$$), 'ERROR:42501', 'A cannot create an order (no checkout exists)');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT billing.apply_provider_event('mock', 'evt-forged-by-client', 'payment.succeeded', '{"order_id":"00000000-0000-4000-8000-000000000000","amount_minor":1,"currency":"HTG","plan_code":"synthetic-all-30"}')$$), 'ERROR:42501', 'A cannot apply a provider event');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT billing.erase_learner('a0000000-0000-4000-8000-000000000002')$$), 'ERROR:42501', 'A cannot erase B''s billing data');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT staff.require_role('admin')$$), 'ERROR:42501', 'A cannot reach the staff role check');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT ops.audit_write('billing.entitlement.grant', NULL, NULL, 'allowed')$$), 'ERROR:42501', 'A cannot forge a billing audit record');
SELECT is((SELECT count(*)::int FROM billing.entitlements), 4, 'after every attempt there are still exactly the 4 fixture grants');
SELECT is((SELECT count(*)::int FROM billing.entitlement_revocations), 1, '... and exactly the 1 fixture revocation');

-- ---- plans, orders, provider events, refunds, providers: closed --------------------------
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM billing.plans'), 'ERROR:42501', 'student API cannot read plans');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM billing.plan_prices'), 'ERROR:42501', 'student API cannot read prices');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM billing.orders'), 'ERROR:42501', 'student API cannot read orders');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM billing.provider_events'), 'ERROR:42501', 'student API cannot read provider events');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM billing.refunds'), 'ERROR:42501', 'student API cannot read refunds');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM billing.providers'), 'ERROR:42501', 'student API cannot read providers');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO billing.providers (code, is_simulated, is_enabled) VALUES ('evil', true, true) RETURNING 1$$), 'ERROR:42501', 'student API cannot register a provider');
SELECT is(pg_temp.as_api(:A::uuid, $$UPDATE billing.plan_prices SET amount_minor = 1 RETURNING 1$$), 'ERROR:42501', 'student API cannot change a price');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO billing.orders (learner_id, plan_id, provider, currency, amount_expected_minor, status, idempotency_key) VALUES ('a0000000-0000-4000-8000-000000000001', 'f0000000-0000-4000-8000-000000000001', 'mock', 'HTG', 1, 'paid', 'forged-paid-order') RETURNING 1$$), 'ERROR:42501', 'student API cannot forge a paid order');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO billing.provider_events (provider, provider_event_id, event_type, payload, payload_sha256, outcome, outcome_code) VALUES ('mock', 'forged', 'payment.succeeded', '{}', sha256('x'), 'applied', 'entitlement_granted') RETURNING 1$$), 'ERROR:42501', 'student API cannot forge a provider event row');
SELECT is(pg_temp.as_api(:A::uuid, 'CREATE TABLE billing.exfil (x int)'), 'ERROR:42501', 'student API cannot create objects in billing');

-- ---- Supabase Data API roles cannot reach the schema at all ---------------------------------
SET LOCAL ROLE anon;
SELECT throws_ok('SELECT count(*) FROM billing.entitlements', '42501', NULL, 'anon: schema billing is unreachable');
SELECT throws_ok('SELECT billing.is_entitled()', '42501', NULL, 'anon: cannot call billing functions');
RESET ROLE;
SET LOCAL ROLE authenticated;
SELECT throws_ok('SELECT count(*) FROM billing.entitlements', '42501', NULL, 'authenticated (Data API): schema billing is unreachable');
SELECT throws_ok('SELECT count(*) FROM billing.orders', '42501', NULL, 'authenticated (Data API): cannot read orders');
RESET ROLE;
SET LOCAL ROLE service_role;
SELECT throws_ok('SELECT count(*) FROM billing.entitlements', '42501', NULL, 'service_role (Data API secret key): schema billing is unreachable');
SELECT throws_ok($$SELECT billing.apply_provider_event('mock', 'x', 'payment.succeeded', '{}')$$, '42501', NULL, 'service_role: cannot apply a provider event');
RESET ROLE;

-- ============================================================================
-- Learning does not depend on billing (Platform-06 gate; Platform-00 doc 05
-- "Lessons work when everything else is down")
-- ============================================================================
-- (1) billing unreachable to the API role: learning reads and writes are normal.
-- (Counts are restricted to the seed lesson: other local test runs publish more
-- lessons, which are immutable and therefore stay in the database.)
REVOKE USAGE ON SCHEMA billing FROM edu_api;
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM billing.entitlements'), 'ERROR:42501', 'billing is now unreachable to the student API');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT billing.is_entitled()'), 'ERROR:42501', '... including its read function');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM app.courses'), '1', 'billing unreachable: the catalogue is still readable');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM app.lesson_revisions WHERE lesson_id = 'b0000000-0000-4000-8000-000000000005'$$), '2', 'billing unreachable: both published revisions of the seed lesson are still readable');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM app.question_revisions WHERE lesson_revision_id IN ('c0000000-0000-4000-8000-000000000001', 'c0000000-0000-4000-8000-000000000002')$$), '10', 'billing unreachable: the seed questions are still readable');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM app.learner_profiles'), '1', 'billing unreachable: own profile is still readable');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT app.sync_apply_operation('55555555-5555-4555-8555-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}', sha256('c1'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'billing unreachable: an answer still syncs');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT app.sync_apply_operation('55555555-5555-4555-8555-000000000002','lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000001"}', sha256('c2'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'billing unreachable: a completion still syncs');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM app.account_change_feed'), '2', 'billing unreachable: the change feed is still readable');
GRANT USAGE ON SCHEMA billing TO edu_api;

-- (2) A learner with NO grant, and one whose grant was revoked, read the same
--     free content as an entitled learner: there is no paywall.
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$SELECT count(*) FROM app.lesson_revisions WHERE lesson_id = 'b0000000-0000-4000-8000-000000000005'$$), '2', 'no grant: lessons are readable (no paywall)');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM app.lesson_revisions WHERE lesson_id = 'b0000000-0000-4000-8000-000000000005'$$), '2', 'active grant: the same lessons, no more and no fewer');

-- (3) The strongest form: remove the whole schema. Nothing in `app` refers to
--     it, so the drop succeeds and learning carries on. (Rolled back below.)
SET LOCAL client_min_messages = warning;
SELECT lives_ok('DROP SCHEMA billing CASCADE', 'the billing schema can be dropped: no object in app depends on it');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM app.lesson_revisions WHERE lesson_id = 'b0000000-0000-4000-8000-000000000005'$$), '2', 'billing gone: lessons are still readable');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT app.sync_apply_operation('55555555-5555-4555-8555-000000000003','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000201","response":{"choice_id":"a"}}', sha256('c3'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'billing gone: an answer still syncs');
SELECT is((SELECT count(*)::int FROM pg_tables WHERE schemaname = 'app'), 22, 'billing gone: schema app is intact (22 tables)');

SELECT * FROM finish();
ROLLBACK;
