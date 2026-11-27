-- Review fixes of B2 (migration 20261124010600): only the author touches a
-- draft — an admin does not (M-B2-1) — and a pack holds one revision per
-- lesson (L-B2-2).
BEGIN;
SELECT * FROM no_plan();

GRANT edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
-- Returns the first column as text, or 'ERROR:<sqlstate>:<message>'.
CREATE FUNCTION pg_temp.staff(p_actor uuid, p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    PERFORM set_config('edu.actor_id', COALESCE(p_actor::text, ''), true);
    SET LOCAL ROLE edu_staff;
    BEGIN
        EXECUTE p_sql INTO v_out;
    EXCEPTION WHEN OTHERS THEN
        v_out := 'ERROR:' || SQLSTATE || ':' || SQLERRM;
    END;
    RESET ROLE;
    PERFORM set_config('edu.actor_id', '', true);
    RETURN v_out;
END;
$fn$;

\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
\set REVIEWER '''a0000000-0000-4000-8000-000000000004'''
\set ADMIN '''a0000000-0000-4000-8000-0000000000d1'''
\set ADMINEDITOR '''a0000000-0000-4000-8000-0000000000d2'''
\set BLOCKS '''[{"key":"a","type":"paragraph","text":"x"}]'''
\set ADMINBLOCKS '''[{"key":"a","type":"paragraph","text":"words of the admin"}]'''

-- synthetic staff for this test only (rolled back): one person holding ONLY
-- admin, and one holding every role.
INSERT INTO auth.users (instance_id, id, aud, role, email) VALUES
    ('00000000-0000-0000-0000-000000000000', :ADMIN, 'authenticated', 'authenticated', 'admin.t106@edupreneur.test'),
    ('00000000-0000-0000-0000-000000000000', :ADMINEDITOR, 'authenticated', 'authenticated', 'all.t106@edupreneur.test');
INSERT INTO app.staff_roles (user_id, role) VALUES
    (:ADMIN, 'admin'),
    (:ADMINEDITOR, 'admin'), (:ADMINEDITOR, 'editor'), (:ADMINEDITOR, 'reviewer'), (:ADMINEDITOR, 'publisher');

CREATE TEMP TABLE ids (label text PRIMARY KEY, id uuid);
GRANT SELECT ON ids TO edu_staff;
CREATE FUNCTION pg_temp.id(p_label text) RETURNS uuid LANGUAGE sql AS
$$ SELECT id FROM ids WHERE label = p_label $$;

-- ---- the functions keep their shape ----------------------------------------------------
SELECT is((SELECT row(p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner))::text FROM pg_proc p
           WHERE p.oid = 'staff.require_author(app.lesson_revisions, uuid)'::regprocedure),
    row(false, ARRAY['search_path=pg_catalog, pg_temp'], 'postgres')::text,
    'require_author: internal helper, pinned search_path, owned by postgres');
SELECT ok(NOT has_function_privilege('edu_staff', 'staff.require_author(app.lesson_revisions, uuid)', 'EXECUTE'),
    'require_author is not callable by edu_staff');
SELECT is((SELECT row(p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner))::text FROM pg_proc p
           WHERE p.oid = 'staff.build_pack(text, text, uuid[])'::regprocedure),
    row(true, ARRAY['search_path=pg_catalog, pg_temp'], 'postgres')::text,
    'build_pack: SECURITY DEFINER, pinned search_path, owned by postgres');
SELECT ok(has_function_privilege('edu_staff', 'staff.build_pack(text, text, uuid[])', 'EXECUTE'),
    'build_pack is still callable by edu_staff');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'staff'::regnamespace
           AND (has_function_privilege('edu_api', p.oid, 'EXECUTE') OR has_function_privilege('anon', p.oid, 'EXECUTE')
                OR has_function_privilege('authenticated', p.oid, 'EXECUTE'))), 0,
    'nothing in staff became callable by edu_api, anon or authenticated');
SELECT is(pg_get_functiondef('staff.require_author(app.lesson_revisions, uuid)'::regprocedure) ~* 'staff_roles|admin', false,
    'require_author looks at no role at all');

-- ---- M-B2-1: an admin does not touch another author's draft -----------------------------
INSERT INTO ids VALUES ('lesson', pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_lesson('b0000000-0000-4000-8000-000000000004', 't106-lesson')$$)::uuid);
INSERT INTO ids VALUES ('rev', pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.create_revision(%L, 'fr', 'Titre editeur', %L, '[]')$$, pg_temp.id('lesson'), :BLOCKS))::uuid);
INSERT INTO ids VALUES ('source', pg_temp.staff(:ADMIN::uuid, $$SELECT staff.create_source('Source t106', NULL)$$)::uuid);
SELECT is(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.set_source_rights(%L, 'cleared', 'Synthetic.')$$, pg_temp.id('source'))), '', 'the admin clears the rights of a source');
INSERT INTO ids VALUES ('own_source', pg_temp.staff(:EDITOR::uuid, $$SELECT staff.create_source('Source editeur t106', NULL)$$)::uuid);
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.attach_source(%L, %L)$$, pg_temp.id('rev'), pg_temp.id('own_source'))), '', 'the author attaches a source of their own');
CREATE TEMP TABLE audit_before AS SELECT count(*) AS n FROM app.audit_events;

SELECT is(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.update_revision(%L, 'Titre admin', %L, '[]')$$, pg_temp.id('rev'), :ADMINBLOCKS)),
    'ERROR:42501:not_the_author', 'an admin cannot change another author''s draft');
SELECT is(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.attach_source(%L, %L)$$, pg_temp.id('rev'), pg_temp.id('source'))),
    'ERROR:42501:not_the_author', 'an admin cannot attach a source to another author''s draft');
SELECT is(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.detach_source(%L, %L)$$, pg_temp.id('rev'), pg_temp.id('own_source'))),
    'ERROR:42501:not_the_author', 'an admin cannot detach a source from another author''s draft');
SELECT is(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.submit_revision(%L)$$, pg_temp.id('rev'))),
    'ERROR:42501:not_the_author', 'an admin cannot submit another author''s draft');
SELECT is(pg_temp.staff(:ADMINEDITOR::uuid, format($$SELECT staff.update_revision(%L, 'Titre admin', %L, '[]')$$, pg_temp.id('rev'), :ADMINBLOCKS)),
    'ERROR:42501:not_the_author', 'holding every role does not help either');
SELECT is(pg_temp.staff(:ADMINEDITOR::uuid, format($$SELECT staff.submit_revision(%L)$$, pg_temp.id('rev'))),
    'ERROR:42501:not_the_author', 'every role: cannot submit another author''s draft');
SELECT is((SELECT row(status, title, blocks, created_by)::text FROM app.lesson_revisions WHERE id = pg_temp.id('rev')),
    row('draft', 'Titre editeur', :BLOCKS::jsonb, :EDITOR::uuid)::text, 'the draft is exactly as its author left it');
SELECT is((SELECT array_agg(source_id) FROM app.lesson_revision_sources WHERE lesson_revision_id = pg_temp.id('rev')),
    ARRAY[pg_temp.id('own_source')], 'its sources are exactly those the author attached');
SELECT is((SELECT count(*) FROM app.audit_events), (SELECT n FROM audit_before), 'the refused calls wrote no audit event of success');

-- the sequence of the finding cannot release anything: draft not submitted => no review, no pack
SELECT is(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.review_revision(%L, 'approved', NULL)$$, pg_temp.id('rev'))),
    'ERROR:ED409:revision_not_in_review', 'the admin cannot approve the draft they could not submit');
SELECT is(left(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.build_pack('t106-pack', 'fr', ARRAY[%L]::uuid[])$$, pg_temp.id('rev'))), 12),
    'ERROR:P0001:', 'TRIGGER: the unreviewed draft cannot enter a pack');
SELECT is((SELECT count(*)::int FROM app.pack_releases WHERE pack_key = 't106-pack'), 0, 'nothing was built');
SELECT is((SELECT count(*)::int FROM app.editorial_reviews WHERE lesson_revision_id = pg_temp.id('rev')), 0, 'nothing was reviewed');

-- the author still does all of it
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.update_revision(%L, 'Titre editeur 2', %L, '[]')$$, pg_temp.id('rev'), :BLOCKS)), '', 'the author changes the draft');
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.detach_source(%L, %L)$$, pg_temp.id('rev'), pg_temp.id('own_source'))), '', 'the author detaches a source');
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.attach_source(%L, %L)$$, pg_temp.id('rev'), pg_temp.id('source'))), '', 'the author attaches the cleared source');
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.submit_revision(%L)$$, pg_temp.id('rev'))), '', 'the author submits');
SELECT isnt(left(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.review_revision(%L, 'approved', NULL)$$, pg_temp.id('rev'))), 6), 'ERROR:',
    'an admin may approve words that are entirely the author''s');
SELECT is((SELECT row(status, title, created_by, approved_by)::text FROM app.lesson_revisions WHERE id = pg_temp.id('rev')),
    row('approved', 'Titre editeur 2', :EDITOR::uuid, :ADMIN::uuid)::text, 'approved: author and reviewer are two people, the text is the author''s');

-- ---- an admin who IS the author cannot approve their own revision -----------------------
INSERT INTO ids VALUES ('lesson2', pg_temp.staff(:ADMINEDITOR::uuid, $$SELECT staff.create_lesson('b0000000-0000-4000-8000-000000000004', 't106-lesson-2')$$)::uuid);
INSERT INTO ids VALUES ('own', pg_temp.staff(:ADMINEDITOR::uuid, format($$SELECT staff.create_revision(%L, 'fr', 'Titre admin', %L, '[]')$$, pg_temp.id('lesson2'), :ADMINBLOCKS))::uuid);
SELECT is(pg_temp.staff(:ADMINEDITOR::uuid, format($$SELECT staff.update_revision(%L, 'Titre admin 2', %L, '[]')$$, pg_temp.id('own'), :ADMINBLOCKS)), '', 'an admin who is the author edits their own draft');
SELECT is(pg_temp.staff(:ADMINEDITOR::uuid, format($$SELECT staff.attach_source(%L, %L)$$, pg_temp.id('own'), pg_temp.id('source'))), '', '… attaches a source');
SELECT is(pg_temp.staff(:ADMINEDITOR::uuid, format($$SELECT staff.submit_revision(%L)$$, pg_temp.id('own'))), '', '… and submits it');
SELECT is(pg_temp.staff(:ADMINEDITOR::uuid, format($$SELECT staff.review_revision(%L, 'approved', NULL)$$, pg_temp.id('own'))),
    'ERROR:P0001:Author cannot review own lesson', 'TRIGGER: … but cannot approve it, whatever roles they hold');
SELECT is(left(pg_temp.staff(:ADMINEDITOR::uuid, format($$SELECT staff.build_pack('t106-pack', 'fr', ARRAY[%L]::uuid[])$$, pg_temp.id('own'))), 12),
    'ERROR:P0001:', 'TRIGGER: and cannot pack it unreviewed');
SELECT is((SELECT row(status, approved_by)::text FROM app.lesson_revisions WHERE id = pg_temp.id('own')),
    row('in_review', NULL::uuid)::text, 'their own revision is still waiting for somebody else');

-- ---- L-B2-2: one revision per lesson in a pack --------------------------------------------
INSERT INTO ids VALUES ('rev_b', pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.create_revision(%L, 'fr', 'Titre editeur 3', %L, '[]')$$, pg_temp.id('lesson'), :BLOCKS))::uuid);
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.attach_source(%L, %L)$$, pg_temp.id('rev_b'), pg_temp.id('source'))), '', 'second revision of the same lesson: source');
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.submit_revision(%L)$$, pg_temp.id('rev_b'))), '', 'second revision: submitted');
SELECT isnt(left(pg_temp.staff(:REVIEWER::uuid, format($$SELECT staff.review_revision(%L, 'approved', NULL)$$, pg_temp.id('rev_b'))), 6), 'ERROR:', 'second revision: approved');
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.build_pack('t106-pack', 'fr', ARRAY[%L, %L]::uuid[])$$, pg_temp.id('rev'), pg_temp.id('rev_b'))),
    'ERROR:ED422:pack_lesson_duplicated', 'two revisions of one lesson are refused (older, newer)');
SELECT is(pg_temp.staff(:ADMIN::uuid, format($$SELECT staff.build_pack('t106-pack', 'fr', ARRAY[%L, %L]::uuid[])$$, pg_temp.id('rev_b'), pg_temp.id('rev'))),
    'ERROR:ED422:pack_lesson_duplicated', 'two revisions of one lesson are refused (newer, older)');
SELECT is(pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.build_pack('t106-pack', 'fr', ARRAY[%L, %L]::uuid[])$$, pg_temp.id('rev'), pg_temp.id('rev'))),
    'ERROR:ED422:pack_items_duplicated', 'the same revision twice keeps its own error');
SELECT is((SELECT count(*)::int FROM app.pack_releases WHERE pack_key = 't106-pack'), 0, 'the refused builds left no release');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE action = 'pack_release.build' AND created_at = now()), 0, 'and no audit event of a build');
INSERT INTO ids VALUES ('rel', pg_temp.staff(:EDITOR::uuid, format($$SELECT staff.build_pack('t106-pack', 'fr', ARRAY[%L]::uuid[])$$, pg_temp.id('rev_b')))::uuid);
SELECT is((SELECT row(status, revision)::text FROM app.pack_releases WHERE id = pg_temp.id('rel')), row('ready', 1)::text,
    'one revision of the lesson builds as before');
SELECT is((SELECT details FROM app.audit_events WHERE action = 'pack_release.build' AND target_id = pg_temp.id('rel')),
    jsonb_build_object('locale', 'fr', 'revision', 1, 'items', 1), 'with the same audit event as before');

SELECT * FROM finish();
ROLLBACK;
