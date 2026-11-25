-- Structure, privileges and exposure of the private `leaderboard` schema.
BEGIN;
SELECT * FROM no_plan();

-- ---- tables, keys, RLS -------------------------------------------------------
SELECT tables_are('leaderboard', ARRAY[
    'pseudonym_pool','periods','cohorts','memberships','snapshot_runs','snapshots'],
    'the 6 leaderboard tables are the intended ones');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'leaderboard' AND c.relkind = 'r' AND NOT c.relrowsecurity), 0,
    'row-level security is enabled on every leaderboard table');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'leaderboard'), 0,
    'no policy at all: every table denies everything to every non-owner role');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'leaderboard' AND c.relkind = 'r'
             AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p')), 0,
    'every leaderboard table has a primary key');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'leaderboard' AND c.relkind IN ('v','m')), 0,
    'no view (a view would run with its owner''s rights and bypass RLS)');
SELECT col_is_pk('leaderboard', 'memberships', ARRAY['cohort_id','learner_id'], 'one consent row per (cohort, learner)');
SELECT col_is_pk('leaderboard', 'snapshots', ARRAY['period_key','cohort_id','learner_id'], 'one snapshot row per (period, cohort, learner)');
SELECT col_is_unique('leaderboard', 'memberships', ARRAY['cohort_id','pseudonym_id','pseudonym_suffix'], 'a pseudonym is unique within its cohort');
SELECT col_is_unique('leaderboard', 'snapshots', ARRAY['period_key','cohort_id','tie_order'], 'the display order is unique inside a snapshot');
SELECT has_index('leaderboard', 'memberships', 'memberships_one_active_cohort', 'a learner is an active member of at most one cohort');
SELECT col_not_null('leaderboard', 'memberships', 'opted_in_at', 'a membership cannot exist without an opt-in instant');
SELECT fk_ok('leaderboard', 'memberships', 'learner_id', 'app', 'learner_profiles', 'user_id', 'members are learner profiles');
SELECT fk_ok('leaderboard', 'memberships', 'pseudonym_id', 'leaderboard', 'pseudonym_pool', 'id', 'a pseudonym can only come from the allow-list');
SELECT col_has_check('leaderboard', 'snapshots', 'gold', 'a snapshot score cannot be negative');
SELECT col_has_check('leaderboard', 'cohorts', 'is_synthetic', 'a cohort can only be synthetic');
SELECT throws_ok($$INSERT INTO leaderboard.cohorts (kind, code, is_synthetic) VALUES ('class', 'real-class', false)$$, '23514', NULL,
    'a non-synthetic cohort cannot be stored');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'leaderboard'::regnamespace AND contype = 'f' AND confdeltype NOT IN ('r','a')), 0,
    'no leaderboard foreign key cascades or nulls on delete');
SELECT is((SELECT count(*)::int FROM pg_constraint k
           WHERE k.connamespace = 'leaderboard'::regnamespace AND k.contype = 'f'
             AND k.confrelid IN ('app.sync_receipts'::regclass, 'app.practice_attempts'::regclass,
                                 'app.lesson_progress'::regclass, 'app.account_sync_state'::regclass,
                                 'app.account_change_feed'::regclass)), 0,
    'no foreign key onto the five learning tables (ruling R-02)');

-- ---- privacy by shape ---------------------------------------------------------
SELECT is((SELECT count(*)::int FROM information_schema.columns
           WHERE table_schema = 'leaderboard'
             AND column_name ~* '(e_?mail|display|first_?name|last_?name|full_?name|phone|birth|address)'), 0,
    'no leaderboard column can hold a real name, a display name, an e-mail or a contact detail');
SELECT is((SELECT array_agg(table_name || '.' || column_name ORDER BY table_name || '.' || column_name COLLATE "C") FROM information_schema.columns
           WHERE table_schema = 'leaderboard' AND data_type IN ('text', 'character varying', 'jsonb', 'json')),
    ARRAY['cohorts.code','cohorts.kind','periods.kind','periods.period_key','pseudonym_pool.name',
          'snapshot_runs.period_key','snapshots.period_key'],
    'the only text columns are codes, period keys and the allow-list itself: nothing a user can type');
SELECT is((SELECT count(*)::int FROM leaderboard.pseudonym_pool), 576, 'the pseudonym allow-list has 576 generated names');
SELECT is((SELECT count(*)::int FROM leaderboard.pseudonym_pool WHERE name !~ '^[A-Z][a-z]+ [A-Z][a-z]+$'), 0,
    'every pseudonym is "<Word> <Word>"');
SELECT is((SELECT count(*)::int FROM leaderboard.cohorts), 0, 'no cohort is seeded');
SELECT is((SELECT count(*)::int FROM leaderboard.memberships), 0, 'nobody is a member by default (unknown consent = not a member)');

-- ---- nothing was added to other schemas ---------------------------------------
SELECT is((SELECT count(*)::int FROM pg_proc WHERE pronamespace IN ('app'::regnamespace, 'rewards'::regnamespace,
                                                                   'ops'::regnamespace, 'staff'::regnamespace)
             AND prosrc ILIKE '%leaderboard.%'), 0,
    'no app / rewards / ops / staff function refers to the leaderboard schema');
SELECT is((SELECT count(*)::int FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
           WHERE NOT t.tgisinternal AND p.pronamespace = 'leaderboard'::regnamespace), 0,
    'the leaderboard installs no trigger anywhere (it only reads the ledger)');
SELECT is((SELECT count(*)::int FROM pg_policies
           WHERE schemaname IN ('app','rewards') AND (qual ILIKE '%leaderboard.%' OR with_check ILIKE '%leaderboard.%')), 0,
    'no app or rewards policy refers to the leaderboard schema');

-- ---- table privileges ---------------------------------------------------------
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'leaderboard'
             AND grantee IN ('PUBLIC','anon','authenticated','authenticator','service_role','edu_api','edu_staff','edu_worker')), 0,
    'PUBLIC / anon / authenticated / authenticator / service_role / edu_api / edu_staff / edu_worker hold NO table privilege');
SELECT is((SELECT count(*)::int FROM information_schema.column_privileges
           WHERE table_schema = 'leaderboard'
             AND grantee IN ('PUBLIC','anon','authenticated','authenticator','service_role','edu_api','edu_staff','edu_worker')), 0,
    '... and no column privilege');
SELECT is(has_schema_privilege('anon', 'leaderboard', 'USAGE'), false, 'anon cannot use schema leaderboard');
SELECT is(has_schema_privilege('authenticated', 'leaderboard', 'USAGE'), false, 'authenticated cannot use schema leaderboard');
SELECT is(has_schema_privilege('authenticator', 'leaderboard', 'USAGE'), false, 'authenticator (Data API) cannot use schema leaderboard');
SELECT is(has_schema_privilege('service_role', 'leaderboard', 'USAGE'), false, 'service_role cannot use schema leaderboard');
SELECT is(has_schema_privilege('edu_api', 'leaderboard', 'USAGE'), true, 'edu_api can use the schema (to call its one function)');
SELECT is(has_schema_privilege('edu_api', 'leaderboard', 'CREATE'), false, 'edu_api cannot create objects in leaderboard');
SELECT is(has_schema_privilege('edu_staff', 'leaderboard', 'USAGE') OR has_schema_privilege('edu_worker', 'leaderboard', 'USAGE'), false,
    'edu_staff and edu_worker have nothing in leaderboard yet');

-- ---- functions -------------------------------------------------------------------
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p WHERE p.pronamespace = 'leaderboard'::regnamespace),
    ARRAY['display_pseudonym','enroll','erase_learner','is_rankable','my_standing','period_gold',
          'refresh_snapshot','resolve_period','visible_rows','withdraw'],
    'the 10 leaderboard functions are the intended ones');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'leaderboard'::regnamespace
           AND (has_function_privilege('public', p.oid, 'EXECUTE')
             OR has_function_privilege('anon', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticated', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticator', p.oid, 'EXECUTE')
             OR has_function_privilege('service_role', p.oid, 'EXECUTE'))), 0,
    'no leaderboard function is executable by PUBLIC, anon, authenticated, authenticator or service_role');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'leaderboard'::regnamespace AND has_function_privilege('edu_api', p.oid, 'EXECUTE')),
    ARRAY['my_standing'], 'edu_api may execute exactly my_standing');
SELECT is((SELECT array_agg(pg_get_function_identity_arguments(p.oid)) FROM pg_proc p
           WHERE p.pronamespace = 'leaderboard'::regnamespace AND has_function_privilege('edu_api', p.oid, 'EXECUTE')),
    ARRAY['p_period text'], 'the function edu_api can call takes NO learner id and NO cohort id');
SELECT is((SELECT count(*)::int FROM pg_proc p JOIN pg_roles r ON true
           WHERE p.pronamespace = 'leaderboard'::regnamespace AND p.proname <> 'my_standing'
             AND NOT r.rolsuper AND r.rolname NOT LIKE 'pg\_%' AND r.rolname <> 'postgres'
             AND has_function_privilege(r.oid, p.oid, 'EXECUTE')), 0,
    'refresh, enroll, withdraw, the erasure hook and the helpers are executable by NO non-owner role');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'leaderboard'::regnamespace
           AND NOT COALESCE(p.proconfig = ARRAY['search_path=pg_catalog, pg_temp'], false)), 0,
    'every leaderboard function pins search_path to exactly "pg_catalog, pg_temp" (ruling R-03)');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'leaderboard'::regnamespace
           AND pg_get_userbyid(p.proowner) <> 'postgres'), 0,
    'every leaderboard function is owned by the migration owner (postgres)');
SELECT is((SELECT pg_get_function_result(p.oid) FROM pg_proc p
           WHERE p.pronamespace = 'leaderboard'::regnamespace AND p.proname = 'erase_learner'
             AND pg_get_function_identity_arguments(p.oid) = 'p_user_id uuid'), 'jsonb',
    'the erasure hook has the agreed signature: erase_learner(p_user_id uuid) RETURNS jsonb');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace IN ('ops'::regnamespace, 'staff'::regnamespace)
           AND has_function_privilege('edu_api', p.oid, 'EXECUTE')), 0,
    'edu_api still has nothing in ops or staff');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'rewards'::regnamespace AND has_function_privilege('edu_api', p.oid, 'EXECUTE')),
    ARRAY['award_for_operation','haiti_day','reconcile_learner'],
    'nothing was granted on rewards: edu_api can call what it could before');

-- ---- period resolution ---------------------------------------------------------
SELECT is((SELECT period_key || '|' || kind || '|' || (starts_on IS NULL) || '|' || is_closed FROM leaderboard.resolve_period('all')),
    'all|all_time|true|false', 'period "all" is all-time and never closed');
SELECT is((SELECT starts_on FROM leaderboard.resolve_period('week')),
    date_trunc('week', (now() AT TIME ZONE 'America/Port-au-Prince')::date::timestamp)::date,
    'period "week" starts on the Monday of the current HAITI date');
SELECT is((SELECT (ends_on - starts_on) || '|' || is_closed FROM leaderboard.resolve_period('week')), '6|false',
    'a week is Monday..Sunday and the current one is open');
SELECT is((SELECT period_key || '|' || is_closed FROM leaderboard.resolve_period('2026-11-16')), '2026-11-16|true',
    'a past Monday names a closed week');
SELECT throws_ok($$SELECT * FROM leaderboard.resolve_period('2026-11-17')$$, '22023', 'Unknown period', 'a date that is not a Monday is refused');
SELECT throws_ok($$SELECT * FROM leaderboard.resolve_period('2999-01-01')$$, '22023', 'Unknown period', 'a future week is refused');
SELECT throws_ok($$SELECT * FROM leaderboard.resolve_period('2026-13-45')$$, '22023', 'Unknown period', 'an impossible date is refused');
SELECT throws_ok($$SELECT * FROM leaderboard.resolve_period('month')$$, '22023', 'Unknown period', 'an unknown word is refused');
SELECT throws_ok($$SELECT * FROM leaderboard.resolve_period(NULL)$$, '22023', 'Unknown period', 'NULL is refused');
SELECT throws_ok($$SELECT * FROM leaderboard.resolve_period('global')$$, '22023', 'Unknown period', 'there is no "global" period or ranking');

-- ---- Supabase Data API roles cannot reach the schema at all -------------------
SET LOCAL ROLE anon;
SELECT throws_ok('SELECT count(*) FROM leaderboard.snapshots', '42501', NULL, 'anon: schema leaderboard is unreachable');
SELECT throws_ok($$SELECT leaderboard.my_standing('all')$$, '42501', NULL, 'anon: cannot call leaderboard functions');
RESET ROLE;
SET LOCAL ROLE authenticated;
SELECT throws_ok('SELECT count(*) FROM leaderboard.memberships', '42501', NULL, 'authenticated (Data API): schema leaderboard is unreachable');
SELECT throws_ok($$SELECT leaderboard.my_standing('all')$$, '42501', NULL, 'authenticated (Data API): cannot call leaderboard functions');
RESET ROLE;
SET LOCAL ROLE service_role;
SELECT throws_ok('SELECT count(*) FROM leaderboard.cohorts', '42501', NULL, 'service_role: schema leaderboard is unreachable');
RESET ROLE;

SELECT * FROM finish();
ROLLBACK;
