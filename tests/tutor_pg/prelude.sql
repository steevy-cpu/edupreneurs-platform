-- The few objects from main's migrations that the tutor schema proposal relies on,
-- so it can be applied to an otherwise empty throwaway database.
-- Copied from supabase/migrations/20261121000100_core_schema.sql and ...000300_...
CREATE SCHEMA IF NOT EXISTS app;
REVOKE ALL ON SCHEMA app FROM PUBLIC;

CREATE OR REPLACE FUNCTION app.current_actor_id()
RETURNS uuid
LANGUAGE sql STABLE
SET search_path = ''
AS $$ SELECT NULLIF(current_setting('edu.actor_id', true), '')::uuid $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edu_api') THEN
        CREATE ROLE edu_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END $$;
GRANT USAGE ON SCHEMA app TO edu_api;
GRANT EXECUTE ON FUNCTION app.current_actor_id() TO edu_api;
