-- Mon Edupreneur 2.0 — no temporary objects for API roles.
--
-- Weakness class: even with `SET search_path = ''` (or `pg_catalog, pg_temp`), PostgreSQL
-- resolves an unqualified TYPE name through the session's temporary schema before the
-- search path is consulted. A session that may run SQL of its choice on an API login and
-- may create temporary objects can therefore shadow a built-in type used inside a
-- SECURITY DEFINER function, so that code of the session's choosing runs with the
-- function owner's privileges (privilege escalation).
--
-- Fix: nobody but the database owner may create temporary objects in this database.
-- PostgreSQL grants TEMPORARY on every database to PUBLIC by default, so it is revoked
-- from PUBLIC and, explicitly, from the API-facing roles. This closes the class for every
-- definer function, including the verified ones in schema `app`, without altering them.
--
-- Roles that do not exist in this environment are skipped.
DO $$
DECLARE
    r text;
BEGIN
    EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'authenticator', 'service_role', 'edu_api']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM %I', current_database(), r);
        END IF;
    END LOOP;
END $$;
