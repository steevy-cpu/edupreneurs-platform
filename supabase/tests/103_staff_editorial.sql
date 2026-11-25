-- The editorial workflow functions of schema `staff`: who may call them, what
-- they refuse themselves, and that the `app` triggers stay the enforcement of
-- record underneath them.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_worker TO postgres WITH INHERIT FALSE, SET TRUE;
-- Returns the first column as text, or 'ERROR:<sqlstate>:<message>'.
CREATE FUNCTION pg_temp.as_role(p_role text, p_actor uuid, p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    PERFORM set_config('edu.actor_id', COALESCE(p_actor::text, ''), true);
    EXECUTE format('SET LOCAL ROLE %I', p_role);
    BEGIN
        EXECUTE p_sql INTO v_out;
    EXCEPTION WHEN OTHERS THEN
        v_out := 'ERROR:' || SQLSTATE || ':' || SQLERRM;
    END;
    EXECUTE 'RESET ROLE';
    PERFORM set_config('edu.actor_id', '', true);
    RETURN v_out;
END;
$fn$;
CREATE FUNCTION pg_temp.staff(p_actor uuid, p_sql text) RETURNS text LANGUAGE sql AS
$$ SELECT pg_temp.as_role('edu_staff', p_actor, p_sql) $$;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
\set REVIEWER '''a0000000-0000-4000-8000-000000000004'''
\set UNIT '''b0000000-0000-4000-8000-000000000004'''

-- two more synthetic staff for this test only (rolled back)
INSERT INTO auth.users (instance_id, id, aud, role, email) VALUES
    ('00000000-0000-0000-0000-000000000000', 'a0000000-0000-4000-8000-0000000000f1', 'authenticated', 'authenticated', 'publisher.t103@edupreneur.test'),
    ('00000000-0000-0000-0000-000000000000', 'a0000000-0000-4000-8000-0000000000f2', 'authenticated', 'authenticated', 'admin.t103@edupreneur.test');
INSERT INTO app.staff_roles (user_id, role) VALUES
    ('a0000000-0000-4000-8000-0000000000f1', 'publisher'),
    ('a0000000-0000-4000-8000-0000000000f2', 'admin');
\set PUBLISHER '''a0000000-0000-4000-8000-0000000000f1'''
\set ADMIN '''a0000000-0000-4000-8000-0000000000f2'''

CREATE TEMP TABLE ids (label text PRIMARY KEY, id uuid);
GRANT SELECT ON ids TO edu_staff;
CREATE TEMP TABLE counts AS
SELECT (SELECT count(*) FROM app.lessons) AS lessons,
       (SELECT count(*) FROM app.lesson_revisions) AS revisions,
       (SELECT count(*) FROM app.pack_releases) AS releases,
       (SELECT count(*) FROM app.audit_events) AS audit;

-- ---- nobody but edu_staff ------------------------------------------------------------
SELECT is(left(pg_temp.as_role('edu_api', :EDITOR::uuid, $$SELECT staff.create_lesson('b0000000-0000-4000-8000-000000000004', 't103-x')$$), 11), 'ERROR:42501', 'edu_api cannot create a lesson, even as a staff user');
SELECT is(left(pg_temp.as_role('edu_api', :EDITOR::uuid, $$SELECT staff.list_revisions(NULL, false, 10)$$), 11), 'ERROR:42501', 'edu_api cannot list drafts');
SELECT is(left(pg_temp.as_role('edu_api', :PUBLISHER::uuid, $$SELECT staff.release_pack(gen_random_uuid())$$), 11), 'ERROR:42501', 'edu_api cannot release a pack');
SELECT is(left(pg_temp.as_role('edu_worker', :EDITOR::uuid, $$SELECT staff.get_revision('c0000000-0000-4000-8000-000000000001')$$), 11), 'ERROR:42501', 'edu_worker cannot read revisions');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'staff'::regnamespace
           AND has_function_privilege('edu_api', p.oid, 'EXECUTE')), 0, 'edu_api can execute nothing in staff');

-- internal helpers are not callable by the staff API role
SELECT is(left(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.insert_questions('c0000000-0000-4000-8000-000000000001', '[]')$$), 11), 'ERROR:42501', 'insert_questions is internal');
SELECT is(left(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.lock_revision('c0000000-0000-4000-8000-000000000001')$$), 11), 'ERROR:42501', 'lock_revision is internal');
SELECT is(left(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.revision_json('c0000000-0000-4000-8000-000000000001')$$), 11), 'ERROR:42501', 'revision_json (no role check) is internal');
SELECT is(left(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.pack_release_json(gen_random_uuid())$$), 11), 'ERROR:42501', 'pack_release_json (no role check) is internal');
SELECT is(left(pg_temp.staff(:PUBLISHER::uuid, $$SELECT staff.switch_current_pack(NULL, 'pack_release.release')$$), 11), 'ERROR:42501', 'switch_current_pack is internal');
SELECT is(left(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.lock_pack('abc', 'fr')$$), 11), 'ERROR:42501', 'lock_pack is internal');

-- ---- a learner, or no actor, is refused by every function ----------------------------
CREATE TEMP TABLE calls (name text PRIMARY KEY, call text);
INSERT INTO calls VALUES
 ('create_lesson',      $$SELECT staff.create_lesson('b0000000-0000-4000-8000-000000000004', 't103-learner')$$),
 ('create_revision',    $$SELECT staff.create_revision('b0000000-0000-4000-8000-000000000005', 'fr', 't', '[{"key":"a","type":"paragraph","text":"x"}]', '[]')$$),
 ('update_revision',    $$SELECT staff.update_revision('c0000000-0000-4000-8000-000000000001', 't', '[{"key":"a","type":"paragraph","text":"x"}]', '[]')$$),
 ('create_source',      $$SELECT staff.create_source('t', NULL)$$),
 ('set_source_rights',  $$SELECT staff.set_source_rights('e0000000-0000-4000-8000-000000000001', 'blocked', NULL)$$),
 ('attach_source',      $$SELECT staff.attach_source('c0000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000001')$$),
 ('detach_source',      $$SELECT staff.detach_source('c0000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000001')$$),
 ('submit_revision',    $$SELECT staff.submit_revision('c0000000-0000-4000-8000-000000000001')$$),
 ('review_revision',    $$SELECT staff.review_revision('c0000000-0000-4000-8000-000000000001', 'approved', NULL)$$),
 ('get_revision',       $$SELECT staff.get_revision('c0000000-0000-4000-8000-000000000001')$$),
 ('list_revisions',     $$SELECT staff.list_revisions(NULL, false, 10)$$),
 ('list_sources',       $$SELECT staff.list_sources(10)$$),
 ('build_pack',         $$SELECT staff.build_pack('t103-pack', 'fr', ARRAY['c0000000-0000-4000-8000-000000000001']::uuid[])$$),
 ('release_pack',       $$SELECT staff.release_pack(gen_random_uuid())$$),
 ('rollback_pack',      $$SELECT staff.rollback_pack(gen_random_uuid())$$),
 ('get_pack_release',   $$SELECT staff.get_pack_release(gen_random_uuid())$$),
 ('list_pack_releases', $$SELECT staff.list_pack_releases(NULL, NULL, 10)$$);
SELECT is((SELECT array_agg(name ORDER BY name) FROM calls
           WHERE left(pg_temp.staff('a0000000-0000-4000-8000-000000000001', call), 11) <> 'ERROR:42501'),
    NULL, 'a learner is refused (42501) by every editorial function');
SELECT is((SELECT array_agg(name ORDER BY name) FROM calls
           WHERE left(pg_temp.staff(NULL, call), 11) <> 'ERROR:42501'),
    NULL, 'with no actor every editorial function refuses (42501)');
SELECT is((SELECT count(*)::int FROM calls), 17, 'all 17 callable editorial functions are covered');

-- ---- role gates inside the functions (the API gate is not the only one) --------------
SELECT is(left(pg_temp.staff(:REVIEWER::uuid, (SELECT call FROM calls WHERE name = 'create_lesson')), 11), 'ERROR:42501', 'a reviewer cannot create a lesson');
SELECT is(left(pg_temp.staff(:PUBLISHER::uuid, (SELECT call FROM calls WHERE name = 'create_revision')), 11), 'ERROR:42501', 'a publisher cannot write a revision');
SELECT is(left(pg_temp.staff(:EDITOR::uuid, (SELECT call FROM calls WHERE name = 'review_revision')), 11), 'ERROR:42501', 'an editor cannot review');
SELECT is(left(pg_temp.staff(:EDITOR::uuid, (SELECT call FROM calls WHERE name = 'set_source_rights')), 11), 'ERROR:42501', 'an editor cannot decide on rights');
SELECT is(left(pg_temp.staff(:REVIEWER::uuid, (SELECT call FROM calls WHERE name = 'set_source_rights')), 11), 'ERROR:42501', 'a reviewer cannot decide on rights');
SELECT is(left(pg_temp.staff(:EDITOR::uuid, (SELECT call FROM calls WHERE name = 'release_pack')), 11), 'ERROR:42501', 'an editor cannot release');
SELECT is(left(pg_temp.staff(:REVIEWER::uuid, (SELECT call FROM calls WHERE name = 'rollback_pack')), 11), 'ERROR:42501', 'a reviewer cannot roll back');
SELECT is(left(pg_temp.staff(:REVIEWER::uuid, (SELECT call FROM calls WHERE name = 'build_pack')), 11), 'ERROR:42501', 'a reviewer cannot build a pack');
SELECT is((SELECT (SELECT count(*) FROM app.lessons) - lessons + (SELECT count(*) FROM app.audit_events) - audit FROM counts)::int, 0,
    'none of the refused calls wrote anything');

-- ---- input floor of the database -------------------------------------------------------
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_lesson('b0000000-0000-4000-8000-000000000004', 'Bad Slug')$$), 'ERROR:ED422:slug_invalid', 'slug is validated');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_lesson(gen_random_uuid(), 't103-x')$$), 'ERROR:ED404:unit_not_found', 'unknown unit');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_lesson('b0000000-0000-4000-8000-000000000004', 'resoudre-une-equation-simple')$$), 'ERROR:ED409:lesson_slug_taken', 'slug already used in the unit');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_revision('b0000000-0000-4000-8000-000000000005', 'en', 't', '[{"key":"a","type":"paragraph","text":"x"}]', '[]')$$), 'ERROR:ED422:locale_invalid', 'locale is validated');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_revision('b0000000-0000-4000-8000-000000000005', 'fr', '', '[{"key":"a","type":"paragraph","text":"x"}]', '[]')$$), 'ERROR:ED422:title_invalid', 'title is required');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_revision('b0000000-0000-4000-8000-000000000005', 'fr', 't', '[]', '[]')$$), 'ERROR:ED422:blocks_invalid', 'at least one block');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_revision('b0000000-0000-4000-8000-000000000005', 'fr', 't', '{"a":1}', '[]')$$), 'ERROR:ED422:blocks_invalid', 'blocks must be an array');
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.create_revision('b0000000-0000-4000-8000-000000000005', 'fr', 't', %L, '[]')$$,
    (SELECT jsonb_agg(jsonb_build_object('key', 'k' || n, 'type', 'paragraph', 'text', repeat('x', 4000))) FROM generate_series(1, 70) AS n))),
    'ERROR:ED422:blocks_too_large', 'blocks are bounded in size');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_revision(gen_random_uuid(), 'fr', 't', '[{"key":"a","type":"paragraph","text":"x"}]', '[]')$$), 'ERROR:ED404:lesson_not_found', 'unknown lesson');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_revision('b0000000-0000-4000-8000-000000000005', 'fr', 't', '[{"key":"a","type":"paragraph","text":"x"}]', '[{"question_key":"q1","kind":"numeric","prompt":{},"response_spec":{},"answer_key":{},"explanation":{}}]')$$), 'ERROR:ED422:question_kind_unsupported', 'only mcq questions');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_revision('b0000000-0000-4000-8000-000000000005', 'fr', 't', '[{"key":"a","type":"paragraph","text":"x"}]', '[{"question_key":"q1","kind":"mcq","prompt":{"text":"?"},"response_spec":{"choices":[{"id":"a","text":"1"},{"id":"b","text":"2"}]},"answer_key":{"correct_choice_id":"z"},"explanation":{"text":"."}}]')$$), 'ERROR:ED422:question_correct_choice_missing', 'the correct choice must be one of the choices');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_source(repeat('x', 241), NULL)$$), 'ERROR:ED422:source_title_invalid', 'source title is bounded');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_source('t', 'javascript:alert(1)')$$), 'ERROR:ED422:source_uri_invalid', 'source uri must be http(s)');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.build_pack('t103-pack', 'fr', ARRAY[]::uuid[])$$), 'ERROR:ED422:pack_items_invalid', 'a pack needs items');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.build_pack('X', 'fr', ARRAY['c0000000-0000-4000-8000-000000000001']::uuid[])$$), 'ERROR:ED422:pack_key_invalid', 'pack key is validated');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.list_revisions('published', false, 10)$$), 'ERROR:ED422:status_invalid', 'list status is validated');
SELECT is((SELECT (SELECT count(*) FROM app.lesson_revisions) - revisions + (SELECT count(*) FROM app.pack_releases) - releases FROM counts)::int, 0,
    'refused inputs created nothing');

-- ---- the workflow, with the triggers underneath ----------------------------------------
INSERT INTO ids VALUES ('lesson', pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_lesson('b0000000-0000-4000-8000-000000000004', 't103-lesson')$$)::uuid);
SELECT is((SELECT position FROM app.lessons WHERE id = (SELECT id FROM ids WHERE label = 'lesson')),
    (SELECT max(position) FROM app.lessons WHERE unit_id = :UNIT), 'the new lesson is placed at the end of the unit');
INSERT INTO ids VALUES ('rev', pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.create_revision(%L, 'fr', 'Titre', '[{"key":"a","type":"paragraph","text":"x"}]', '[{"question_key":"q1","kind":"mcq","prompt":{"text":"?"},"response_spec":{"choices":[{"id":"a","text":"1"},{"id":"b","text":"2"}]},"answer_key":{"correct_choice_id":"b"},"explanation":{"text":"."}}]')$$, (SELECT id FROM ids WHERE label = 'lesson')))::uuid);
SELECT is((SELECT row(status, revision, created_by, approved_by)::text FROM app.lesson_revisions WHERE id = (SELECT id FROM ids WHERE label = 'rev')),
    row('draft', 1, 'a0000000-0000-4000-8000-000000000003'::uuid, NULL::uuid)::text, 'a revision starts as a draft of the actor');
SELECT is((SELECT count(*)::int FROM app.question_revisions WHERE lesson_revision_id = (SELECT id FROM ids WHERE label = 'rev')), 1, 'with its questions');

-- another editor is not the author; an admin may act for the author
INSERT INTO app.staff_roles (user_id, role) VALUES (:PUBLISHER, 'editor');
SELECT is(pg_temp.staff(:PUBLISHER::uuid, format($$SELECT staff.update_revision(%L, 'Vol', '[{"key":"a","type":"paragraph","text":"y"}]', '[]')$$, (SELECT id FROM ids WHERE label = 'rev'))), 'ERROR:42501:not_the_author', 'another editor cannot change the draft');
SELECT is(pg_temp.staff(:PUBLISHER::uuid, format($$SELECT staff.submit_revision(%L)$$, (SELECT id FROM ids WHERE label = 'rev'))), 'ERROR:42501:not_the_author', 'another editor cannot submit the draft');
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.submit_revision(%L)$$, (SELECT id FROM ids WHERE label = 'rev'))), 'ERROR:ED409:revision_has_no_source', 'a draft without a source cannot be submitted');

INSERT INTO ids VALUES ('source', pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_source('Source synthétique t103', NULL)$$)::uuid);
SELECT is((SELECT rights_status FROM app.content_sources WHERE id = (SELECT id FROM ids WHERE label = 'source')), 'unverified', 'a new source is unverified, whoever creates it');
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.attach_source(%L, %L)$$, (SELECT id FROM ids WHERE label = 'rev'), (SELECT id FROM ids WHERE label = 'source'))), '', 'the author attaches the source');
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.submit_revision(%L)$$, (SELECT id FROM ids WHERE label = 'rev'))), '', 'the author submits');
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.update_revision(%L, 'Tard', '[{"key":"a","type":"paragraph","text":"y"}]', '[]')$$, (SELECT id FROM ids WHERE label = 'rev'))), 'ERROR:ED409:revision_in_review', 'no edits while in the review queue');

-- triggers: uncleared source, author as reviewer
SELECT is(pg_temp.staff(:REVIEWER::uuid, format($$SELECT staff.review_revision(%L, 'approved', NULL)$$, (SELECT id FROM ids WHERE label = 'rev'))),
    'ERROR:P0001:Approval requires at least one source and all sources rights-cleared', 'TRIGGER: approval needs cleared sources');
SELECT is((SELECT count(*)::int FROM app.editorial_reviews WHERE lesson_revision_id = (SELECT id FROM ids WHERE label = 'rev')), 0, 'the refused approval left no review');
SELECT is(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.set_source_rights(%L, 'cleared', 'Synthetic.')$$, (SELECT id FROM ids WHERE label = 'source'))), '', 'the admin clears the rights');
INSERT INTO app.staff_roles (user_id, role) VALUES (:EDITOR, 'reviewer');
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.review_revision(%L, 'approved', NULL)$$, (SELECT id FROM ids WHERE label = 'rev'))),
    'ERROR:P0001:Author cannot review own lesson', 'TRIGGER: the author cannot review, even holding the reviewer role');
DELETE FROM app.staff_roles WHERE user_id = :EDITOR AND role = 'reviewer';

-- an unreviewed revision cannot be packed (trigger), and the refused build leaves nothing
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.build_pack('t103-pack', 'fr', ARRAY[%L]::uuid[])$$, (SELECT id FROM ids WHERE label = 'rev'))),
    'ERROR:P0001:Pack items must be approved and match pack locale', 'TRIGGER: an unreviewed revision cannot enter a pack');
SELECT is((SELECT count(*)::int FROM app.pack_releases WHERE pack_key = 't103-pack'), 0, 'no half-built release remains');

SELECT isnt(pg_temp.staff(:REVIEWER::uuid, format($$SELECT staff.review_revision(%L, 'approved', 'ok')$$, (SELECT id FROM ids WHERE label = 'rev'))), NULL, 'an independent reviewer approves');
SELECT is((SELECT row(status, approved_by, approved_at = now())::text FROM app.lesson_revisions WHERE id = (SELECT id FROM ids WHERE label = 'rev')),
    row('approved', 'a0000000-0000-4000-8000-000000000004'::uuid, true)::text, 'approved by the reviewer, at server time');
SELECT is(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.update_revision(%L, 'Tard', '[{"key":"a","type":"paragraph","text":"y"}]', '[]')$$, (SELECT id FROM ids WHERE label = 'rev'))),
    'ERROR:P0001:Approved/packed lesson revisions are immutable', 'TRIGGER: not even an admin edits an approved revision');
SELECT is(pg_temp.staff(:REVIEWER::uuid, format($$SELECT staff.review_revision(%L, 'rejected', NULL)$$, (SELECT id FROM ids WHERE label = 'rev'))), 'ERROR:ED409:revision_not_in_review', 'an approved revision is not reviewed again');

-- packs
INSERT INTO ids VALUES ('rel1', pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.build_pack('t103-pack', 'fr', ARRAY[%L]::uuid[])$$, (SELECT id FROM ids WHERE label = 'rev')))::uuid);
SELECT is((SELECT row(status, revision, created_by, octet_length(manifest_sha256), manifest_object_key)::text FROM app.pack_releases WHERE id = (SELECT id FROM ids WHERE label = 'rel1')),
    row('ready', 1, 'a0000000-0000-4000-8000-000000000003'::uuid, 32, 'packs/t103-pack/fr/1/manifest.json')::text, 'the release is built and finalised as ready');
SELECT is(pg_temp.staff(:PUBLISHER::uuid, format($$SELECT staff.rollback_pack(%L)$$, (SELECT id FROM ids WHERE label = 'rel1'))), 'ERROR:ED409:pack_release_not_retired', 'a ready release cannot be the target of a rollback');
SELECT is(pg_temp.staff(:PUBLISHER::uuid, format($$SELECT staff.release_pack(%L)::jsonb ->> 'previous_release_id'$$, (SELECT id FROM ids WHERE label = 'rel1'))), NULL, 'the publisher releases; there was no previous release');
SELECT is((SELECT release_id FROM app.pack_current WHERE pack_key = 't103-pack' AND locale = 'fr'), (SELECT id FROM ids WHERE label = 'rel1'), 'the current pointer moved');
SELECT is(pg_temp.staff(:PUBLISHER::uuid, format($$SELECT staff.release_pack(%L)$$, (SELECT id FROM ids WHERE label = 'rel1'))), 'ERROR:ED409:pack_release_not_ready', 'an active release is not released twice');

INSERT INTO ids VALUES ('rel2', pg_temp.staff(:PUBLISHER::uuid, format($$SELECT staff.build_pack('t103-pack', 'fr', ARRAY[%L]::uuid[])$$, (SELECT id FROM ids WHERE label = 'rev')))::uuid);
SELECT is((SELECT revision FROM app.pack_releases WHERE id = (SELECT id FROM ids WHERE label = 'rel2')), 2, 'release numbers count up per pack and language');
SELECT is(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.release_pack(%L)::jsonb ->> 'previous_release_id'$$, (SELECT id FROM ids WHERE label = 'rel2'))), (SELECT id::text FROM ids WHERE label = 'rel1'), 'the second release replaces the first');
SELECT is((SELECT array_agg(status ORDER BY revision) FROM app.pack_releases WHERE pack_key = 't103-pack'), ARRAY['retired','active'], 'the replaced release is retired');
SELECT is(pg_temp.staff(:PUBLISHER::uuid, format($$SELECT staff.rollback_pack(%L)::jsonb ->> 'previous_release_id'$$, (SELECT id FROM ids WHERE label = 'rel1'))), (SELECT id::text FROM ids WHERE label = 'rel2'), 'rollback to the first release');
SELECT is((SELECT array_agg(status ORDER BY revision) FROM app.pack_releases WHERE pack_key = 't103-pack'), ARRAY['active','retired'], 'the roles of the two releases are swapped');
SELECT is((SELECT release_id FROM app.pack_current WHERE pack_key = 't103-pack' AND locale = 'fr'), (SELECT id FROM ids WHERE label = 'rel1'), 'the pointer is back on the first release');

-- rights withdrawn after publication: nothing new can be released from it (trigger)
SELECT is(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.set_source_rights(%L, 'blocked', NULL)$$, (SELECT id FROM ids WHERE label = 'source'))), '', 'rights can be withdrawn later');
SELECT is(pg_temp.staff(:PUBLISHER::uuid, format($$SELECT staff.rollback_pack(%L)$$, (SELECT id FROM ids WHERE label = 'rel2'))),
    'ERROR:P0001:Pack includes content with uncleared rights', 'TRIGGER: a release with withdrawn rights cannot be activated again');
SELECT is((SELECT release_id FROM app.pack_current WHERE pack_key = 't103-pack' AND locale = 'fr'), (SELECT id FROM ids WHERE label = 'rel1'), 'the refused rollback changed nothing');

-- ---- audit: one event per successful action, attributed, no content -----------------------
SELECT is((SELECT array_agg(e.action ORDER BY e.action COLLATE "C") FROM (
               SELECT DISTINCT action FROM app.audit_events WHERE created_at = now()) AS e),
    ARRAY['content_source.create','content_source.set_rights','lesson.create','lesson_revision.attach_source',
          'lesson_revision.create','lesson_revision.review','lesson_revision.submit',
          'pack_release.build','pack_release.release','pack_release.rollback'],
    'every kind of successful action wrote an audit event (refused ones wrote none)');
SELECT is((SELECT (count(*) - (SELECT audit FROM counts))::int FROM app.audit_events), 13, 'exactly one event per successful write');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE created_at = now() AND actor_id IS NULL), 0, 'every event has an actor');
SELECT is((SELECT actor_id FROM app.audit_events WHERE created_at = now() AND action = 'lesson_revision.review'), :REVIEWER::uuid, 'the review is attributed to the reviewer');
SELECT is((SELECT details FROM app.audit_events WHERE created_at = now() AND action = 'pack_release.rollback'),
    jsonb_build_object('locale', 'fr', 'revision', 1, 'previous_release_id', (SELECT id FROM ids WHERE label = 'rel2')),
    'the rollback event names the release it replaced');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE created_at = now()
           AND (details::text LIKE '%Titre%' OR details::text LIKE '%Synth%')), 0, 'no title, text or note is copied into audit details');

-- ---- reading ----------------------------------------------------------------------------------
SELECT is(pg_temp.staff(:PUBLISHER::uuid, format($$SELECT staff.get_revision(%L)::jsonb #>> '{reviews,0,verdict}'$$, (SELECT id FROM ids WHERE label = 'rev'))), 'approved', 'any staff role reads a revision with its reviews');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT staff.get_revision(gen_random_uuid())$$), 'ERROR:ED404:revision_not_found', 'unknown revision');
SELECT is(pg_temp.staff(:EDITOR::uuid, $$SELECT jsonb_array_length(staff.list_revisions('approved', true, 1))$$), '1', 'list: mine + status + limit');
SELECT is(pg_temp.staff(:REVIEWER::uuid, $$SELECT jsonb_array_length(staff.list_revisions('approved', true, 200))$$), '0', 'list: mine is about the author');
SELECT is(pg_temp.staff(:REVIEWER::uuid, $$SELECT jsonb_array_length(staff.list_pack_releases('t103-pack', 'fr', 9999))$$), '2', 'list pack releases (limit is clamped, not an error)');
SELECT is(pg_temp.staff(:REVIEWER::uuid, $$SELECT staff.list_pack_releases('t103-pack', 'fr', 1) #>> '{0,is_current}'$$), 'false', 'the newest release is not the current one after the rollback');

SELECT * FROM finish();
ROLLBACK;
