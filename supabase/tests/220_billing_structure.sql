-- Structure, privileges and exposure of the private `billing` schema.
BEGIN;
SELECT * FROM no_plan();

-- ---- tables, keys, RLS -------------------------------------------------------
SELECT tables_are('billing', ARRAY[
    'providers','plans','plan_prices','orders','provider_events','refunds',
    'entitlements','entitlement_revocations'], 'the 8 billing tables are the intended ones');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'billing' AND c.relkind = 'r' AND NOT c.relrowsecurity), 0,
    'row-level security is enabled on every billing table');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'billing' AND c.relkind = 'r'
             AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p')), 0,
    'every billing table has a primary key');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'billing'::regnamespace AND contype = 'f'), 16,
    '16 foreign keys exist');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE connamespace = 'billing'::regnamespace AND contype = 'f' AND confdeltype <> 'r'), 0,
    'every billing foreign key is ON DELETE RESTRICT (nothing cascades, nothing is nulled silently)');
SELECT is((SELECT count(*)::int FROM pg_class c WHERE c.relnamespace = 'billing'::regnamespace
           AND c.relkind NOT IN ('r','i')), 0,
    'billing holds only tables and indexes (no view, sequence or materialised view)');

SELECT col_is_unique('billing', 'entitlements', ARRAY['idempotency_key'], 'one grant per idempotency key');
SELECT col_is_unique('billing', 'orders', ARRAY['idempotency_key'], 'one order per idempotency key');
SELECT col_is_unique('billing', 'provider_events', ARRAY['provider','provider_event_id'], 'one row per (provider, provider event id)');
SELECT col_is_unique('billing', 'entitlement_revocations', ARRAY['entitlement_id'], 'one revocation per grant');
SELECT col_is_unique('billing', 'refunds', ARRAY['order_id'], 'one refund per order');
SELECT has_index('billing', 'entitlements', 'entitlements_one_per_order', 'one purchase grant per order');
SELECT has_index('billing', 'entitlements', 'idx_billing_entitlements_learner', 'grants-by-learner index');
SELECT fk_ok('billing', 'entitlements', 'learner_id', 'auth', 'users', 'id', 'grants reference auth.users');
SELECT col_not_null('billing', 'entitlements', 'ends_at', 'no open-ended grant');
SELECT col_not_null('billing', 'entitlements', 'idempotency_key', 'every grant carries an idempotency key');

-- ---- money is integer minor units + currency code -------------------------------
SELECT col_type_is('billing', 'plan_prices', 'amount_minor', 'bigint', 'plan price is an integer number of minor units');
SELECT col_type_is('billing', 'orders', 'amount_expected_minor', 'bigint', 'order amount is an integer number of minor units');
SELECT col_type_is('billing', 'refunds', 'amount_minor', 'bigint', 'refund amount is an integer number of minor units');
SELECT is((SELECT count(*)::int FROM information_schema.columns
           WHERE table_schema = 'billing' AND data_type IN ('numeric','real','double precision','money')), 0,
    'no floating-point, numeric or money column exists in billing');
SELECT col_not_null('billing', 'plan_prices', 'currency', 'a price always has a currency');
SELECT col_not_null('billing', 'orders', 'currency', 'an order always has a currency');

-- ---- no payment configuration ships with the schema ------------------------------
SELECT is((SELECT count(*)::int FROM billing.providers), 0, 'the migration registers no provider (the simulated one included)');
SELECT is((SELECT count(*)::int FROM billing.plans), 0, 'the migration creates no plan');
SELECT is((SELECT count(*)::int FROM billing.plan_prices), 0, 'the migration creates no price');
SELECT is((SELECT count(*)::int FROM billing.entitlements), 0, 'the migration grants nothing to anyone');

-- ---- policies -----------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'billing'), 2, '2 policies exist');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'billing' AND roles <> ARRAY['edu_api']::name[]), 0,
    'every policy applies to edu_api only (none to public, anon or authenticated)');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'billing' AND cmd <> 'SELECT'), 0,
    'no policy allows INSERT, UPDATE or DELETE');
SELECT is((SELECT array_agg(tablename::text ORDER BY tablename) FROM pg_policies WHERE schemaname = 'billing'),
    ARRAY['entitlement_revocations','entitlements'],
    'only grants and revocations have a policy; plans, orders, events, refunds and providers deny everything');

-- ---- privileges ---------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'billing' AND grantee <> 'postgres'), 0,
    'nobody but the owner holds a table-level privilege in billing');
SELECT is((SELECT count(*)::int FROM information_schema.column_privileges
           WHERE table_schema = 'billing' AND grantee NOT IN ('postgres','edu_api')), 0,
    'PUBLIC / anon / authenticated / authenticator / service_role hold no column privilege in billing');
SELECT is((SELECT array_agg(table_name || '.' || column_name || ':' || privilege_type ORDER BY (table_name || '.' || column_name)::text COLLATE "C")
           FROM information_schema.column_privileges
           WHERE table_schema = 'billing' AND grantee = 'edu_api'),
    ARRAY['entitlement_revocations.entitlement_id:SELECT','entitlement_revocations.revoked_at:SELECT',
          'entitlements.ends_at:SELECT','entitlements.id:SELECT','entitlements.learner_id:SELECT',
          'entitlements.scope_course_id:SELECT','entitlements.scope_grade_id:SELECT',
          'entitlements.scope_kind:SELECT','entitlements.source:SELECT','entitlements.starts_at:SELECT'],
    'edu_api may read exactly ten columns of grants and revocations, and write none');
SELECT is((SELECT array_agg(DISTINCT r.rolname::text ORDER BY r.rolname::text)
           FROM pg_roles r CROSS JOIN pg_class c
           WHERE c.relnamespace = 'billing'::regnamespace AND c.relkind = 'r'
             AND NOT r.rolsuper AND r.rolname <> 'postgres' AND NOT pg_has_role(r.oid, 'postgres', 'MEMBER')
             -- PostgreSQL's built-in "all data" roles (and the platform's members of them) reach
             -- every table of every schema, `app` included; they are not grants of this schema.
             AND r.rolname !~ '^pg_' AND NOT pg_has_role(r.oid, 'pg_read_all_data', 'MEMBER')
             AND NOT pg_has_role(r.oid, 'pg_write_all_data', 'MEMBER')
             AND (has_table_privilege(r.oid, c.oid, 'INSERT') OR has_table_privilege(r.oid, c.oid, 'UPDATE')
               OR has_table_privilege(r.oid, c.oid, 'DELETE') OR has_table_privilege(r.oid, c.oid, 'TRUNCATE')
               OR has_table_privilege(r.oid, c.oid, 'SELECT')
               OR has_any_column_privilege(r.oid, c.oid, 'INSERT') OR has_any_column_privilege(r.oid, c.oid, 'UPDATE'))),
    NULL,
    'effective privileges: no non-owner role can write any billing table or read a whole one');
SELECT is((SELECT array_agg(DISTINCT r.rolname::text ORDER BY r.rolname::text)
           FROM pg_roles r CROSS JOIN pg_class c
           WHERE c.relnamespace = 'billing'::regnamespace AND c.relkind = 'r'
             AND NOT r.rolsuper AND r.rolname <> 'postgres' AND NOT pg_has_role(r.oid, 'postgres', 'MEMBER')
             -- PostgreSQL's built-in "all data" roles (and the platform's members of them) reach
             -- every table of every schema, `app` included; they are not grants of this schema.
             AND r.rolname !~ '^pg_' AND NOT pg_has_role(r.oid, 'pg_read_all_data', 'MEMBER')
             AND NOT pg_has_role(r.oid, 'pg_write_all_data', 'MEMBER')
             AND has_any_column_privilege(r.oid, c.oid, 'SELECT')),
    ARRAY['edu_api','edu_api_login'],
    'effective privileges: only the student API role (and its login) can read any billing column');
SELECT is(has_schema_privilege('anon', 'billing', 'USAGE'), false, 'anon cannot use schema billing');
SELECT is(has_schema_privilege('authenticated', 'billing', 'USAGE'), false, 'authenticated cannot use schema billing');
SELECT is(has_schema_privilege('authenticator', 'billing', 'USAGE'), false, 'authenticator (Data API) cannot use schema billing');
SELECT is(has_schema_privilege('service_role', 'billing', 'USAGE'), false, 'service_role cannot use schema billing');
SELECT is(has_schema_privilege('public', 'billing', 'USAGE'), false, 'PUBLIC cannot use schema billing');
SELECT is(has_schema_privilege('edu_api', 'billing', 'USAGE'), true, 'edu_api can use schema billing');
SELECT is(has_schema_privilege('edu_api', 'billing', 'CREATE'), false, 'edu_api cannot create objects in billing');

-- ---- functions ------------------------------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'billing'::regnamespace
           AND (has_function_privilege('public', p.oid, 'EXECUTE')
             OR has_function_privilege('anon', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticated', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticator', p.oid, 'EXECUTE')
             OR has_function_privilege('service_role', p.oid, 'EXECUTE'))), 0,
    'no billing function is executable by PUBLIC, anon, authenticated, authenticator or service_role');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'billing'::regnamespace AND has_function_privilege('edu_api', p.oid, 'EXECUTE')),
    ARRAY['is_entitled'],
    'edu_api may execute exactly one billing function: the read-only is_entitled');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'billing'::regnamespace
             AND EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname NOT IN ('postgres','supabase_admin','edu_api','edu_api_login')
                           AND NOT r.rolsuper AND has_function_privilege(r.oid, p.oid, 'EXECUTE'))),
    NULL,
    'no other role can execute any billing function: staff, order, provider-event and erasure functions are granted to nobody');
SELECT is((SELECT p.provolatile::text FROM pg_proc p WHERE p.pronamespace = 'billing'::regnamespace AND p.proname = 'is_entitled'),
    's', 'is_entitled is STABLE (it cannot write)');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'billing'::regnamespace
           AND NOT COALESCE(p.proconfig @> ARRAY['search_path=""'], false)), 0,
    'every billing function pins an empty search_path');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'billing'::regnamespace
           AND pg_get_userbyid(p.proowner) <> 'postgres'), 0,
    'every billing function is owned by the migration owner (postgres)');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'billing'::regnamespace), 16,
    '16 billing functions exist');
SELECT is((SELECT count(*)::int FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
           WHERE c.relnamespace = 'billing'::regnamespace AND NOT t.tgisinternal), 5,
    '5 history guards are installed');

-- ---- the staff roles are NOT created by this lane ------------------------------
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'billing'::regnamespace
           AND p.proname LIKE 'staff\_%'), 3, 'three staff functions await the staff boundary');

-- ---- nothing was added to schema app ---------------------------------------------
SELECT is((SELECT count(*)::int FROM pg_tables WHERE schemaname = 'app'), 22, 'schema app still has exactly 22 tables');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'app'), 17, 'schema app still has exactly 17 policies');
SELECT is((SELECT array_agg(p.proname::text ORDER BY p.proname) FROM pg_proc p
           WHERE p.pronamespace = 'app'::regnamespace AND has_function_privilege('edu_api', p.oid, 'EXECUTE')),
    ARRAY['current_actor_id','sync_apply_operation'],
    'edu_api gained no function in schema app');

SELECT * FROM finish();
ROLLBACK;
