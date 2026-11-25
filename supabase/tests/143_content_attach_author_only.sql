-- NF-2: only the author of a draft revision attaches or detaches its assets,
-- admins included. Statements run AS edu_staff with a verified actor.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
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

\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
\set EDITOR2 '''a0000000-0000-4000-8000-000000000243'''
\set ADMIN '''a0000000-0000-4000-8000-000000000143'''
\set REV '''c0000000-0000-4000-8000-000000002431'''
\set SRC '''e0000000-0000-4000-8000-000000000001'''

INSERT INTO auth.users (instance_id, id, aud, role, email)
SELECT '00000000-0000-0000-0000-000000000000', id, 'authenticated', 'authenticated', email FROM (VALUES
  (:EDITOR2::uuid, 'editor2.143@edupreneur.test'),
  (:ADMIN::uuid, 'admin.143@edupreneur.test')) AS u(id, email);
INSERT INTO app.staff_roles (user_id, role, is_active) VALUES
  (:EDITOR2, 'editor', true), (:ADMIN, 'admin', true);
-- The draft belongs to :EDITOR and cites the (cleared) seed source.
INSERT INTO app.lesson_revisions (id, lesson_id, revision, locale, title, blocks, created_by) VALUES
  (:REV, 'b0000000-0000-4000-8000-000000000005', 2431, 'fr', 'content fixture 2431',
   '[{"key":"p","type":"paragraph","text":"x"}]', :EDITOR);
INSERT INTO app.lesson_revision_sources VALUES (:REV, :SRC);

CREATE FUNCTION pg_temp.q_attach() RETURNS text LANGUAGE sql AS $fn$ SELECT $q$SELECT content.attach_asset('c0000000-0000-4000-8000-000000002431', sha256('img-143')) ->> 'attached'$q$::text $fn$;
CREATE FUNCTION pg_temp.q_detach() RETURNS text LANGUAGE sql AS $fn$ SELECT $q$SELECT content.detach_asset('c0000000-0000-4000-8000-000000002431', sha256('img-143')) ->> 'detached'$q$::text $fn$;

SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT content.register_asset(sha256('img-143'), 1200, 'image/png', 320, 180, NULL, '{"fr": "x"}', 'e0000000-0000-4000-8000-000000000001') ->> 'created'$$), 'true', 'fixture: asset registered');

-- Refused: another editor, an admin. Nothing is written.
SELECT is(left(pg_temp.as_role('edu_staff', :EDITOR2::uuid, pg_temp.q_attach()), 11), 'ERROR:42501', 'another editor cannot attach to the draft');
SELECT is(left(pg_temp.as_role('edu_staff', :ADMIN::uuid, pg_temp.q_attach()), 11), 'ERROR:42501', 'an admin cannot attach to someone else''s draft');
SELECT is((SELECT count(*)::int FROM content.revision_assets WHERE lesson_revision_id = :REV), 0, 'nothing was attached by the refused callers');

-- The author may.
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, pg_temp.q_attach()), 'true', 'the author attaches');
SELECT is((SELECT attached_by::text FROM content.revision_assets WHERE lesson_revision_id = :REV), 'a0000000-0000-4000-8000-000000000003', 'the link records the author');

-- Detach: same rule, and a refused caller leaves the link in place.
SELECT is(left(pg_temp.as_role('edu_staff', :EDITOR2::uuid, pg_temp.q_detach()), 11), 'ERROR:42501', 'another editor cannot detach');
SELECT is(left(pg_temp.as_role('edu_staff', :ADMIN::uuid, pg_temp.q_detach()), 11), 'ERROR:42501', 'an admin cannot detach from someone else''s draft');
SELECT is((SELECT count(*)::int FROM content.revision_assets WHERE lesson_revision_id = :REV), 1, 'the link is still there');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, pg_temp.q_detach()), 'true', 'the author detaches');
SELECT is(pg_temp.as_role('edu_staff', :EDITOR::uuid, pg_temp.q_attach()), 'true', 'the author can attach again');

-- An admin who is the author of a revision may (the rule is authorship, not role).
INSERT INTO app.lesson_revisions (id, lesson_id, revision, locale, title, blocks, created_by) VALUES
  ('c0000000-0000-4000-8000-000000002432', 'b0000000-0000-4000-8000-000000000005', 2432, 'fr', 'content fixture 2432',
   '[{"key":"p","type":"paragraph","text":"x"}]', :ADMIN);
INSERT INTO app.lesson_revision_sources VALUES ('c0000000-0000-4000-8000-000000002432', :SRC);
SELECT is(pg_temp.as_role('edu_staff', :ADMIN::uuid, $$SELECT content.attach_asset('c0000000-0000-4000-8000-000000002432', sha256('img-143')) ->> 'attached'$$), 'true', 'an admin attaches to their own draft');
SELECT is(left(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT content.attach_asset('c0000000-0000-4000-8000-000000002432', sha256('img-143')) ->> 'attached'$$), 11), 'ERROR:42501', 'an editor cannot attach to the admin''s draft');

-- Unknown revision and no actor stay refused; function properties unchanged.
SELECT is(left(pg_temp.as_role('edu_staff', :EDITOR::uuid, $$SELECT content.detach_asset(gen_random_uuid(), sha256('img-143'))$$), 11), 'ERROR:22023', 'detach: unknown revision is refused');
SELECT is(left(pg_temp.as_role('edu_staff', NULL, pg_temp.q_attach()), 11), 'ERROR:42501', 'no actor: refused');
SELECT is((SELECT array_agg(p.proname || ':' || pg_get_userbyid(p.proowner) || ':' || p.prosecdef::text || ':' || coalesce(p.proconfig::text, '') ORDER BY p.proname)
             FROM pg_proc p WHERE p.pronamespace = 'content'::regnamespace AND p.proname IN ('attach_asset', 'detach_asset')),
    ARRAY['attach_asset:postgres:true:{"search_path=pg_catalog, pg_temp"}', 'detach_asset:postgres:true:{"search_path=pg_catalog, pg_temp"}'],
    'owner postgres, SECURITY DEFINER, search_path pinned');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
            WHERE p.pronamespace = 'content'::regnamespace AND p.proname IN ('attach_asset', 'detach_asset')
              AND has_function_privilege('edu_staff', p.oid, 'EXECUTE') AND NOT has_function_privilege('edu_api', p.oid, 'EXECUTE')),
    ARRAY['attach_asset', 'detach_asset'], 'EXECUTE: edu_staff only');

SELECT * FROM finish();
ROLLBACK;
