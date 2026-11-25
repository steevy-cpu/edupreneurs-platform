-- billing orders and provider events: server-side price, exactly-once
-- application, duplicate / replay / out-of-order safety, amount and plan
-- verification. Runs as the owner: no other role can execute these functions.
-- NOTHING here talks to a payment provider; 'mock' is a simulated provider that
-- exists only inside this transaction.
BEGIN;
SELECT * FROM no_plan();

TRUNCATE billing.refunds, billing.entitlement_revocations, billing.entitlements,
         billing.provider_events, billing.orders, billing.plan_prices, billing.plans,
         billing.providers;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
\set GRADE '''b0000000-0000-4000-8000-000000000001'''

-- A provider message body, as the simulated provider would send it.
CREATE FUNCTION pg_temp.msg(p_order uuid, p_amount bigint, p_currency text, p_plan text DEFAULT NULL)
RETURNS jsonb LANGUAGE sql AS $fn$
    SELECT jsonb_strip_nulls(jsonb_build_object(
        'order_id', p_order, 'amount_minor', p_amount, 'currency', p_currency, 'plan_code', p_plan))
$fn$;
CREATE FUNCTION pg_temp.snapshot() RETURNS text LANGUAGE sql AS $fn$
    SELECT (SELECT count(*) FROM billing.entitlements) || ' grants, '
        || (SELECT count(*) FROM billing.entitlement_revocations) || ' revocations, '
        || (SELECT count(*) FROM billing.provider_events) || ' events, '
        || (SELECT count(*) FROM billing.refunds) || ' refunds'
$fn$;

-- Synthetic configuration (BLOCKED_BY_OWNER PO-01/PO-05: these are NOT prices).
INSERT INTO billing.providers (code, is_simulated, is_enabled) VALUES
    ('mock', true, true), ('mock_two', true, true), ('mock_off', true, false), ('realpay', false, true);
INSERT INTO billing.plans (id, code, scope_kind, scope_grade_id, duration_days, is_synthetic) VALUES
    ('f0000000-0000-4000-8000-000000000001', 'synthetic-all-30', 'all', NULL, 30, true),
    ('f0000000-0000-4000-8000-000000000002', 'synthetic-grade-90', 'grade', :GRADE, 90, true),
    ('f0000000-0000-4000-8000-000000000003', 'not-synthetic-all-30', 'all', NULL, 30, false);
INSERT INTO billing.plans (id, code, scope_kind, duration_days, is_active) VALUES
    ('f0000000-0000-4000-8000-000000000004', 'synthetic-retired', 'all', 30, false);
INSERT INTO billing.plan_prices (plan_id, currency, amount_minor) VALUES
    ('f0000000-0000-4000-8000-000000000001', 'HTG', 50000),
    ('f0000000-0000-4000-8000-000000000001', 'USD', 400),
    ('f0000000-0000-4000-8000-000000000002', 'HTG', 120000),
    ('f0000000-0000-4000-8000-000000000003', 'HTG', 50000),
    ('f0000000-0000-4000-8000-000000000004', 'HTG', 50000);

-- ============================================================================
-- Orders: the price comes from the server
-- ============================================================================
SELECT throws_ok($$SELECT billing.create_order('synthetic-all-30', 'HTG', 'mock', 'order-key-0000')$$, '42501', 'No verified actor in this transaction', 'no actor: no order');
SELECT set_config('edu.actor_id', :A, true);
SELECT is(billing.create_order('synthetic-all-30', 'HTG', 'mock', 'order-key-0001') - 'order_id',
    '{"status":"created","replayed":false,"plan_code":"synthetic-all-30","amount_expected_minor":50000,"currency":"HTG"}'::jsonb,
    'an order copies the amount from the plan price (integer minor units + currency)');
SELECT is(billing.create_order('synthetic-all-30', 'HTG', 'mock', 'order-key-0001') ->> 'replayed', 'true', 'the same order request again is a replay');
SELECT is((SELECT count(*)::int FROM billing.orders), 1, '... with one order row');
SELECT is(billing.create_order('synthetic-all-30', 'USD', 'mock', 'order-key-0001') ->> 'status', 'conflict', 'same key, other currency: conflict');
SELECT set_config('edu.actor_id', :B, true);
SELECT is(billing.create_order('synthetic-all-30', 'HTG', 'mock', 'order-key-0001') ->> 'status', 'conflict', 'same key, other learner: conflict');
SELECT throws_ok($$SELECT billing.create_order('no-such-plan', 'HTG', 'mock', 'order-key-0002')$$, '22023', 'Unknown plan', 'unknown plan refused');
SELECT throws_ok($$SELECT billing.create_order('synthetic-retired', 'HTG', 'mock', 'order-key-0003')$$, '22023', 'Unknown plan', 'inactive plan refused');
SELECT throws_ok($$SELECT billing.create_order('synthetic-all-30', 'EUR', 'mock', 'order-key-0004')$$, '22023', 'Plan has no price in this currency', 'no price in that currency: refused, never converted');
SELECT throws_ok($$SELECT billing.create_order('synthetic-all-30', 'htg', 'mock', 'order-key-0005')$$, '22023', NULL, 'malformed currency refused');
SELECT throws_ok($$SELECT billing.create_order('synthetic-all-30', 'HTG', 'mock_off', 'order-key-0006')$$, '42501', 'Payment provider is not enabled', 'a disabled provider is refused');
SELECT throws_ok($$SELECT billing.create_order('synthetic-all-30', 'HTG', 'stripe', 'order-key-0007')$$, '42501', 'Payment provider is not enabled', 'an unregistered provider is refused');
SELECT throws_ok($$SELECT billing.create_order('synthetic-all-30', 'HTG', 'realpay', 'order-key-0008')$$, '42501', 'Synthetic plans and simulated providers only go together', 'a REAL provider can never charge a SYNTHETIC plan');
SELECT throws_ok($$SELECT billing.create_order('not-synthetic-all-30', 'HTG', 'mock', 'order-key-0009')$$, '42501', 'Synthetic plans and simulated providers only go together', 'a SIMULATED provider can never pay for a real plan');
SELECT is((SELECT count(*)::int FROM billing.orders), 1, 'refused requests created no order');
SELECT is((SELECT count(*)::int FROM billing.entitlements), 0, 'creating an order grants nothing');
SELECT set_config('edu.actor_id', '', true);
SELECT id AS o1 FROM billing.orders WHERE idempotency_key = 'order-key-0001' \gset

-- ============================================================================
-- Messages that must change nothing
-- ============================================================================
SELECT throws_ok(format($$SELECT billing.apply_provider_event('stripe', 'evt-x', 'payment.succeeded', %L)$$, pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-all-30')), '42501', 'Payment provider is not enabled', 'a message for an unregistered provider is refused and not stored');
SELECT throws_ok(format($$SELECT billing.apply_provider_event('mock_off', 'evt-x', 'payment.succeeded', %L)$$, pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-all-30')), '42501', NULL, 'a message for a disabled provider is refused and not stored');
SELECT throws_ok($$SELECT billing.apply_provider_event('mock', 'evt-x', 'payment.succeeded', '[]')$$, '22023', NULL, 'a non-object payload is refused');
SELECT throws_ok($$SELECT billing.apply_provider_event('mock', 'evt-x', 'payment.succeeded', jsonb_build_object('pad', repeat('x', 20000)))$$, '22023', NULL, 'an oversized payload is refused');
SELECT is(pg_temp.snapshot(), '0 grants, 0 revocations, 0 events, 0 refunds', 'refused calls stored nothing');

SELECT is(billing.apply_provider_event('mock', 'evt-bad-amount', 'payment.succeeded', pg_temp.msg(:'o1', 49999, 'HTG', 'synthetic-all-30')) ->> 'code', 'amount_mismatch', 'paying one minor unit less is refused');
SELECT is(billing.apply_provider_event('mock', 'evt-bad-amount-high', 'payment.succeeded', pg_temp.msg(:'o1', 5000000, 'HTG', 'synthetic-all-30')) ->> 'code', 'amount_mismatch', 'a different (higher) amount is refused too');
SELECT is(billing.apply_provider_event('mock', 'evt-bad-currency', 'payment.succeeded', pg_temp.msg(:'o1', 50000, 'USD', 'synthetic-all-30')) ->> 'code', 'currency_mismatch', 'the right number in the wrong currency is refused');
SELECT is(billing.apply_provider_event('mock', 'evt-bad-plan', 'payment.succeeded', pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-grade-90')) ->> 'code', 'plan_mismatch', 'a message naming another plan is refused');
SELECT is(billing.apply_provider_event('mock', 'evt-no-order', 'payment.succeeded', pg_temp.msg(gen_random_uuid(), 50000, 'HTG', 'synthetic-all-30')) ->> 'code', 'unknown_order', 'a message for an unknown order is refused');
SELECT is(billing.apply_provider_event('mock_two', 'evt-other-provider', 'payment.succeeded', pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-all-30')) ->> 'code', 'unknown_order', 'another provider cannot settle this provider''s order');
SELECT is(billing.apply_provider_event('mock', 'evt-malformed-1', 'payment.succeeded', jsonb_build_object('order_id', :'o1', 'amount_minor', '50000', 'currency', 'HTG', 'plan_code', 'synthetic-all-30')) ->> 'code', 'malformed_payload', 'an amount sent as a string is refused');
SELECT is(billing.apply_provider_event('mock', 'evt-malformed-2', 'payment.succeeded', jsonb_build_object('order_id', :'o1', 'amount_minor', 500.5, 'currency', 'HTG', 'plan_code', 'synthetic-all-30')) ->> 'code', 'malformed_payload', 'a fractional amount is refused (minor units are integers)');
SELECT is(billing.apply_provider_event('mock', 'evt-malformed-3', 'payment.succeeded', jsonb_build_object('order_id', :'o1', 'amount_minor', -50000, 'currency', 'HTG', 'plan_code', 'synthetic-all-30')) ->> 'code', 'malformed_payload', 'a negative amount is refused');
SELECT is(billing.apply_provider_event('mock', 'evt-malformed-4', 'payment.succeeded', jsonb_build_object('amount_minor', 50000, 'currency', 'HTG', 'plan_code', 'synthetic-all-30')) ->> 'code', 'malformed_payload', 'a message without an order id is refused');
SELECT is(billing.apply_provider_event('mock', 'evt-malformed-5', 'payment.succeeded', jsonb_build_object('order_id', :'o1', 'amount_minor', 50000, 'currency', 'HTG')) ->> 'code', 'malformed_payload', 'a payment message without a plan is refused');
SELECT is(billing.apply_provider_event('mock', 'evt-unknown-type', 'customer.created', pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-all-30')) ->> 'status', 'ignored', 'an unknown message type is ignored');
SELECT is(pg_temp.snapshot(), '0 grants, 0 revocations, 12 events, 0 refunds', 'every authentic message is stored, none of them granted anything');
SELECT is((SELECT status FROM billing.orders WHERE id = :'o1'), 'pending', 'the order is still pending');
SELECT is((SELECT count(*)::int FROM billing.provider_events WHERE outcome = 'rejected'), 11, '11 stored as rejected');
SELECT is((SELECT count(*)::int FROM billing.provider_events WHERE outcome = 'ignored'), 1, '1 stored as ignored');
SELECT is((SELECT count(*)::int FROM billing.provider_events WHERE order_id = :'o1'), 4, 'the 4 amount / currency / plan rejections are linked to the order for reconciliation');

-- ============================================================================
-- A valid payment: applied exactly once
-- ============================================================================
SELECT is(billing.apply_provider_event('mock', 'evt-pay-1', 'payment.succeeded', pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-all-30')) #>> '{code}', 'entitlement_granted', 'a valid payment grants');
SELECT is((SELECT status FROM billing.orders WHERE id = :'o1'), 'paid', 'the order is paid');
SELECT is((SELECT learner_id::text || '|' || scope_kind || '|' || source || '|' || (extract(epoch FROM ends_at - starts_at) / 3600)::int || 'h|' || plan_id::text || '|' || idempotency_key
           FROM billing.entitlements WHERE order_id = :'o1'),
          'a0000000-0000-4000-8000-000000000001|all|purchase|720h|f0000000-0000-4000-8000-000000000001|order:' || :'o1',
          'the grant belongs to the order''s learner, with the plan''s scope and duration (30 x 24 hours)');
SELECT is((SELECT starts_at FROM billing.entitlements WHERE order_id = :'o1'), now(), 'the grant starts on the server clock');
SELECT is(billing.learner_is_entitled_at(:A, 'all', NULL, now()), true, 'the learner is entitled');
SELECT is((SELECT actor_kind || '|' || action || '|' || outcome FROM app.audit_events WHERE target_id = :'o1'), 'system|billing.provider_event.entitlement_granted|allowed', 'the access change is audited as a system action');

-- duplicate delivery of the same message
SELECT is(billing.apply_provider_event('mock', 'evt-pay-1', 'payment.succeeded', pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-all-30')) ->> 'replayed', 'true', 'the same message again is a replay');
SELECT is(billing.apply_provider_event('mock', 'evt-pay-1', 'payment.succeeded', pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-all-30')) #>> '{result,entitlement_id}',
          (SELECT id::text FROM billing.entitlements WHERE order_id = :'o1'), 'the replay returns the ORIGINAL grant id');
-- same event id, different content (a forged "upgrade" of a seen message)
SELECT is(billing.apply_provider_event('mock', 'evt-pay-1', 'payment.succeeded', pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-grade-90')) ->> 'status', 'conflict', 'a seen event id with different content is a conflict');
SELECT is(billing.apply_provider_event('mock', 'evt-pay-1', 'payment.refunded', pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-all-30')) ->> 'code', 'event_id_reused_with_different_payload', 'a seen event id with another type is a conflict');
-- the provider sends a SECOND success message with a new id for the same order
SELECT is(billing.apply_provider_event('mock', 'evt-pay-2', 'payment.succeeded', pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-all-30')) ->> 'code', 'order_already_paid', 'a second payment message for a paid order is ignored');
-- a stale failure arrives late
SELECT is(billing.apply_provider_event('mock', 'evt-fail-late', 'payment.failed', pg_temp.msg(:'o1', 50000, 'HTG')) ->> 'code', 'order_already_paid', 'a late failure message cannot un-pay an order');
SELECT is((SELECT status FROM billing.orders WHERE id = :'o1'), 'paid', 'the order is still paid');
SELECT is(pg_temp.snapshot(), '1 grants, 0 revocations, 15 events, 0 refunds', 'six deliveries about one payment: exactly one grant');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE target_id = :'o1'), 1, '... and exactly one audit record');
SELECT throws_ok(format($$SELECT billing.grant_entitlement('a0000000-0000-4000-8000-000000000001', 'all', NULL, now(), now() + interval '30 days', 'purchase', NULL, 'another-key-for-the-same-order', NULL, NULL, %L)$$, :'o1'), '23505', NULL, 'a second grant for the same order is impossible even with a new idempotency key');

-- ============================================================================
-- Refund: revokes the grant, once
-- ============================================================================
SELECT is(billing.apply_provider_event('mock', 'evt-refund-bad', 'payment.refunded', pg_temp.msg(:'o1', 100, 'HTG')) ->> 'code', 'amount_mismatch', 'a refund for another amount is refused (partial refunds are not modelled)');
SELECT is(billing.learner_is_entitled_at(:A, 'all', NULL, now()), true, '... and access is unchanged');
SELECT is(billing.apply_provider_event('mock', 'evt-refund-1', 'payment.refunded', pg_temp.msg(:'o1', 50000, 'HTG')) ->> 'code', 'order_refunded', 'a full refund is applied');
SELECT is((SELECT status FROM billing.orders WHERE id = :'o1'), 'refunded', 'the order is refunded');
SELECT is((SELECT reason_code FROM billing.entitlement_revocations r JOIN billing.entitlements e ON e.id = r.entitlement_id WHERE e.order_id = :'o1'), 'refund', 'the grant is revoked by a new record');
SELECT is((SELECT amount_minor::text || ' ' || currency FROM billing.refunds WHERE order_id = :'o1'), '50000 HTG', 'the refund is recorded in minor units + currency');
SELECT is(billing.learner_is_entitled_at(:A, 'all', NULL, now()), false, 'the learner is no longer entitled');
SELECT is(billing.apply_provider_event('mock', 'evt-refund-1', 'payment.refunded', pg_temp.msg(:'o1', 50000, 'HTG')) ->> 'replayed', 'true', 'the same refund message again is a replay');
SELECT is(billing.apply_provider_event('mock', 'evt-refund-2', 'payment.refunded', pg_temp.msg(:'o1', 50000, 'HTG')) ->> 'code', 'order_already_refunded', 'a second refund message is ignored');
SELECT is(billing.apply_provider_event('mock', 'evt-pay-3', 'payment.succeeded', pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-all-30')) ->> 'code', 'order_already_refunded', 'a payment message replayed after the refund cannot restore access');
SELECT is(billing.learner_is_entitled_at(:A, 'all', NULL, now()), false, '... the learner is still not entitled');
SELECT is(pg_temp.snapshot(), '1 grants, 1 revocations, 19 events, 1 refunds', 'one grant, one revocation, one refund');

-- ============================================================================
-- Out-of-order delivery
-- ============================================================================
-- (a) the refund message arrives BEFORE the payment message
SELECT set_config('edu.actor_id', :B, true);
SELECT billing.create_order('synthetic-all-30', 'USD', 'mock', 'order-key-0020') ->> 'order_id' AS o2 \gset
SELECT billing.create_order('synthetic-grade-90', 'HTG', 'mock', 'order-key-0021') ->> 'order_id' AS o3 \gset
SELECT set_config('edu.actor_id', '', true);
SELECT is(billing.apply_provider_event('mock', 'evt-o2-refund', 'payment.refunded', pg_temp.msg(:'o2', 400, 'USD')) ->> 'code', 'order_refunded', 'refund first: the order is closed as refunded');
SELECT is(billing.apply_provider_event('mock', 'evt-o2-pay', 'payment.succeeded', pg_temp.msg(:'o2', 400, 'USD', 'synthetic-all-30')) ->> 'code', 'order_already_refunded', 'the payment message that arrives after its own refund grants nothing');
SELECT is((SELECT count(*)::int FROM billing.entitlements WHERE learner_id = :B), 0, 'B holds no grant');
SELECT is(billing.learner_is_entitled_at(:B, 'all', NULL, now()), false, 'B is not entitled');
SELECT is((SELECT count(*)::int FROM billing.refunds WHERE order_id = :'o2'), 1, 'the refund is still on record for reconciliation');

-- (b) a failure, a duplicate failure, then the real success (failed -> paid)
SELECT is(billing.apply_provider_event('mock', 'evt-o3-fail', 'payment.failed', pg_temp.msg(:'o3', 120000, 'HTG')) ->> 'code', 'order_failed', 'a failure marks the order failed');
SELECT is(billing.apply_provider_event('mock', 'evt-o3-fail-2', 'payment.failed', pg_temp.msg(:'o3', 120000, 'HTG')) ->> 'code', 'order_already_failed', 'a second failure is ignored');
SELECT is((SELECT count(*)::int FROM billing.entitlements WHERE learner_id = :B), 0, 'a failed payment grants nothing');
SELECT is(billing.apply_provider_event('mock', 'evt-o3-pay', 'payment.succeeded', pg_temp.msg(:'o3', 120000, 'HTG', 'synthetic-grade-90')) ->> 'code', 'entitlement_granted', 'a later verified success for the same order is honoured');
SELECT is((SELECT scope_kind || '|' || scope_grade_id::text || '|' || (extract(epoch FROM ends_at - starts_at) / 3600)::int || 'h' FROM billing.entitlements WHERE order_id = :'o3'),
          'grade|b0000000-0000-4000-8000-000000000001|2160h', 'a grade plan gives a grade-scoped grant for 90 x 24 hours');
SELECT is(billing.learner_is_entitled_at(:B, 'grade', :GRADE, now()), true, 'B is entitled to the grade');
SELECT is(billing.learner_is_entitled_at(:B, 'all', NULL, now()), false, '... and not to everything');

-- ============================================================================
-- History guards (even the owner)
-- ============================================================================
SELECT throws_ok($$UPDATE billing.provider_events SET outcome = 'applied', outcome_code = 'entitlement_granted' WHERE outcome = 'rejected'$$, 'P0001', 'Provider events are append-only', 'a stored outcome cannot be rewritten');
SELECT throws_ok($$DELETE FROM billing.provider_events$$, 'P0001', NULL, 'provider events cannot be deleted');
SELECT throws_ok($$UPDATE billing.orders SET amount_expected_minor = 1$$, 'P0001', NULL, 'the expected amount of an order cannot be changed afterwards');
SELECT throws_ok($$UPDATE billing.orders SET status = 'pending' WHERE status = 'refunded'$$, 'P0001', NULL, 'a refunded order cannot be reopened');
SELECT throws_ok($$UPDATE billing.orders SET status = 'paid' WHERE status = 'refunded'$$, 'P0001', NULL, 'a refunded order cannot be marked paid');
SELECT throws_ok(format($$UPDATE billing.orders SET learner_id = 'a0000000-0000-4000-8000-000000000003' WHERE id = %L$$, :'o3'), 'P0001', NULL, 'an order cannot be moved to another learner');
SELECT throws_ok($$DELETE FROM billing.orders$$, 'P0001', NULL, 'orders cannot be deleted');
SELECT throws_ok($$UPDATE billing.refunds SET amount_minor = 1$$, 'P0001', NULL, 'refunds cannot be edited');
SELECT throws_ok($$DELETE FROM billing.refunds$$, 'P0001', NULL, 'refunds cannot be deleted');
SELECT set_config('billing.erasing', 'on', true);
SELECT throws_ok($$UPDATE billing.provider_events SET outcome = 'applied', outcome_code = 'entitlement_granted' WHERE outcome = 'rejected'$$, 'P0001', NULL, 'the erasure marker allows blanking a payload, never rewriting an outcome');
SELECT throws_ok($$DELETE FROM billing.provider_events$$, 'P0001', NULL, 'the erasure marker never allows deleting an event');
SELECT set_config('billing.erasing', '', true);

-- ============================================================================
-- Erasure with orders and events
-- ============================================================================
SELECT is(billing.erase_learner(:A),
    '{"schema":"billing","entitlements_deleted":1,"revocations_deleted":1,"orders_anonymised":1,"provider_event_payloads_blanked":11}'::jsonb,
    'erasing A: grant and revocation deleted, order anonymised, the raw payload of each of its 11 linked events blanked');
SELECT is((SELECT learner_id IS NULL AND erased_at IS NOT NULL AND amount_expected_minor = 50000 AND status = 'refunded' FROM billing.orders WHERE id = :'o1'), true, 'the order keeps its money facts and loses the person');
SELECT is((SELECT count(*)::int FROM billing.provider_events WHERE order_id = :'o1' AND payload <> '{}'::jsonb), 0, 'no raw payload of that order is left');
SELECT is((SELECT count(*)::int FROM billing.provider_events WHERE order_id = :'o3' AND payload = '{}'::jsonb), 0, 'another learner''s events are untouched');
SELECT is((SELECT count(*)::int FROM billing.entitlements WHERE learner_id = :B), 1, 'another learner''s grant is untouched');
SELECT is((SELECT count(*)::int FROM billing.refunds), 2, 'refund records are kept (amounts only)');
SELECT is(billing.apply_provider_event('mock', 'evt-pay-1', 'payment.succeeded', pg_temp.msg(:'o1', 50000, 'HTG', 'synthetic-all-30')) ->> 'replayed', 'true', 'after erasure a replayed message is still recognised (by its digest) and changes nothing');
-- an order erased while pending can never be fulfilled afterwards
SELECT set_config('edu.actor_id', :EDITOR, true);
SELECT billing.create_order('synthetic-all-30', 'HTG', 'mock', 'order-key-0030') ->> 'order_id' AS o4 \gset
SELECT set_config('edu.actor_id', '', true);
SELECT is(billing.erase_learner(:EDITOR) ->> 'orders_anonymised', '1', 'fixture: a pending order is anonymised');
SELECT is(billing.apply_provider_event('mock', 'evt-o4-pay', 'payment.succeeded', pg_temp.msg(:'o4', 50000, 'HTG', 'synthetic-all-30')) ->> 'code', 'order_erased', 'a payment for an erased order grants nothing');
SELECT is((SELECT count(*)::int FROM billing.entitlements), 1, 'only B''s grant exists at the end');

SELECT * FROM finish();
ROLLBACK;
