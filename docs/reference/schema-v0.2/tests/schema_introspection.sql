-- READ-ONLY introspection for STAGING/local Supabase, after both migrations.
-- Run with administrative SQL inspector on the disposable database.
SELECT count(*) AS app_table_count_expected_22
FROM pg_catalog.pg_tables WHERE schemaname = 'app';

SELECT c.relname AS table_name,
       c.relrowsecurity AS rls_enabled,
       c.relforcerowsecurity AS force_rls,
       COALESCE(p.policy_count, 0) AS policy_count
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN LATERAL (
    SELECT count(*) AS policy_count FROM pg_catalog.pg_policy po WHERE po.polrelid = c.oid
) p ON true
WHERE n.nspname = 'app' AND c.relkind = 'r'
ORDER BY c.relname;

SELECT pol.tablename, pol.policyname, pol.roles, pol.cmd
FROM pg_catalog.pg_policies pol
WHERE pol.schemaname = 'app'
ORDER BY pol.tablename, pol.policyname;

SELECT r.rolname, r.rolcanlogin, r.rolbypassrls
FROM pg_catalog.pg_roles r WHERE r.rolname = 'edu_api';

SELECT conrelid::regclass AS table_name,
       conname, contype, pg_get_constraintdef(oid) AS definition
FROM pg_catalog.pg_constraint
WHERE connamespace = 'app'::regnamespace
ORDER BY conrelid::regclass::text, contype, conname;
