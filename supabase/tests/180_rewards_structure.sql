-- Structure, privileges and exposure of the private `rewards` schema.
BEGIN;
SELECT * FROM no_plan();

-- ---- tables, keys, RLS -------------------------------------------------------
SELECT tables_are('rewards', ARRAY[
    'rules','achievement_definitions','ledger','balances','processed_operations',
    'activity_days','streak_state','achievement_awards','forfeited_sources','pending_completions'],
    'the 10 rewards tables are the intended ones');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'rewards' AND c.relkind = 'r' AND NOT c.relrowsecurity), 0,
    'row-level security is enabled on every rewards table');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'rewards' AND c.relkind = 'r'
             AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p')), 0,
    'every rewards table has a primary key');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'rewards' AND c.relkind IN ('v','m')), 0,
    'no view (a view would run with its owner''s rights and bypass RLS)');

SELECT col_is_unique('rewards', 'ledger', ARRAY['learner_id','source_key'], 'the exactly-once key: one ledger row per (learner, source key)');
SELECT is((SELECT attgenerated::text FROM pg_attribute WHERE attrelid = 'rewards.ledger'::regclass AND attname = 'source_key'), 's',
    'the source key is a GENERATED column: no writer can supply it');
SELECT col_is_pk('rewards', 'processed_operations', ARRAY['learner_id','op_id'], 'one decision per (learner, operation)');
SELECT col_is_pk('rewards', 'achievement_awards', ARRAY['learner_id','achievement_code'], 'an achievement is earned once per learner');
SELECT col_is_pk('rewards', 'activity_days', ARRAY['learner_id','day'], 'one row per learner and day');
SELECT col_is_pk('rewards', 'rules', ARRAY['code','version'], 'rules are versioned');
SELECT fk_ok('rewards', 'ledger', 'learner_id', 'app', 'learner_profiles', 'user_id', 'ledger rows belong to a learner profile');
SELECT fk_ok('rewards', 'ledger', ARRAY['rule_code','rule_version'], 'rewards', 'rules', ARRAY['code','version'], 'every ledger row names its rule version');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'rewards'::regnamespace AND contype = 'f' AND confdeltype NOT IN ('r','a')), 0,
    'no rewards foreign key cascades or nulls on delete');
SELECT is((SELECT count(*)::int FROM pg_constraint k
           WHERE k.connamespace = 'rewards'::regnamespace AND k.contype = 'f'
             AND k.confrelid IN ('app.sync_receipts'::regclass, 'app.practice_attempts'::regclass,
                                 'app.lesson_progress'::regclass, 'app.account_sync_state'::regclass,
                                 'app.account_change_feed'::regclass)), 0,
    'no foreign key onto the sync tables (they must stay truncatable and compactable)');
SELECT has_index('rewards', 'ledger', 'idx_ledger_learner_recent', 'paging index (created_at, id) — not the global sequence');
SELECT has_index('rewards', 'ledger', 'idx_ledger_day', 'period aggregate index');
SELECT col_has_check('rewards', 'ledger', 'amount', 'ledger amounts are checked (non-zero, bounded)');
SELECT col_has_check('rewards', 'balances', 'balance', 'a balance cannot be negative');

-- ---- nothing was added to schema app -------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_proc WHERE pronamespace = 'app'::regnamespace AND prosrc ILIKE '%rewards.%'), 0,
    'no app function refers to the rewards schema (the sync function is untouched)');
SELECT is((SELECT count(*)::int FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
           JOIN pg_proc p ON p.oid = t.tgfoid
           WHERE c.relnamespace = 'app'::regnamespace AND NOT t.tgisinternal
             AND p.pronamespace = 'rewards'::regnamespace), 0,
    'no rewards trigger is attached to an app table');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'app' AND (qual ILIKE '%rewards.%' OR with_check ILIKE '%rewards.%')), 0,
    'no app policy refers to the rewards schema');

-- ---- policies -----------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'rewards'), 5, '5 policies exist');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'rewards' AND roles <> ARRAY['edu_api']::name[]), 0,
    'every policy applies to edu_api only');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'rewards' AND cmd <> 'SELECT'), 0,
    'no policy allows INSERT, UPDATE or DELETE');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'rewards'
           AND tablename IN ('rules','processed_operations','activity_days','forfeited_sources','pending_completions')), 0,
    'rules and the four bookkeeping tables have no policy at all (deny everything)');

-- ---- table privileges --------------------------------------------------------
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'rewards' AND grantee IN ('PUBLIC','anon','authenticated','authenticator','service_role')), 0,
    'PUBLIC / anon / authenticated / authenticator / service_role hold no table privilege in rewards');
SELECT is((SELECT count(*)::int FROM information_schema.column_privileges
           WHERE table_schema = 'rewards' AND grantee IN ('PUBLIC','anon','authenticated','authenticator','service_role')), 0,
    '... and no column privilege');
SELECT is(has_schema_privilege('anon', 'rewards', 'USAGE'), false, 'anon cannot use schema rewards');
SELECT is(has_schema_privilege('authenticated', 'rewards', 'USAGE'), false, 'authenticated cannot use schema rewards');
SELECT is(has_schema_privilege('authenticator', 'rewards', 'USAGE'), false, 'authenticator (Data API) cannot use schema rewards');
SELECT is(has_schema_privilege('service_role', 'rewards', 'USAGE'), false, 'service_role cannot use schema rewards');
SELECT is(has_schema_privilege('edu_api', 'rewards', 'CREATE'), false, 'edu_api cannot create objects in rewards');
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'rewards' AND grantee = 'edu_api' AND privilege_type <> 'SELECT'), 0,
    'edu_api has no INSERT/UPDATE/DELETE/TRUNCATE on any rewards table');
SELECT is((SELECT count(*)::int FROM information_schema.column_privileges
           WHERE table_schema = 'rewards' AND grantee = 'edu_api' AND privilege_type <> 'SELECT'), 0,
    'edu_api has no column-level write privilege in rewards');
SELECT is((SELECT array_agg(table_name::text ORDER BY table_name) FROM information_schema.role_table_grants
           WHERE table_schema = 'rewards' AND grantee = 'edu_api'),
    ARRAY['achievement_awards','achievement_definitions','balances','ledger','streak_state'],
    'edu_api may read exactly five rewards tables');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'rewards' AND c.relkind = 'S'
             AND CASE WHEN c.relkind = 'S' THEN has_sequence_privilege('edu_api', c.oid, 'USAGE') END), 0,
    'edu_api cannot use the ledger sequence');

-- ---- functions ------------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'rewards'::regnamespace
           AND (has_function_privilege('public', p.oid, 'EXECUTE')
             OR has_function_privilege('anon', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticated', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticator', p.oid, 'EXECUTE')
             OR has_function_privilege('service_role', p.oid, 'EXECUTE'))), 0,
    'no rewards function is executable by PUBLIC, anon, authenticated, authenticator or service_role');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'rewards'::regnamespace AND has_function_privilege('edu_api', p.oid, 'EXECUTE')),
    ARRAY['award_for_operation','haiti_day','reconcile_learner'],
    'edu_api may execute exactly award_for_operation, haiti_day and reconcile_learner');
SELECT is((SELECT count(*)::int FROM pg_proc p JOIN pg_roles r ON true
           WHERE p.pronamespace = 'rewards'::regnamespace
             AND p.proname IN ('apply_operation','reconcile_learner_internal','rebuild_balance','rebuild_streak',
                               'reverse_entry','erase_learner','lock_learner','try_lock_learner','is_correction_reason',
                               'try_award_event','set_active_rule_version',
                               'validate_ledger_entry','apply_ledger_entry_to_balance',
                               'prevent_history_change','protect_rule_version')
             AND NOT r.rolsuper AND r.rolname NOT LIKE 'pg\_%' AND r.rolname <> 'postgres'
             AND has_function_privilege(r.oid, p.oid, 'EXECUTE')), 0,
    'the internal functions, the trigger functions and the erasure hook are executable by NO non-owner role');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'rewards'::regnamespace AND has_function_privilege('edu_worker', p.oid, 'EXECUTE')),
    ARRAY['reconcile_batch'], 'edu_worker may execute exactly reconcile_batch');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'rewards'::regnamespace AND has_function_privilege('edu_staff', p.oid, 'EXECUTE')),
    ARRAY['staff_adjust','staff_reverse_entry'], 'edu_staff may execute exactly the two audited admin functions');
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'rewards' AND grantee IN ('edu_staff','edu_worker')), 0,
    'edu_staff and edu_worker hold no table privilege in rewards');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace IN ('ops'::regnamespace, 'staff'::regnamespace)
           AND has_function_privilege('edu_api', p.oid, 'EXECUTE')), 0,
    'edu_api still has nothing in ops or staff');
SELECT is(has_schema_privilege('edu_staff', 'rewards', 'CREATE') OR has_schema_privilege('edu_worker', 'rewards', 'CREATE'), false,
    'edu_staff and edu_worker cannot create objects in rewards');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'rewards'::regnamespace
           AND NOT COALESCE(p.proconfig = ARRAY['search_path=pg_catalog, pg_temp'], false)), 0,
    'every rewards function pins search_path to exactly "pg_catalog, pg_temp" (ruling R-03)');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'rewards'::regnamespace
           AND p.prosecdef AND pg_get_userbyid(p.proowner) <> 'postgres'), 0,
    'every SECURITY DEFINER rewards function is owned by postgres');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'rewards'::regnamespace
           AND pg_get_userbyid(p.proowner) <> 'postgres'), 0,
    'every rewards function is owned by the migration owner (postgres)');
SELECT is((SELECT array_agg(pg_get_function_identity_arguments(p.oid) ORDER BY pg_get_function_identity_arguments(p.oid) COLLATE "C") FROM pg_proc p
           WHERE p.pronamespace = 'rewards'::regnamespace AND has_function_privilege('edu_api', p.oid, 'EXECUTE')
             AND p.proname <> 'haiti_day'),
    ARRAY['p_limit integer','p_op_id uuid'],
    'the functions edu_api can call take NO learner id and NO amount');
SELECT is((SELECT count(*)::int FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
           WHERE c.relnamespace = 'rewards'::regnamespace AND NOT t.tgisinternal), 7,
    '7 rewards triggers are installed');

-- ---- reference data is marked as a placeholder ------------------------------------
SELECT is((SELECT count(*)::int FROM rewards.rules WHERE decision_status NOT LIKE 'BLOCKED_BY_OWNER:PO-09%'), 0,
    'every seeded reward rule is marked BLOCKED_BY_OWNER (PO-09)');
SELECT is((SELECT array_agg(code || ':' || amount ORDER BY code) FROM rewards.rules WHERE is_active),
    ARRAY['achievement_first_lesson:10','achievement_ten_correct:15','lesson_first_completed:20','question_first_correct:5'],
    'the synthetic placeholder amounts are the documented ones');
SELECT is((SELECT count(*)::int FROM rewards.achievement_definitions d
           WHERE d.bonus_rule_code IS NOT NULL AND NOT EXISTS (
               SELECT 1 FROM rewards.rules r WHERE r.code = d.bonus_rule_code AND r.event_kind = 'achievement')), 0,
    'every achievement bonus names an existing achievement rule');

-- ---- Supabase Data API roles cannot reach the schema at all -------------------
SET LOCAL ROLE anon;
SELECT throws_ok('SELECT count(*) FROM rewards.ledger', '42501', NULL, 'anon: schema rewards is unreachable');
SELECT throws_ok($$SELECT rewards.award_for_operation(gen_random_uuid())$$, '42501', NULL, 'anon: cannot call rewards functions');
RESET ROLE;
SET LOCAL ROLE authenticated;
SELECT throws_ok('SELECT count(*) FROM rewards.balances', '42501', NULL, 'authenticated (Data API): schema rewards is unreachable');
SELECT throws_ok($$SELECT rewards.reconcile_learner(10)$$, '42501', NULL, 'authenticated (Data API): cannot call rewards functions');
RESET ROLE;
SET LOCAL ROLE service_role;
SELECT throws_ok('SELECT count(*) FROM rewards.ledger', '42501', NULL, 'service_role: schema rewards is unreachable');
RESET ROLE;

SELECT * FROM finish();
ROLLBACK;
