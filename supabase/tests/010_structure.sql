-- Structure, privileges and exposure of the private `app` schema.
BEGIN;
SELECT * FROM no_plan();

-- ---- tables, keys, RLS -------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_tables WHERE schemaname = 'app'), 26,
    'exactly 26 application tables');
SELECT tables_are('app', ARRAY[
    'learner_profiles','staff_roles','grades','subjects','courses','units','lessons',
    'lesson_revisions','question_revisions','content_sources','lesson_revision_sources',
    'editorial_reviews','pack_releases','pack_items','pack_current','lesson_progress',
    'practice_attempts','account_sync_state','sync_receipts','account_change_feed',
    'background_jobs','audit_events',
    'exams','exam_questions','exam_attempts','exam_answers'], 'the 26 tables are the intended ones');

SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'app' AND c.relkind = 'r' AND NOT c.relrowsecurity), 0,
    'row-level security is enabled on every app table');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'app' AND c.relkind = 'r'
             AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p')), 0,
    'every app table has a primary key');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'app'::regnamespace AND contype = 'f'), 38,
    '38 foreign keys exist');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'app'::regnamespace AND contype = 'f'
             AND confrelid = 'auth.users'::regclass AND confdeltype NOT IN ('r','n')), 0,
    'no foreign key to auth.users cascades a delete');

SELECT col_is_pk('app', 'sync_receipts', ARRAY['learner_id','op_id'], 'receipts keyed by (learner, op_id)');
SELECT col_is_pk('app', 'account_change_feed', ARRAY['learner_id','version'], 'feed keyed by (learner, version)');
SELECT col_is_pk('app', 'lesson_progress', ARRAY['learner_id','lesson_id'], 'progress keyed by (learner, lesson)');
SELECT col_is_unique('app', 'practice_attempts', ARRAY['learner_id','op_id'], 'one attempt per (learner, op_id)');
SELECT col_is_unique('app', 'lesson_revisions', ARRAY['lesson_id','locale','revision'], 'revision numbers unique per lesson+locale');
SELECT col_not_null('app', 'lesson_revisions', 'created_by', 'lesson revisions always have an author');
SELECT fk_ok('app', 'learner_profiles', 'user_id', 'auth', 'users', 'id', 'profiles reference auth.users');
SELECT fk_ok('app', 'practice_attempts', ARRAY['question_revision_id','lesson_revision_id'],
             'app', 'question_revisions', ARRAY['id','lesson_revision_id'], 'attempt question belongs to attempt lesson revision');
SELECT fk_ok('app', 'pack_current', ARRAY['release_id','pack_key','locale'],
             'app', 'pack_releases', ARRAY['id','pack_key','locale'], 'current pointer matches release key+locale');

SELECT has_index('app', 'practice_attempts', 'idx_attempts_learner_time', 'attempt history index');
SELECT has_index('app', 'lesson_revisions', 'idx_lesson_revs_published', 'published revision index');
SELECT has_index('app', 'lesson_progress', 'idx_progress_lesson', 'FK index on lesson_progress.lesson_id');
SELECT has_index('app', 'editorial_reviews', 'idx_reviews_reviewer', 'FK index on editorial_reviews.reviewer_id');

-- ---- the API role ---------------------------------------------------------------
SELECT has_role('edu_api');
SELECT is((SELECT rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication
           FROM pg_roles WHERE rolname = 'edu_api'), false,
    'edu_api cannot log in and has no admin attribute or BYPASSRLS');
SELECT is((SELECT count(*)::int FROM pg_auth_members m JOIN pg_roles u ON u.oid = m.member
           WHERE u.rolname = 'edu_api'), 0, 'edu_api is not a member of any other role');

-- ---- policies -----------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'app'), 21, '21 policies exist');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'app' AND roles <> ARRAY['edu_api']::name[]), 0,
    'every policy applies to edu_api only (none to public, anon or authenticated)');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'app' AND cmd NOT IN ('SELECT','INSERT')), 0,
    'no policy allows UPDATE or DELETE');
SELECT is((SELECT array_agg(tablename::text ORDER BY tablename) FROM pg_policies WHERE schemaname = 'app' AND cmd = 'INSERT'),
    ARRAY['learner_profiles'], 'the only INSERT policy is "create my own profile"');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'app'
           AND tablename IN ('staff_roles','content_sources','lesson_revision_sources','editorial_reviews','background_jobs','audit_events')), 0,
    'staff, provenance, job and audit tables have no policy at all (deny everything)');

-- ---- table privileges --------------------------------------------------------
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'app' AND grantee IN ('PUBLIC','anon','authenticated','authenticator')), 0,
    'PUBLIC / anon / authenticated / authenticator hold no table privilege in app');
SELECT is(has_schema_privilege('anon', 'app', 'USAGE'), false, 'anon cannot use schema app');
SELECT is(has_schema_privilege('authenticated', 'app', 'USAGE'), false, 'authenticated cannot use schema app');
SELECT is(has_schema_privilege('authenticator', 'app', 'USAGE'), false, 'authenticator (Data API) cannot use schema app');
SELECT is(has_schema_privilege('edu_api', 'app', 'CREATE'), false, 'edu_api cannot create objects in app');
SELECT is(has_schema_privilege('edu_api', 'public', 'CREATE'), false, 'edu_api cannot create objects in public');
SELECT is(has_schema_privilege('edu_api', 'auth', 'USAGE'), false, 'edu_api cannot reach the auth schema');

SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'app' AND grantee = 'edu_api' AND privilege_type <> 'SELECT'), 0,
    'edu_api has no table-level INSERT/UPDATE/DELETE/TRUNCATE anywhere');
SELECT is((SELECT array_agg(table_name || '.' || column_name || ':' || privilege_type ORDER BY 1)
           FROM information_schema.column_privileges
           WHERE table_schema = 'app' AND grantee = 'edu_api' AND privilege_type <> 'SELECT'),
    ARRAY['learner_profiles.user_id:INSERT'],
    'the single write privilege of edu_api is INSERT(user_id) on learner_profiles');
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'app' AND grantee = 'edu_api'
             AND table_name IN ('staff_roles','content_sources','lesson_revision_sources','editorial_reviews','background_jobs','audit_events')), 0,
    'edu_api has no privilege on staff, provenance, job or audit tables');

-- ---- functions ------------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'app'::regnamespace
           AND (has_function_privilege('public', p.oid, 'EXECUTE')
             OR has_function_privilege('anon', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticated', p.oid, 'EXECUTE'))), 0,
    'no app function is executable by PUBLIC, anon or authenticated');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'app'::regnamespace AND has_function_privilege('edu_api', p.oid, 'EXECUTE')),
    ARRAY['current_actor_id','exam_attempt_review','exam_finish_attempt','exam_start_attempt',
          'exam_submit_answer','sync_apply_operation'],
    'edu_api may execute exactly the actor function, the sync function and the four exam functions');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'app'::regnamespace
           AND NOT COALESCE(p.proconfig @> ARRAY['search_path=""'], false)), 0,
    'every app function pins an empty search_path');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'app'::regnamespace
           AND p.prosecdef AND pg_get_userbyid(p.proowner) <> 'postgres'), 0,
    'SECURITY DEFINER functions are owned by the migration owner (postgres)');
SELECT is((SELECT count(*)::int FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
           WHERE c.relnamespace = 'app'::regnamespace AND NOT t.tgisinternal), 18,
    '18 integrity triggers are installed');

SELECT * FROM finish();
ROLLBACK;
