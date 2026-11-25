-- Structure, privileges and exposure of the shared platform interface:
-- roles edu_staff / edu_worker and the private schemas `ops` and `staff`.
BEGIN;
SELECT * FROM no_plan();

-- ---- group roles ----------------------------------------------------------------
SELECT has_role('edu_staff');
SELECT has_role('edu_worker');
SELECT is((SELECT bool_or(rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication)
           FROM pg_roles WHERE rolname IN ('edu_staff','edu_worker')), false,
    'edu_staff and edu_worker cannot log in and have no admin attribute or BYPASSRLS');
SELECT is((SELECT count(*)::int FROM pg_auth_members m JOIN pg_roles u ON u.oid = m.member
           WHERE u.rolname IN ('edu_api','edu_staff','edu_worker')), 0,
    'none of the three group roles is a member of any other role');
-- A login role may carry the privileges of ONE group only. (The role that
-- created a group holds an ADMIN-only membership: inherit and set are both off.)
SELECT is((SELECT count(*)::int FROM (
               SELECT m.member FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid
               WHERE g.rolname IN ('edu_api','edu_staff','edu_worker') AND (m.inherit_option OR m.set_option)
               GROUP BY m.member HAVING count(*) > 1) AS mixed), 0,
    'no role combines student API, staff and worker privileges');
SELECT is((SELECT count(*)::int FROM pg_auth_members m
           JOIN pg_roles g ON g.oid = m.roleid JOIN pg_roles u ON u.oid = m.member
           WHERE g.rolname IN ('edu_staff','edu_worker') AND (m.inherit_option OR m.set_option)
             AND u.rolname NOT IN ('edu_staff_login','edu_worker_login')), 0,
    'only the dedicated login roles use edu_staff / edu_worker');
SELECT is((SELECT count(*)::int FROM pg_auth_members m
           JOIN pg_roles g ON g.oid = m.roleid JOIN pg_roles u ON u.oid = m.member
           WHERE u.rolname IN ('edu_api_login','edu_staff_login','edu_worker_login')
             AND g.rolname <> replace(u.rolname, '_login', '')), 0,
    'each login role (where provisioned) belongs to its own group and nothing else');

-- ---- schemas ----------------------------------------------------------------------
SELECT has_schema('ops');
SELECT has_schema('staff');
SELECT schema_owner_is('ops', 'postgres');
SELECT schema_owner_is('staff', 'postgres');

SELECT is((SELECT array_agg(r || ':' || s ORDER BY (r || ':' || s) COLLATE "C")
           FROM unnest(ARRAY['anon','authenticated','authenticator','service_role','edu_api','edu_staff','edu_worker']) AS r,
                unnest(ARRAY['ops','staff']) AS s
           WHERE has_schema_privilege(r, s, 'USAGE')),
    ARRAY['edu_staff:ops','edu_staff:staff','edu_worker:ops'],
    'USAGE: edu_staff on ops+staff, edu_worker on ops, and nobody else (not edu_api, not the Data API roles)');
SELECT is((SELECT count(*)::int
           FROM unnest(ARRAY['anon','authenticated','authenticator','service_role','edu_api','edu_staff','edu_worker']) AS r,
                unnest(ARRAY['ops','staff','app','public']) AS s
           WHERE has_schema_privilege(r, s, 'CREATE')
             AND NOT (s = 'public' AND r = 'service_role')), 0,
    'no API, worker or Data API role can create objects in ops, staff, app (or public)');
SELECT is((SELECT count(*)::int
           FROM unnest(ARRAY['edu_staff','edu_worker']) AS r, unnest(ARRAY['app','auth']) AS s
           WHERE has_schema_privilege(r, s, 'USAGE')), 0,
    'edu_staff and edu_worker cannot use schema app or auth directly');

-- ---- tables: the new roles hold none, anywhere --------------------------------------
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE grantee IN ('edu_staff','edu_worker')), 0,
    'edu_staff and edu_worker hold no table privilege in any schema');
SELECT is((SELECT count(*)::int FROM information_schema.column_privileges
           WHERE grantee IN ('edu_staff','edu_worker')), 0,
    'edu_staff and edu_worker hold no column privilege in any schema');
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema IN ('ops','staff')
             AND grantee IN ('PUBLIC','anon','authenticated','authenticator','service_role','edu_api')), 0,
    'PUBLIC / Data API roles / edu_api hold no table privilege in ops or staff');
SELECT is((SELECT count(*)::int FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname IN ('ops','staff') AND c.relkind = 'r' AND NOT c.relrowsecurity), 0,
    'row-level security is enabled on every table in ops and staff');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'app'
           AND (roles && ARRAY['edu_staff','edu_worker']::name[])), 0,
    'no app policy mentions edu_staff or edu_worker');

-- ---- functions ------------------------------------------------------------------------
SELECT functions_are('ops', ARRAY['actor_kind_for','check_audit_details','audit_write'],
    'ops holds exactly the expected functions');
SELECT functions_are('staff', ARRAY['check_role_names','actor_roles','actor_has_role','require_role'],
    'staff holds exactly the expected functions');
SELECT function_returns('ops', 'audit_write', ARRAY['text','text','uuid','text','jsonb'], 'uuid');
SELECT function_returns('staff', 'actor_has_role', ARRAY['text[]'], 'boolean');
SELECT function_returns('staff', 'require_role', ARRAY['text[]'], 'uuid');
SELECT function_returns('staff', 'actor_roles', ARRAY[]::text[], 'text[]');
SELECT is((SELECT p.proargnames::text[] FROM pg_proc p
           WHERE p.pronamespace = 'ops'::regnamespace AND p.proname = 'audit_write'),
    ARRAY['p_action','p_target_kind','p_target_id','p_outcome','p_details'],
    'audit_write takes no actor and no actor kind: neither can be supplied by the caller');
SELECT is((SELECT bool_and(p.provariadic <> 0) FROM pg_proc p
           WHERE p.pronamespace = 'staff'::regnamespace AND p.proname IN ('actor_has_role','require_role')), true,
    'actor_has_role and require_role are VARIADIC');

SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace IN ('ops'::regnamespace, 'staff'::regnamespace)
           AND (has_function_privilege('public', p.oid, 'EXECUTE')
             OR has_function_privilege('anon', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticated', p.oid, 'EXECUTE')
             OR has_function_privilege('authenticator', p.oid, 'EXECUTE')
             OR has_function_privilege('service_role', p.oid, 'EXECUTE')
             OR has_function_privilege('edu_api', p.oid, 'EXECUTE'))), 0,
    'no ops/staff function is executable by PUBLIC, the Data API roles or edu_api');
SELECT is((SELECT array_agg(n.nspname || '.' || p.proname ORDER BY (n.nspname || '.' || p.proname) COLLATE "C") FROM pg_proc p
           JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname IN ('ops','staff') AND has_function_privilege('edu_staff', p.oid, 'EXECUTE')),
    ARRAY['ops.audit_write','staff.actor_has_role','staff.actor_roles','staff.require_role'],
    'edu_staff may execute exactly audit_write and the three role checks');
SELECT is((SELECT array_agg(n.nspname || '.' || p.proname ORDER BY (n.nspname || '.' || p.proname) COLLATE "C") FROM pg_proc p
           JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname IN ('ops','staff') AND has_function_privilege('edu_worker', p.oid, 'EXECUTE')),
    ARRAY['ops.audit_write'],
    'edu_worker may execute exactly audit_write');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace = 'app'::regnamespace
           AND (has_function_privilege('edu_staff', p.oid, 'EXECUTE')
             OR has_function_privilege('edu_worker', p.oid, 'EXECUTE'))), 0,
    'edu_staff and edu_worker may execute nothing in app');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace IN ('ops'::regnamespace, 'staff'::regnamespace)
           AND NOT COALESCE(p.proconfig @> ARRAY['search_path=""'], false)), 0,
    'every ops/staff function pins an empty search_path');
SELECT is((SELECT count(*)::int FROM pg_proc p WHERE p.pronamespace IN ('ops'::regnamespace, 'staff'::regnamespace)
           AND pg_get_userbyid(p.proowner) <> 'postgres'), 0,
    'every ops/staff function is owned by the migration owner (postgres)');
SELECT is((SELECT array_agg(n.nspname || '.' || p.proname ORDER BY (n.nspname || '.' || p.proname) COLLATE "C") FROM pg_proc p
           JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname IN ('ops','staff') AND p.prosecdef),
    ARRAY['ops.audit_write','staff.actor_has_role','staff.actor_roles','staff.require_role'],
    'exactly the four callable functions are SECURITY DEFINER; the internal helpers are not');

SELECT * FROM finish();
ROLLBACK;
