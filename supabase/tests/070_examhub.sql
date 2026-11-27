-- ExamHub-01: keys never reach the API role, attempts are private, scoring and the
-- time limit are decided by the database. Synthetic fixtures only; rolled back.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
-- Run one statement AS THE STUDENT API ROLE with the given actor. Returns the first
-- column of the first row as text, or 'ERROR:<sqlstate>'.
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

-- ---- fixtures --------------------------------------------------------------------
-- student A …0001, student B …0002, editor …0003, reviewer …0004 (seed accounts)
INSERT INTO app.content_sources (id, source_title, rights_status) VALUES
  ('e1000000-0000-4000-8000-000000000001', 'Synthetic exam source (cleared)', 'cleared'),
  ('e1000000-0000-4000-8000-000000000002', 'Synthetic exam source (unverified)', 'unverified');

INSERT INTO app.exams (id, slug, grade_id, subject_id, exam_type, session_year, duration_minutes, titles,
                       status, source_id, created_by)
SELECT x.id, x.slug, (SELECT id FROM app.grades ORDER BY sort_order LIMIT 1),
       (SELECT id FROM app.subjects ORDER BY slug LIMIT 1), 'practice', 2026, 30,
       '{"fr":"Examen synthétique","ht":"Egzamen sentetik"}', 'draft', x.source, 'a0000000-0000-4000-8000-000000000003'
FROM (VALUES
  ('f1000000-0000-4000-8000-000000000001'::uuid, 'synthetic-exam-published', 'e1000000-0000-4000-8000-000000000001'::uuid),
  ('f1000000-0000-4000-8000-000000000002'::uuid, 'synthetic-exam-draft', 'e1000000-0000-4000-8000-000000000001'::uuid),
  ('f1000000-0000-4000-8000-000000000003'::uuid, 'synthetic-exam-unverified', 'e1000000-0000-4000-8000-000000000002'::uuid),
  ('f1000000-0000-4000-8000-000000000004'::uuid, 'synthetic-exam-bad-key', 'e1000000-0000-4000-8000-000000000001'::uuid),
  ('f1000000-0000-4000-8000-000000000005'::uuid, 'synthetic-exam-empty', 'e1000000-0000-4000-8000-000000000001'::uuid)
) AS x(id, slug, source);

INSERT INTO app.exam_questions (id, exam_id, locale, position, kind, points, prompt, response_spec, answer_key, explanation) VALUES
  ('f2000000-0000-4000-8000-000000000001', 'f1000000-0000-4000-8000-000000000001', 'fr', 1, 'mcq', 1,
   '{"text":"2 + 2 = ?"}', '{"choices":[{"id":"a","text":"3"},{"id":"b","text":"4"}]}', '{"correct_choice_id":"b"}', '{"text":"SECRET-EXPLANATION-1"}'),
  ('f2000000-0000-4000-8000-000000000002', 'f1000000-0000-4000-8000-000000000001', 'fr', 2, 'mcq', 2,
   '{"text":"3 × 3 = ?"}', '{"choices":[{"id":"a","text":"9"},{"id":"b","text":"6"}]}', '{"correct_choice_id":"a"}', '{"text":"SECRET-EXPLANATION-2"}'),
  ('f2000000-0000-4000-8000-000000000003', 'f1000000-0000-4000-8000-000000000001', 'fr', 3, 'open', 0,
   '{"text":"Explique."}', '{"max_chars":4000}', '{"model_answer":"SECRET-MODEL-ANSWER"}', '{"text":"SECRET-EXPLANATION-3"}'),
  ('f2000000-0000-4000-8000-000000000011', 'f1000000-0000-4000-8000-000000000001', 'ht', 1, 'mcq', 1,
   '{"text":"2 + 2 = ?"}', '{"choices":[{"id":"a","text":"3"},{"id":"b","text":"4"}]}', '{"correct_choice_id":"b"}', '{"text":"SEKRE"}'),
  ('f2000000-0000-4000-8000-000000000021', 'f1000000-0000-4000-8000-000000000002', 'fr', 1, 'mcq', 1,
   '{"text":"draft"}', '{"choices":[{"id":"a","text":"1"},{"id":"b","text":"2"}]}', '{"correct_choice_id":"a"}', '{"text":"draft"}'),
  ('f2000000-0000-4000-8000-000000000031', 'f1000000-0000-4000-8000-000000000003', 'fr', 1, 'mcq', 1,
   '{"text":"x"}', '{"choices":[{"id":"a","text":"1"},{"id":"b","text":"2"}]}', '{"correct_choice_id":"a"}', '{"text":"x"}'),
  ('f2000000-0000-4000-8000-000000000041', 'f1000000-0000-4000-8000-000000000004', 'fr', 1, 'mcq', 1,
   '{"text":"x"}', '{"choices":[{"id":"a","text":"1"},{"id":"b","text":"2"}]}', '{"correct_choice_id":"z"}', '{"text":"x"}');

-- ---- publication guards -------------------------------------------------------------
SELECT throws_ok($$UPDATE app.exams SET status = 'published' WHERE id = 'f1000000-0000-4000-8000-000000000001'$$,
    '23514', NULL, 'an exam cannot be published without an approver');
SELECT throws_ok($$UPDATE app.exams SET status = 'published', approved_by = created_by WHERE id = 'f1000000-0000-4000-8000-000000000001'$$,
    '23514', NULL, 'nobody approves their own exam');
SELECT throws_ok($$UPDATE app.exams SET status = 'published', approved_by = 'a0000000-0000-4000-8000-000000000004' WHERE id = 'f1000000-0000-4000-8000-000000000003'$$,
    '23514', NULL, 'an exam whose source rights are not cleared cannot be published');
SELECT throws_ok($$UPDATE app.exams SET status = 'published', approved_by = 'a0000000-0000-4000-8000-000000000004' WHERE id = 'f1000000-0000-4000-8000-000000000004'$$,
    '23514', NULL, 'a multiple-choice key must name one of the choices');
SELECT throws_ok($$UPDATE app.exams SET status = 'published', approved_by = 'a0000000-0000-4000-8000-000000000004' WHERE id = 'f1000000-0000-4000-8000-000000000005'$$,
    '23514', NULL, 'an exam without questions cannot be published');
SELECT lives_ok($$UPDATE app.exams SET status = 'published', approved_by = 'a0000000-0000-4000-8000-000000000004' WHERE id = 'f1000000-0000-4000-8000-000000000001'$$,
    'a reviewed exam with cleared rights and valid keys can be published');
SELECT throws_ok($$UPDATE app.exam_questions SET answer_key = '{"correct_choice_id":"a"}' WHERE id = 'f2000000-0000-4000-8000-000000000001'$$,
    '23514', NULL, 'questions of a published exam are immutable');
SELECT throws_ok($$DELETE FROM app.exam_questions WHERE id = 'f2000000-0000-4000-8000-000000000002'$$,
    '23514', NULL, 'questions of a published exam cannot be deleted');

-- ---- what the API role can and cannot read ------------------------------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', 'SELECT count(*) FROM app.exams'), '1',
    'only the published exam is visible (drafts are hidden)');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', 'SELECT count(*) FROM app.exam_questions'), '4',
    'only questions of the published exam are visible');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', 'SELECT answer_key FROM app.exam_questions LIMIT 1'), 'ERROR:42501',
    'the API role cannot select answer_key');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', 'SELECT explanation FROM app.exam_questions LIMIT 1'), 'ERROR:42501',
    'the API role cannot select explanation');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', 'SELECT * FROM app.exam_questions LIMIT 1'), 'ERROR:42501',
    'SELECT * on questions is refused (it would include the key)');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001',
    $$INSERT INTO app.exam_attempts (learner_id, exam_id, locale, mode) VALUES ('a0000000-0000-4000-8000-000000000001','f1000000-0000-4000-8000-000000000001','fr','practice') RETURNING id$$),
    'ERROR:42501', 'a learner cannot insert an attempt directly');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.exam_close_attempt(gen_random_uuid(), 'finished')$$), 'ERROR:42501',
    'the internal scoring function is not callable by the API role');

-- ---- starting ------------------------------------------------------------------------
SELECT is(pg_temp.as_api(NULL, $$SELECT app.exam_start_attempt('f1000000-0000-4000-8000-000000000001','fr','practice') ->> 'status'$$),
    'unauthenticated', 'no actor, no attempt');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.exam_start_attempt('f1000000-0000-4000-8000-000000000002','fr','practice') ->> 'status'$$),
    'exam_not_found', 'a draft exam cannot be started');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.exam_start_attempt('f1000000-0000-4000-8000-000000000001','fr','graded') ->> 'status'$$),
    'invalid_request', 'unknown mode is refused');

-- practice attempt for student A
CREATE TEMP TABLE t_ids (name text PRIMARY KEY, id uuid);
GRANT SELECT ON t_ids TO edu_api;
INSERT INTO t_ids SELECT 'practice', (pg_temp.as_api('a0000000-0000-4000-8000-000000000001',
    $$SELECT app.exam_start_attempt('f1000000-0000-4000-8000-000000000001','fr','practice') ->> 'attempt_id'$$))::uuid;
SELECT isnt((SELECT id FROM t_ids WHERE name = 'practice'), NULL, 'a practice attempt is created');
SELECT is((SELECT expires_at FROM app.exam_attempts WHERE id = (SELECT id FROM t_ids WHERE name = 'practice')), NULL,
    'a practice attempt has no deadline');

-- ---- answering (practice) ---------------------------------------------------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000001', '{"choice_id":"zz"}') ->> 'status'$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    'invalid_response', 'a choice that is not offered is refused');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000001', '{"choice_id":5}') ->> 'status'$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    'invalid_response', 'a non-string choice is refused');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000011', '{"choice_id":"b"}') ->> 'status'$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    'question_not_found', 'a question of another language is not part of this attempt');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000002', format(
    $$SELECT app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000001', '{"choice_id":"b"}') ->> 'status'$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    'attempt_not_found', 'another learner cannot answer in this attempt');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000001', '{"choice_id":"b"}') ->> 'is_correct'$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    'true', 'the server marks the correct choice as correct');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000001', '{"choice_id":"a"}') ->> 'status'$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    'already_answered', 'in practice the first answer stands once feedback was given');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT (app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000002', '{"choice_id":"b"}') -> 'explanation' ->> 'text')$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    'SECRET-EXPLANATION-2', 'practice feedback carries the explanation after the answer');
SELECT is((SELECT is_correct FROM app.exam_answers WHERE question_id = 'f2000000-0000-4000-8000-000000000002'), false,
    'a wrong choice is recorded as wrong');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000003', '{"text":"ma réponse"}') ->> 'status'$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    'recorded', 'an open answer is stored');
SELECT is((SELECT is_correct FROM app.exam_answers WHERE question_id = 'f2000000-0000-4000-8000-000000000003'), NULL,
    'an open answer is never auto-scored');

-- ---- finishing and history -----------------------------------------------------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000002', format(
    $$SELECT app.exam_finish_attempt(%L) ->> 'status'$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    'attempt_not_found', 'another learner cannot finish this attempt');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT app.exam_finish_attempt(%L) ->> 'status'$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    'closed', 'the owner finishes the attempt');
SELECT results_eq($$SELECT status, score_points, max_points FROM app.exam_attempts WHERE id = (SELECT id FROM t_ids WHERE name = 'practice')$$,
    $$VALUES ('finished'::text, 1, 3)$$, 'score is computed by the server: 1 of 3 points');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT app.exam_finish_attempt(%L) ->> 'status'$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    'closed', 'finishing twice is harmless');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000001', '{"choice_id":"b"}') ->> 'status'$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    'attempt_closed', 'a finished attempt accepts no answer');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', 'SELECT count(*) FROM app.exam_attempts'), '1',
    'the owner sees the attempt in their history');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000002', 'SELECT count(*) FROM app.exam_attempts'), '0',
    'another learner sees no attempt');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000002', 'SELECT count(*) FROM app.exam_answers'), '0',
    'another learner sees no answer');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000002', format(
    $$SELECT app.exam_attempt_review(%L)::text$$, (SELECT id FROM t_ids WHERE name = 'practice'))), NULL,
    'another learner gets no review');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT count(*) FROM jsonb_array_elements(app.exam_attempt_review(%L)) i WHERE i ->> 'answer_key' IS NOT NULL$$, (SELECT id FROM t_ids WHERE name = 'practice'))),
    '3', 'after finishing, the review reveals every key');

-- ---- timed attempts: the server clock decides -------------------------------------------------
INSERT INTO t_ids SELECT 'timed', (pg_temp.as_api('a0000000-0000-4000-8000-000000000001',
    $$SELECT app.exam_start_attempt('f1000000-0000-4000-8000-000000000001','fr','timed') ->> 'attempt_id'$$))::uuid;
SELECT is((SELECT expires_at - started_at FROM app.exam_attempts WHERE id = (SELECT id FROM t_ids WHERE name = 'timed')),
    interval '30 minutes', 'the deadline is start + the exam duration');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001',
    $$SELECT app.exam_start_attempt('f1000000-0000-4000-8000-000000000001','fr','timed') ->> 'status'$$),
    'resumed', 'starting again resumes the open timed attempt');
SELECT is((SELECT count(*)::int FROM app.exam_attempts WHERE mode = 'timed'), 1, 'there is still one timed attempt');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT (app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000001', '{"choice_id":"a"}') ? 'answer_key')::text$$, (SELECT id FROM t_ids WHERE name = 'timed'))),
    'false', 'a timed answer reveals no key');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT (app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000001', '{"choice_id":"b"}') ? 'is_correct')::text$$, (SELECT id FROM t_ids WHERE name = 'timed'))),
    'false', 'a timed answer can be changed and reveals no verdict');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT count(*) FROM jsonb_array_elements(app.exam_attempt_review(%L)) i
      WHERE i ->> 'answer_key' IS NOT NULL OR i ->> 'explanation' IS NOT NULL OR (i ->> 'revealed')::boolean
         OR i ->> 'is_correct' IS NOT NULL OR (i ->> 'points_awarded')::int <> 0$$, (SELECT id FROM t_ids WHERE name = 'timed'))),
    '0', 'while a timed attempt is open, its review reveals no key, explanation, verdict or points');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000002', '{"choice_id":"a"}') ->> 'status'$$, (SELECT id FROM t_ids WHERE name = 'timed'))),
    'recorded', 'a second timed answer is recorded');

-- Move the clock: the attempt started 40 minutes ago; question 1 was answered in time, question 2 too late.
UPDATE app.exam_attempts SET started_at = now() - interval '40 minutes', expires_at = now() - interval '10 minutes'
    WHERE id = (SELECT id FROM t_ids WHERE name = 'timed');
UPDATE app.exam_answers SET answered_at = now() - interval '20 minutes'
    WHERE attempt_id = (SELECT id FROM t_ids WHERE name = 'timed') AND question_id = 'f2000000-0000-4000-8000-000000000001';
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', format(
    $$SELECT app.exam_submit_answer(%L, 'f2000000-0000-4000-8000-000000000003', '{"text":"trop tard"}') ->> 'status'$$, (SELECT id FROM t_ids WHERE name = 'timed'))),
    'attempt_expired', 'an answer after the deadline is refused');
SELECT results_eq($$SELECT status, score_points, max_points, finished_at = expires_at FROM app.exam_attempts WHERE id = (SELECT id FROM t_ids WHERE name = 'timed')$$,
    $$VALUES ('expired'::text, 1, 3, true)$$, 'the expired attempt is scored from answers recorded before the deadline only');
SELECT is((SELECT count(*)::int FROM app.exam_answers WHERE attempt_id = (SELECT id FROM t_ids WHERE name = 'timed')), 2,
    'the late answer was not stored');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001',
    $$SELECT app.exam_start_attempt('f1000000-0000-4000-8000-000000000001','fr','timed') ->> 'status'$$),
    'started', 'after expiry a new timed attempt can be started');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001',
    $$SELECT app.exam_start_attempt('f1000000-0000-4000-8000-000000000001','ht','practice') ->> 'status'$$),
    'started', 'the Creole version of the exam can be started');

SELECT * FROM finish();
ROLLBACK;
