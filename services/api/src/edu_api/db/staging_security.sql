-- Read-only post-restore invariants for the five migrations on main.
WITH api_roles AS (
    SELECT * FROM pg_catalog.pg_roles WHERE rolname IN ('edu_api', 'edu_api_login')
), members AS (
    SELECT child.rolname AS child, parent.rolname AS parent, m.admin_option,
           m.inherit_option FROM pg_catalog.pg_auth_members m
    JOIN api_roles child ON child.oid = m.member
    JOIN pg_catalog.pg_roles parent ON parent.oid = m.roleid
), app_tables AS (
    SELECT c.* FROM pg_catalog.pg_class c WHERE c.relnamespace = 'app'::regnamespace
      AND c.relkind IN ('r','p')
)
SELECT
  (SELECT count(*) = 2 AND bool_and(NOT (rolsuper OR rolbypassrls OR rolcreaterole
    OR rolcreatedb OR rolreplication) AND rolcanlogin = (rolname = 'edu_api_login')
    AND NOT has_database_privilege(oid, current_database(), 'CREATE')) FROM api_roles)
    AS api_attributes,
  (SELECT count(*) = 1 AND bool_and(child = 'edu_api_login' AND parent = 'edu_api'
    AND NOT admin_option AND inherit_option) FROM members) AS memberships,
  NOT EXISTS (SELECT FROM unnest(ARRAY['edu_api','edu_api_login','anon','authenticated',
    'authenticator','service_role']) role_name
    WHERE has_database_privilege(role_name, current_database(), 'TEMP')) AS temp_revoked,
  NOT EXISTS (SELECT FROM pg_catalog.pg_extension WHERE extname NOT IN
    ('plpgsql','pgcrypto','uuid-ossp','pg_stat_statements','supabase_vault')) AS extensions,
  has_schema_privilege('edu_api_login','app','USAGE') AND
    NOT has_schema_privilege('edu_api_login','auth','USAGE') AND
    NOT EXISTS (SELECT FROM pg_catalog.pg_namespace WHERE
      has_schema_privilege('edu_api_login', oid, 'CREATE')) AND
    NOT EXISTS (SELECT FROM unnest(ARRAY['anon','authenticated','authenticator']) r
      WHERE has_schema_privilege(r,'app','USAGE')) AS schemas,
  (SELECT count(*) = 22 AND bool_and(relrowsecurity AND NOT pg_has_role(
    'edu_api_login', relowner, 'MEMBER')) FROM app_tables) AS row_security,
  NOT EXISTS (SELECT FROM app_tables WHERE has_table_privilege(
    'edu_api_login', oid, 'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER,REFERENCES')) AND
    NOT EXISTS (SELECT FROM app_tables WHERE relname IN
      ('staff_roles','content_sources','lesson_revision_sources','editorial_reviews','audit_events','background_jobs')
      AND has_any_column_privilege('edu_api_login', oid, 'SELECT')) AS private_tables,
  (SELECT array_agg(proname::text ORDER BY proname) = ARRAY['current_actor_id','sync_apply_operation']
   FROM pg_proc WHERE pronamespace = 'app'::regnamespace AND
   has_function_privilege('edu_api_login',oid,'EXECUTE')) AND
   NOT EXISTS (SELECT FROM pg_proc WHERE pronamespace = 'app'::regnamespace AND
     (NOT coalesce(proconfig @> ARRAY['search_path=""'], false) OR
      (prosecdef AND pg_get_userbyid(proowner) <> 'postgres') OR
      has_function_privilege('anon',oid,'EXECUTE') OR
      has_function_privilege('authenticated',oid,'EXECUTE'))) AS functions
