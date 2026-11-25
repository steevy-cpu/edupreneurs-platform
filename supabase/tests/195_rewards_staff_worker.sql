-- Worker reconciliation and audited admin corrections of the Gold ledger.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_worker TO postgres WITH INHERIT FALSE, SET TRUE;
-- Run one statement AS THE GIVEN ROLE with the given actor (same helper as 101).
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
CREATE FUNCTION pg_temp.balance_ok(p_learner uuid) RETURNS boolean LANGUAGE sql AS $fn$
    SELECT COALESCE((SELECT sum(amount) FROM rewards.ledger WHERE learner_id = p_learner), 0)
         = COALESCE((SELECT balance FROM rewards.balances WHERE learner_id = p_learner), 0)
$fn$;
CREATE FUNCTION pg_temp.ledger_state(p_learner uuid) RETURNS text LANGUAGE sql AS $fn$
    SELECT count(*) || ' rows / ' || COALESCE(sum(amount), 0) || ' gold' FROM rewards.ledger WHERE learner_id = p_learner
$fn$;
-- Audit events are append-only and other test runs leave theirs behind, so
-- every look at the audit trail is limited to THIS transaction's events
-- (created_at defaults to now(), the transaction start).
CREATE TEMP VIEW my_audit AS SELECT * FROM app.audit_events WHERE created_at = now();
CREATE FUNCTION pg_temp.audits(p_action text) RETURNS integer LANGUAGE sql AS $fn$
    SELECT count(*)::int FROM my_audit WHERE action = p_action
$fn$;

TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;
TRUNCATE rewards.achievement_awards, rewards.ledger, rewards.processed_operations,
         rewards.activity_days, rewards.streak_state, rewards.balances;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
\set ADMIN '''a0000000-0000-4000-8000-000000000004'''
-- The synthetic reviewer is also made an admin for this test (rolled back).
INSERT INTO app.staff_roles (user_id, role) VALUES (:ADMIN, 'admin');
SELECT is((SELECT count(*)::int FROM my_audit WHERE action LIKE 'rewards%'), 0, 'no rewards audit event before the test');

-- Two learners sync with the hook off: accepted operations nobody examined.
SELECT is(pg_temp.as_role('edu_api', :A, $$SELECT app.sync_apply_operation('19500000-0000-4000-8000-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}', sha256('a1'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'A answers correctly (hook off)');
SELECT is(pg_temp.as_role('edu_api', :A, $$SELECT app.sync_apply_operation('19500000-0000-4000-8000-000000000002','lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000001"}', sha256('a2'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'A completes the lesson (hook off)');
SELECT is(pg_temp.as_role('edu_api', :B, $$SELECT app.sync_apply_operation('19500000-0000-4000-8000-000000000003','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000102","response":{"choice_id":"a"}}', sha256('b1'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'B answers correctly (hook off)');
SELECT is((SELECT count(*)::int FROM rewards.ledger), 0, 'nothing awarded yet');

-- ---- the worker --------------------------------------------------------------------
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT rewards.reconcile_batch(1, 200)::text$$),
    '{"gold": 35, "examined": 2, "learners": 1}', 'the worker reconciles a bounded number of learners (first by id: A)');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT rewards.reconcile_batch(50, 200)::text$$),
    '{"gold": 5, "examined": 1, "learners": 1}', 'the next run takes the rest (B)');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT rewards.reconcile_batch(50, 200)::text$$),
    '{"gold": 0, "examined": 0, "learners": 0}', 'with nothing pending the worker does nothing');
SELECT is(pg_temp.ledger_state(:A), '3 rows / 35 gold', 'A was healed by the worker');
SELECT is(pg_temp.ledger_state(:B), '1 rows / 5 gold', 'B was healed by the worker');
SELECT ok(pg_temp.balance_ok(:A) AND pg_temp.balance_ok(:B), 'sum(ledger) = balance after the worker run');
SELECT is(pg_temp.as_role('edu_worker', NULL, 'SELECT count(*) FROM rewards.ledger'), 'ERROR:42501', 'the worker cannot read the ledger');
SELECT is(pg_temp.as_role('edu_worker', NULL, 'SELECT count(*) FROM rewards.balances'), 'ERROR:42501', 'the worker cannot read balances');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$UPDATE rewards.balances SET balance = 1000 RETURNING 1$$), 'ERROR:42501', 'the worker cannot edit balances');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT rewards.apply_operation('a0000000-0000-4000-8000-000000000001', gen_random_uuid())$$), 'ERROR:42501', 'the worker cannot call the internal award function');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT rewards.rebuild_balance('a0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'the worker cannot call rebuild_balance');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT rewards.erase_learner('a0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'the worker cannot call the erasure hook');
SELECT is(pg_temp.as_role('edu_worker', NULL, $$SELECT rewards.reverse_entry((SELECT gen_random_uuid()), 'test_correction')$$), 'ERROR:42501', 'the worker cannot reverse entries');
SELECT is(pg_temp.as_role('edu_worker', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 50, 'support_goodwill', gen_random_uuid())$$), 'ERROR:42501', 'the worker cannot adjust, even with an admin actor id');
SELECT is(pg_temp.as_role('edu_worker', :ADMIN, $$SELECT rewards.staff_reverse_entry(gen_random_uuid(), 'test_correction')$$), 'ERROR:42501', 'the worker cannot call the staff reversal');
SELECT is(pg_temp.as_role('edu_worker', :A, $$SELECT rewards.award_for_operation('19500000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'the worker cannot call the learner award function');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.reconcile_batch(10, 10)$$), 'ERROR:42501', 'staff cannot run the worker reconcile');
SELECT is(pg_temp.as_role('edu_api', :A, $$SELECT rewards.reconcile_batch(10, 10)$$), 'ERROR:42501', 'the student API cannot run the worker reconcile');

-- ---- who may correct: an ACTIVE ADMIN through edu_staff, nobody else ------------------
CREATE TEMP TABLE target AS
    SELECT (SELECT id FROM rewards.ledger WHERE learner_id = :A::uuid AND source_kind = 'question_first_correct') AS question_row,
           (SELECT id FROM rewards.ledger WHERE learner_id = :A::uuid AND source_kind = 'lesson_first_completed') AS lesson_row;
GRANT SELECT ON target TO edu_staff, edu_api, edu_worker;
SELECT is(pg_temp.as_role('edu_staff', :EDITOR, $$SELECT rewards.staff_reverse_entry((SELECT question_row FROM target), 'test_correction')$$), 'ERROR:42501', 'an editor cannot reverse');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 10, 'support_goodwill', gen_random_uuid())$$), 'ERROR:42501', 'an editor cannot adjust');
SELECT is(pg_temp.as_role('edu_staff', :A, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 10, 'support_goodwill', gen_random_uuid())$$), 'ERROR:42501', 'a learner on the staff channel cannot adjust');
SELECT is(pg_temp.as_role('edu_staff', NULL, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 10, 'support_goodwill', gen_random_uuid())$$), 'ERROR:42501', 'no actor: refused');
UPDATE app.staff_roles SET is_active = false WHERE user_id = :ADMIN AND role = 'admin';
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 10, 'support_goodwill', gen_random_uuid())$$), 'ERROR:42501', 'an INACTIVE admin role is refused');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_reverse_entry((SELECT question_row FROM target), 'test_correction')$$), 'ERROR:42501', 'an INACTIVE admin cannot reverse');
UPDATE app.staff_roles SET is_active = true WHERE user_id = :ADMIN AND role = 'admin';
SELECT is(pg_temp.ledger_state(:A), '3 rows / 35 gold', 'none of the refused calls changed the ledger');
SELECT is((SELECT count(*)::int FROM my_audit WHERE action LIKE 'rewards%'), 0, '... and none left an "allowed" audit event');

-- ---- audited reversal ---------------------------------------------------------------------
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_reverse_entry((SELECT question_row FROM target), 'a learner said it was unfair')$$), 'ERROR:22023', 'free text is not a reason: a code from the list is required');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_reverse_entry((SELECT question_row FROM target), 'made_up_code')$$), 'ERROR:22023', 'an unknown reason code is refused');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_reverse_entry((SELECT question_row FROM target), NULL)$$), 'ERROR:22023', 'a reason code is mandatory');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_reverse_entry(gen_random_uuid(), 'scoring_error')$$), 'ERROR:22023', 'an unknown ledger row cannot be reversed');
SELECT is(pg_temp.audits('rewards_ledger.reverse'), 0, 'refused reversals leave no audit event');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT (o ->> 'amount') || '/' || (o ->> 'balance') FROM (SELECT rewards.staff_reverse_entry((SELECT question_row FROM target), 'scoring_error') AS o) t$$), '-5/30',
    'an admin reverses the question award: a new -5 row, balance 30');
SELECT is((SELECT entry_kind || '|' || amount || '|' || reason_code || '|' || actor_id FROM rewards.ledger WHERE reverses_ledger_id = (SELECT question_row FROM target)),
    'reversal|-5|scoring_error|a0000000-0000-4000-8000-000000000004', 'the reversal row records the reason code and the admin');
SELECT is((SELECT amount FROM rewards.ledger WHERE id = (SELECT question_row FROM target)), 5, 'the original row is untouched');
SELECT is((SELECT actor_id::text || '|' || outcome || '|' || target_kind || '|' || (target_id = (SELECT id FROM rewards.ledger WHERE source_kind = 'reversal'))
                  || '|' || (details ->> 'learner_id') || '|' || (details ->> 'amount') || '|' || (details ->> 'reason_code')
                  || '|' || ((details ->> 'reversed_ledger_id')::uuid = (SELECT question_row FROM target))
           FROM my_audit WHERE action = 'rewards_ledger.reverse'),
    'a0000000-0000-4000-8000-000000000004|allowed|rewards_ledger|true|a0000000-0000-4000-8000-000000000001|-5|scoring_error|true',
    'one audit event names the admin, the new row, the learner, the amount and the reason code');
SELECT is((SELECT array_agg(k ORDER BY k) FROM my_audit e, jsonb_object_keys(e.details) k WHERE e.action = 'rewards_ledger.reverse'),
    ARRAY['amount','learner_id','reason_code','reversed_ledger_id'], 'the audit details hold ids, a number and a code — nothing typed by a person');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_reverse_entry((SELECT question_row FROM target), 'scoring_error')$$), 'ERROR:23505', 'an award can be reversed only once');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_reverse_entry(NULL, 'scoring_error')$$), 'ERROR:22023', 'a NULL ledger id is refused');
SELECT is(pg_temp.audits('rewards_ledger.reverse'), 1, 'still exactly one reversal audit event');
SELECT ok(pg_temp.balance_ok(:A), 'sum(ledger) = balance after the staff reversal');

-- ---- audited, bounded adjustment ---------------------------------------------------------------
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 101, 'support_goodwill', gen_random_uuid())$$), 'ERROR:22023', 'more than 100 Gold in one adjustment is refused');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', -101, 'abuse_confirmed', gen_random_uuid())$$), 'ERROR:22023', 'more than -100 Gold in one adjustment is refused');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 1000000, 'support_goodwill', gen_random_uuid())$$), 'ERROR:22023', 'a fortune is refused');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 0, 'support_goodwill', gen_random_uuid())$$), 'ERROR:22023', 'a zero adjustment is refused');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', NULL, 'support_goodwill', gen_random_uuid())$$), 'ERROR:22023', 'a NULL amount is refused');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 10, 'because I felt like it', gen_random_uuid())$$), 'ERROR:22023', 'free text is not a reason');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 10, 'support_goodwill', NULL)$$), 'ERROR:22023', 'an adjustment id is mandatory');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust(gen_random_uuid(), 10, 'support_goodwill', gen_random_uuid())$$), 'ERROR:22023', 'an unknown learner is refused');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', -31, 'abuse_confirmed', gen_random_uuid())$$), 'ERROR:22023', 'an adjustment cannot push a balance below zero (balance is 30)');
SELECT is(pg_temp.audits('rewards_ledger.adjust'), 0, 'refused adjustments leave no audit event');
SELECT is(pg_temp.ledger_state(:A), '4 rows / 30 gold', 'refused adjustments changed nothing');

SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT (o ->> 'amount') || '/' || (o ->> 'balance') || '/' || (o ->> 'replayed') FROM (SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 40, 'support_goodwill', '19500000-0000-4000-8000-0000000000a1') AS o) t$$), '40/70/false',
    'an admin credits 40 Gold');
SELECT is((SELECT entry_kind || '|' || source_kind || '|' || amount || '|' || reason_code || '|' || actor_id || '|' || source_key || '|' || (rule_code IS NULL)
           FROM rewards.ledger WHERE adjustment_id = '19500000-0000-4000-8000-0000000000a1'),
    'adjustment|adjustment|40|support_goodwill|a0000000-0000-4000-8000-000000000004|adj:19500000-0000-4000-8000-0000000000a1|true',
    'the adjustment is its own kind of ledger row, keyed by the adjustment id');
SELECT is((SELECT actor_id::text || '|' || outcome || '|' || (details ->> 'learner_id') || '|' || (details ->> 'amount') || '|' || (details ->> 'reason_code') || '|' || (details ->> 'adjustment_id')
           FROM my_audit WHERE action = 'rewards_ledger.adjust'),
    'a0000000-0000-4000-8000-000000000004|allowed|a0000000-0000-4000-8000-000000000001|40|support_goodwill|19500000-0000-4000-8000-0000000000a1',
    'one audit event describes the adjustment');
-- idempotent on the adjustment id
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT (o ->> 'balance') || '/' || (o ->> 'replayed') FROM (SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 40, 'support_goodwill', '19500000-0000-4000-8000-0000000000a1') AS o) t$$), '70/true',
    'retrying the same adjustment is a replay');
SELECT is(pg_temp.audits('rewards_ledger.adjust'), 1, 'a replay writes no second audit event');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 50, 'support_goodwill', '19500000-0000-4000-8000-0000000000a1')$$), 'ERROR:22023', 'the same id with another amount is refused');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000002', 40, 'support_goodwill', '19500000-0000-4000-8000-0000000000a1')$$), 'ERROR:22023', 'the same id for another learner is refused');
SELECT is(pg_temp.ledger_state(:A), '5 rows / 70 gold', 'exactly one adjustment row');
-- negative adjustment
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', -20, 'abuse_confirmed', '19500000-0000-4000-8000-0000000000a2') ->> 'balance'$$), '50', 'an admin removes 20 Gold');
SELECT is((SELECT balance || '/' || lifetime_earned FROM rewards.balances WHERE learner_id = :A::uuid), '50/75', 'balance and lifetime total after reversal and adjustments');
-- daily credit bound per learner (300)
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 100, 'support_goodwill', '19500000-0000-4000-8000-0000000000a3') ->> 'balance'$$), '150', 'second credit of the day (140 so far)');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 100, 'support_goodwill', '19500000-0000-4000-8000-0000000000a4') ->> 'balance'$$), '250', 'third credit of the day (240 so far)');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 61, 'support_goodwill', '19500000-0000-4000-8000-0000000000a5')$$), 'ERROR:22023', 'a credit that would pass 300 for the learner today is refused');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 60, 'support_goodwill', '19500000-0000-4000-8000-0000000000a5') ->> 'balance'$$), '310', 'exactly up to the daily bound is allowed');
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 1, 'support_goodwill', '19500000-0000-4000-8000-0000000000a6')$$), 'ERROR:22023', 'then not one Gold more');
SELECT is(pg_temp.audits('rewards_ledger.adjust'), 5, 'five accepted adjustments, five audit events');
SELECT ok(pg_temp.balance_ok(:A), 'sum(ledger) = balance after the adjustments');
SELECT is(pg_temp.ledger_state(:B), '1 rows / 5 gold', 'the other learner is untouched');
-- an admin cannot adjust their own account
INSERT INTO app.learner_profiles (user_id) VALUES (:ADMIN);
SELECT is(pg_temp.as_role('edu_staff', :ADMIN, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000004', 10, 'support_goodwill', gen_random_uuid())$$), 'ERROR:42501', 'an admin cannot adjust their own Gold');

-- ---- the ledger defends itself even against a privileged direct insert ------------------------
SELECT throws_ok($$INSERT INTO rewards.ledger (learner_id, entry_kind, amount, source_kind, adjustment_id, actor_id, reason_code, accepted_at, accepted_day)
                   VALUES ('a0000000-0000-4000-8000-000000000002', 'adjustment', 101, 'adjustment', gen_random_uuid(), 'a0000000-0000-4000-8000-000000000004', 'support_goodwill', now(), rewards.haiti_day(now()))$$,
    '23514', NULL, 'a direct adjustment above 100 violates the ledger shape');
SELECT throws_ok($$INSERT INTO rewards.ledger (learner_id, entry_kind, amount, source_kind, adjustment_id, actor_id, reason_code, accepted_at, accepted_day)
                   VALUES ('a0000000-0000-4000-8000-000000000002', 'adjustment', 10, 'adjustment', gen_random_uuid(), 'a0000000-0000-4000-8000-000000000003', 'support_goodwill', now(), rewards.haiti_day(now()))$$,
    '23514', NULL, 'a direct adjustment attributed to a non-admin is refused');
SELECT throws_ok($$INSERT INTO rewards.ledger (learner_id, entry_kind, amount, source_kind, adjustment_id, actor_id, reason_code, accepted_at, accepted_day)
                   VALUES ('a0000000-0000-4000-8000-000000000004', 'adjustment', 10, 'adjustment', gen_random_uuid(), 'a0000000-0000-4000-8000-000000000004', 'support_goodwill', now(), rewards.haiti_day(now()))$$,
    '23514', NULL, 'a direct self-adjustment is refused');
SELECT throws_ok($$INSERT INTO rewards.ledger (learner_id, entry_kind, amount, source_kind, adjustment_id, actor_id, accepted_at, accepted_day)
                   VALUES ('a0000000-0000-4000-8000-000000000002', 'adjustment', 10, 'adjustment', gen_random_uuid(), 'a0000000-0000-4000-8000-000000000004', now(), rewards.haiti_day(now()))$$,
    '23514', NULL, 'a direct adjustment without a reason code is refused');
SELECT throws_ok($$INSERT INTO rewards.ledger (learner_id, entry_kind, amount, source_kind, adjustment_id, actor_id, reason_code, accepted_at, accepted_day)
                   VALUES ('a0000000-0000-4000-8000-000000000002', 'adjustment', 10, 'adjustment', gen_random_uuid(), 'a0000000-0000-4000-8000-000000000004', 'Free text reason!', now(), rewards.haiti_day(now()))$$,
    '23514', NULL, 'the reason column itself accepts only a code');
SELECT throws_ok($$INSERT INTO rewards.ledger (learner_id, entry_kind, amount, source_kind, adjustment_id, actor_id, reason_code, accepted_at, accepted_day)
                   VALUES ('a0000000-0000-4000-8000-000000000002', 'adjustment', 10, 'adjustment', '19500000-0000-4000-8000-0000000000a1', 'a0000000-0000-4000-8000-000000000004', 'support_goodwill', now(), rewards.haiti_day(now()))$$,
    '23505', NULL, 'an adjustment id cannot be spent twice, even for another learner');
SELECT throws_ok($$UPDATE rewards.ledger SET amount = 100 WHERE entry_kind = 'adjustment'$$, '23514', NULL, 'adjustment rows are append-only like every other row');

-- ---- adjustments do not disturb the earning rules ------------------------------------------------
SELECT is(pg_temp.as_role('edu_api', :A, $$WITH s AS MATERIALIZED (SELECT app.sync_apply_operation('19500000-0000-4000-8000-000000000009','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000103","response":{"choice_id":"c"}}', sha256('a9'), 'mep-canon-1') AS o)
        SELECT (rewards.award_for_operation('19500000-0000-4000-8000-000000000009') ->> 'status') FROM s$$), 'awarded',
    'staff credits do not count against the learner''s earning caps');
SELECT is(pg_temp.as_role('edu_api', :A, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM rewards.ledger'), '10/0',
    'the learner sees reversals and adjustments in their own ledger, and only their own');
SELECT is((rewards.rebuild_balance(:A) ->> 'corrected')::boolean, false, 'a rebuild from the ledger agrees with the running balance');
SELECT is((rewards.erase_learner(:A) #>> '{deleted,ledger}')::int, 10, 'the erasure hook removes reversal and adjustment rows too');

SELECT * FROM finish();
ROLLBACK;
