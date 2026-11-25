-- Structure, privileges and exposure of the private `account` schema
-- (identity lane, slices 1 and 2).
BEGIN;
SELECT * FROM no_plan();

-- ---- the schema is private ------------------------------------------------------
SELECT has_schema('account');
SELECT is(has_schema_privilege('anon', 'account', 'USAGE'), false, 'anon cannot use schema account');
SELECT is(has_schema_privilege('authenticated', 'account', 'USAGE'), false, 'authenticated cannot use schema account');
SELECT is(has_schema_privilege('authenticator', 'account', 'USAGE'), false, 'authenticator (Data API) cannot use schema account');
SELECT is(has_schema_privilege('service_role', 'account', 'USAGE'), false, 'service_role cannot use schema account');
SELECT is(has_schema_privilege('edu_api', 'account', 'USAGE'), true, 'edu_api can use schema account');
SELECT is(has_schema_privilege('edu_api', 'account', 'CREATE'), false, 'edu_api cannot create objects in account');
SELECT is((SELECT count(*)::int FROM pg_namespace n, aclexplode(n.nspacl) a
           WHERE n.nspname = 'account' AND a.grantee = 0), 0,
    'PUBLIC holds nothing on schema account');
SELECT is(current_setting('pgrst.db_schemas', true) IS NULL
          OR current_setting('pgrst.db_schemas', true) !~ '(^|,)\s*account\s*(,|$)', true,
    'account is not configured as a Data API schema in this session');

-- ---- tables ---------------------------------------------------------------------
SELECT has_table('account', 'onboarding_state', 'onboarding_state exists');
SELECT col_is_pk('account', 'onboarding_state', 'user_id', 'one onboarding row per learner');
SELECT fk_ok('account', 'onboarding_state', 'user_id', 'auth', 'users', 'id', 'onboarding rows reference auth.users');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'account' AND c.relkind = 'r' AND NOT c.relrowsecurity), 0,
    'row-level security is enabled on every account table');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'account' AND c.relkind = 'r'
             AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p')), 0,
    'every account table has a primary key');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'account'::regnamespace AND contype = 'f'
             AND confdeltype NOT IN ('r', 'a')), 0,
    'no account foreign key cascades or nulls on delete');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'account'::regnamespace AND contype = 'f'
             AND confrelid IN (SELECT c.oid FROM pg_class c WHERE c.relnamespace = 'app'::regnamespace)), 0,
    'no account foreign key points into schema app (so nothing, not even a system trigger, is added there)');
SELECT is((SELECT count(*)::int FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
           WHERE c.relnamespace = 'app'::regnamespace AND t.tgisinternal
             AND t.tgconstrrelid IN (SELECT c2.oid FROM pg_class c2 WHERE c2.relnamespace = 'account'::regnamespace)), 0,
    'no system trigger on an app table belongs to an account constraint');

-- Ruling R-02: the baseline suites TRUNCATE these five tables without CASCADE.
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'account'::regnamespace AND contype = 'f'
             AND confrelid IN ('app.practice_attempts'::regclass, 'app.sync_receipts'::regclass,
                               'app.account_change_feed'::regclass, 'app.lesson_progress'::regclass,
                               'app.account_sync_state'::regclass)), 0,
    'no account foreign key references one of the five learning tables');

-- ---- policies -------------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'account' AND roles <> ARRAY['edu_api']::name[]), 0,
    'every account policy applies to edu_api only');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'account' AND cmd <> 'SELECT'), 0,
    'account policies are read-only: every write goes through a function');
SELECT policies_are('account', 'onboarding_state', ARRAY['onboarding_select_own'], 'onboarding has exactly the own-row read policy');

-- ---- table privileges -----------------------------------------------------------
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'account' AND grantee IN ('PUBLIC', 'anon', 'authenticated', 'authenticator', 'service_role')), 0,
    'PUBLIC / anon / authenticated / authenticator / service_role hold no table privilege in account');
SELECT is((SELECT count(*)::int FROM information_schema.column_privileges
           WHERE table_schema = 'account' AND grantee IN ('PUBLIC', 'anon', 'authenticated', 'authenticator', 'service_role')), 0,
    'nor any column privilege');
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'account' AND grantee = 'edu_api' AND privilege_type <> 'SELECT'), 0,
    'edu_api has no INSERT/UPDATE/DELETE/TRUNCATE on any account table');
SELECT is((SELECT count(*)::int FROM information_schema.column_privileges
           WHERE table_schema = 'account' AND grantee = 'edu_api' AND privilege_type <> 'SELECT'), 0,
    'edu_api has no column-level write privilege in account');

-- ---- functions ------------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'account'::regnamespace
           AND (has_function_privilege('public', p.oid, 'EXECUTE')
             OR has_function_privilege('anon', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticated', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticator', p.oid, 'EXECUTE')
             OR has_function_privilege('service_role', p.oid, 'EXECUTE'))), 0,
    'no account function is executable by PUBLIC, anon, authenticated, authenticator or service_role');
-- Ruling R-03: temporary schema explicitly LAST, so it can never shadow a type
-- or function name inside a definer function.
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'account'::regnamespace
           AND (SELECT array_agg(c) FROM unnest(p.proconfig) AS c WHERE c LIKE 'search_path=%')
               IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']), 0,
    'every account function pins search_path to exactly pg_catalog, pg_temp');
SELECT isnt((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'account'::regnamespace AND p.prosecdef), 0,
    'the schema has SECURITY DEFINER functions (the two checks around this one are not vacuous)');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'account'::regnamespace
           AND pg_get_userbyid(p.proowner) <> 'postgres'), 0,
    'every account function is owned by the migration owner (postgres)');
SELECT ok(has_function_privilege('edu_api', 'account.update_own_profile(jsonb)', 'EXECUTE'), 'edu_api may execute update_own_profile');
SELECT ok(has_function_privilege('edu_api', 'account.get_own_onboarding()', 'EXECUTE'), 'edu_api may execute get_own_onboarding');
SELECT ok(has_function_privilege('edu_api', 'account.advance_onboarding(text, integer, integer, boolean)', 'EXECUTE'), 'edu_api may execute advance_onboarding');
SELECT is(has_function_privilege('edu_api', 'account.audit_seam(text, text, uuid, text, jsonb)', 'EXECUTE'), false, 'the audit seam is internal');
SELECT is(has_function_privilege('edu_api', 'account.onboarding_floor(uuid)', 'EXECUTE'), false, 'onboarding_floor (takes a user id) is internal');
SELECT is(has_function_privilege('edu_api', 'account.onboarding_rank(text)', 'EXECUTE'), false, 'onboarding_rank is internal');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'account'::regnamespace
           AND has_function_privilege('edu_api', p.oid, 'EXECUTE')
           AND EXISTS (SELECT 1 FROM unnest(p.proargnames) AS a(name) WHERE a.name ~ 'user|learner|actor')), 0,
    'no function edu_api can call takes a user, learner or actor parameter');

-- ---- the student API role itself is unchanged ------------------------------------
SELECT is((SELECT count(*)::int FROM pg_auth_members m JOIN pg_roles u ON u.oid = m.member
           WHERE u.rolname = 'edu_api'), 0, 'edu_api is still not a member of any other role');
SELECT is((SELECT array_agg(table_name || '.' || column_name || ':' || privilege_type ORDER BY 1)
           FROM information_schema.column_privileges
           WHERE table_schema = 'app' AND grantee = 'edu_api' AND privilege_type <> 'SELECT'),
    ARRAY['learner_profiles.user_id:INSERT'],
    'edu_api still has no UPDATE privilege on app.learner_profiles');
SELECT is(has_table_privilege('edu_api', 'app.audit_events', 'INSERT'), false, 'edu_api still cannot write audit events');

SELECT * FROM finish();
ROLLBACK;
