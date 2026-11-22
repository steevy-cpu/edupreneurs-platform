-- Editorial, publication and append-only integrity rules.
-- Runs as the migration owner on purpose: these rules must hold even for
-- privileged writers (future staff services, a person in a SQL console).
BEGIN;
SELECT * FROM no_plan();

-- extra synthetic staff: a second editor, a reviewer whose role is inactive,
-- and a reviewer who ALSO holds an inactive admin role (duplicate role rows)
INSERT INTO auth.users (instance_id, id, aud, role, email)
SELECT '00000000-0000-0000-0000-000000000000', id, 'authenticated', 'authenticated', email FROM (VALUES
  ('a0000000-0000-4000-8000-000000000011'::uuid, 'inactive.reviewer@edupreneur.test'),
  ('a0000000-0000-4000-8000-000000000012'::uuid, 'two.roles@edupreneur.test'),
  ('a0000000-0000-4000-8000-000000000013'::uuid, 'no.role@edupreneur.test')) AS u(id, email);
INSERT INTO app.staff_roles (user_id, role, is_active) VALUES
  ('a0000000-0000-4000-8000-000000000011', 'reviewer', false),
  ('a0000000-0000-4000-8000-000000000012', 'admin', false),
  ('a0000000-0000-4000-8000-000000000012', 'reviewer', true);
INSERT INTO app.content_sources (id, source_title, rights_status) VALUES
  ('e0000000-0000-4000-8000-000000000002', 'Synthetic source with unverified rights', 'unverified');

-- ============================ lesson revisions ============================
SELECT throws_ok($$INSERT INTO app.lesson_revisions (lesson_id, revision, locale, title, blocks, created_by, status, approved_by, approved_at)
    VALUES ('b0000000-0000-4000-8000-000000000005', 20, 'fr', 'x', '[]', 'a0000000-0000-4000-8000-000000000003', 'approved', 'a0000000-0000-4000-8000-000000000004', now())$$,
    'P0001', 'Lesson revisions must be created as unapproved drafts', 'a revision cannot be inserted already approved');
SELECT throws_ok($$INSERT INTO app.lesson_revisions (lesson_id, revision, locale, title, blocks, created_by, status)
    VALUES ('b0000000-0000-4000-8000-000000000005', 20, 'fr', 'x', '[]', 'a0000000-0000-4000-8000-000000000003', 'in_review')$$,
    'P0001', 'Lesson revisions must be created as unapproved drafts', 'a revision cannot be inserted in_review');
SELECT throws_ok($$INSERT INTO app.lesson_revisions (lesson_id, revision, locale, title, blocks) VALUES ('b0000000-0000-4000-8000-000000000005', 20, 'fr', 'x', '[]')$$,
    '23502', NULL, 'a revision needs an author');

INSERT INTO app.lesson_revisions (id, lesson_id, revision, locale, title, blocks, created_by) VALUES
  ('c0000000-0000-4000-8000-000000000021', 'b0000000-0000-4000-8000-000000000005', 21, 'fr', 'guard fixture 21', '[]', 'a0000000-0000-4000-8000-000000000003'),
  ('c0000000-0000-4000-8000-000000000022', 'b0000000-0000-4000-8000-000000000005', 22, 'fr', 'guard fixture 22', '[]', 'a0000000-0000-4000-8000-000000000003'),
  ('c0000000-0000-4000-8000-000000000023', 'b0000000-0000-4000-8000-000000000005', 23, 'fr', 'guard fixture 23', '[]', 'a0000000-0000-4000-8000-000000000003'),
  ('c0000000-0000-4000-8000-000000000024', 'b0000000-0000-4000-8000-000000000005', 24, 'ht', 'guard fixture 24', '[]', 'a0000000-0000-4000-8000-000000000003');
INSERT INTO app.question_revisions (id, lesson_revision_id, question_key, position, kind, prompt, response_spec, answer_key, explanation) VALUES
  ('d0000000-0000-4000-8000-000000000421', 'c0000000-0000-4000-8000-000000000021', 'q', 1, 'mcq', '{"text":"?"}', '{"choices":[{"id":"a","text":"1"}]}', '{"correct_choice_id":"a"}', '{"text":"."}');

-- ---- approval prerequisites ----
SELECT throws_ok($$UPDATE app.lesson_revisions SET status='approved', approved_by='a0000000-0000-4000-8000-000000000004', approved_at=now() WHERE id='c0000000-0000-4000-8000-000000000021'$$,
    'P0001', NULL, 'approval without any review is rejected');

SELECT throws_ok($$INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES ('c0000000-0000-4000-8000-000000000021', 'a0000000-0000-4000-8000-000000000003', 'approved')$$,
    'P0001', 'Author cannot review own lesson', 'self-review is rejected');
SELECT throws_ok($$INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES ('c0000000-0000-4000-8000-000000000021', 'a0000000-0000-4000-8000-000000000013', 'approved')$$,
    'P0001', 'Reviewer role required', 'a user without the reviewer role cannot review');
SELECT throws_ok($$INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES ('c0000000-0000-4000-8000-000000000021', 'a0000000-0000-4000-8000-000000000011', 'approved')$$,
    'P0001', 'Reviewer role required', 'an INACTIVE reviewer role does not count');
SELECT throws_ok($$INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES ('c0000000-0000-4000-8000-000000000021', 'a0000000-0000-4000-8000-000000000001', 'approved')$$,
    'P0001', 'Reviewer role required', 'a student cannot review');
SELECT throws_ok($$UPDATE app.lesson_revisions SET created_by = 'a0000000-0000-4000-8000-000000000004' WHERE id = 'c0000000-0000-4000-8000-000000000021'$$,
    'P0001', 'Lesson revision identity and authorship cannot be changed', 'authorship cannot be reassigned to dodge the independence rule');

-- uncleared / missing sources
INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES ('c0000000-0000-4000-8000-000000000021', 'a0000000-0000-4000-8000-000000000004', 'approved');
SELECT throws_ok($$UPDATE app.lesson_revisions SET status='approved', approved_by='a0000000-0000-4000-8000-000000000004', approved_at=now() WHERE id='c0000000-0000-4000-8000-000000000021'$$,
    'P0001', 'Approval requires at least one source and all sources rights-cleared', 'approval with NO source is rejected');
INSERT INTO app.lesson_revision_sources VALUES ('c0000000-0000-4000-8000-000000000022', 'e0000000-0000-4000-8000-000000000001'), ('c0000000-0000-4000-8000-000000000022', 'e0000000-0000-4000-8000-000000000002');
INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES ('c0000000-0000-4000-8000-000000000022', 'a0000000-0000-4000-8000-000000000004', 'approved');
SELECT throws_ok($$UPDATE app.lesson_revisions SET status='approved', approved_by='a0000000-0000-4000-8000-000000000004', approved_at=now() WHERE id='c0000000-0000-4000-8000-000000000022'$$,
    'P0001', 'Approval requires at least one source and all sources rights-cleared', 'approval with an UNCLEARED source is rejected');

-- review freezes content, questions and sources
SELECT throws_ok($$UPDATE app.lesson_revisions SET title = 'edited after review' WHERE id='c0000000-0000-4000-8000-000000000021'$$,
    'P0001', 'Reviewed content cannot be modified; create a new revision', 'reviewed content is frozen');
SELECT throws_ok($$UPDATE app.question_revisions SET answer_key = '{"correct_choice_id":"z"}' WHERE id='d0000000-0000-4000-8000-000000000421'$$,
    'P0001', 'Questions in reviewed/approved/packed lessons are immutable', 'questions of a reviewed revision are frozen');
SELECT throws_ok($$INSERT INTO app.question_revisions (lesson_revision_id, question_key, position, kind, prompt, response_spec, answer_key, explanation)
    VALUES ('c0000000-0000-4000-8000-000000000021', 'late', 2, 'mcq', '{}', '{}', '{}', '{}')$$,
    'P0001', 'Questions in reviewed/approved/packed lessons are immutable', 'no question can be added after review');
SELECT throws_ok($$INSERT INTO app.lesson_revision_sources VALUES ('c0000000-0000-4000-8000-000000000021', 'e0000000-0000-4000-8000-000000000001')$$,
    'P0001', 'Reviewed source references cannot be modified', 'sources cannot be attached after review');
SELECT throws_ok($$UPDATE app.editorial_reviews SET verdict = 'approved'$$, 'P0001', 'Append-only records cannot be updated or deleted', 'reviews cannot be edited');
SELECT throws_ok($$DELETE FROM app.editorial_reviews$$, 'P0001', 'Append-only records cannot be updated or deleted', 'reviews cannot be deleted');

-- the LATEST review decides, and the approver must be that reviewer
INSERT INTO app.lesson_revision_sources VALUES ('c0000000-0000-4000-8000-000000000023', 'e0000000-0000-4000-8000-000000000001');
INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES ('c0000000-0000-4000-8000-000000000023', 'a0000000-0000-4000-8000-000000000004', 'approved');
INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict, reviewed_at) VALUES ('c0000000-0000-4000-8000-000000000023', 'a0000000-0000-4000-8000-000000000004', 'rejected', '2000-01-01');
SELECT ok((SELECT max(reviewed_at) > now() - interval '1 minute' FROM app.editorial_reviews WHERE verdict = 'rejected' AND lesson_revision_id = 'c0000000-0000-4000-8000-000000000023'),
    'a caller-supplied (back-dated) review time is replaced by the server clock');
SELECT throws_ok($$UPDATE app.lesson_revisions SET status='approved', approved_by='a0000000-0000-4000-8000-000000000004', approved_at=now() WHERE id='c0000000-0000-4000-8000-000000000023'$$,
    'P0001', NULL, 'an earlier approval does not survive a later rejection');
INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES ('c0000000-0000-4000-8000-000000000023', 'a0000000-0000-4000-8000-000000000012', 'approved');
SELECT throws_ok($$UPDATE app.lesson_revisions SET status='approved', approved_by='a0000000-0000-4000-8000-000000000004', approved_at=now() WHERE id='c0000000-0000-4000-8000-000000000023'$$,
    'P0001', NULL, 'approved_by must be the reviewer who gave the latest approval');
SELECT throws_ok($$UPDATE app.lesson_revisions SET status='approved', approved_by='a0000000-0000-4000-8000-000000000003', approved_at=now() WHERE id='c0000000-0000-4000-8000-000000000023'$$,
    'P0001', NULL, 'the author cannot be recorded as approver');
SELECT lives_ok($$UPDATE app.lesson_revisions SET status='approved', approved_by='a0000000-0000-4000-8000-000000000012', approved_at='1999-01-01' WHERE id='c0000000-0000-4000-8000-000000000023'$$,
    'a reviewer with an active reviewer role AND an inactive admin role can approve (duplicate role rows)');
SELECT ok((SELECT approved_at > now() - interval '1 minute' FROM app.lesson_revisions WHERE id='c0000000-0000-4000-8000-000000000023'),
    'approved_at is stamped by the server, not the caller');

-- approved content is immutable
SELECT throws_ok($$UPDATE app.lesson_revisions SET blocks = '[{"type":"paragraph","key":"x","text":"tampered"}]' WHERE id = 'c0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Approved/packed lesson revisions are immutable', 'approved lesson content cannot change');
SELECT throws_ok($$UPDATE app.lesson_revisions SET status = 'draft', approved_by = NULL, approved_at = NULL WHERE id = 'c0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Approved/packed lesson revisions are immutable', 'an approved revision cannot be un-approved');
SELECT throws_ok($$DELETE FROM app.lesson_revisions WHERE id = 'c0000000-0000-4000-8000-000000000023'$$,
    'P0001', 'Approved/packed lesson revisions are immutable', 'an approved revision cannot be deleted');
SELECT throws_ok($$UPDATE app.question_revisions SET answer_key = '{"correct_choice_id":"a"}' WHERE id = 'd0000000-0000-4000-8000-000000000101'$$,
    'P0001', 'Questions in reviewed/approved/packed lessons are immutable', 'a published answer key cannot change');
SELECT throws_ok($$DELETE FROM app.question_revisions WHERE id = 'd0000000-0000-4000-8000-000000000101'$$,
    'P0001', 'Questions in reviewed/approved/packed lessons are immutable', 'a published question cannot be deleted');
SELECT throws_ok($$DELETE FROM app.lesson_revision_sources WHERE lesson_revision_id = 'c0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Reviewed source references cannot be modified', 'source attribution of approved content is frozen');
SELECT throws_ok($$UPDATE app.content_sources SET source_title = 'renamed' WHERE id = 'e0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Source identity used in reviewed material is immutable', 'a cited source cannot be renamed');
SELECT throws_ok($$DELETE FROM app.content_sources WHERE id = 'e0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Referenced sources cannot be deleted', 'a cited source cannot be deleted');
SELECT throws_ok($$INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict) VALUES ('c0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000004', 'rejected')$$,
    'P0001', 'Cannot review a finalized lesson revision', 'an approved revision cannot be re-reviewed');

-- ================================= packs =================================
SELECT throws_ok($$INSERT INTO app.pack_releases (pack_key, revision, locale, status, manifest_object_key, manifest_sha256, compressed_bytes, released_at)
    VALUES ('math-9af', 30, 'fr', 'active', 'x', sha256('x'), 1, now())$$,
    'P0001', 'Pack releases must be created in building state', 'a release cannot be inserted already active');

INSERT INTO app.pack_releases (id, pack_key, revision, locale) VALUES
  ('f0000000-0000-4000-8000-000000000031', 'math-9af', 31, 'fr'),
  ('f0000000-0000-4000-8000-000000000032', 'math-9af', 32, 'fr'),
  ('f0000000-0000-4000-8000-000000000033', 'math-9af', 33, 'ht');
SELECT throws_ok($$INSERT INTO app.pack_items VALUES ('f0000000-0000-4000-8000-000000000031', 'c0000000-0000-4000-8000-000000000002', 1)$$,
    'P0001', 'Pack items must be approved and match pack locale', 'a Creole revision cannot go in a French pack');
SELECT throws_ok($$INSERT INTO app.pack_items VALUES ('f0000000-0000-4000-8000-000000000031', 'c0000000-0000-4000-8000-000000000021', 1)$$,
    'P0001', 'Pack items must be approved and match pack locale', 'an unapproved revision cannot go in a pack');
SELECT throws_ok($$UPDATE app.pack_releases SET status='ready', manifest_object_key='x', manifest_sha256=sha256('x'), compressed_bytes=1 WHERE id='f0000000-0000-4000-8000-000000000031'$$,
    'P0001', 'Empty packs cannot be finalized', 'an empty pack cannot be finalized');
SELECT throws_ok($$UPDATE app.pack_releases SET status='active' WHERE id='f0000000-0000-4000-8000-000000000031'$$,
    'P0001', 'Invalid pack lifecycle transition', 'building -> active skips "ready" and is rejected');

INSERT INTO app.pack_items VALUES ('f0000000-0000-4000-8000-000000000031', 'c0000000-0000-4000-8000-000000000023', 1);
SELECT throws_ok($$UPDATE app.pack_releases SET status='ready' WHERE id='f0000000-0000-4000-8000-000000000031'$$,
    '23514', NULL, 'a finalized pack needs manifest key, hash and size');
-- pointer rules
SELECT throws_ok($$UPDATE app.pack_current SET release_id = 'f0000000-0000-4000-8000-000000000031' WHERE pack_key='math-9af' AND locale='fr'$$,
    'P0001', 'Current pointer requires matching active pack', 'the pointer cannot move to a pack that is not active');
SELECT throws_ok($$UPDATE app.pack_current SET release_id = 'f0000000-0000-4000-8000-000000000002' WHERE pack_key='math-9af' AND locale='fr'$$,
    NULL, NULL, 'the French pointer cannot point at the Creole release');
SELECT throws_ok($$INSERT INTO app.pack_current (pack_key, locale, release_id) VALUES ('other-pack', 'fr', 'f0000000-0000-4000-8000-000000000001')$$,
    NULL, NULL, 'a pointer cannot reference a release of another pack_key');
SELECT throws_ok($$UPDATE app.pack_releases SET status='retired' WHERE id='f0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Switch current pointer before retiring/revoking pack', 'the current release cannot be retired');
SELECT throws_ok($$UPDATE app.pack_releases SET status='revoked' WHERE id='f0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Switch current pointer before retiring/revoking pack', 'the current release cannot be revoked');

-- finalized packs are immutable
SELECT throws_ok($$UPDATE app.pack_releases SET manifest_sha256 = sha256('tampered') WHERE id='f0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Finalized pack contents are immutable', 'a released manifest hash cannot change');
SELECT throws_ok($$DELETE FROM app.pack_releases WHERE id='f0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Finalized packs must be retained or revoked', 'a released pack cannot be deleted');
SELECT throws_ok($$DELETE FROM app.pack_items WHERE pack_release_id='f0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Cannot remove finalized pack items', 'items cannot be removed from a released pack');
SELECT throws_ok($$INSERT INTO app.pack_items VALUES ('f0000000-0000-4000-8000-000000000001', 'c0000000-0000-4000-8000-000000000023', 2)$$,
    'P0001', 'Cannot modify items of a finalized pack', 'items cannot be added to a released pack');
SELECT throws_ok($$UPDATE app.pack_items SET pack_release_id = 'f0000000-0000-4000-8000-000000000032' WHERE pack_release_id='f0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Pack items cannot be moved; delete and re-add while the pack is building', 'an item cannot be moved OUT of a released pack');

-- rights withdrawn after approval block publication
UPDATE app.content_sources SET rights_status = 'blocked' WHERE id = 'e0000000-0000-4000-8000-000000000001';
SELECT throws_ok($$UPDATE app.pack_releases SET status='ready', manifest_object_key='x', manifest_sha256=sha256('x'), compressed_bytes=1 WHERE id='f0000000-0000-4000-8000-000000000031'$$,
    'P0001', 'Pack includes content with uncleared rights', 'a pack with withdrawn rights cannot be finalized');
UPDATE app.content_sources SET rights_status = 'cleared' WHERE id = 'e0000000-0000-4000-8000-000000000001';

-- a full, legal publication still works end to end
SELECT lives_ok($$UPDATE app.pack_releases SET status='ready', manifest_object_key='x', manifest_sha256=sha256('x'), compressed_bytes=1 WHERE id='f0000000-0000-4000-8000-000000000031'$$, 'legal: building -> ready');
SELECT lives_ok($$UPDATE app.pack_releases SET status='active' WHERE id='f0000000-0000-4000-8000-000000000031'$$, 'legal: ready -> active');
SELECT ok((SELECT released_at IS NOT NULL FROM app.pack_releases WHERE id='f0000000-0000-4000-8000-000000000031'), 'released_at is stamped by the server on activation');
SELECT lives_ok($$UPDATE app.pack_current SET release_id = 'f0000000-0000-4000-8000-000000000031', switched_at = now() WHERE pack_key='math-9af' AND locale='fr'$$, 'legal: pointer moves to the new active release');
SELECT lives_ok($$UPDATE app.pack_releases SET status='retired' WHERE id='f0000000-0000-4000-8000-000000000001'$$, 'legal: the previous release can now be retired');
SELECT lives_ok($$UPDATE app.pack_releases SET status='revoked' WHERE id='f0000000-0000-4000-8000-000000000001'$$, 'legal: retired -> revoked');
SELECT throws_ok($$UPDATE app.pack_releases SET status='active' WHERE id='f0000000-0000-4000-8000-000000000001'$$,
    'P0001', 'Cannot restore revoked pack', 'a revoked pack can never come back');

-- ============================ append-only history ============================
SET LOCAL edu.actor_id = 'a0000000-0000-4000-8000-000000000001';
SELECT lives_ok($$SELECT app.sync_apply_operation('33333333-3333-4333-8333-000000000001','practice_answer','{"question_revision_id":"d0000000-0000-4000-8000-000000000201","response":{"choice_id":"b"}}', sha256('g1'), 'mep-canon-1')$$, 'fixture: one synced answer');
SET LOCAL edu.actor_id = '';
SELECT throws_ok($$UPDATE app.practice_attempts SET score = 1$$, 'P0001', 'Append-only records cannot be updated or deleted', 'attempts cannot be edited, even by the owner role');
SELECT throws_ok($$DELETE FROM app.practice_attempts$$, 'P0001', 'Append-only records cannot be updated or deleted', 'attempts cannot be deleted');
SELECT throws_ok($$UPDATE app.sync_receipts SET result = '{}'$$, 'P0001', 'Append-only records cannot be updated or deleted', 'receipts cannot be edited');
SELECT throws_ok($$DELETE FROM app.account_change_feed$$, 'P0001', 'Append-only records cannot be updated or deleted', 'the change feed cannot be deleted');
INSERT INTO app.audit_events (actor_kind, action, outcome) VALUES ('system', 'test.fixture', 'allowed');
SELECT throws_ok($$UPDATE app.audit_events SET outcome = 'denied'$$, 'P0001', 'Append-only records cannot be updated or deleted', 'audit events cannot be edited');

SELECT * FROM finish();
ROLLBACK;
