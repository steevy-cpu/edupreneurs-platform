-- Word of the Day: the editorial workflow (draft -> review by a different person
-- -> approved), the rights gate, immutability, the audio size cap, the staff
-- role seam and the audit trail. Runs as the migration owner on purpose: the
-- trigger rules must hold even for privileged writers.
BEGIN;
SELECT * FROM no_plan();

-- Exact counts need an empty schema. Inside the test transaction; rolled back.
TRUNCATE vocab.daily_assignments, vocab.audio_assets, vocab.reviews, vocab.word_revisions, vocab.words, vocab.sources;

-- Seed staff: editor ...03 (role editor), reviewer ...04 (role reviewer).
-- Extra synthetic staff for this file:
INSERT INTO auth.users (instance_id, id, aud, role, email)
SELECT '00000000-0000-0000-0000-000000000000', id, 'authenticated', 'authenticated', email FROM (VALUES
  ('a0000000-0000-4000-8000-000000000021'::uuid, 'vocab.publisher@edupreneur.test'),
  ('a0000000-0000-4000-8000-000000000022'::uuid, 'vocab.editor2@edupreneur.test'),
  ('a0000000-0000-4000-8000-000000000023'::uuid, 'vocab.inactive.reviewer@edupreneur.test'),
  ('a0000000-0000-4000-8000-000000000024'::uuid, 'vocab.no.role@edupreneur.test'),
  ('a0000000-0000-4000-8000-000000000025'::uuid, 'vocab.editor.and.reviewer@edupreneur.test'),
  ('a0000000-0000-4000-8000-000000000026'::uuid, 'vocab.admin@edupreneur.test')) AS u(id, email);
INSERT INTO app.staff_roles (user_id, role, is_active) VALUES
  ('a0000000-0000-4000-8000-000000000021', 'publisher', true),
  ('a0000000-0000-4000-8000-000000000022', 'editor', true),
  ('a0000000-0000-4000-8000-000000000023', 'reviewer', false),
  ('a0000000-0000-4000-8000-000000000023', 'editor', false),
  ('a0000000-0000-4000-8000-000000000025', 'editor', true),
  ('a0000000-0000-4000-8000-000000000025', 'reviewer', true),
  ('a0000000-0000-4000-8000-000000000026', 'admin', true);

CREATE TEMP TABLE ids (k text PRIMARY KEY, v uuid NOT NULL);
CREATE FUNCTION pg_temp.id(p_k text) RETURNS uuid LANGUAGE sql AS $fn$ SELECT v FROM ids WHERE k = p_k $fn$;

-- ================================ sources ================================
SELECT throws_ok($$INSERT INTO vocab.sources (source_title, licence, rights_status, created_by) VALUES ('x', 'synthetic', 'cleared', 'a0000000-0000-4000-8000-000000000003')$$,
    'P0001', 'Sources must be created with unverified rights', 'a source cannot be inserted already cleared');

SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000004';
SELECT throws_ok($$SELECT vocab.register_source('Synthetic test source', NULL, 'synthetic-test-only')$$,
    '42501', 'Staff role required', 'a reviewer cannot register a source');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000003';
INSERT INTO ids SELECT 'src_ok', vocab.register_source('Synthetic test source (text)', NULL, 'synthetic-test-only');
INSERT INTO ids SELECT 'src_unverified', vocab.register_source('Synthetic test source (unverified)', NULL, 'synthetic-test-only');
INSERT INTO ids SELECT 'src_audio', vocab.register_source('Synthetic test source (recording)', NULL, 'synthetic-test-only');
SELECT throws_ok($$SELECT vocab.set_source_rights(pg_temp.id('src_ok'), 'cleared')$$,
    '42501', 'Staff role required', 'an editor cannot decide rights');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000021';
SELECT lives_ok($$SELECT vocab.set_source_rights(pg_temp.id('src_ok'), 'cleared', 'synthetic decision')$$, 'a publisher clears rights');
SELECT lives_ok($$SELECT vocab.set_source_rights(pg_temp.id('src_audio'), 'cleared')$$, 'a publisher clears the recording rights');
SELECT throws_ok($$SELECT vocab.set_source_rights(gen_random_uuid(), 'cleared')$$, 'P0002', 'Source not found', 'unknown source');
SELECT throws_ok($$SELECT vocab.set_source_rights(pg_temp.id('src_ok'), 'public-domain-ish')$$, '23514', NULL, 'rights status is a closed list');
SELECT is((SELECT rights_decided_by FROM vocab.sources WHERE id = pg_temp.id('src_ok')), 'a0000000-0000-4000-8000-000000000021'::uuid,
    'the rights decision records who decided');
UPDATE vocab.sources SET rights_decided_at = '1999-01-01', rights_decided_by = 'a0000000-0000-4000-8000-000000000001' WHERE id = pg_temp.id('src_ok');
SELECT ok((SELECT rights_decided_at > now() - interval '1 minute' AND rights_decided_by = 'a0000000-0000-4000-8000-000000000021'
           FROM vocab.sources WHERE id = pg_temp.id('src_ok')),
    'a caller cannot rewrite who/when of a rights decision');

-- ============================ who may write words ============================
SET LOCAL edu.actor_id = '';
SELECT throws_ok($$SELECT vocab.create_word('no-actor')$$, '42501', 'Staff role required', 'no actor: refused');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000001';
SELECT throws_ok($$SELECT vocab.create_word('learner-word')$$, '42501', 'Staff role required', 'a learner cannot create a word');
SELECT throws_ok($$SELECT * FROM vocab.review_queue()$$, '42501', 'Staff role required', 'a learner cannot read the review queue');
SELECT throws_ok($$SELECT * FROM vocab.calendar(current_date, 7)$$, '42501', 'Staff role required', 'a learner cannot read the calendar');
SELECT throws_ok($$SELECT vocab.retire_word(gen_random_uuid())$$, '42501', 'Staff role required', 'a learner cannot retire a word');
SELECT throws_ok($$SELECT * FROM vocab.staff_ensure_assignments(current_date, 7)$$, '42501', 'Staff role required', 'a learner cannot run the fill');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000004';
SELECT throws_ok($$SELECT vocab.create_word('reviewer-word')$$, '42501', 'Staff role required', 'a reviewer cannot create a word');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000023';
SELECT throws_ok($$SELECT vocab.create_word('inactive-word')$$, '42501', 'Staff role required', 'an INACTIVE editor role does not count');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000024';
SELECT throws_ok($$SELECT vocab.create_word('norole-word')$$, '42501', 'Staff role required', 'a signed-in account without a role is refused');

SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000003';
INSERT INTO ids SELECT 'w1', vocab.create_word('test-word-one');
SELECT throws_ok($$SELECT vocab.create_word('test-word-one')$$, '23505', NULL, 'slugs are unique');
SELECT throws_ok($$SELECT vocab.create_word('Bad Slug')$$, '23514', NULL, 'slugs are validated');
SELECT throws_ok($$SELECT vocab.create_draft(gen_random_uuid(), 'fr', 't', NULL, 'noun', 'd', 'e', NULL, pg_temp.id('src_ok'))$$,
    'P0002', 'Word not found', 'a draft needs an existing word');
SELECT throws_ok($$SELECT vocab.create_draft(pg_temp.id('w1'), 'fr', 't', NULL, 'noun', 'd', 'e', NULL, gen_random_uuid())$$,
    'P0002', 'Source not found', 'a draft needs an existing source record');

-- ============================ direct-insert guards ============================
SELECT throws_ok($$INSERT INTO vocab.word_revisions (word_id, locale, revision, term, part_of_speech, definition, example, source_id, created_by, status, approved_by, approved_at)
    VALUES (pg_temp.id('w1'), 'fr', 90, 't', 'noun', 'd', 'e', pg_temp.id('src_ok'), 'a0000000-0000-4000-8000-000000000003', 'approved', 'a0000000-0000-4000-8000-000000000004', now())$$,
    'P0001', 'Word revisions must be created as unapproved drafts', 'a revision cannot be inserted already approved');
SELECT throws_ok($$INSERT INTO vocab.word_revisions (word_id, locale, revision, term, part_of_speech, definition, example, source_id, created_by, status)
    VALUES (pg_temp.id('w1'), 'fr', 90, 't', 'noun', 'd', 'e', pg_temp.id('src_ok'), 'a0000000-0000-4000-8000-000000000003', 'in_review')$$,
    'P0001', 'Word revisions must be created as unapproved drafts', 'a revision cannot be inserted in_review');
SELECT throws_ok($$INSERT INTO vocab.word_revisions (word_id, locale, revision, term, part_of_speech, definition, example, source_id)
    VALUES (pg_temp.id('w1'), 'fr', 90, 't', 'noun', 'd', 'e', pg_temp.id('src_ok'))$$,
    '23502', NULL, 'a revision needs an author');
SELECT throws_ok($$INSERT INTO vocab.word_revisions (word_id, locale, revision, term, part_of_speech, definition, example, created_by)
    VALUES (pg_temp.id('w1'), 'fr', 90, 't', 'noun', 'd', 'e', 'a0000000-0000-4000-8000-000000000003')$$,
    '23502', NULL, 'a revision needs a source/licence record');

-- ============================ bounded content ============================
SELECT throws_ok($$SELECT vocab.create_draft(pg_temp.id('w1'), 'fr', repeat('a', 61), NULL, 'noun', 'd', 'e', NULL, pg_temp.id('src_ok'))$$, '23514', NULL, 'term longer than 60 characters is refused');
SELECT throws_ok($$SELECT vocab.create_draft(pg_temp.id('w1'), 'fr', ' padded ', NULL, 'noun', 'd', 'e', NULL, pg_temp.id('src_ok'))$$, '23514', NULL, 'term with surrounding spaces is refused');
SELECT throws_ok($$SELECT vocab.create_draft(pg_temp.id('w1'), 'fr', 't', repeat('a', 81), 'noun', 'd', 'e', NULL, pg_temp.id('src_ok'))$$, '23514', NULL, 'pronunciation longer than 80 characters is refused');
SELECT throws_ok($$SELECT vocab.create_draft(pg_temp.id('w1'), 'fr', 't', NULL, 'noun', repeat('a', 301), 'e', NULL, pg_temp.id('src_ok'))$$, '23514', NULL, 'definition longer than 300 characters is refused');
SELECT throws_ok($$SELECT vocab.create_draft(pg_temp.id('w1'), 'fr', 't', NULL, 'noun', 'd', repeat('a', 241), NULL, pg_temp.id('src_ok'))$$, '23514', NULL, 'example longer than 240 characters is refused');
SELECT throws_ok($$SELECT vocab.create_draft(pg_temp.id('w1'), 'fr', 't', NULL, 'noun', 'd', 'e', repeat('a', 81), pg_temp.id('src_ok'))$$, '23514', NULL, 'gloss longer than 80 characters is refused');
SELECT throws_ok($$SELECT vocab.create_draft(pg_temp.id('w1'), 'fr', 't', NULL, 'noun', '', 'e', NULL, pg_temp.id('src_ok'))$$, '23514', NULL, 'an empty definition is refused');
SELECT throws_ok($$SELECT vocab.create_draft(pg_temp.id('w1'), 'fr', 't', NULL, 'noun', E'line one\nline two', 'e', NULL, pg_temp.id('src_ok'))$$, '23514', NULL, 'control characters (a line break) are refused');
SELECT throws_ok($$SELECT vocab.create_draft(pg_temp.id('w1'), 'fr', 't', NULL, 'gerund', 'd', 'e', NULL, pg_temp.id('src_ok'))$$, '23514', NULL, 'part of speech is a closed list');
SELECT throws_ok($$SELECT vocab.create_draft(pg_temp.id('w1'), 'en', 't', NULL, 'noun', 'd', 'e', NULL, pg_temp.id('src_ok'))$$, '23514', NULL, 'only fr and ht exist');
-- Each field is within its own character limit, but together they exceed the byte budget.
SELECT throws_ok($$SELECT vocab.create_draft(pg_temp.id('w1'), 'fr', 't', NULL, 'noun', repeat('é', 300), repeat('é', 240), NULL, pg_temp.id('src_ok'))$$,
    '23514', NULL, 'the whole word payload has a hard byte budget (accented text counts double)');
SELECT is((SELECT count(*)::int FROM vocab.word_revisions), 0, 'no refused draft left a row behind');

-- ============================ draft, edit, submit ============================
INSERT INTO ids SELECT 'r1', vocab.create_draft(pg_temp.id('w1'), 'fr', 'mot-test', 'mo-tèst', 'noun', 'Définition synthétique de test.', 'Exemple synthétique de test.', 'mo tès', pg_temp.id('src_ok'));
INSERT INTO ids SELECT 'r2', vocab.create_draft(pg_temp.id('w1'), 'fr', 'mot-test-deux', NULL, 'noun', 'Deuxième brouillon.', 'Exemple.', NULL, pg_temp.id('src_unverified'));
INSERT INTO ids SELECT 'r_ht', vocab.create_draft(pg_temp.id('w1'), 'ht', 'mo-tès', NULL, 'noun', 'Definisyon sentetik pou tès.', 'Egzanp sentetik.', 'mot-test', pg_temp.id('src_ok'));
SELECT is((SELECT array_agg(locale || revision ORDER BY locale, revision) FROM vocab.word_revisions), ARRAY['fr1','fr2','ht1'],
    'revision numbers count up per word and locale');
SELECT is((SELECT status || '/' || created_by FROM vocab.word_revisions WHERE id = pg_temp.id('r1')), 'draft/a0000000-0000-4000-8000-000000000003',
    'a new revision is a draft authored by the actor');

SELECT lives_ok($$SELECT vocab.update_draft(pg_temp.id('r1'), 'mot-test', 'mo-tèst', 'noun', 'Définition synthétique corrigée.', 'Exemple synthétique de test.', 'mo tès', pg_temp.id('src_ok'))$$,
    'the author edits the draft');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000022';
SELECT throws_ok($$SELECT vocab.update_draft(pg_temp.id('r1'), 'pris', NULL, 'noun', 'd', 'e', NULL, pg_temp.id('src_ok'))$$,
    '42501', 'Only the author can change this draft', 'another editor cannot rewrite the draft');
SELECT throws_ok($$SELECT vocab.submit_revision(pg_temp.id('r1'))$$,
    '42501', 'Only the author can change this draft', 'another editor cannot submit it');
SELECT throws_ok($$SELECT vocab.set_audio(pg_temp.id('r1'), 'vocab/test/x.m4a', 1000, sha256('x'), 'audio/mp4', 900, pg_temp.id('src_audio'))$$,
    '42501', 'Only the author can change this draft', 'another editor cannot attach a recording');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000003';
SELECT throws_ok($$UPDATE vocab.word_revisions SET created_by = 'a0000000-0000-4000-8000-000000000022' WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Word revision identity and authorship cannot be changed', 'authorship cannot be reassigned to dodge the independence rule');
SELECT throws_ok($$UPDATE vocab.word_revisions SET status = 'in_review', term = 'glisse' WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Submit a draft without changing it in the same step', 'content cannot change in the submitting step');
SELECT throws_ok($$UPDATE vocab.word_revisions SET status = 'rejected' WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Invalid word revision transition', 'draft -> rejected is not a transition');

-- ============================ audio metadata and its cap ============================
SELECT throws_ok($$SELECT vocab.set_audio(pg_temp.id('r1'), 'vocab/test/big.m4a', 102401, sha256('x'), 'audio/mp4', 900, pg_temp.id('src_audio'))$$, '23514', NULL, 'AUDIO SIZE CAP: 102 401 bytes is refused');
SELECT throws_ok($$SELECT vocab.set_audio(pg_temp.id('r1'), 'vocab/test/huge.m4a', 5000000, sha256('x'), 'audio/mp4', 900, pg_temp.id('src_audio'))$$, '23514', NULL, 'AUDIO SIZE CAP: 5 MB is refused');
SELECT throws_ok($$SELECT vocab.set_audio(pg_temp.id('r1'), 'vocab/test/empty.m4a', 0, sha256('x'), 'audio/mp4', 900, pg_temp.id('src_audio'))$$, '23514', NULL, 'an empty recording is refused');
SELECT throws_ok($$SELECT vocab.set_audio(pg_temp.id('r1'), 'vocab/test/x.wav', 1000, sha256('x'), 'audio/wav', 900, pg_temp.id('src_audio'))$$, '23514', NULL, 'only compact speech formats are accepted');
SELECT throws_ok($$SELECT vocab.set_audio(pg_temp.id('r1'), 'vocab/test/x.m4a', 1000, '\x00'::bytea, 'audio/mp4', 900, pg_temp.id('src_audio'))$$, '23514', NULL, 'the checksum must be a SHA-256');
SELECT throws_ok($$SELECT vocab.set_audio(pg_temp.id('r1'), 'vocab/test/x.m4a', 1000, sha256('x'), 'audio/mp4', 15001, pg_temp.id('src_audio'))$$, '23514', NULL, 'a recording longer than 15 s is refused');
SELECT throws_ok($$SELECT vocab.set_audio(pg_temp.id('r1'), '../etc/passwd', 1000, sha256('x'), 'audio/mp4', 900, pg_temp.id('src_audio'))$$, '23514', NULL, 'object keys are validated');
SELECT throws_ok($$SELECT vocab.set_audio(pg_temp.id('r1'), 'vocab/test/x.m4a', 1000, sha256('x'), 'audio/mp4', 900, NULL)$$, 'P0002', 'Source not found', 'a recording needs a rights record');
SELECT lives_ok($$SELECT vocab.set_audio(pg_temp.id('r1'), 'vocab/test/first.m4a', 102400, sha256('x'), 'audio/mp4', 900, pg_temp.id('src_unverified'))$$, 'exactly 102 400 bytes is accepted');
SELECT lives_ok($$SELECT vocab.set_audio(pg_temp.id('r1'), 'vocab/test/second.m4a', 2000, sha256('y'), 'audio/mp4', 800, pg_temp.id('src_unverified'))$$, 'the recording metadata can be replaced while drafting');
SELECT is((SELECT count(*)::int || ':' || max(object_key) FROM vocab.audio_assets), '1:vocab/test/second.m4a', 'one recording per revision');

-- ============================ submit ============================
SELECT lives_ok($$SELECT vocab.submit_revision(pg_temp.id('r1'))$$, 'the author submits');
SELECT throws_ok($$SELECT vocab.submit_revision(pg_temp.id('r1'))$$, '23514', 'Only a draft can be submitted', 'it cannot be submitted twice');
SELECT throws_ok($$SELECT vocab.update_draft(pg_temp.id('r1'), 'apres', NULL, 'noun', 'd', 'e', NULL, pg_temp.id('src_ok'))$$,
    'P0001', 'Submitted content cannot be modified; create a new revision', 'submitted content is frozen');
SELECT throws_ok($$SELECT vocab.remove_audio(pg_temp.id('r1'))$$,
    'P0001', 'Recordings of submitted, approved or rejected words are immutable', 'the recording is frozen with the submission');
SELECT throws_ok($$UPDATE vocab.audio_assets SET byte_size = 1 WHERE word_revision_id = pg_temp.id('r1')$$,
    'P0001', 'Recordings of submitted, approved or rejected words are immutable', 'recording metadata cannot be edited after submission');
SELECT throws_ok($$UPDATE vocab.word_revisions SET status = 'draft' WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Invalid word revision transition', 'a submission cannot be pulled back to draft');
SELECT throws_ok($$DELETE FROM vocab.word_revisions WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Only draft word revisions can be deleted', 'a submitted revision cannot be deleted');
SELECT throws_ok($$UPDATE vocab.sources SET source_title = 'renamed' WHERE id = pg_temp.id('src_ok')$$,
    'P0001', 'Source identity used in submitted material is immutable', 'a cited source cannot be renamed');
SELECT throws_ok($$DELETE FROM vocab.sources WHERE id = pg_temp.id('src_ok')$$, '23503', NULL, 'a cited source cannot be deleted');

-- ============================ review: a different person ============================
SELECT throws_ok($$UPDATE vocab.word_revisions SET status='approved', approved_by='a0000000-0000-4000-8000-000000000004', approved_at=now() WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Approval requires the latest review to be an approval by an active, independent reviewer', 'approval without any review is refused');
SELECT throws_ok($$UPDATE vocab.word_revisions SET status='rejected' WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Rejection requires the latest review to be a rejection', 'rejection without any review is refused');
SELECT throws_ok($$SELECT vocab.review_revision(pg_temp.id('r1'), 'approved')$$, '42501', 'Staff role required', 'the author (an editor) cannot review through the function');
SELECT throws_ok($$INSERT INTO vocab.reviews (word_revision_id, reviewer_id, verdict) VALUES (pg_temp.id('r1'), 'a0000000-0000-4000-8000-000000000003', 'approved')$$,
    'P0001', 'Author cannot review own word', 'self-review is refused by the table itself');
SELECT throws_ok($$INSERT INTO vocab.reviews (word_revision_id, reviewer_id, verdict) VALUES (pg_temp.id('r1'), 'a0000000-0000-4000-8000-000000000024', 'approved')$$,
    'P0001', 'Reviewer role required', 'a user without the reviewer role cannot review');
SELECT throws_ok($$INSERT INTO vocab.reviews (word_revision_id, reviewer_id, verdict) VALUES (pg_temp.id('r1'), 'a0000000-0000-4000-8000-000000000023', 'approved')$$,
    'P0001', 'Reviewer role required', 'an INACTIVE reviewer role does not count');
SELECT throws_ok($$INSERT INTO vocab.reviews (word_revision_id, reviewer_id, verdict) VALUES (pg_temp.id('r1'), 'a0000000-0000-4000-8000-000000000001', 'approved')$$,
    'P0001', 'Reviewer role required', 'a student cannot review');
SELECT throws_ok($$INSERT INTO vocab.reviews (word_revision_id, reviewer_id, verdict) VALUES (pg_temp.id('r2'), 'a0000000-0000-4000-8000-000000000004', 'approved')$$,
    'P0001', 'Only a submitted word revision can be reviewed', 'a draft cannot be reviewed');
SELECT throws_ok($$INSERT INTO vocab.reviews (word_revision_id, reviewer_id, verdict) VALUES (pg_temp.id('r1'), 'a0000000-0000-4000-8000-000000000004', 'changes_requested')$$,
    '23514', NULL, 'verdict is approved or rejected');

-- A person holding BOTH roles writes a word and then tries to review it.
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000025';
INSERT INTO ids SELECT 'w_self', vocab.create_word('test-word-self');
INSERT INTO ids SELECT 'r_self', vocab.create_draft(pg_temp.id('w_self'), 'fr', 'auto-relu', NULL, 'verb', 'd', 'e', NULL, pg_temp.id('src_ok'));
SELECT lives_ok($$SELECT vocab.submit_revision(pg_temp.id('r_self'))$$, 'fixture: editor+reviewer submits own word');
SELECT throws_ok($$SELECT vocab.review_revision(pg_temp.id('r_self'), 'approved')$$,
    'P0001', 'Author cannot review own word', 'REVIEWER <> AUTHOR: holding both roles does not allow approving your own word');
SELECT is((SELECT count(*)::int FROM vocab.reviews), 0, 'no refused review left a row behind');

-- ============================ rights gate ============================
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000004';
-- r1's text source is cleared but its recording's rights are not.
SELECT throws_ok($$SELECT vocab.review_revision(pg_temp.id('r1'), 'approved')$$,
    'P0001', 'Approval requires the recording''s rights to be cleared', 'RIGHTS GATE: an uncleared recording blocks approval');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000021';
SELECT lives_ok($$SELECT vocab.set_source_rights(pg_temp.id('src_unverified'), 'cleared')$$, 'fixture: rights cleared for now');
SELECT lives_ok($$SELECT vocab.set_source_rights(pg_temp.id('src_ok'), 'restricted')$$, 'fixture: text rights withdrawn');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000004';
SELECT throws_ok($$SELECT vocab.review_revision(pg_temp.id('r1'), 'approved')$$,
    'P0001', 'Approval requires a rights-cleared source record', 'RIGHTS GATE: an uncleared text source blocks approval');
SELECT is((SELECT status FROM vocab.word_revisions WHERE id = pg_temp.id('r1')), 'in_review', 'the refused approval changed nothing');
SELECT is((SELECT count(*)::int FROM vocab.reviews WHERE word_revision_id = pg_temp.id('r1')), 0, 'and recorded no review');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000021';
SELECT lives_ok($$SELECT vocab.set_source_rights(pg_temp.id('src_ok'), 'cleared')$$, 'fixture: text rights cleared again');

-- ============================ the latest review decides ============================
INSERT INTO vocab.reviews (word_revision_id, reviewer_id, verdict) VALUES (pg_temp.id('r1'), 'a0000000-0000-4000-8000-000000000004', 'approved');
INSERT INTO vocab.reviews (word_revision_id, reviewer_id, verdict, reviewed_at) VALUES (pg_temp.id('r1'), 'a0000000-0000-4000-8000-000000000026', 'rejected', '2000-01-01');
SELECT ok((SELECT max(reviewed_at) > now() - interval '1 minute' FROM vocab.reviews WHERE verdict = 'rejected' AND word_revision_id = pg_temp.id('r1')),
    'a caller-supplied (back-dated) review time is replaced by the server clock');
SELECT throws_ok($$UPDATE vocab.word_revisions SET status='approved', approved_by='a0000000-0000-4000-8000-000000000004', approved_at=now() WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Approval requires the latest review to be an approval by an active, independent reviewer', 'an earlier approval does not survive a later rejection');
INSERT INTO vocab.reviews (word_revision_id, reviewer_id, verdict) VALUES (pg_temp.id('r1'), 'a0000000-0000-4000-8000-000000000025', 'approved');
SELECT throws_ok($$UPDATE vocab.word_revisions SET status='rejected' WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Rejection requires the latest review to be a rejection', 'an earlier rejection does not survive a later approval');
SELECT throws_ok($$UPDATE vocab.word_revisions SET status='approved', approved_by='a0000000-0000-4000-8000-000000000004', approved_at=now() WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Approval requires the latest review to be an approval by an active, independent reviewer', 'approved_by must be the reviewer who gave the latest approval');
SELECT throws_ok($$UPDATE vocab.word_revisions SET status='approved', approved_by='a0000000-0000-4000-8000-000000000003', approved_at=now() WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Approval requires the latest review to be an approval by an active, independent reviewer', 'the author cannot be recorded as approver');
UPDATE app.staff_roles SET is_active = false WHERE user_id = 'a0000000-0000-4000-8000-000000000025' AND role = 'reviewer';
SELECT throws_ok($$UPDATE vocab.word_revisions SET status='approved', approved_by='a0000000-0000-4000-8000-000000000025', approved_at=now() WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Approval requires the latest review to be an approval by an active, independent reviewer', 'a reviewer whose role was deactivated after reviewing cannot approve');
UPDATE app.staff_roles SET is_active = true WHERE user_id = 'a0000000-0000-4000-8000-000000000025' AND role = 'reviewer';

-- ============================ approval through the function ============================
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000004';
SELECT lives_ok($$SELECT vocab.review_revision(pg_temp.id('r1'), 'approved', 'synthetic note')$$, 'an independent reviewer approves');
SELECT is((SELECT status || '/' || approved_by FROM vocab.word_revisions WHERE id = pg_temp.id('r1')), 'approved/a0000000-0000-4000-8000-000000000004',
    'the revision is approved by the reviewer');
SELECT ok((SELECT approved_at > now() - interval '1 minute' FROM vocab.word_revisions WHERE id = pg_temp.id('r1')), 'approved_at is stamped by the server');
SELECT is((SELECT count(*)::int FROM vocab.review_queue() q WHERE q.word_revision_id = pg_temp.id('r1')), 0, 'an approved revision leaves the review queue');
SELECT is((SELECT count(*)::int FROM vocab.review_queue() q WHERE q.word_revision_id = pg_temp.id('r_self')), 1, 'a submitted revision is in the review queue');
SELECT throws_ok($$SELECT vocab.review_revision(gen_random_uuid(), 'approved')$$, 'P0002', 'Word revision not found', 'unknown revision');
SELECT throws_ok($$SELECT vocab.review_revision(pg_temp.id('r_self'), 'maybe')$$, '22023', NULL, 'unknown verdict');

-- ============================ approved content is immutable ============================
SELECT throws_ok($$UPDATE vocab.word_revisions SET definition = 'tampered' WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Approved and rejected word revisions are immutable; create a new revision', 'approved text cannot change');
SELECT throws_ok($$UPDATE vocab.word_revisions SET status = 'draft', approved_by = NULL, approved_at = NULL WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Approved and rejected word revisions are immutable; create a new revision', 'an approved revision cannot be un-approved');
SELECT throws_ok($$DELETE FROM vocab.word_revisions WHERE id = pg_temp.id('r1')$$,
    'P0001', 'Only draft word revisions can be deleted', 'an approved revision cannot be deleted');
SELECT throws_ok($$SELECT vocab.review_revision(pg_temp.id('r1'), 'rejected')$$,
    'P0001', 'Only a submitted word revision can be reviewed', 'an approved revision cannot be re-reviewed');
SELECT throws_ok($$DELETE FROM vocab.audio_assets WHERE word_revision_id = pg_temp.id('r1')$$,
    'P0001', 'Recordings of submitted, approved or rejected words are immutable', 'an approved recording cannot be removed');
SELECT throws_ok($$UPDATE vocab.reviews SET verdict = 'rejected'$$, 'P0001', 'Append-only records cannot be updated or deleted', 'reviews cannot be edited');
SELECT throws_ok($$DELETE FROM vocab.reviews$$, 'P0001', 'Append-only records cannot be updated or deleted', 'reviews cannot be deleted');
SELECT throws_ok($$UPDATE vocab.words SET slug = 'renamed-word' WHERE id = pg_temp.id('w1')$$,
    'P0001', 'Word identity and authorship cannot be changed', 'a word cannot be renamed');
SELECT throws_ok($$DELETE FROM vocab.words WHERE id = pg_temp.id('w1')$$, '23503', NULL, 'a word with revisions cannot be deleted');

-- ============================ rejection is final too ============================
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000003';
SELECT lives_ok($$SELECT vocab.submit_revision(pg_temp.id('r_ht'))$$, 'fixture: Creole revision submitted');
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000026';
SELECT lives_ok($$SELECT vocab.review_revision(pg_temp.id('r_ht'), 'rejected', 'synthetic note')$$, 'an admin rejects');
SELECT is((SELECT status || '/' || COALESCE(approved_by::text, 'none') FROM vocab.word_revisions WHERE id = pg_temp.id('r_ht')), 'rejected/none', 'the revision is rejected, with no approver');
SELECT throws_ok($$UPDATE vocab.word_revisions SET status = 'in_review' WHERE id = pg_temp.id('r_ht')$$,
    'P0001', 'Approved and rejected word revisions are immutable; create a new revision', 'a rejected revision cannot be resubmitted');
SELECT throws_ok($$SELECT vocab.review_revision(pg_temp.id('r_ht'), 'approved')$$,
    'P0001', 'Only a submitted word revision can be reviewed', 'a rejected revision cannot be approved afterwards');
-- A correction is a NEW revision, with a new number.
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000003';
INSERT INTO ids SELECT 'r_ht2', vocab.create_draft(pg_temp.id('w1'), 'ht', 'mo-tès', NULL, 'noun', 'Definisyon korije.', 'Egzanp.', NULL, pg_temp.id('src_ok'));
SELECT is((SELECT revision FROM vocab.word_revisions WHERE id = pg_temp.id('r_ht2')), 2, 'the corrected Creole text is revision 2');
SELECT lives_ok($$DELETE FROM vocab.word_revisions WHERE id = pg_temp.id('r2')$$, 'an unsubmitted draft can be deleted');

-- ============================ audit trail (seam) ============================
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE created_at = now() AND action LIKE 'vocab.%' AND (actor_kind <> 'staff' OR outcome <> 'allowed' OR actor_id IS NULL)), 0,
    'every vocab audit row is a staff decision with an actor');
SELECT is((SELECT actor_id::text || '|' || (details ->> 'verdict') FROM app.audit_events
           WHERE created_at = now() AND action = 'vocab.revision.review' AND target_id = pg_temp.id('r1')),
    'a0000000-0000-4000-8000-000000000004|approved', 'the approval is audited with reviewer and verdict');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE created_at = now() AND action = 'vocab.revision.review' AND target_id = pg_temp.id('r_self')), 0,
    'a refused review leaves no "allowed" audit row');
SELECT is((SELECT array_agg(DISTINCT action ORDER BY action) FROM app.audit_events WHERE created_at = now() AND action LIKE 'vocab.%'),
    ARRAY['vocab.audio.set','vocab.revision.create','vocab.revision.review','vocab.revision.submit','vocab.revision.update','vocab.source.register','vocab.source.rights','vocab.word.create'],
    'each successful staff write of this file was audited');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE created_at = now() AND action LIKE 'vocab.%'
           AND details::text ~* '(synthetic|définition|definisyon|mot-test)'), 0,
    'audit details never contain word text or free-text notes');

SELECT * FROM finish();
ROLLBACK;
