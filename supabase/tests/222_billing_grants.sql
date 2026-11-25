-- billing grants: exactly-once, overlap, expiry boundary, revocation, scope
-- matching, the staff functions (as the staff API role), audit and the erasure
-- hook. The internal writers run as the owner: no other role can execute them.
BEGIN;
SELECT * FROM no_plan();

TRUNCATE billing.refunds, billing.entitlement_revocations, billing.entitlements,
         billing.provider_events, billing.orders, billing.plan_prices, billing.plans,
         billing.providers;
-- The audit trail is append-only and may hold rows from earlier local test runs;
-- empty it INSIDE this transaction (rolled back at the end) so counts are exact.
TRUNCATE app.audit_events;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
\set ADMIN '''a0000000-0000-4000-8000-000000000004'''
\set GRADE '''b0000000-0000-4000-8000-000000000001'''
\set COURSE '''b0000000-0000-4000-8000-000000000003'''
-- now() is constant inside this transaction, so T0 below is one exact instant.

-- ---- a double grant with the same idempotency key is impossible ------------------
SELECT is(billing.grant_entitlement(:A, 'all', NULL, now(), now() + interval '30 days', 'gift', NULL, 'grant-key-0001', NULL) ->> 'replayed', 'false', 'first grant is new');
SELECT is(billing.grant_entitlement(:A, 'all', NULL, now(), now() + interval '30 days', 'gift', NULL, 'grant-key-0001', NULL) ->> 'replayed', 'true', 'same key + same request is a replay');
SELECT is(billing.grant_entitlement(:A, 'all', NULL, now(), now() + interval '30 days', 'gift', NULL, 'grant-key-0001', NULL) ->> 'entitlement_id',
          (SELECT id::text FROM billing.entitlements WHERE idempotency_key = 'grant-key-0001'), 'the replay returns the ORIGINAL grant id');
SELECT is((billing.grant_entitlement(:A, 'all', NULL, now() + interval '2 hours', now() + interval '30 days 2 hours', 'gift', NULL, 'grant-key-0001', NULL) ->> 'ends_at')::timestamptz,
          now() + interval '30 days', 'a later retry of the same request gets the ORIGINAL dates, not new ones');
SELECT is((SELECT count(*)::int FROM billing.entitlements), 1, 'four calls, one row');
SELECT is(billing.grant_entitlement(:B, 'all', NULL, now(), now() + interval '30 days', 'gift', NULL, 'grant-key-0001', NULL) ->> 'status', 'conflict', 'same key for another learner is a conflict');
SELECT is(billing.grant_entitlement(:A, 'all', NULL, now(), now() + interval '90 days', 'gift', NULL, 'grant-key-0001', NULL) ->> 'status', 'conflict', 'same key with a longer duration is a conflict (cannot extend by retrying)');
SELECT is(billing.grant_entitlement(:A, 'grade', :GRADE, now(), now() + interval '30 days', 'gift', NULL, 'grant-key-0001', NULL) ->> 'code', 'idempotency_key_reused_with_different_grant', 'same key with another scope: clear conflict code');
SELECT is(billing.grant_entitlement(:A, 'all', NULL, now(), now() + interval '30 days', 'promo', NULL, 'grant-key-0001', NULL) ->> 'status', 'conflict', 'same key with another source is a conflict');
SELECT is((SELECT count(*)::int FROM billing.entitlements), 1, 'conflicts created no row');
SELECT is((SELECT ends_at FROM billing.entitlements WHERE idempotency_key = 'grant-key-0001'), now() + interval '30 days', 'the original grant is untouched');
SELECT throws_ok($$INSERT INTO billing.entitlements (learner_id, scope_kind, starts_at, ends_at, source, idempotency_key) VALUES ('a0000000-0000-4000-8000-000000000001', 'all', now(), now() + interval '1 day', 'gift', 'grant-key-0001')$$, '23505', NULL, 'even the owner cannot insert a second row with the same key');

-- ---- inputs are bounded -----------------------------------------------------------
SELECT throws_ok($$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', 'b0000000-0000-4000-8000-000000000001', now(), now() + interval '1 day', 'gift', NULL, 'grant-bad-0001', NULL)$$, '22023', NULL, 'scope all takes no id');
SELECT throws_ok($$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'grade', NULL, now(), now() + interval '1 day', 'gift', NULL, 'grant-bad-0002', NULL)$$, '22023', NULL, 'scope grade needs an id');
SELECT throws_ok($$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'lesson', gen_random_uuid(), now(), now() + interval '1 day', 'gift', NULL, 'grant-bad-0003', NULL)$$, '22023', NULL, 'unknown scope kind refused');
SELECT throws_ok($$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'grade', gen_random_uuid(), now(), now() + interval '1 day', 'gift', NULL, 'grant-bad-0004', NULL)$$, '22023', 'Unknown grade', 'unknown grade refused');
SELECT throws_ok($$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'course', 'b0000000-0000-4000-8000-000000000001', now(), now() + interval '1 day', 'gift', NULL, 'grant-bad-0005', NULL)$$, '22023', 'Unknown course', 'a grade id is not a course id');
SELECT throws_ok($$SELECT billing.grant_entitlement(gen_random_uuid(), 'all', NULL, now(), now() + interval '1 day', 'gift', NULL, 'grant-bad-0006', NULL)$$, '22023', 'Unknown learner', 'unknown learner refused');
SELECT throws_ok($$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, now(), now(), 'gift', NULL, 'grant-bad-0007', NULL)$$, '22023', NULL, 'an empty period is refused');
SELECT throws_ok($$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, now(), now() + interval '100 years', 'gift', NULL, 'grant-bad-0008', NULL)$$, '22023', NULL, 'a 100-year grant is refused');
SELECT throws_ok($$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, now() - interval '2 years', now() + interval '1 day', 'gift', NULL, 'grant-bad-0009', NULL)$$, '22023', NULL, 'a back-dated grant is refused');
SELECT throws_ok($$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, now(), now() + interval '1 day', 'lottery', NULL, 'grant-bad-0010', NULL)$$, '22023', NULL, 'unknown source refused');
SELECT throws_ok($$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, now(), now() + interval '1 day', 'purchase', NULL, 'grant-bad-0011', NULL)$$, '22023', NULL, 'a purchase grant without an order is refused');
SELECT throws_ok($$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, now(), now() + interval '1 day', 'gift', NULL, 'short', NULL)$$, '22023', NULL, 'a too-short idempotency key is refused');
SELECT is((SELECT count(*)::int FROM billing.entitlements), 1, 'refused requests created no row');

-- ---- expiry at the boundary: starts_at <= t < ends_at -------------------------------
-- EDITOR is used as a learner with exactly one 24-hour grant [T0, T0 + 24h).
SELECT is(billing.grant_entitlement(:EDITOR, 'all', NULL, now(), now() + interval '24 hours', 'trial', NULL, 'boundary-key-0001', NULL) ->> 'status', 'granted', 'fixture: one 24-hour grant');
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'all', NULL, now() - interval '1 microsecond'), false, 'one microsecond before the start: not entitled');
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'all', NULL, now()), true, 'exactly at the start: entitled');
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'all', NULL, now() + interval '24 hours' - interval '1 microsecond'), true, 'one microsecond before the end: entitled');
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'all', NULL, now() + interval '24 hours'), false, 'exactly at the end: NOT entitled');
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'all', NULL, now() + interval '24 hours 1 microsecond'), false, 'after the end: not entitled');
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'all', NULL, NULL), false, 'no time: not entitled');
SELECT is(billing.learner_is_entitled_at(NULL, 'all', NULL, now()), false, 'no learner: not entitled');

-- ---- overlapping grants: access = ANY active grant ------------------------------------
-- B: X = [T0, T0+10d) and Y = [T0+5d, T0+20d). They overlap for five days.
SELECT is(billing.grant_entitlement(:B, 'all', NULL, now(), now() + interval '10 days', 'gift', NULL, 'overlap-key-000X', NULL) ->> 'status', 'granted', 'fixture: grant X');
SELECT is(billing.grant_entitlement(:B, 'all', NULL, now() + interval '5 days', now() + interval '20 days', 'promo', NULL, 'overlap-key-000Y', NULL) ->> 'status', 'granted', 'an overlapping grant is allowed');
SELECT is((SELECT count(*)::int FROM billing.entitlements WHERE learner_id = :B), 2, 'both grants are kept as separate rows');
SELECT is(billing.learner_is_entitled_at(:B, 'all', NULL, now() + interval '7 days'), true, 'inside the overlap: entitled');
SELECT is(billing.learner_is_entitled_at(:B, 'all', NULL, now() + interval '12 days'), true, 'after X ended, Y still gives access (extending = a new row)');
SELECT is(billing.learner_is_entitled_at(:B, 'all', NULL, now() + interval '20 days'), false, 'when the last grant ends, access ends');
SELECT is((SELECT ends_at FROM billing.entitlements WHERE idempotency_key = 'overlap-key-000X'), now() + interval '10 days', 'extending did not edit the first grant');

-- ---- revocation is a new record ---------------------------------------------------------
SELECT is(billing.revoke_entitlement((SELECT id FROM billing.entitlements WHERE idempotency_key = 'overlap-key-000X'), 'staff_revoke', :ADMIN) ->> 'replayed', 'false', 'X is revoked');
SELECT is(billing.learner_is_entitled_at(:B, 'all', NULL, now() + interval '3 days'), false, 'X revoked: no access where only X applied');
SELECT is(billing.learner_is_entitled_at(:B, 'all', NULL, now() + interval '7 days'), true, 'X revoked: Y still gives access in its own period');
SELECT is(billing.revoke_entitlement((SELECT id FROM billing.entitlements WHERE idempotency_key = 'overlap-key-000X'), 'staff_revoke', :ADMIN) ->> 'replayed', 'true', 'revoking twice is a replay');
SELECT is((SELECT count(*)::int FROM billing.entitlement_revocations), 1, '... with one revocation row');
SELECT is((SELECT ends_at FROM billing.entitlements WHERE idempotency_key = 'overlap-key-000X'), now() + interval '10 days', 'the revoked grant row itself is unchanged');
SELECT is(billing.learner_is_entitled_at(:B, 'all', NULL, now() - interval '1 microsecond'), false, 'a revocation does not rewrite the past before the grant either');
SELECT throws_ok($$SELECT billing.revoke_entitlement(gen_random_uuid(), 'staff_revoke', NULL)$$, 'P0002', 'Unknown entitlement', 'revoking an unknown grant is refused');
SELECT throws_ok(format($$SELECT billing.revoke_entitlement(%L, 'because', NULL)$$, (SELECT id FROM billing.entitlements WHERE idempotency_key = 'overlap-key-000Y')), '22023', NULL, 'unknown revocation reason refused');
-- a new grant after a revocation restores access: history, not state
SELECT is(billing.grant_entitlement(:B, 'all', NULL, now(), now() + interval '4 days', 'gift', NULL, 'overlap-key-000Z', NULL) ->> 'status', 'granted', 'a fresh grant after a revocation');
SELECT is(billing.learner_is_entitled_at(:B, 'all', NULL, now() + interval '3 days'), true, '... gives access again');

-- ---- history cannot be rewritten, even by the owner ---------------------------------------
SELECT throws_ok($$UPDATE billing.entitlements SET ends_at = ends_at + interval '1 year'$$, 'P0001', NULL, 'the owner cannot extend a grant by editing it');
SELECT throws_ok($$UPDATE billing.entitlements SET learner_id = 'a0000000-0000-4000-8000-000000000002'$$, 'P0001', NULL, 'the owner cannot move a grant to another learner');
SELECT throws_ok($$DELETE FROM billing.entitlement_revocations$$, 'P0001', NULL, 'the owner cannot un-revoke by deleting');
SELECT throws_ok($$UPDATE billing.entitlement_revocations SET revoked_at = now() + interval '1 year'$$, 'P0001', NULL, 'the owner cannot postpone a revocation');
SELECT throws_ok($$DELETE FROM billing.entitlements WHERE idempotency_key = 'boundary-key-0001'$$, 'P0001', NULL, 'the owner cannot delete a grant');
SELECT set_config('billing.erasing', 'on', true);
SELECT throws_ok($$UPDATE billing.entitlements SET ends_at = ends_at + interval '1 year'$$, 'P0001', NULL, 'the erasure marker never allows an UPDATE of a grant');
SELECT set_config('billing.erasing', '', true);

-- ---- scope matching -----------------------------------------------------------------------
-- A already holds 'all'. EDITOR's 24-hour 'all' grant is revoked first, then
-- EDITOR gets a GRADE grant; ADMIN gets a COURSE grant.
SELECT is(billing.revoke_entitlement((SELECT id FROM billing.entitlements WHERE idempotency_key = 'boundary-key-0001'), 'staff_revoke', NULL) ->> 'status', 'revoked', 'fixture: clear EDITOR');
SELECT is(billing.grant_entitlement(:EDITOR, 'grade', :GRADE, now(), now() + interval '30 days', 'school_licence', 'synthetic-school', 'scope-key-grade', NULL) ->> 'status', 'granted', 'fixture: grade grant');
SELECT is(billing.grant_entitlement(:ADMIN, 'course', :COURSE, now(), now() + interval '30 days', 'promo', NULL, 'scope-key-course', NULL) ->> 'status', 'granted', 'fixture: course grant');
SELECT is(billing.learner_is_entitled_at(:A, 'all', NULL, now()), true, 'all grant covers all');
SELECT is(billing.learner_is_entitled_at(:A, 'grade', :GRADE, now()), true, 'all grant covers a grade');
SELECT is(billing.learner_is_entitled_at(:A, 'course', :COURSE, now()), true, 'all grant covers a course');
SELECT is(billing.learner_is_entitled_at(:A, 'course', gen_random_uuid(), now()), true, 'all grant covers any course id');
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'grade', :GRADE, now()), true, 'grade grant covers its grade');
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'course', :COURSE, now()), true, 'grade grant covers a course of that grade');
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'all', NULL, now()), false, 'grade grant does not cover all');
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'grade', gen_random_uuid(), now()), false, 'grade grant does not cover another grade');
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'course', gen_random_uuid(), now()), false, 'grade grant does not cover a course outside the grade');
-- no existence probe: a draft or archived course of the SAME grade answers exactly like an unknown id
INSERT INTO app.courses (id, grade_id, subject_id, slug, titles, visibility)
SELECT x.id, c.grade_id, c.subject_id, x.slug, '{"fr":"Cours synthetique"}', x.visibility
FROM app.courses c, (VALUES ('b0000000-0000-4000-8000-0000000000d1'::uuid, 'probe-draft', 'draft'),
                            ('b0000000-0000-4000-8000-0000000000d2'::uuid, 'probe-archived', 'archived')) AS x(id, slug, visibility)
WHERE c.id = :COURSE;
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'course', 'b0000000-0000-4000-8000-0000000000d1', now()), false, 'grade grant: a DRAFT course of the grade answers false, like an unknown id');
SELECT is(billing.learner_is_entitled_at(:EDITOR, 'course', 'b0000000-0000-4000-8000-0000000000d2', now()), false, 'grade grant: an ARCHIVED course of the grade answers false, like an unknown id');
SELECT is(billing.learner_is_entitled_at(:ADMIN, 'course', 'b0000000-0000-4000-8000-0000000000d1', now()), false, 'a course grant elsewhere: the same false for the draft course');
SELECT is(billing.learner_is_entitled_at(:ADMIN, 'course', :COURSE, now()), true, 'course grant covers its course');
SELECT is(billing.learner_is_entitled_at(:ADMIN, 'grade', :GRADE, now()), false, 'course grant does not cover the whole grade');
SELECT is(billing.learner_is_entitled_at(:ADMIN, 'all', NULL, now()), false, 'course grant does not cover all');
SELECT is(billing.learner_is_entitled_at(:ADMIN, 'course', gen_random_uuid(), now()), false, 'course grant does not cover another course');
SELECT is(billing.learner_is_entitled_at(:A, 'all', gen_random_uuid(), now()), false, 'malformed request (all + id) is not entitled');
SELECT is(billing.learner_is_entitled_at(:A, 'course', NULL, now()), false, 'malformed request (course without id) is not entitled');
SELECT is(billing.learner_is_entitled_at(:A, NULL, NULL, now()), false, 'malformed request (no kind) is not entitled');
SELECT throws_ok($$INSERT INTO billing.entitlements (learner_id, scope_kind, scope_grade_id, scope_course_id, starts_at, ends_at, source, idempotency_key) VALUES ('a0000000-0000-4000-8000-000000000001', 'grade', NULL, 'b0000000-0000-4000-8000-000000000003', now(), now() + interval '1 day', 'gift', 'scope-shape-bad')$$, '23514', NULL, 'the table itself refuses a scope whose kind and id disagree');
-- the caller-facing function uses the actor and the server clock
SELECT set_config('edu.actor_id', :EDITOR, true);
SELECT is(billing.is_entitled('course', :COURSE), true, 'is_entitled: the actor with a grade grant, asked about a course');
SELECT is(billing.is_entitled(), false, 'is_entitled: default scope is all');
SELECT set_config('edu.actor_id', '', true);
SELECT is(billing.is_entitled(), false, 'is_entitled: no actor, not entitled');

-- ============================================================================
-- Staff grant / revoke / list: role admin, as the staff API role, audited
-- ============================================================================
-- Run one statement AS THE STAFF API ROLE with the given actor. Returns the
-- first column of the first row as text, or 'ERROR:<sqlstate>'.
GRANT edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
CREATE FUNCTION pg_temp.as_staff(p_actor uuid, p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    PERFORM set_config('edu.actor_id', COALESCE(p_actor::text, ''), true);
    EXECUTE 'SET LOCAL ROLE edu_staff';
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
-- The seed has an editor and a reviewer but no admin. The reviewer is made an
-- admin inside this transaction only.
INSERT INTO app.staff_roles (user_id, role) VALUES (:ADMIN, 'admin');
SELECT is((SELECT count(*)::int FROM app.audit_events), 0, 'no audit record exists before the first staff action');

SELECT is(pg_temp.as_staff(NULL, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000002', 'all', NULL, 30, 'gift', 'goodwill', 'staff-key-0000')$$), 'ERROR:42501', 'no actor: staff grant refused');
SELECT is(pg_temp.as_staff(:A::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, 30, 'gift', 'goodwill', 'staff-key-0001')$$), 'ERROR:42501', 'a learner cannot staff-grant, even on the staff connection');
SELECT is(pg_temp.as_staff(:EDITOR::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000002', 'all', NULL, 30, 'gift', 'goodwill', 'staff-key-0002')$$), 'ERROR:42501', 'an editor (not admin) cannot staff-grant');
SELECT is(pg_temp.as_staff(:EDITOR::uuid, $$SELECT billing.staff_list_entitlements('a0000000-0000-4000-8000-000000000002')$$), 'ERROR:42501', 'an editor cannot list a learner''s grants');
SELECT is(pg_temp.as_staff(:EDITOR::uuid, format($$SELECT billing.staff_revoke_entitlement(%L, 'correction')$$, (SELECT id FROM billing.entitlements WHERE idempotency_key = 'grant-key-0001'))), 'ERROR:42501', 'an editor cannot revoke');
UPDATE app.staff_roles SET is_active = false WHERE user_id = :ADMIN AND role = 'admin';
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000002', 'all', NULL, 30, 'gift', 'goodwill', 'staff-key-0003')$$), 'ERROR:42501', 'an INACTIVE admin role does not count');
UPDATE app.staff_roles SET is_active = true WHERE user_id = :ADMIN AND role = 'admin';
SELECT is((SELECT count(*)::int FROM billing.entitlements WHERE idempotency_key LIKE 'staff-key-%'), 0, 'refused staff grants created nothing');
SELECT is((SELECT count(*)::int FROM billing.entitlement_revocations WHERE reason_code = 'staff_revoke' AND source_ref LIKE 'staff:%'), 0, 'the refused revocation revoked nothing');

-- the staff role reaches billing ONLY through the three functions
SELECT is(pg_temp.as_staff(:ADMIN::uuid, 'SELECT count(*) FROM billing.entitlements'), 'ERROR:42501', 'edu_staff (even an admin) cannot read the grants table');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, 'SELECT count(*) FROM billing.orders'), 'ERROR:42501', 'edu_staff cannot read orders');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, 'SELECT count(*) FROM billing.provider_events'), 'ERROR:42501', 'edu_staff cannot read provider events');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$INSERT INTO billing.entitlements (learner_id, scope_kind, starts_at, ends_at, source, idempotency_key) VALUES ('a0000000-0000-4000-8000-000000000002', 'all', now(), now() + interval '10 years', 'gift', 'staff-direct-insert') RETURNING 1$$), 'ERROR:42501', 'edu_staff cannot insert a grant around the function');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$UPDATE billing.entitlements SET ends_at = ends_at + interval '1 year' RETURNING 1$$), 'ERROR:42501', 'edu_staff cannot extend a grant by editing it');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000002', 'all', NULL, now(), now() + interval '3000 days', 'purchase', NULL, 'staff-internal-writer', NULL)$$), 'ERROR:42501', 'edu_staff cannot call the internal writer (no unaudited, unbounded grant)');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, format($$SELECT billing.revoke_entitlement(%L, 'staff_revoke', NULL)$$, (SELECT id FROM billing.entitlements WHERE idempotency_key = 'grant-key-0001'))), 'ERROR:42501', 'edu_staff cannot call the internal revoker (no unaudited revocation)');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.apply_provider_event('mock', 'evt-by-staff', 'payment.succeeded', '{}')$$), 'ERROR:42501', 'edu_staff cannot apply a provider event');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.create_order('synthetic-all-30', 'HTG', 'mock', 'order-by-staff-1')$$), 'ERROR:42501', 'edu_staff cannot create an order');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.erase_learner('a0000000-0000-4000-8000-000000000002')$$), 'ERROR:42501', 'edu_staff cannot run the erasure hook');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, 'SELECT billing.is_entitled()'), 'ERROR:42501', 'edu_staff cannot call the learner-facing reader');
SELECT is((SELECT count(*)::int FROM app.audit_events), 0, 'none of the refused attempts wrote an audit row inside this transaction');

SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'grade', 'b0000000-0000-4000-8000-000000000001', 30, 'school_licence', 'school_agreement', 'staff-key-0010') ->> 'status'$$), 'granted', 'an admin grants');
SELECT is((SELECT granted_by FROM billing.entitlements WHERE idempotency_key = 'staff-key-0010'), :ADMIN::uuid, 'the grant records WHO granted, taken from the verified actor');
SELECT is((SELECT source_ref FROM billing.entitlements WHERE idempotency_key = 'staff-key-0010'), 'staff:school_agreement', 'the grant records the reason code');
SELECT is((SELECT ends_at - starts_at FROM billing.entitlements WHERE idempotency_key = 'staff-key-0010'), interval '720 hours', 'a staff grant lasts days x 24 hours exactly');
SELECT is((SELECT starts_at FROM billing.entitlements WHERE idempotency_key = 'staff-key-0010'), now(), 'a staff grant starts on the server clock by default');
SELECT is((SELECT actor_id::text || '|' || action || '|' || target_kind || '|' || outcome FROM app.audit_events WHERE target_id = (SELECT id FROM billing.entitlements WHERE idempotency_key = 'staff-key-0010')),
          'a0000000-0000-4000-8000-000000000004|billing.entitlement.grant|billing_entitlement|allowed', 'the grant is audited with actor, action, target and outcome');
SELECT is((SELECT details FROM app.audit_events WHERE action = 'billing.entitlement.grant'),
          '{"status":"granted","replayed":false,"learner_id":"a0000000-0000-4000-8000-000000000001","scope_kind":"grade","scope_id":"b0000000-0000-4000-8000-000000000001","duration_days":30,"source":"school_licence","reason_code":"school_agreement"}'::jsonb,
          'the audit details are ids, codes and numbers only: no free text, no idempotency key');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'grade', 'b0000000-0000-4000-8000-000000000001', 30, 'school_licence', 'school_agreement', 'staff-key-0010') ->> 'replayed'$$), 'true', 'the same staff request again is a replay');
SELECT is((SELECT count(*)::int FROM billing.entitlements WHERE idempotency_key = 'staff-key-0010'), 1, '... one grant row');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE action = 'billing.entitlement.grant'), 2, '... and the retry is audited too');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'grade', 'b0000000-0000-4000-8000-000000000001', 300, 'school_licence', 'school_agreement', 'staff-key-0010') ->> 'status'$$), 'conflict', 'reusing the key with a longer duration is a conflict');
SELECT is((SELECT outcome FROM app.audit_events WHERE action = 'billing.entitlement.grant' AND details ->> 'status' = 'conflict'), 'denied', '... audited as denied');

SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, 30, 'purchase', 'goodwill', 'staff-key-0011')$$), 'ERROR:22023', 'staff cannot create a purchase grant');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, 0, 'gift', 'goodwill', 'staff-key-0012')$$), 'ERROR:22023', 'zero days refused');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, 367, 'gift', 'goodwill', 'staff-key-0013')$$), 'ERROR:22023', 'more than 366 days per staff grant refused');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, 30, 'gift', 'Because the learner asked nicely', 'staff-key-0014')$$), 'ERROR:22023', 'a free-text reason is refused: only reason codes');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, 30, 'gift', NULL, 'staff-key-0014')$$), 'ERROR:22023', 'a reason code is required');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.staff_grant_entitlement('a0000000-0000-4000-8000-000000000004', 'all', NULL, 30, 'gift', 'goodwill', 'staff-key-0015')$$), 'ERROR:42501', 'an admin cannot grant to themselves');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.staff_grant_entitlement(gen_random_uuid(), 'all', NULL, 30, 'gift', 'goodwill', 'staff-key-0016')$$), 'ERROR:22023', 'unknown learner refused');
SELECT is((SELECT count(*)::int FROM billing.entitlements WHERE idempotency_key LIKE 'staff-key-%'), 1, 'refused requests created no grant');

SELECT is(pg_temp.as_staff(:ADMIN::uuid, format($$SELECT billing.staff_revoke_entitlement(%L, 'granted_in_error') ->> 'status'$$, (SELECT id FROM billing.entitlements WHERE idempotency_key = 'staff-key-0010'))), 'revoked', 'an admin revokes');
SELECT is((SELECT revoked_by::text || '|' || reason_code || '|' || source_ref FROM billing.entitlement_revocations WHERE entitlement_id = (SELECT id FROM billing.entitlements WHERE idempotency_key = 'staff-key-0010')),
          'a0000000-0000-4000-8000-000000000004|staff_revoke|staff:granted_in_error', 'the revocation records who and why (a code)');
SELECT is((SELECT details FROM app.audit_events WHERE action = 'billing.entitlement.revoke' AND outcome = 'allowed'),
          '{"replayed":false,"reason_code":"granted_in_error"}'::jsonb, 'the revocation is audited, with a code only');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, format($$SELECT billing.staff_revoke_entitlement(%L, 'duplicate') ->> 'replayed'$$, (SELECT id FROM billing.entitlements WHERE idempotency_key = 'staff-key-0010'))), 'true', 'revoking again is a replay');
SELECT is(billing.learner_is_entitled_at(:A, 'grade', :GRADE, now()), true, 'A still has access through the separate all grant: revoking one grant leaves the others');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT billing.staff_revoke_entitlement(gen_random_uuid(), 'correction')$$), 'ERROR:P0002', 'revoking an unknown grant is refused');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, format($$SELECT billing.staff_revoke_entitlement(%L, 'he was rude')$$, (SELECT id FROM billing.entitlements WHERE idempotency_key = 'grant-key-0001'))), 'ERROR:22023', 'a free-text revocation reason is refused');

SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT jsonb_array_length(billing.staff_list_entitlements('a0000000-0000-4000-8000-000000000002'))$$), '3', 'an admin lists every grant of a learner');
SELECT is(pg_temp.as_staff(:ADMIN::uuid, $$SELECT string_agg(x ->> 'state', ',' ORDER BY x ->> 'state') FROM jsonb_array_elements(billing.staff_list_entitlements('a0000000-0000-4000-8000-000000000002')) x$$), 'active,revoked,scheduled', 'each grant carries its state now');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE action = 'billing.entitlement.list' AND target_kind = 'learner' AND target_id = :B AND details = '{"count":3}'), 2, 'reading a learner''s grants is audited');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE actor_id IS DISTINCT FROM :ADMIN::uuid), 0, 'every audit row of this section is attributed to the acting admin');

-- ============================================================================
-- Erasure hook
-- ============================================================================
-- A fresh synthetic account that has nothing but billing rows.
INSERT INTO auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
    raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
    confirmation_token, recovery_token, email_change_token_new, email_change)
VALUES ('00000000-0000-0000-0000-000000000000', 'a0000000-0000-4000-8000-0000000000e1', 'authenticated', 'authenticated',
    'erase.me@edupreneur.test', '', now(), '{"provider":"email","providers":["email"]}', '{}', now(), now(), '', '', '', '');
\set GONE '''a0000000-0000-4000-8000-0000000000e1'''
SELECT is(billing.grant_entitlement(:GONE, 'all', NULL, now(), now() + interval '30 days', 'gift', NULL, 'erase-key-0001', NULL) ->> 'status', 'granted', 'fixture: grant 1 for the account to erase');
SELECT is(billing.grant_entitlement(:GONE, 'course', :COURSE, now(), now() + interval '30 days', 'promo', NULL, 'erase-key-0002', NULL) ->> 'status', 'granted', 'fixture: grant 2');
SELECT is(billing.revoke_entitlement((SELECT id FROM billing.entitlements WHERE idempotency_key = 'erase-key-0002'), 'staff_revoke', NULL) ->> 'status', 'revoked', 'fixture: one revocation');
SELECT throws_ok($$DELETE FROM auth.users WHERE id = 'a0000000-0000-4000-8000-0000000000e1'$$, '23503', NULL, 'an account with grants cannot be deleted before the hook has run (no cascade)');
SELECT is((SELECT count(*)::int FROM billing.entitlements WHERE learner_id <> :GONE), 8, 'other learners hold 8 grants before the erasure');
SELECT is(billing.erase_learner(:GONE),
    '{"schema":"billing","entitlements_deleted":2,"revocations_deleted":1,"orders_anonymised":0,"provider_event_payloads_blanked":0}'::jsonb,
    'the hook reports exactly what it removed');
SELECT is((SELECT count(*)::int FROM billing.entitlements WHERE learner_id = :GONE), 0, 'the erased learner has no grant left');
SELECT is((SELECT count(*)::int FROM billing.entitlements), 8, 'other learners'' grants are untouched');
SELECT is((SELECT count(*)::int FROM billing.entitlement_revocations), 3, 'other learners'' revocations are untouched');
SELECT is(billing.erase_learner(:GONE) ->> 'entitlements_deleted', '0', 'running the hook again is harmless');
SELECT is(current_setting('billing.erasing', true), '', 'the erasure marker is cleared when the hook returns');
SELECT throws_ok($$DELETE FROM billing.entitlements$$, 'P0001', NULL, 'after the hook, grants are append-only again');
SELECT lives_ok($$DELETE FROM auth.users WHERE id = 'a0000000-0000-4000-8000-0000000000e1'$$, 'after the hook the account itself can be deleted');
SELECT throws_ok($$SELECT billing.erase_learner(NULL)$$, '22023', NULL, 'the hook needs a user id');

SELECT * FROM finish();
ROLLBACK;
