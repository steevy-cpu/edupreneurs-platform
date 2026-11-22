-- Students (and the student API role) can only ever see approved revisions that
-- are in a CURRENT pack of a PUBLISHED course.
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

-- ---- fixtures: revisions in every non-published state -------------------------
INSERT INTO app.lesson_revisions (id, lesson_id, revision, locale, title, blocks, created_by) VALUES
  ('c0000000-0000-4000-8000-000000000011', 'b0000000-0000-4000-8000-000000000005', 2, 'fr', 'DRAFT fr', '[]', 'a0000000-0000-4000-8000-000000000003'),
  ('c0000000-0000-4000-8000-000000000012', 'b0000000-0000-4000-8000-000000000005', 2, 'ht', 'IN REVIEW ht', '[]', 'a0000000-0000-4000-8000-000000000003'),
  ('c0000000-0000-4000-8000-000000000013', 'b0000000-0000-4000-8000-000000000005', 3, 'fr', 'REJECTED fr', '[]', 'a0000000-0000-4000-8000-000000000003'),
  ('c0000000-0000-4000-8000-000000000014', 'b0000000-0000-4000-8000-000000000005', 4, 'fr', 'APPROVED NOT PACKED fr', '[]', 'a0000000-0000-4000-8000-000000000003'),
  ('c0000000-0000-4000-8000-000000000015', 'b0000000-0000-4000-8000-000000000005', 5, 'fr', 'APPROVED IN UNRELEASED PACK fr', '[]', 'a0000000-0000-4000-8000-000000000003');
INSERT INTO app.question_revisions (id, lesson_revision_id, question_key, position, kind, prompt, response_spec, answer_key, explanation)
SELECT ('d0000000-0000-4000-8000-0000000003' || n)::uuid, ('c0000000-0000-4000-8000-0000000000' || n)::uuid, 'q', 1, 'mcq',
       '{"text":"hidden"}', '{"choices":[{"id":"a","text":"1"},{"id":"b","text":"2"}]}', '{"correct_choice_id":"a"}', '{"text":"hidden"}'
FROM unnest(ARRAY['11','12','13','14','15']) AS n;
INSERT INTO app.lesson_revision_sources (lesson_revision_id, source_id)
SELECT ('c0000000-0000-4000-8000-0000000000' || n)::uuid, 'e0000000-0000-4000-8000-000000000001' FROM unnest(ARRAY['13','14','15']) AS n;

UPDATE app.lesson_revisions SET status = 'in_review'
 WHERE id IN ('c0000000-0000-4000-8000-000000000012','c0000000-0000-4000-8000-000000000013',
              'c0000000-0000-4000-8000-000000000014','c0000000-0000-4000-8000-000000000015');
INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES
  ('c0000000-0000-4000-8000-000000000013', 'a0000000-0000-4000-8000-000000000004', 'rejected'),
  ('c0000000-0000-4000-8000-000000000014', 'a0000000-0000-4000-8000-000000000004', 'approved'),
  ('c0000000-0000-4000-8000-000000000015', 'a0000000-0000-4000-8000-000000000004', 'approved');
UPDATE app.lesson_revisions SET status = 'rejected' WHERE id = 'c0000000-0000-4000-8000-000000000013';
UPDATE app.lesson_revisions SET status = 'approved', approved_by = 'a0000000-0000-4000-8000-000000000004', approved_at = now()
 WHERE id IN ('c0000000-0000-4000-8000-000000000014','c0000000-0000-4000-8000-000000000015');
-- revision 15 sits in a pack that is finalized ("ready") but was never released
INSERT INTO app.pack_releases (id, pack_key, revision, locale) VALUES ('f0000000-0000-4000-8000-000000000015', 'math-9af', 2, 'fr');
INSERT INTO app.pack_items (pack_release_id, lesson_revision_id, position) VALUES ('f0000000-0000-4000-8000-000000000015', 'c0000000-0000-4000-8000-000000000015', 1);
UPDATE app.pack_releases SET status = 'ready', manifest_object_key = 'synthetic/x', manifest_sha256 = sha256('x'), compressed_bytes = 1
 WHERE id = 'f0000000-0000-4000-8000-000000000015';

SELECT is((SELECT count(*)::int FROM app.lesson_revisions WHERE lesson_id = 'b0000000-0000-4000-8000-000000000005'), 7, 'fixture: the seed lesson now has 7 revisions in total');

-- ---- what the student API role can see -------------------------------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT string_agg(id::text, ',' ORDER BY id) FROM app.lesson_revisions WHERE lesson_id = 'b0000000-0000-4000-8000-000000000005'$$),
    'c0000000-0000-4000-8000-000000000001,c0000000-0000-4000-8000-000000000002', 'only the two published revisions of the lesson are visible');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', 'SELECT count(*) FROM app.lesson_revisions WHERE status <> $$approved$$'), '0', 'no draft / in_review / rejected revision is visible');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT count(*) FROM app.lesson_revisions WHERE id = 'c0000000-0000-4000-8000-000000000011'$$), '0', 'draft is invisible by id');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT count(*) FROM app.lesson_revisions WHERE id = 'c0000000-0000-4000-8000-000000000013'$$), '0', 'rejected revision is invisible by id');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT count(*) FROM app.lesson_revisions WHERE id = 'c0000000-0000-4000-8000-000000000014'$$), '0', 'approved but unpublished revision is invisible');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT count(*) FROM app.lesson_revisions WHERE id = 'c0000000-0000-4000-8000-000000000015'$$), '0', 'approved revision in an unreleased pack is invisible');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT count(*) FROM app.question_revisions q JOIN app.lesson_revisions r ON r.id = q.lesson_revision_id WHERE r.lesson_id = 'b0000000-0000-4000-8000-000000000005'$$), '10', 'only the 10 published questions of the lesson are visible');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT count(*) FROM app.question_revisions WHERE id::text LIKE 'd0000000-0000-4000-8000-0000000003%'$$), '0', 'questions of unpublished revisions are invisible (no leak through the join)');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT count(*) FROM app.pack_releases WHERE pack_key = 'math-9af'$$), '2', 'only the two current releases of the pack are visible');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT count(*) FROM app.pack_items i JOIN app.pack_releases r ON r.id = i.pack_release_id WHERE r.pack_key = 'math-9af'$$), '2', 'only items of current releases are visible');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM app.lesson_revisions WHERE status <> $$approved$$'), '0', 'no actor: still no drafts');

-- ---- unpublished content cannot be used through sync either ---------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation(gen_random_uuid(),'practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000311","response":{"choice_id":"a"}}', sha256('d1'), 'mep-canon-1') #>> '{result,code}'$$),
    'content_not_available', 'answering a DRAFT question is rejected');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation(gen_random_uuid(),'practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000314","response":{"choice_id":"a"}}', sha256('d2'), 'mep-canon-1') #>> '{result,code}'$$),
    'content_not_available', 'answering an approved-but-unpublished question is rejected');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation(gen_random_uuid(),'lesson_completed','{"lesson_revision_id":"c0000000-0000-4000-8000-000000000015"}', sha256('d3'), 'mep-canon-1') #>> '{result,code}'$$),
    'content_not_available', 'completing a revision from an unreleased pack is rejected');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT app.sync_apply_operation(gen_random_uuid(),'practice_answer','{"question_revision_id":"99999999-9999-4999-8999-999999999999","response":{"choice_id":"a"}}', sha256('d4'), 'mep-canon-1') #>> '{result,code}'$$),
    'content_not_available', 'an unknown question gets the SAME answer as a draft (no probing)');
SELECT is((SELECT count(*)::int FROM app.practice_attempts), 0, 'none of the rejected operations created an attempt');
SELECT is((SELECT count(*)::int FROM app.account_change_feed), 0, 'none of the rejected operations created a change');

-- ---- moving the pointer / archiving hides content --------------------------------
DELETE FROM app.pack_current WHERE pack_key = 'math-9af' AND locale = 'fr';
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT string_agg(id::text, ',') FROM app.lesson_revisions WHERE lesson_id = 'b0000000-0000-4000-8000-000000000005'$$), 'c0000000-0000-4000-8000-000000000002',
    'a revision whose pack is no longer current disappears; the other locale stays');
UPDATE app.lessons SET is_active = false WHERE id = 'b0000000-0000-4000-8000-000000000005';
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT count(*) FROM app.lesson_revisions WHERE lesson_id = 'b0000000-0000-4000-8000-000000000005'$$), '0', 'deactivating the lesson hides its revisions');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', $$SELECT count(*) FROM app.question_revisions WHERE id::text LIKE 'd0000000-0000-4000-8000-0000000002%'$$), '0', '... and their questions');
UPDATE app.lessons SET is_active = true WHERE id = 'b0000000-0000-4000-8000-000000000005';
UPDATE app.courses SET visibility = 'archived';
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', 'SELECT (SELECT count(*) FROM app.courses) + (SELECT count(*) FROM app.units) + (SELECT count(*) FROM app.lessons) + (SELECT count(*) FROM app.lesson_revisions) + (SELECT count(*) FROM app.question_revisions)'),
    '0', 'archiving the course hides the course, its units, lessons, revisions and questions');

SELECT * FROM finish();
ROLLBACK;
