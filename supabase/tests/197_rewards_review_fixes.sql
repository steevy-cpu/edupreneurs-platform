-- Review fixes: caps are final per source key, a switched-off rule is NOT final,
-- a completion needs evidence of learning (rule parameter), atomic rule switch.
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
-- Push one operation and run the hook: '<sync status>/<award status>/<gold>'.
CREATE FUNCTION pg_temp.push(p_actor uuid, p_op uuid, p_kind text, p_payload jsonb) RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.as_api(p_actor, format(
        $q$WITH s AS MATERIALIZED (
               SELECT app.sync_apply_operation(%L, %L, %L::jsonb, sha256(convert_to(%L, 'UTF8')), 'mep-canon-1') AS o)
           SELECT (s.o ->> 'status') || (SELECT '/' || (a.o ->> 'status') || '/' || (a.o ->> 'gold')
                                         FROM (SELECT rewards.award_for_operation(%L) AS o) a) FROM s$q$,
        p_op, p_kind, p_payload::text, p_kind || p_payload::text, p_op))
$fn$;
CREATE FUNCTION pg_temp.answer(p_actor uuid, p_op uuid, p_question uuid, p_choice text) RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.push(p_actor, p_op, 'practice_answer',
        jsonb_build_object('question_revision_id', p_question, 'response', jsonb_build_object('choice_id', p_choice)))
$fn$;
CREATE FUNCTION pg_temp.complete(p_actor uuid, p_op uuid, p_revision uuid) RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.push(p_actor, p_op, 'lesson_completed', jsonb_build_object('lesson_revision_id', p_revision))
$fn$;
CREATE FUNCTION pg_temp.balance_ok(p_learner uuid) RETURNS boolean LANGUAGE sql AS $fn$
    SELECT COALESCE((SELECT sum(amount) FROM rewards.ledger WHERE learner_id = p_learner), 0)
         = COALESCE((SELECT balance FROM rewards.balances WHERE learner_id = p_learner), 0)
$fn$;
CREATE FUNCTION pg_temp.ledger_state(p_learner uuid) RETURNS text LANGUAGE sql AS $fn$
    SELECT count(*) || ' rows / ' || COALESCE(sum(amount), 0) || ' gold' FROM rewards.ledger WHERE learner_id = p_learner
$fn$;
-- An accepted correct answer at an exact server instant (clock pinned).
CREATE FUNCTION pg_temp.correct_at(p_learner uuid, p_op uuid, p_question uuid, p_choice text, p_instant timestamptz)
RETURNS void LANGUAGE sql AS $fn$
    INSERT INTO app.sync_receipts (learner_id, op_id, op_kind, canon_version, payload_sha256, result_code, result, created_at)
    VALUES (p_learner, p_op, 'practice_answer', 'mep-canon-1', sha256(p_op::text::bytea), 'accepted', '{}', p_instant);
    INSERT INTO app.practice_attempts (learner_id, op_id, lesson_revision_id, question_revision_id, response, score, scoring_version, accepted_at)
    VALUES (p_learner, p_op, 'c0000000-0000-4000-8000-000000000001', p_question, jsonb_build_object('choice_id', p_choice), 1, 'mcq-v1', p_instant);
$fn$;

TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;
TRUNCATE rewards.achievement_awards, rewards.ledger, rewards.processed_operations, rewards.forfeited_sources,
         rewards.pending_completions, rewards.activity_days, rewards.streak_state, rewards.balances;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set Q1 '''d0000000-0000-4000-8000-000000000101'''
\set Q2 '''d0000000-0000-4000-8000-000000000102'''
\set Q3 '''d0000000-0000-4000-8000-000000000103'''
\set Q4 '''d0000000-0000-4000-8000-000000000104'''
\set REVFR '''c0000000-0000-4000-8000-000000000001'''
\set REVHT '''c0000000-0000-4000-8000-000000000002'''

-- ---- M2: a completion needs evidence of learning (default ON) ------------------------
SELECT is((SELECT requires_scored_answer FROM rewards.rules WHERE code = 'lesson_first_completed' AND is_active), true,
    'the seeded lesson rule requires a server-scored answer (safer synthetic default, PO-09)');
SELECT is(pg_temp.complete(:A, '19700000-0000-4000-8000-000000000001', :REVFR), 'accepted/awaiting_evidence/0',
    'a bare completion is accepted as learning data but earns nothing yet');
SELECT is(pg_temp.complete(:A, '19700000-0000-4000-8000-000000000002', :REVHT), 'accepted/awaiting_evidence/0',
    'a second bare completion changes nothing');
SELECT is(pg_temp.ledger_state(:A), '0 rows / 0 gold', 'no Gold and ...');
SELECT is((SELECT count(*)::int FROM rewards.achievement_awards WHERE learner_id = :A::uuid), 0, '... no achievement without evidence');
SELECT throws_ok($$INSERT INTO rewards.ledger (learner_id, entry_kind, amount, rule_code, rule_version, source_kind, source_op_id, lesson_id, accepted_at, accepted_day)
                   SELECT learner_id, 'award', 20, 'lesson_first_completed', 1, 'lesson_first_completed', op_id, 'b0000000-0000-4000-8000-000000000005', created_at, rewards.haiti_day(created_at)
                   FROM app.sync_receipts WHERE op_id = '19700000-0000-4000-8000-000000000001'$$,
    '23514', NULL, 'even a privileged direct insert cannot pay a completion without evidence under this rule');
SELECT is(pg_temp.answer(:A, '19700000-0000-4000-8000-000000000003', :Q1, 'a'), 'accepted/not_eligible/30',
    'the first scored answer (even a wrong one) releases the waiting completion: 20 + 10 bonus');
SELECT is((SELECT source_op_id::text FROM rewards.ledger WHERE learner_id = :A::uuid AND source_kind = 'lesson_first_completed'),
    '19700000-0000-4000-8000-000000000001', 'the completion is paid under its own (first) operation');
SELECT is((SELECT l.accepted_at = r.created_at FROM rewards.ledger l JOIN app.sync_receipts r ON r.op_id = l.source_op_id AND r.learner_id = l.learner_id
           WHERE l.learner_id = :A::uuid AND l.source_kind = 'lesson_first_completed'), true, '... and dated by the completion''s acceptance');
SELECT is((SELECT count(*)::int FROM rewards.pending_completions WHERE learner_id = :A::uuid), 0, 'nothing is left waiting');
SELECT is(pg_temp.answer(:A, '19700000-0000-4000-8000-000000000003', :Q1, 'a'), 'accepted/not_eligible/30', 'the replay repeats the decision');
SELECT is(pg_temp.complete(:A, '19700000-0000-4000-8000-000000000004', :REVFR), 'accepted/duplicate/0', 'a later completion is a duplicate');
SELECT is(pg_temp.ledger_state(:A), '2 rows / 30 gold', 'paid exactly once');
SELECT ok(pg_temp.balance_ok(:A), 'sum(ledger) = balance');
-- with evidence already there, the completion pays at once
SELECT is(pg_temp.answer(:B, '19700000-0000-4000-8000-000000000011', :Q1, 'a'), 'accepted/not_eligible/0', 'B answers (wrongly) first');
SELECT is(pg_temp.complete(:B, '19700000-0000-4000-8000-000000000012', :REVHT), 'accepted/awarded/30', 'B''s completion pays immediately');
-- the other setting: a rule version WITHOUT the requirement
SELECT lives_ok($$SELECT rewards.erase_learner('a0000000-0000-4000-8000-000000000002')$$, 'reset B');
TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed, app.lesson_progress, app.account_sync_state;
INSERT INTO rewards.rules (code, version, event_kind, amount, per_lesson_cap, per_day_cap, requires_scored_answer)
    VALUES ('lesson_first_completed', 2, 'lesson_first_completed', 20, 20, 200, false);
SELECT lives_ok($$SELECT rewards.set_active_rule_version('lesson_first_completed', 2)$$, 'switch to the version without the requirement');
SELECT is(pg_temp.complete(:B, '19700000-0000-4000-8000-000000000013', :REVHT), 'accepted/awarded/30',
    'requirement OFF: a bare completion pays (the behaviour before the review)');
SELECT throws_ok($$UPDATE rewards.rules SET requires_scored_answer = true WHERE code = 'lesson_first_completed' AND version = 2$$, '23514', NULL,
    'the requirement is part of the immutable rule version');
SELECT throws_ok($$INSERT INTO rewards.rules (code, version, event_kind, amount, requires_scored_answer) VALUES ('question_first_correct', 7, 'question_first_correct', 5, true)$$,
    '23514', NULL, 'the parameter exists only for the lesson rule');
SELECT lives_ok($$SELECT rewards.set_active_rule_version('lesson_first_completed', 1)$$, 'switch back');

-- ---- atomic rule switch -----------------------------------------------------------------
SELECT is((SELECT string_agg(version::text, ',') FROM rewards.rules WHERE code = 'lesson_first_completed' AND is_active), '1', 'exactly one live version after switching');
SELECT throws_ok($$SELECT rewards.set_active_rule_version('lesson_first_completed', 99)$$, '22023', NULL, 'an unknown version is refused (and nothing is switched off)');
SELECT is((SELECT count(*)::int FROM rewards.rules WHERE code = 'lesson_first_completed' AND is_active), 1, 'still one live version');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.set_active_rule_version('lesson_first_completed', 2)$$), 'ERROR:42501', 'edu_api cannot switch rules');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.try_award_event('a0000000-0000-4000-8000-000000000001', 'question_first_correct', 'b0000000-0000-4000-8000-000000000005', 'addition', gen_random_uuid())$$), 'ERROR:42501', 'edu_api cannot call the internal decision function');
SELECT is(pg_temp.as_api(:A, 'SELECT count(*) FROM rewards.forfeited_sources'), 'ERROR:42501', 'edu_api cannot read forfeits');
SELECT is(pg_temp.as_api(:A, 'DELETE FROM rewards.pending_completions RETURNING 1'), 'ERROR:42501', 'edu_api cannot touch pending completions');

-- ---- security L1: a cap is final for the source key ----------------------------------------
SELECT lives_ok($$SELECT rewards.erase_learner('a0000000-0000-4000-8000-000000000001')$$, 'reset A');
TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed, app.lesson_progress, app.account_sync_state;
INSERT INTO rewards.rules (code, version, event_kind, amount, per_lesson_cap, per_day_cap)
    VALUES ('question_first_correct', 2, 'question_first_correct', 5, NULL, 5);
SELECT lives_ok($$SELECT rewards.set_active_rule_version('question_first_correct', 2)$$, 'a test rule: at most 5 Gold per day');
SELECT lives_ok($$SELECT pg_temp.correct_at('a0000000-0000-4000-8000-000000000001', '19700000-0000-4000-8000-000000000021', 'd0000000-0000-4000-8000-000000000101', 'b', '2026-01-15T04:59:58Z')$$, 'day 1, 23:59:58 local: Q1 correct');
SELECT lives_ok($$SELECT pg_temp.correct_at('a0000000-0000-4000-8000-000000000001', '19700000-0000-4000-8000-000000000022', 'd0000000-0000-4000-8000-000000000102', 'a', '2026-01-15T04:59:59Z')$$, 'day 1, 23:59:59 local: Q2 correct');
SELECT lives_ok($$SELECT pg_temp.correct_at('a0000000-0000-4000-8000-000000000001', '19700000-0000-4000-8000-000000000023', 'd0000000-0000-4000-8000-000000000103', 'c', '2026-01-15T05:00:00Z')$$, 'day 2, 00:00:00 local: Q3 correct');
SELECT is(pg_temp.as_api(:A, $$SELECT (o ->> 'examined') || '/' || (o ->> 'gold') FROM (SELECT rewards.reconcile_learner(200) AS o) t$$), '3/10', 'three answers examined, two paid');
SELECT is((SELECT string_agg(p.outcome, ',' ORDER BY r.created_at) FROM rewards.processed_operations p JOIN app.sync_receipts r ON r.op_id = p.op_id AND r.learner_id = p.learner_id WHERE p.learner_id = :A::uuid),
    'awarded,capped_day,awarded', 'the day cap applies per Haiti day: one second after local midnight is a new day');
SELECT is((SELECT string_agg(accepted_day || '=' || amount, ',' ORDER BY accepted_day) FROM rewards.ledger WHERE learner_id = :A::uuid),
    '2026-01-14=5,2026-01-15=5', 'one award on each side of Haiti midnight');
SELECT is((SELECT source_key || '|' || outcome FROM rewards.forfeited_sources WHERE learner_id = :A::uuid),
    'q:b0000000-0000-4000-8000-000000000005:multiplication|capped_day', 'the capped question is recorded as forfeited');
-- the attack from the review: come back another day with a NEW operation for the capped question
SELECT lives_ok($$SELECT pg_temp.correct_at('a0000000-0000-4000-8000-000000000001', '19700000-0000-4000-8000-000000000024', 'd0000000-0000-4000-8000-000000000102', 'a', '2026-01-20T15:00:00Z')$$, 'five days later: Q2 correct again, new op id');
SELECT is(pg_temp.as_api(:A, $$SELECT (o ->> 'examined') || '/' || (o ->> 'gold') FROM (SELECT rewards.reconcile_learner(200) AS o) t$$), '1/0', 'examined, not paid');
SELECT is((SELECT outcome FROM rewards.processed_operations WHERE op_id = '19700000-0000-4000-8000-000000000024'), 'forfeited',
    'a capped source key cannot be re-earned later: the cap binds a modified client like an honest one');
SELECT is(pg_temp.answer(:A, '19700000-0000-4000-8000-000000000025', 'd0000000-0000-4000-8000-000000000202', 'a'), 'accepted/forfeited/0', '... nor through the other locale, through the live hook');
SELECT throws_ok($$DELETE FROM rewards.forfeited_sources$$, '23514', NULL, 'forfeits are append-only');
SELECT is(pg_temp.ledger_state(:A), '2 rows / 10 gold', 'the ledger is unchanged');
SELECT ok(pg_temp.balance_ok(:A), 'sum(ledger) = balance');

-- ---- integration L3: a switched-off rule is NOT final ---------------------------------------
UPDATE rewards.rules SET is_active = false WHERE code = 'question_first_correct';
SELECT is(pg_temp.answer(:B, '19700000-0000-4000-8000-000000000031', :Q4, 'd'), 'accepted/no_active_rule/0', 'with no live rule a correct answer is not paid ...');
SELECT is(pg_temp.answer(:B, '19700000-0000-4000-8000-000000000031', :Q4, 'd'), 'accepted/no_active_rule/0', '... and a replay says the same');
SELECT is((SELECT count(*)::int FROM rewards.forfeited_sources WHERE learner_id = :B::uuid), 0, '... but nothing is forfeited');
SELECT is((SELECT count(*)::int FROM rewards.activity_days WHERE learner_id = :B::uuid), 1, 'the day still counts for the streak while Gold is off');
SELECT lives_ok($$SELECT rewards.set_active_rule_version('question_first_correct', 1)$$, 'the rule is switched on again');
SELECT is((SELECT count(*)::int FROM rewards.processed_operations WHERE outcome = 'no_active_rule'), 0, 'the unpaid decisions were forgotten');
SELECT is(pg_temp.as_api(:B, $$SELECT (o ->> 'examined') || '/' || (o ->> 'gold') FROM (SELECT rewards.reconcile_learner(200) AS o) t$$), '1/5',
    'reconcile heals the operation after re-activation, without the phone sending anything');
SELECT is((SELECT source_op_id::text || '|' || rule_version FROM rewards.ledger WHERE learner_id = :B::uuid AND question_key = 'soustraction'),
    '19700000-0000-4000-8000-000000000031|1', 'paid under the original operation by the version now in force');
SELECT throws_ok($$DELETE FROM rewards.processed_operations WHERE outcome = 'awarded'$$, '23514', NULL, 'other decisions stay undeletable');
SELECT lives_ok($$SELECT set_config('rewards.reexamining', 'on', true)$$, 'forge the re-examination marker');
SELECT throws_ok($$DELETE FROM rewards.processed_operations WHERE outcome <> 'no_active_rule'$$, '23514', NULL, 'the marker only ever frees unpaid no_active_rule rows');
SELECT lives_ok($$SELECT set_config('rewards.reexamining', 'off', true)$$, 'clear the marker');
SELECT ok(pg_temp.balance_ok(:B), 'sum(ledger) = balance');

-- ---- erasure covers the new tables -----------------------------------------------------------
SELECT is((rewards.erase_learner(:A) #>> '{deleted,forfeited_sources}')::int, 1, 'the erasure hook removes forfeits');
SELECT is(pg_temp.complete(:A, '19700000-0000-4000-8000-000000000041', :REVFR), 'accepted/awarded/30', 'control: A has scored answers in the lesson, so the completion pays');
SELECT lives_ok($$SELECT rewards.erase_learner('a0000000-0000-4000-8000-000000000001')$$, 'erase A again');
SELECT is((SELECT (SELECT count(*) FROM rewards.forfeited_sources WHERE learner_id = :A::uuid) + (SELECT count(*) FROM rewards.pending_completions WHERE learner_id = :A::uuid))::int, 0,
    'no forfeit or pending completion of the erased learner remains');

SELECT * FROM finish();
ROLLBACK;
