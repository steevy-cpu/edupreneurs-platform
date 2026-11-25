-- Structure, privileges and exposure of the private `content` schema.
-- (The `app` schema is pinned by 010_structure.sql, which this lane leaves untouched.)
BEGIN;
SELECT * FROM no_plan();

-- ---- tables, keys, RLS -------------------------------------------------------
SELECT tables_are('content', ARRAY['assets', 'revision_assets', 'pack_manifests'],
    'the content schema holds exactly its three tables');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'content' AND c.relkind = 'r' AND NOT c.relrowsecurity), 0,
    'row-level security is enabled on every content table');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'content'), 0,
    'no policy exists: default deny for every role but the owner');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'content' AND c.relkind NOT IN ('r', 'i')), 0,
    'no view, sequence or other relation in content');
SELECT col_is_pk('content', 'assets', 'sha256', 'an asset is identified by its sha256');
SELECT col_type_is('content', 'assets', 'sha256', 'bytea', 'the hash is stored as bytes');
SELECT col_is_pk('content', 'revision_assets', ARRAY['lesson_revision_id', 'asset_sha256'],
    'one link per (revision, asset)');
SELECT col_is_pk('content', 'pack_manifests', 'pack_release_id', 'one recorded manifest per release');
SELECT col_is_unique('content', 'assets', 'object_key', 'one storage object per asset');
SELECT col_not_null('content', 'assets', 'source_id', 'every asset has a rights/source reference');
SELECT col_not_null('content', 'assets', 'created_by', 'every asset records who registered it');
SELECT col_not_null('content', 'assets', 'alt_text', 'every asset has alternative text');

SELECT fk_ok('content', 'assets', 'source_id', 'app', 'content_sources', 'id',
    'assets reference a recorded content source');
SELECT fk_ok('content', 'revision_assets', 'lesson_revision_id', 'app', 'lesson_revisions', 'id',
    'links reference a lesson revision');
SELECT fk_ok('content', 'revision_assets', ARRAY['asset_sha256', 'source_id'],
             'content', 'assets', ARRAY['sha256', 'source_id'],
    'rights gate, half 1: a link carries the source of its asset');
SELECT fk_ok('content', 'revision_assets', ARRAY['lesson_revision_id', 'source_id'],
             'app', 'lesson_revision_sources', ARRAY['lesson_revision_id', 'source_id'],
    'rights gate, half 2: that source must be cited by the revision');
SELECT fk_ok('content', 'pack_manifests', 'pack_release_id', 'app', 'pack_releases', 'id',
    'manifests reference a pack release');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'content'::regnamespace AND contype = 'f'), 8,
    '8 foreign keys exist in content');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'content'::regnamespace AND contype = 'f' AND confdeltype <> 'r'), 0,
    'every foreign key is ON DELETE RESTRICT (nothing cascades into or out of content)');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'content'::regnamespace AND contype = 'f'
             AND confrelid = 'auth.users'::regclass), 3,
    'three references to auth.users (staff authorship), none cascading');

SELECT has_index('content', 'assets', 'idx_assets_source', 'FK index on assets.source_id');
SELECT has_index('content', 'revision_assets', 'idx_revision_assets_asset', 'FK index on the asset side');
SELECT has_index('content', 'revision_assets', 'idx_revision_assets_citation', 'FK index on the citation side');

SELECT is((SELECT count(*)::int FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
           WHERE c.relnamespace = 'content'::regnamespace AND NOT t.tgisinternal), 3,
    '3 integrity triggers are installed in content');

-- ---- nothing of this lane lives in `app` -----------------------------------------
SELECT is((SELECT count(*)::int FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
           JOIN pg_proc p ON p.oid = t.tgfoid
           WHERE c.relnamespace = 'app'::regnamespace AND NOT t.tgisinternal
             AND p.pronamespace = 'content'::regnamespace), 0,
    'no trigger on an app table calls a content function');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'app'
           AND (qual LIKE '%content.%' OR with_check LIKE '%content.%')), 0,
    'no app policy depends on the content schema');

-- ---- privileges: explicit grants ---------------------------------------------------
SELECT is((SELECT array_agg(pg_get_userbyid(a.grantee)::text || ':' || a.privilege_type ORDER BY pg_get_userbyid(a.grantee)::text || ':' || a.privilege_type)
           FROM pg_namespace n, aclexplode(n.nspacl) a WHERE n.nspname = 'content'),
    ARRAY['edu_staff:USAGE', 'postgres:CREATE', 'postgres:USAGE'],
    'besides the owner, only edu_staff may use schema content (USAGE, not CREATE)');
SELECT is((SELECT count(*)::int FROM pg_class c, aclexplode(c.relacl) a
           WHERE c.relnamespace = 'content'::regnamespace
             AND pg_get_userbyid(a.grantee) <> 'postgres'), 0,
    'no table privilege in content is granted to anyone but the owner');
SELECT is((SELECT array_agg(p.proname::text || ':' || pg_get_userbyid(a.grantee) ORDER BY p.proname)
           FROM pg_proc p, aclexplode(p.proacl) a
           WHERE p.pronamespace = 'content'::regnamespace
             AND (a.grantee = 0 OR pg_get_userbyid(a.grantee) <> 'postgres')),
    ARRAY['attach_asset:edu_staff', 'detach_asset:edu_staff', 'record_release_manifest:edu_staff', 'register_asset:edu_staff'],
    'the only EXECUTE grants beyond the owner: the four staff write functions, to edu_staff');
SELECT is((SELECT count(*)::int FROM pg_proc p
           WHERE p.pronamespace = 'content'::regnamespace AND p.proacl IS NULL), 0,
    'every content function has an explicit ACL (the PUBLIC default was revoked)');
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'content'
             AND grantee <> 'postgres'), 0,
    'nobody but the owner holds a table privilege in content (edu_staff and edu_worker included)');
SELECT is((SELECT count(*)::int FROM information_schema.column_privileges
           WHERE table_schema = 'content' AND grantee <> 'postgres'), 0,
    'no column-level privilege in content either');

SELECT is(has_schema_privilege('anon', 'content', 'USAGE'), false, 'anon cannot use schema content');
SELECT is(has_schema_privilege('authenticated', 'content', 'USAGE'), false, 'authenticated cannot use schema content');
SELECT is(has_schema_privilege('authenticator', 'content', 'USAGE'), false, 'authenticator (Data API) cannot use schema content');
SELECT is(has_schema_privilege('service_role', 'content', 'USAGE'), false, 'service_role cannot use schema content');
SELECT is(has_schema_privilege('edu_api', 'content', 'USAGE'), false, 'the student API role cannot use schema content');
SELECT is(has_schema_privilege('edu_worker', 'content', 'USAGE'), false, 'the worker role cannot use schema content');
SELECT is(has_schema_privilege('edu_staff', 'content', 'CREATE'), false, 'the staff role cannot create objects in content');
SELECT is(has_schema_privilege('edu_api', 'content', 'CREATE'), false, 'the student API role cannot create objects in content');

-- ---- functions ------------------------------------------------------------------
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'content'::regnamespace),
    ARRAY['asset_object_key', 'attach_asset', 'audit', 'block_asset_hashes', 'blocks_required_format',
          'detach_asset', 'guard_pack_manifest', 'guard_revision_asset', 'is_locale_text_map',
          'protect_asset', 'record_release_manifest', 'register_asset', 'release_required_format',
          'revision_required_format', 'staff_gate'],
    'the content functions are the intended fifteen');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'content'::regnamespace
           AND (has_function_privilege('public', p.oid, 'EXECUTE')
             OR has_function_privilege('anon', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticated', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticator', p.oid, 'EXECUTE')
             OR has_function_privilege('service_role', p.oid, 'EXECUTE')
             OR has_function_privilege('edu_worker', p.oid, 'EXECUTE')
             OR has_function_privilege('edu_api', p.oid, 'EXECUTE'))), 0,
    'no content function is executable by PUBLIC, the Data API roles, the worker role or the student API role');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'content'::regnamespace
           AND p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']), 0,
    'every content function pins exactly search_path = pg_catalog, pg_temp (ruling R-03)');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'content'::regnamespace
           AND pg_get_userbyid(p.proowner) <> 'postgres'), 0,
    'every content function is owned by the migration owner (postgres)');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'content'::regnamespace AND p.prosecdef),
    ARRAY['attach_asset', 'detach_asset', 'guard_pack_manifest', 'guard_revision_asset', 'protect_asset',
          'record_release_manifest', 'register_asset', 'release_required_format', 'revision_required_format'],
    'SECURITY DEFINER is used only by the guards, the two read helpers and the four staff write functions');
-- The staff seam: exactly two functions mention the staff lane's schemas.
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'content'::regnamespace AND (p.prosrc ~ '\mstaff\.' OR p.prosrc ~ '\mops\.')),
    ARRAY['audit', 'staff_gate'], 'only the two seam functions reference the staff lane (staff.*, ops.*)');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'content'::regnamespace
           AND p.prosrc ~* '\mexecute\M'), 0, 'no content function uses dynamic SQL');

-- ---- the student API role cannot reach anything here ------------------------------
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
\set A '''a0000000-0000-4000-8000-000000000001'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM content.assets'), 'ERROR:42501', 'student API: cannot read assets');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM content.revision_assets'), 'ERROR:42501', 'student API: cannot read asset links');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM content.pack_manifests'), 'ERROR:42501', 'student API: cannot read recorded manifests');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO content.assets (sha256, object_key, bytes, mime, width, height, alt_text, source_id, created_by) VALUES (sha256('x'), content.asset_object_key(sha256('x')), 1, 'image/png', 1, 1, '{"fr":"x"}', 'e0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000001') RETURNING 1$$), 'ERROR:42501', 'student API: cannot insert an asset');
SELECT is(pg_temp.as_api(:A::uuid, 'DELETE FROM content.revision_assets RETURNING 1'), 'ERROR:42501', 'student API: cannot delete asset links');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT content.register_asset(sha256('x'), 1, 'image/png', 1, 1, NULL, '{"fr":"x"}', 'e0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'student API: cannot call the asset registration function');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$SELECT content.register_asset(sha256('x'), 1, 'image/png', 1, 1, NULL, '{"fr":"x"}', 'e0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'student API: not even with a staff user''s identity');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$SELECT content.attach_asset('c0000000-0000-4000-8000-000000000001', sha256('x'))$$), 'ERROR:42501', 'student API: cannot attach assets');
SELECT is(pg_temp.as_api(:EDITOR::uuid, $$SELECT content.record_release_manifest('f0000000-0000-4000-8000-000000000001', '{}', sha256('x'), 1)$$), 'ERROR:42501', 'student API: cannot record a manifest');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT content.staff_gate('editor')$$), 'ERROR:42501', 'student API: cannot call the staff seam');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT content.revision_required_format('c0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'student API: cannot call the read helpers');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT content.blocks_required_format('[]')$$), 'ERROR:42501', 'student API: cannot call even the pure helpers');
-- ... and what the student API could do before, it still can.
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM app.lesson_revisions WHERE id = $$c0000000-0000-4000-8000-000000000001$$'), '1', 'student API still reads the published seed lesson');

-- ---- Supabase Data API roles cannot reach the schema at all -------------------
SET LOCAL ROLE anon;
SELECT throws_ok('SELECT count(*) FROM content.assets', '42501', NULL, 'anon: schema content is unreachable');
SELECT throws_ok($$SELECT content.asset_object_key(sha256('x'))$$, '42501', NULL, 'anon: cannot call content functions');
RESET ROLE;
SET LOCAL ROLE authenticated;
SELECT throws_ok('SELECT count(*) FROM content.assets', '42501', NULL, 'authenticated (Data API): schema content is unreachable');
SELECT throws_ok('SELECT count(*) FROM content.pack_manifests', '42501', NULL, 'authenticated (Data API): cannot read manifests');
RESET ROLE;
SET LOCAL ROLE service_role;
SELECT throws_ok('SELECT count(*) FROM content.assets', '42501', NULL, 'service_role: schema content is unreachable (despite BYPASSRLS)');
SELECT throws_ok($$SELECT content.register_asset(sha256('x'), 1, 'image/png', 1, 1, NULL, '{"fr":"x"}', 'e0000000-0000-4000-8000-000000000001')$$, '42501', NULL, 'service_role: cannot call the staff write functions');
RESET ROLE;

SELECT * FROM finish();
ROLLBACK;
