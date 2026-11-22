-- app.sync_apply_operation(): exactly-once, server-scored, gap-free versions.
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

-- Start from empty learner state so counts are exact. This runs inside the
-- test transaction and is rolled back at the end: nothing is really deleted.
TRUNCATE app.practice_attempts, app.sync_receipts, app.account_change_feed,
         app.lesson_progress, app.account_sync_state;

-- ---- first submission -----------------------------------------------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}', sha256('op1'), 'mep-canon-1') ::text$$)::jsonb #>> '{result,is_correct}', 'true', 'a correct answer is scored correct by the server');
SELECT is((SELECT score::text FROM app.practice_attempts WHERE op_id = '44444444-4444-4444-8444-000000000001'), '1.0000', 'canonical score 1 stored');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000002','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000102","response":{"choice_id":"d"}}', sha256('op2'), 'mep-canon-1') #>> '{{result,is_correct}}'$$), 'false', 'a wrong answer is scored incorrect');
SELECT is((SELECT score::text FROM app.practice_attempts WHERE op_id = '44444444-4444-4444-8444-000000000002'), '0.0000', 'canonical score 0 stored');
SELECT is((SELECT lesson_revision_id::text FROM app.practice_attempts WHERE op_id = '44444444-4444-4444-8444-000000000001'), 'c0000000-0000-4000-8000-000000000001', 'the lesson revision is derived by the server from the question');

-- ---- identical retry ------------------------------------------------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}', sha256('op1'), 'mep-canon-1') ->> 'replayed'$$), 'true', 'same op_id + same digest is a replay');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}', sha256('op1'), 'mep-canon-1') #>> '{{result,attempt_id}}'$$),
          (SELECT id::text FROM app.practice_attempts WHERE op_id = '44444444-4444-4444-8444-000000000001'), 'the replay returns the ORIGINAL attempt id');
SELECT is((SELECT count(*)::int FROM app.practice_attempts), 2, 'replays created no attempt');
SELECT is((SELECT count(*)::int FROM app.account_change_feed), 2, 'replays created no change');
SELECT is((SELECT count(*)::int FROM app.sync_receipts), 2, 'replays created no receipt');

-- ---- op_id reuse with different content -------------------------------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"a"}}', sha256('DIFFERENT'), 'mep-canon-1') ->> 'status'$$), 'conflict', 'same op_id + different digest is a conflict');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000001','lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000001"}', sha256('DIFFERENT2'), 'mep-canon-1') #>> '{{result,code}}'$$), 'op_id_reused_with_different_payload', 'conflict carries a clear code');
SELECT is((SELECT count(*)::int FROM app.practice_attempts), 2, 'conflict created no attempt');
SELECT is((SELECT count(*)::int FROM app.account_change_feed), 2, 'conflict created no change');
SELECT is((SELECT count(*)::int FROM app.lesson_progress), 0, 'conflict created no progress');
SELECT is((SELECT response ->> 'choice_id' FROM app.practice_attempts WHERE op_id = '44444444-4444-4444-8444-000000000001'), 'b', 'the original answer is untouched');
SELECT is((SELECT current_version::int FROM app.account_sync_state WHERE learner_id = 'a0000000-0000-4000-8000-000000000001'), 2, 'conflict did not advance the version');

-- ---- rejected operations are terminal and durable -----------------------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000003','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"zz"}}', sha256('op3'), 'mep-canon-1') #>> '{{result,code}}'$$), 'invalid_choice', 'a choice that is not offered is rejected');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000003','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"zz"}}', sha256('op3'), 'mep-canon-1') ->> 'status'$$), 'rejected', 'retrying a rejected op returns rejected again');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000003','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"zz"}}', sha256('op3'), 'mep-canon-1') ->> 'replayed'$$), 'true', '... as a replay');
SELECT is((SELECT result_code FROM app.sync_receipts WHERE op_id = '44444444-4444-4444-8444-000000000003'), 'rejected', 'the rejection has a durable receipt');
SELECT is((SELECT count(*)::int FROM app.practice_attempts), 2, 'rejected op created no attempt');

-- ---- lesson completion ---------------------------------------------------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000004','lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000001"}', sha256('op4'), 'mep-canon-1') #>> '{{result,already_completed}}'$$), 'false', 'first completion is recorded');
SELECT is((SELECT last_revision_id::text FROM app.lesson_progress WHERE learner_id = 'a0000000-0000-4000-8000-000000000001'), 'c0000000-0000-4000-8000-000000000001', 'progress points at the completed revision');
SELECT is((SELECT last_change_version::int FROM app.lesson_progress WHERE learner_id = 'a0000000-0000-4000-8000-000000000001'), 3, 'progress records its change version');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000005','lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000002"}', sha256('op5'), 'mep-canon-1') #>> '{{result,already_completed}}'$$), 'true', 'a second completion (other device) merges: already completed');
SELECT is((SELECT last_revision_id::text FROM app.lesson_progress WHERE learner_id = 'a0000000-0000-4000-8000-000000000001'), 'c0000000-0000-4000-8000-000000000001', 'the first completion keeps its revision');
SELECT is((SELECT count(*)::int FROM app.account_change_feed WHERE learner_id = 'a0000000-0000-4000-8000-000000000001'), 3, 'the no-op completion produced no extra change');

-- ---- versions: gap-free per learner, independent across learners ------------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000002', $$SELECT app.sync_apply_operation('55555555-5555-4555-8555-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}', sha256('b1'), 'mep-canon-1') #>> '{{result,change_version}}'$$), '1', 'B starts at version 1 regardless of A');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000002', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000102","response":{"choice_id":"a"}}', sha256('b2'), 'mep-canon-1') ->> 'status'$$), 'accepted', 'B may reuse an op_id that A used: op_ids are per learner');
SELECT is((SELECT array_agg(version::int ORDER BY version) FROM app.account_change_feed WHERE learner_id = 'a0000000-0000-4000-8000-000000000001'), ARRAY[1,2,3], 'A versions are 1,2,3 with no gap');
SELECT is((SELECT array_agg(version::int ORDER BY version) FROM app.account_change_feed WHERE learner_id = 'a0000000-0000-4000-8000-000000000002'), ARRAY[1,2], 'B versions are 1,2 with no gap');
SELECT is((SELECT count(*)::int FROM app.practice_attempts WHERE learner_id = 'a0000000-0000-4000-8000-000000000001'), 2, 'B activity added nothing to A');

-- ---- argument validation ---------------------------------------------------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000009','award_points','{"points":1000}', sha256('x'), 'mep-canon-1') ->> 'status'$$), 'ERROR:22023', 'unsupported kinds are refused');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation('44444444-4444-4444-8444-000000000009','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000101","response":{"choice_id":"b"}}', '\x00', 'mep-canon-1')$$), 'ERROR:22023', 'a digest that is not 32 bytes is refused');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-0000000000ff', $$SELECT app.sync_apply_operation(gen_random_uuid(),'lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000001"}', sha256('x'), 'mep-canon-1')$$), 'ERROR:42501', 'an actor without a learner profile is refused');

SELECT * FROM finish();
ROLLBACK;
