-- The Gold ledger cannot be double-spent, forged, edited or read across accounts.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
-- Run one statement AS THE STUDENT API ROLE with the given actor (same helper
-- as 020/050). Returns the first column as text, or 'ERROR:<sqlstate>'.
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

-- What the API does for one pushed operation: apply it, then (as the hook
-- does) ask for the award. Returns '<sync status>/<award status>/<gold>'.
CREATE FUNCTION pg_temp.push(p_actor uuid, p_op uuid, p_kind text, p_payload jsonb, p_award boolean DEFAULT true)
RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.as_api(p_actor, format(
        $q$WITH s AS MATERIALIZED (
               SELECT app.sync_apply_operation(%L, %L, %L::jsonb, sha256(convert_to(%L, 'UTF8')), 'mep-canon-1') AS o)
           SELECT (s.o ->> 'status') || CASE WHEN %L::boolean THEN
                      (SELECT '/' || (a.o ->> 'status') || '/' || (a.o ->> 'gold')
                       FROM (SELECT rewards.award_for_operation(%L) AS o) a)
                  ELSE '' END
           FROM s$q$,
        p_op, p_kind, p_payload::text, p_kind || p_payload::text, p_award, p_op))
$fn$;
CREATE FUNCTION pg_temp.answer(p_actor uuid, p_op uuid, p_question uuid, p_choice text, p_award boolean DEFAULT true)
RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.push(p_actor, p_op, 'practice_answer',
        jsonb_build_object('question_revision_id', p_question, 'response', jsonb_build_object('choice_id', p_choice)), p_award)
$fn$;
CREATE FUNCTION pg_temp.complete(p_actor uuid, p_op uuid, p_revision uuid, p_award boolean DEFAULT true)
RETURNS text LANGUAGE sql AS $fn$
    SELECT pg_temp.push(p_actor, p_op, 'lesson_completed', jsonb_build_object('lesson_revision_id', p_revision), p_award)
$fn$;
-- THE invariant: the cached balance equals the sum of the ledger.
CREATE FUNCTION pg_temp.balance_ok(p_learner uuid) RETURNS boolean LANGUAGE sql AS $fn$
    SELECT COALESCE((SELECT sum(amount) FROM rewards.ledger WHERE learner_id = p_learner), 0)
         = COALESCE((SELECT balance FROM rewards.balances WHERE learner_id = p_learner), 0)
$fn$;
CREATE FUNCTION pg_temp.ledger_state(p_learner uuid) RETURNS text LANGUAGE sql AS $fn$
    SELECT count(*) || ' rows / ' || COALESCE(sum(amount), 0) || ' gold' FROM rewards.ledger WHERE learner_id = p_learner
$fn$;

-- Empty learner state so counts are exact (rolled back at the end).
TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;
TRUNCATE rewards.achievement_awards, rewards.ledger, rewards.processed_operations,
         rewards.activity_days, rewards.streak_state, rewards.balances;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set Q1 '''d0000000-0000-4000-8000-000000000101'''
\set Q2 '''d0000000-0000-4000-8000-000000000102'''
\set Q3 '''d0000000-0000-4000-8000-000000000103'''
\set Q4 '''d0000000-0000-4000-8000-000000000104'''
\set Q5 '''d0000000-0000-4000-8000-000000000105'''
\set Q1HT '''d0000000-0000-4000-8000-000000000201'''
\set REVFR '''c0000000-0000-4000-8000-000000000001'''
\set REVHT '''c0000000-0000-4000-8000-000000000002'''

-- ---- first correct answer -------------------------------------------------------
SELECT is(pg_temp.answer(:A, '18500000-0000-4000-8000-000000000001', :Q1, 'b'), 'accepted/awarded/5',
    'a first correct answer earns the rule amount');
SELECT is((SELECT amount || '|' || entry_kind || '|' || source_kind || '|' || rule_code || '|' || rule_version || '|' || source_key
           FROM rewards.ledger WHERE learner_id = :A::uuid),
    '5|award|question_first_correct|question_first_correct|1|q:b0000000-0000-4000-8000-000000000005:addition',
    'the ledger row names the rule version and is keyed by (lesson, question key)');
SELECT is((SELECT accepted_day FROM rewards.ledger WHERE learner_id = :A::uuid),
    (SELECT (created_at AT TIME ZONE 'America/Port-au-Prince')::date FROM app.sync_receipts
      WHERE op_id = '18500000-0000-4000-8000-000000000001'),
    'the ledger day is the Haiti date of SERVER acceptance');
SELECT ok(pg_temp.balance_ok(:A), 'sum(ledger) = balance after the first award');

-- ---- replay / op-id reuse / other device / other locale -------------------------
SELECT is(pg_temp.answer(:A, '18500000-0000-4000-8000-000000000001', :Q1, 'b'), 'accepted/awarded/5',
    'replaying the same op (same payload) repeats the recorded decision ...');
SELECT is(pg_temp.ledger_state(:A), '1 rows / 5 gold', '... and awards nothing more');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.award_for_operation('18500000-0000-4000-8000-000000000001') ->> 'replayed'$$), 'true',
    'asking again for an examined operation is reported as a replay');
SELECT is(pg_temp.answer(:A, '18500000-0000-4000-8000-000000000001', :Q2, 'a'), 'conflict/awarded/5',
    'op-id reuse with a different payload is a sync conflict; the award step only repeats the old decision');
SELECT is(pg_temp.ledger_state(:A), '1 rows / 5 gold', 'the conflicting payload earned nothing');
SELECT is((SELECT count(*)::int FROM rewards.ledger WHERE learner_id = :A::uuid AND question_key = 'multiplication'), 0,
    'no row exists for the question smuggled in under a reused op id');
SELECT is(pg_temp.answer(:A, '18500000-0000-4000-8000-000000000002', :Q1, 'b'), 'accepted/duplicate/0',
    'the same correct answer from a second device (new op id) earns nothing');
SELECT is(pg_temp.answer(:A, '18500000-0000-4000-8000-000000000003', :Q1HT, 'b'), 'accepted/duplicate/0',
    'the same question in the other locale revision earns nothing (same lesson + question key)');
SELECT is(pg_temp.ledger_state(:A), '1 rows / 5 gold', 'still exactly one award for that question');
SELECT ok(pg_temp.balance_ok(:A), 'sum(ledger) = balance after replays and duplicates');

-- ---- wrong only / correct after wrong / rejected / unknown ------------------------
SELECT is(pg_temp.answer(:A, '18500000-0000-4000-8000-000000000004', :Q3, 'a'), 'accepted/not_eligible/0',
    'a wrong answer earns nothing');
SELECT is(pg_temp.ledger_state(:A), '1 rows / 5 gold', 'wrong only: no ledger row');
SELECT is(pg_temp.answer(:A, '18500000-0000-4000-8000-000000000005', :Q3, 'c'), 'accepted/awarded/5',
    'correct after wrong: the first CORRECT answer is rewarded');
SELECT is(pg_temp.answer(:A, '18500000-0000-4000-8000-000000000006', :Q4, 'zz'), 'rejected/no_award/0',
    'a rejected operation earns nothing');
SELECT is((SELECT count(*)::int FROM rewards.processed_operations WHERE op_id = '18500000-0000-4000-8000-000000000006'), 0,
    'a rejected operation leaves no trace in rewards');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.award_for_operation('18500000-0000-4000-8000-0000000000ff')::text$$),
    '{"gold": 0, "status": "no_award", "replayed": false, "achievements": []}',
    'an unknown op id earns nothing');
SELECT is(pg_temp.as_api(:B, $$SELECT rewards.award_for_operation('18500000-0000-4000-8000-000000000001')::text$$),
    pg_temp.as_api(:B, $$SELECT rewards.award_for_operation('18500000-0000-4000-8000-0000000000ff')::text$$),
    'someone else''s op id is indistinguishable from an unknown one (no information leak)');
SELECT is(pg_temp.as_api(:B, $$SELECT rewards.award_for_operation('18500000-0000-4000-8000-000000000006')::text$$),
    pg_temp.as_api(:A, $$SELECT rewards.award_for_operation('18500000-0000-4000-8000-000000000006')::text$$),
    'a rejected op answers exactly like an unknown one');
SELECT is((SELECT count(*)::int FROM rewards.ledger WHERE learner_id = :B::uuid), 0, 'B earned nothing from A''s operations');
SELECT is(pg_temp.as_api(NULL, $$SELECT rewards.award_for_operation('18500000-0000-4000-8000-000000000001')$$), 'ERROR:42501',
    'no actor: the award function refuses');
SELECT is(pg_temp.as_api(NULL, $$SELECT rewards.reconcile_learner(10)$$), 'ERROR:42501', 'no actor: reconcile refuses');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.award_for_operation(NULL)->>'status'$$), 'no_award', 'a NULL op id earns nothing');

-- ---- lesson completion --------------------------------------------------------------
SELECT is(pg_temp.complete(:A, '18500000-0000-4000-8000-000000000007', :REVFR), 'accepted/awarded/30',
    'first completion earns the lesson amount (20) plus the first-lesson achievement bonus (10)');
SELECT is(pg_temp.complete(:A, '18500000-0000-4000-8000-000000000008', :REVHT), 'accepted/duplicate/0',
    'a repeated completion (other device, other revision) earns nothing');
SELECT is(pg_temp.complete(:A, '18500000-0000-4000-8000-000000000007', :REVFR), 'accepted/awarded/30',
    'replaying the first completion repeats the decision');
SELECT is(pg_temp.ledger_state(:A), '4 rows / 40 gold', '2 questions (5+5) + lesson (20) + achievement bonus (10)');
SELECT is((SELECT string_agg(source_key, ',' ORDER BY source_key) FROM rewards.ledger WHERE learner_id = :A::uuid AND source_kind <> 'question_first_correct'),
    'a:first_lesson_completed,l:b0000000-0000-4000-8000-000000000005', 'the lesson is keyed by lesson id, the bonus by achievement code');
SELECT is((SELECT string_agg(achievement_code || ':' || (ledger_id IS NOT NULL), ',' ORDER BY achievement_code)
           FROM rewards.achievement_awards WHERE learner_id = :A::uuid),
    'first_correct_answer:false,first_lesson_completed:true',
    'achievements are recorded once; the one with a bonus links its ledger row');
SELECT is((SELECT l.source_kind || '|' || l.amount FROM rewards.achievement_awards a JOIN rewards.ledger l ON l.id = a.ledger_id
           WHERE a.learner_id = :A::uuid AND a.achievement_code = 'first_lesson_completed'), 'achievement|10',
    'the linked row is the achievement bonus');
SELECT ok(pg_temp.balance_ok(:A), 'sum(ledger) = balance after the completion');
SELECT is((SELECT string_agg(outcome || '=' || n, ',' ORDER BY outcome) FROM (
               SELECT outcome, count(*) AS n FROM rewards.processed_operations WHERE learner_id = :A::uuid GROUP BY outcome) t),
    'awarded=3,duplicate=3,not_eligible=1', 'every accepted operation was examined exactly once');

-- ---- immutability (even for the table owner) --------------------------------------
SELECT throws_ok($$UPDATE rewards.ledger SET amount = 500$$, '23514', NULL, 'ledger rows cannot be updated');
SELECT throws_ok($$UPDATE rewards.ledger SET learner_id = 'a0000000-0000-4000-8000-000000000002'$$, '23514', NULL, 'ledger rows cannot be moved to another learner');
SELECT throws_ok($$DELETE FROM rewards.ledger$$, '23514', NULL, 'ledger rows cannot be deleted');
SELECT throws_ok($$DELETE FROM rewards.achievement_awards$$, '23514', NULL, 'achievement awards cannot be deleted');
SELECT throws_ok($$UPDATE rewards.processed_operations SET outcome = 'awarded', gold = 99$$, '23514', NULL, 'recorded decisions cannot be rewritten');
SELECT throws_ok($$UPDATE rewards.rules SET amount = 1000 WHERE code = 'question_first_correct'$$, '23514', NULL, 'a rule version''s amount cannot be edited');
SELECT throws_ok($$UPDATE rewards.rules SET per_day_cap = NULL WHERE code = 'question_first_correct'$$, '23514', NULL, 'a rule version''s caps cannot be edited');
SELECT throws_ok($$INSERT INTO rewards.rules (code, version, event_kind, amount, is_active) VALUES ('question_first_correct', 2, 'question_first_correct', 50, true)$$,
    '23505', NULL, 'two live versions of one rule are impossible');
SELECT throws_ok($$DELETE FROM rewards.rules WHERE code = 'question_first_correct'$$, '23503', NULL, 'a rule version used by the ledger cannot be deleted');

-- ---- forged / zero / negative amounts are impossible (even for the table owner) ----
-- A legitimate accepted, correct, not-yet-rewarded attempt to forge around: Q2.
SELECT is(pg_temp.answer(:A, '18500000-0000-4000-8000-000000000009', :Q2, 'a', false), 'accepted', 'A answers Q2 correctly; the hook is not run');
CREATE FUNCTION pg_temp.forge(p_amount integer, p_op uuid, p_question_key text, p_rule text DEFAULT 'question_first_correct') RETURNS text
LANGUAGE plpgsql AS $fn$
BEGIN
    INSERT INTO rewards.ledger (learner_id, entry_kind, amount, rule_code, rule_version, source_kind,
                                source_op_id, lesson_id, question_key, accepted_at, accepted_day)
    SELECT 'a0000000-0000-4000-8000-000000000001', 'award', p_amount, p_rule, 1, 'question_first_correct',
           p_op, 'b0000000-0000-4000-8000-000000000005', p_question_key,
           COALESCE(r.created_at, now()), rewards.haiti_day(COALESCE(r.created_at, now()))
    FROM (SELECT 1) one LEFT JOIN app.sync_receipts r
      ON r.learner_id = 'a0000000-0000-4000-8000-000000000001' AND r.op_id = p_op;
    RETURN 'inserted';
EXCEPTION WHEN OTHERS THEN
    RETURN 'ERROR:' || SQLSTATE;
END;
$fn$;
SELECT is(pg_temp.forge(999, '18500000-0000-4000-8000-000000000009', 'multiplication'), 'ERROR:23514', 'an amount other than the rule''s is refused');
SELECT is(pg_temp.forge(6, '18500000-0000-4000-8000-000000000009', 'multiplication'), 'ERROR:23514', 'even one Gold more than the rule is refused');
SELECT is(pg_temp.forge(0, '18500000-0000-4000-8000-000000000009', 'multiplication'), 'ERROR:23514', 'a zero amount is refused');
SELECT is(pg_temp.forge(-5, '18500000-0000-4000-8000-000000000009', 'multiplication'), 'ERROR:23514', 'a negative award is refused');
SELECT is(pg_temp.forge(5000, '18500000-0000-4000-8000-000000000009', 'multiplication'), 'ERROR:23514', 'an out-of-range amount is refused');
SELECT is(pg_temp.forge(10, '18500000-0000-4000-8000-000000000009', 'multiplication', 'achievement_first_lesson'), 'ERROR:23514', 'borrowing another rule''s amount is refused');
SELECT is(pg_temp.forge(5, gen_random_uuid(), 'multiplication'), 'ERROR:23514', 'a row without an accepted operation is refused');
SELECT is(pg_temp.forge(5, '18500000-0000-4000-8000-000000000006', 'soustraction'), 'ERROR:23514', 'a row pointing at a REJECTED operation is refused');
SELECT is(pg_temp.forge(5, '18500000-0000-4000-8000-000000000004', 'deux-etapes'), 'ERROR:23514', 'a row pointing at a WRONG answer is refused');
SELECT is(pg_temp.forge(5, '18500000-0000-4000-8000-000000000009', 'egal-zero'), 'ERROR:23514', 'a row for a question the operation did not answer is refused');
SELECT is(pg_temp.forge(5, '18500000-0000-4000-8000-000000000002', 'addition'), 'ERROR:23505', 'a second row for an already rewarded question hits the unique key');
SELECT throws_ok($$INSERT INTO rewards.ledger (learner_id, entry_kind, amount, rule_code, rule_version, source_kind, source_op_id, lesson_id, question_key, source_key, accepted_at, accepted_day)
                   VALUES ('a0000000-0000-4000-8000-000000000001', 'award', 5, 'question_first_correct', 1, 'question_first_correct', '18500000-0000-4000-8000-000000000009', 'b0000000-0000-4000-8000-000000000005', 'multiplication', 'q:anything', now(), rewards.haiti_day(now()))$$,
    '428C9', NULL, 'the source key cannot be supplied by the writer');
SELECT throws_ok($$INSERT INTO rewards.ledger (learner_id, entry_kind, amount, rule_code, rule_version, source_kind, source_op_id, lesson_id, question_key, accepted_at, accepted_day)
                   SELECT learner_id, 'award', 5, 'question_first_correct', 1, 'question_first_correct', op_id, 'b0000000-0000-4000-8000-000000000005', 'multiplication', created_at, rewards.haiti_day(created_at) + 1
                   FROM app.sync_receipts WHERE op_id = '18500000-0000-4000-8000-000000000009'$$,
    '23514', NULL, 'the ledger day cannot differ from the Haiti date of acceptance');
SELECT is(pg_temp.ledger_state(:A), '4 rows / 40 gold', 'none of the forgeries changed the ledger');
SELECT is(pg_temp.forge(5, '18500000-0000-4000-8000-000000000009', 'multiplication'), 'inserted',
    'control: the same insert with the true facts and the rule amount is accepted ...');
SELECT ok(pg_temp.balance_ok(:A), '... and the balance followed it through the trigger (sum(ledger) = balance)');

-- ---- the student API role can read its own rows and write nothing ------------------
SELECT is(pg_temp.as_api(:A, $$INSERT INTO rewards.ledger (learner_id, entry_kind, amount, rule_code, rule_version, source_kind, source_op_id, lesson_id, question_key, accepted_at, accepted_day) VALUES ('a0000000-0000-4000-8000-000000000001', 'award', 5, 'question_first_correct', 1, 'question_first_correct', '18500000-0000-4000-8000-000000000009', 'b0000000-0000-4000-8000-000000000005', 'egal-zero', now(), current_date) RETURNING 1$$), 'ERROR:42501', 'edu_api cannot insert into the ledger');
SELECT is(pg_temp.as_api(:A, 'UPDATE rewards.ledger SET amount = 1000 RETURNING 1'), 'ERROR:42501', 'edu_api cannot update the ledger');
SELECT is(pg_temp.as_api(:A, 'DELETE FROM rewards.ledger RETURNING 1'), 'ERROR:42501', 'edu_api cannot delete from the ledger');
SELECT is(pg_temp.as_api(:A, 'UPDATE rewards.balances SET balance = 1000000 RETURNING 1'), 'ERROR:42501', 'edu_api cannot edit a balance');
SELECT is(pg_temp.as_api(:A, $$INSERT INTO rewards.balances (learner_id, balance, lifetime_earned) VALUES ('a0000000-0000-4000-8000-000000000001', 9, 9) RETURNING 1$$), 'ERROR:42501', 'edu_api cannot create a balance');
SELECT is(pg_temp.as_api(:A, $$INSERT INTO rewards.achievement_awards (learner_id, achievement_code, source_op_id, awarded_at, awarded_day) VALUES ('a0000000-0000-4000-8000-000000000001', 'three_day_streak', gen_random_uuid(), now(), current_date) RETURNING 1$$), 'ERROR:42501', 'edu_api cannot grant itself an achievement');
SELECT is(pg_temp.as_api(:A, $$UPDATE rewards.streak_state SET longest_run_days = 365 RETURNING 1$$), 'ERROR:42501', 'edu_api cannot edit a streak');
SELECT is(pg_temp.as_api(:A, $$UPDATE rewards.rules SET is_active = false RETURNING 1$$), 'ERROR:42501', 'edu_api cannot touch the rules');
SELECT is(pg_temp.as_api(:A, 'SELECT count(*) FROM rewards.rules'), 'ERROR:42501', 'edu_api cannot read the rules table');
SELECT is(pg_temp.as_api(:A, 'SELECT count(*) FROM rewards.processed_operations'), 'ERROR:42501', 'edu_api cannot read processed operations');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.rebuild_balance('a0000000-0000-4000-8000-000000000002')$$), 'ERROR:42501', 'edu_api cannot call rebuild for another learner');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.rebuild_balance('a0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', '... nor for itself: rebuild is not an API capability');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.apply_operation('a0000000-0000-4000-8000-000000000002', gen_random_uuid())$$), 'ERROR:42501', 'edu_api cannot name a learner to award');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.reconcile_learner_internal('a0000000-0000-4000-8000-000000000002', 10)$$), 'ERROR:42501', 'edu_api cannot reconcile another learner');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.reconcile_batch(10, 10)$$), 'ERROR:42501', 'edu_api cannot run the batch reconcile (worker only)');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.reverse_entry((SELECT id FROM rewards.ledger LIMIT 1), 'test_correction')$$), 'ERROR:42501', 'edu_api cannot reverse entries');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.staff_reverse_entry((SELECT id FROM rewards.ledger LIMIT 1), 'test_correction')$$), 'ERROR:42501', 'edu_api cannot call the staff reversal');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.staff_adjust('a0000000-0000-4000-8000-000000000001', 100, 'support_goodwill', gen_random_uuid())$$), 'ERROR:42501', 'edu_api cannot call the staff adjustment');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.erase_learner('a0000000-0000-4000-8000-000000000002')$$), 'ERROR:42501', 'edu_api cannot call the erasure hook');
SELECT is(pg_temp.as_api(:A, $$SELECT rewards.rebuild_streak('a0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'edu_api cannot call rebuild_streak');
SELECT is(pg_temp.as_api(:A, $$WITH s AS (SELECT set_config('rewards.erasing_learner', 'a0000000-0000-4000-8000-000000000001', true)), d AS (DELETE FROM rewards.ledger RETURNING 1) SELECT count(*) FROM d, s$$), 'ERROR:42501',
    'setting the erasure marker does not give edu_api a way to delete');

-- ---- cross-account isolation ---------------------------------------------------------
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-000000000001', :Q1, 'b'), 'accepted/awarded/5',
    'B earns for the same question independently (and may reuse an op id A used)');
SELECT is(pg_temp.as_api(:A, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM rewards.ledger'), '5/0', 'A reads only own ledger rows');
SELECT is(pg_temp.as_api(:B, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM rewards.ledger'), '1/0', 'B reads only own ledger rows');
SELECT is(pg_temp.as_api(:B, $$SELECT count(*) FROM rewards.ledger WHERE learner_id = 'a0000000-0000-4000-8000-000000000001'$$), '0', 'B cannot read A''s ledger by id');
SELECT is(pg_temp.as_api(:A, 'SELECT string_agg(learner_id::text || $$=$$ || balance, $$,$$) FROM rewards.balances'), 'a0000000-0000-4000-8000-000000000001=45', 'A reads only own balance');
SELECT is(pg_temp.as_api(:B, 'SELECT string_agg(learner_id::text || $$=$$ || balance, $$,$$) FROM rewards.balances'), 'a0000000-0000-4000-8000-000000000002=5', 'B reads only own balance');
SELECT is(pg_temp.as_api(:B, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM rewards.achievement_awards'), '1/0', 'B reads only own achievements');
SELECT is(pg_temp.as_api(:B, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE learner_id <> app.current_actor_id()) FROM rewards.streak_state'), '1/0', 'B reads only own streak');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM rewards.ledger'), '0', 'no actor: no ledger rows');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM rewards.balances'), '0', 'no actor: no balances');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM rewards.achievement_awards'), '0', 'no actor: no achievements');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM rewards.streak_state'), '0', 'no actor: no streak');
SELECT is(pg_temp.as_api(:A, 'SELECT count(*) FROM rewards.achievement_definitions'), '4', 'active achievement definitions are readable');
UPDATE rewards.achievement_definitions SET is_active = false WHERE code = 'three_day_streak';
SELECT is(pg_temp.as_api(:A, 'SELECT count(*) FROM rewards.achievement_definitions'), '3', 'an inactive definition is hidden from the API');
UPDATE rewards.achievement_definitions SET is_active = true WHERE code = 'three_day_streak';

-- ---- reconcile after the hook was off -------------------------------------------------
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-00000000000a', :Q2, 'a', false), 'accepted', 'hook off: B answers correctly');
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-00000000000b', :Q3, 'a', false), 'accepted', 'hook off: B answers wrongly');
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-00000000000c', :Q4, 'zz', false), 'rejected', 'hook off: B sends a rejected op');
SELECT is(pg_temp.complete(:B, '18500000-0000-4000-8000-00000000000d', :REVHT, false), 'accepted', 'hook off: B completes the lesson');
SELECT is(pg_temp.ledger_state(:B), '1 rows / 5 gold', 'with the hook off nothing was awarded for those operations');
SELECT is(pg_temp.as_api(:B, $$SELECT rewards.reconcile_learner(200)::text$$),
    '{"gold": 35, "more": false, "examined": 3, "balance_corrected": false}',
    'reconcile examines the 3 accepted operations: 5 (question) + 20 (lesson) + 10 (bonus)');
SELECT is(pg_temp.ledger_state(:B), '4 rows / 40 gold', 'the ledger is healed');
SELECT is(pg_temp.as_api(:B, $$SELECT rewards.reconcile_learner(200)::text$$),
    '{"gold": 0, "more": false, "examined": 0, "balance_corrected": false}', 'reconcile is idempotent');
SELECT is(pg_temp.ledger_state(:B), '4 rows / 40 gold', 'a second reconcile changes nothing');
SELECT ok(pg_temp.balance_ok(:B), 'sum(ledger) = balance after reconcile');
SELECT is((SELECT l.accepted_at = r.created_at FROM rewards.ledger l JOIN app.sync_receipts r ON r.learner_id = l.learner_id AND r.op_id = l.source_op_id
           WHERE l.learner_id = :B::uuid AND l.source_kind = 'lesson_first_completed'), true,
    'a reconciled award carries the ORIGINAL acceptance instant, not the reconcile time');
SELECT is(pg_temp.as_api(:A, $$SELECT (o ->> 'examined') || '/' || (o ->> 'gold') FROM (SELECT rewards.reconcile_learner(200) AS o) t$$), '1/0',
    'A''s reconcile examines only A''s own pending operation (the Q2 answer, already paid by the control insert)');
SELECT is(pg_temp.ledger_state(:B), '4 rows / 40 gold', '... and does not touch B');
-- bounded: limit 1 leaves the rest for the next call
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-00000000000e', :Q4, 'd', false), 'accepted', 'hook off: another correct answer');
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-00000000000f', :Q5, 'b', false), 'accepted', 'hook off: and another');
SELECT is(pg_temp.as_api(:B, $$SELECT (o ->> 'examined') || '/' || (o ->> 'more') FROM (SELECT rewards.reconcile_learner(1) AS o) t$$), '1/true', 'reconcile is bounded and says when more remains');
SELECT is((SELECT (o ->> 'learners') || '/' || (o ->> 'examined') FROM (SELECT rewards.reconcile_batch(10, 10) AS o) t), '1/1',
    'the batch variant (run here as owner) finishes the remaining operation');
SELECT ok(pg_temp.balance_ok(:B), 'sum(ledger) = balance after bounded and batch reconcile');
SELECT is(pg_temp.ledger_state(:B), '6 rows / 50 gold', 'B: 4 questions + lesson + bonus');

-- ---- rebuild equality ------------------------------------------------------------------
UPDATE rewards.balances SET balance = 9999, lifetime_earned = 9999 WHERE learner_id = :A::uuid;
SELECT ok(NOT pg_temp.balance_ok(:A), 'control: the cached balance was corrupted by hand');
SELECT is((rewards.rebuild_balance(:A) ->> 'corrected')::boolean, true, 'rebuild_balance reports the correction');
SELECT ok(pg_temp.balance_ok(:A), 'sum(ledger) = balance after rebuild');
DELETE FROM rewards.balances WHERE learner_id = :A::uuid;
SELECT is(rewards.rebuild_balance(:A)::text, '{"balance": 45, "corrected": true, "balance_before": 0, "ledger_entries": 5}',
    'rebuild from scratch recreates the balance from the ledger alone');
SELECT is((SELECT balance || '/' || lifetime_earned FROM rewards.balances WHERE learner_id = :A::uuid), '45/45', 'rebuilt balance and lifetime total');
SELECT is((rewards.rebuild_balance(:A) ->> 'corrected')::boolean, false, 'a rebuild of a correct balance changes nothing');
SELECT is(rewards.rebuild_balance('a0000000-0000-4000-8000-000000000003') ->> 'balance', '0', 'rebuild for a learner with no ledger is zero');
SELECT is((SELECT count(*)::int FROM rewards.balances WHERE learner_id = 'a0000000-0000-4000-8000-000000000003'), 0, '... and creates no row');

-- ---- corrections are new reversal rows ---------------------------------------------------
CREATE TEMP TABLE reversal AS
    SELECT rewards.reverse_entry((SELECT id FROM rewards.ledger WHERE learner_id = :A::uuid AND question_key = 'addition'),
                                 'test_correction') AS id;
SELECT is((SELECT entry_kind || '|' || amount || '|' || source_kind FROM rewards.ledger WHERE id = (SELECT id FROM reversal)),
    'reversal|-5|reversal', 'a correction is a new negative row');
SELECT is((SELECT balance || '/' || lifetime_earned FROM rewards.balances WHERE learner_id = :A::uuid), '40/45',
    'the balance drops; the lifetime total keeps what was earned');
SELECT ok(pg_temp.balance_ok(:A), 'sum(ledger) = balance after a reversal');
SELECT throws_ok($$SELECT rewards.reverse_entry((SELECT id FROM rewards.ledger WHERE learner_id = 'a0000000-0000-4000-8000-000000000001' AND question_key = 'addition'), 'test_correction')$$,
    '23505', NULL, 'an award can be reversed only once');
SELECT throws_ok($$SELECT rewards.reverse_entry((SELECT id FROM reversal), 'test_correction')$$, '22023', NULL, 'a reversal cannot itself be reversed');
SELECT throws_ok($$INSERT INTO rewards.ledger (learner_id, entry_kind, amount, rule_code, rule_version, source_kind, reverses_ledger_id, accepted_at, accepted_day, reason_code)
                   SELECT learner_id, 'reversal', -20, rule_code, rule_version, 'reversal', id, now(), rewards.haiti_day(now()), 'test_correction'
                   FROM rewards.ledger WHERE learner_id = 'a0000000-0000-4000-8000-000000000001' AND question_key = 'deux-etapes'$$,
    '23514', NULL, 'a reversal cannot remove more than the award it negates');
SELECT throws_ok($$INSERT INTO rewards.ledger (learner_id, entry_kind, amount, rule_code, rule_version, source_kind, reverses_ledger_id, accepted_at, accepted_day, reason_code)
                   SELECT 'a0000000-0000-4000-8000-000000000002', 'reversal', -5, rule_code, rule_version, 'reversal', id, now(), rewards.haiti_day(now()), 'test_correction'
                   FROM rewards.ledger WHERE learner_id = 'a0000000-0000-4000-8000-000000000001' AND question_key = 'deux-etapes'$$,
    '23514', NULL, 'a reversal cannot be booked against another learner');
SELECT is(pg_temp.answer(:A, '18500000-0000-4000-8000-000000000010', :Q1, 'b'), 'accepted/duplicate/0',
    'a reversed award cannot be earned again');
SELECT ok(pg_temp.balance_ok(:A), 'sum(ledger) = balance after the reversal scenarios');

-- ---- bounded farming: caps ---------------------------------------------------------------
-- A fresh start for B with a stricter (synthetic) rule version.
SELECT lives_ok($$SELECT rewards.erase_learner('a0000000-0000-4000-8000-000000000002')$$, 'B is erased for the cap scenarios');
TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed, app.lesson_progress, app.account_sync_state;
SELECT lives_ok($$SELECT rewards.erase_learner('a0000000-0000-4000-8000-000000000001')$$, 'A is erased for the cap scenarios');
UPDATE rewards.rules SET is_active = false WHERE code = 'question_first_correct' AND version = 1;
INSERT INTO rewards.rules (code, version, event_kind, amount, per_lesson_cap, per_day_cap, is_active)
    VALUES ('question_first_correct', 2, 'question_first_correct', 5, 10, NULL, true);
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-000000000101', :Q1, 'b'), 'accepted/awarded/5', 'per-lesson cap 10: first question pays');
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-000000000102', :Q2, 'a'), 'accepted/awarded/5', 'per-lesson cap 10: second question pays');
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-000000000103', :Q3, 'c'), 'accepted/capped_lesson/0', 'per-lesson cap 10: the third is capped');
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-000000000103', :Q3, 'c'), 'accepted/capped_lesson/0', 'a capped decision is final on replay');
SELECT is((SELECT rule_version FROM rewards.ledger WHERE learner_id = :B::uuid AND question_key = 'multiplication'), 2, 'rows record the rule version that paid them');
SELECT is(pg_temp.ledger_state(:B), '2 rows / 10 gold', 'the cap bounded the lesson at 10 Gold');
SELECT ok(pg_temp.balance_ok(:B), 'sum(ledger) = balance under the per-lesson cap');

UPDATE rewards.rules SET is_active = false WHERE code = 'question_first_correct' AND version = 2;
INSERT INTO rewards.rules (code, version, event_kind, amount, per_lesson_cap, per_day_cap, is_active)
    VALUES ('question_first_correct', 3, 'question_first_correct', 5, NULL, 15, true);
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-000000000104', :Q4, 'd'), 'accepted/awarded/5', 'per-day cap 15: third award of the day pays (10 + 5)');
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-000000000105', :Q5, 'b'), 'accepted/capped_day/0', 'per-day cap 15: the next one is capped');
SELECT is(pg_temp.ledger_state(:B), '3 rows / 15 gold', 'the cap bounded the day at 15 Gold');
-- The cap is per Haiti day of acceptance: the same learner on ANOTHER accepted day is not capped.
INSERT INTO app.sync_receipts (learner_id, op_id, op_kind, canon_version, payload_sha256, result_code, result, created_at)
    VALUES (:A, '18500000-0000-4000-8000-000000000201', 'practice_answer', 'mep-canon-1', sha256('d1'), 'accepted', '{}', '2026-06-01T15:00:00Z'),
           (:A, '18500000-0000-4000-8000-000000000202', 'practice_answer', 'mep-canon-1', sha256('d2'), 'accepted', '{}', '2026-06-01T15:01:00Z'),
           (:A, '18500000-0000-4000-8000-000000000203', 'practice_answer', 'mep-canon-1', sha256('d3'), 'accepted', '{}', '2026-06-01T15:02:00Z'),
           (:A, '18500000-0000-4000-8000-000000000204', 'practice_answer', 'mep-canon-1', sha256('d4'), 'accepted', '{}', '2026-06-01T15:03:00Z'),
           (:A, '18500000-0000-4000-8000-000000000205', 'practice_answer', 'mep-canon-1', sha256('d5'), 'accepted', '{}', '2026-06-02T15:00:00Z');
INSERT INTO app.practice_attempts (learner_id, op_id, lesson_revision_id, question_revision_id, response, score, scoring_version, accepted_at)
    VALUES (:A, '18500000-0000-4000-8000-000000000201', :REVFR, :Q1, '{"choice_id":"b"}', 1, 'mcq-v1', '2026-06-01T15:00:00Z'),
           (:A, '18500000-0000-4000-8000-000000000202', :REVFR, :Q2, '{"choice_id":"a"}', 1, 'mcq-v1', '2026-06-01T15:01:00Z'),
           (:A, '18500000-0000-4000-8000-000000000203', :REVFR, :Q3, '{"choice_id":"c"}', 1, 'mcq-v1', '2026-06-01T15:02:00Z'),
           (:A, '18500000-0000-4000-8000-000000000204', :REVFR, :Q4, '{"choice_id":"d"}', 1, 'mcq-v1', '2026-06-01T15:03:00Z'),
           (:A, '18500000-0000-4000-8000-000000000205', :REVFR, :Q5, '{"choice_id":"b"}', 1, 'mcq-v1', '2026-06-02T15:00:00Z');
SELECT is(pg_temp.as_api(:A, $$SELECT (o ->> 'examined') || '/' || (o ->> 'gold') FROM (SELECT rewards.reconcile_learner(200) AS o) t$$), '5/20',
    'five correct answers accepted over two days: 15 on day one (capped), 5 on day two');
SELECT is((SELECT string_agg(accepted_day || '=' || total, ',' ORDER BY accepted_day) FROM (
               SELECT accepted_day, sum(amount) AS total FROM rewards.ledger WHERE learner_id = :A::uuid GROUP BY accepted_day) t),
    '2026-06-01=15,2026-06-02=5', 'the day cap is applied per Haiti day of server acceptance');
SELECT is((SELECT outcome FROM rewards.processed_operations WHERE op_id = '18500000-0000-4000-8000-000000000204'), 'capped_day',
    'the fourth answer of day one was capped');
SELECT ok(pg_temp.balance_ok(:A), 'sum(ledger) = balance under the per-day cap');

UPDATE rewards.rules SET is_active = false WHERE code = 'question_first_correct';
SELECT is(pg_temp.answer(:B, '18500000-0000-4000-8000-000000000106', :Q1HT, 'a'), 'accepted/not_eligible/0', 'control: wrong answers stay not eligible');
SELECT is(pg_temp.answer(:A, '18500000-0000-4000-8000-000000000206', :Q4, 'd'), 'accepted/no_active_rule/0',
    'with no live rule a correct answer earns nothing (switching Gold off is a data change)');

-- ---- erasure hook ------------------------------------------------------------------------
SELECT throws_ok($$DELETE FROM rewards.ledger WHERE learner_id = 'a0000000-0000-4000-8000-000000000002'$$, '23514', NULL,
    'control: outside the hook nothing can be deleted');
SELECT is((rewards.erase_learner(:A) #>> '{deleted,ledger}')::int, 4, 'erase_learner reports what it removed');
SELECT is((SELECT (SELECT count(*) FROM rewards.ledger WHERE learner_id = :A::uuid)
                + (SELECT count(*) FROM rewards.balances WHERE learner_id = :A::uuid)
                + (SELECT count(*) FROM rewards.processed_operations WHERE learner_id = :A::uuid)
                + (SELECT count(*) FROM rewards.activity_days WHERE learner_id = :A::uuid)
                + (SELECT count(*) FROM rewards.streak_state WHERE learner_id = :A::uuid)
                + (SELECT count(*) FROM rewards.achievement_awards WHERE learner_id = :A::uuid))::int, 0,
    'no rewards row of the erased learner remains in any table');
SELECT is(pg_temp.ledger_state(:B), '3 rows / 15 gold', 'the other learner is untouched');
SELECT ok(pg_temp.balance_ok(:B), 'the other learner''s balance still equals the ledger');
SELECT throws_ok($$DELETE FROM rewards.ledger WHERE learner_id = 'a0000000-0000-4000-8000-000000000002'$$, '23514', NULL,
    'after the hook returns, deletes are blocked again in the same transaction');
SELECT lives_ok($$SELECT set_config('rewards.erasing_learner', 'a0000000-0000-4000-8000-000000000001', true)$$, 'forge the erasure marker for A');
SELECT throws_ok($$DELETE FROM rewards.ledger WHERE learner_id = 'a0000000-0000-4000-8000-000000000002'$$, '23514', NULL,
    'the erasure marker for one learner never unlocks another learner''s rows');
SELECT lives_ok($$SELECT set_config('rewards.erasing_learner', 'a0000000-0000-4000-8000-000000000002', true)$$, 'forge the erasure marker for B');
SELECT throws_ok($$UPDATE rewards.ledger SET amount = 1 WHERE learner_id = 'a0000000-0000-4000-8000-000000000002'$$, '23514', NULL,
    'the erasure marker never allows an UPDATE');
SELECT lives_ok($$SELECT set_config('rewards.erasing_learner', '', true)$$, 'clear the marker');
SELECT is(rewards.erase_learner(:A) #>> '{deleted,ledger}', '0', 'erasing twice is harmless');
SELECT throws_ok($$SELECT rewards.erase_learner(NULL)$$, '22023', NULL, 'the hook needs a learner id');

SELECT * FROM finish();
ROLLBACK;
