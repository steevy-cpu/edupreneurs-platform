-- ============================================================================
-- PROPOSED — NOT APPLIED. Social-00 design artefact.
-- This file lives under docs/ on purpose: the Supabase CLI only applies files in
-- supabase/migrations/, so nothing here runs. To adopt it in Social-01, copy it
-- to supabase/migrations/<timestamp>_social_schema_and_roles.sql and review it.
-- ============================================================================
-- Edupreneurs 2.0 — social module: private schema, database roles, actor helper
--
-- BOUNDARY RULE (asserted by tests in Social-01):
--   * No statement in any social migration names the `app` schema.
--   * No foreign key, view or function body crosses between `app` and `social`.
--   * The social roles hold no privilege on `app`; `edu_api` holds none on `social`.
-- The only things the two modules share are (a) auth.users as the identity and
-- (b) the transaction-local setting `edu.actor_id` that FastAPI sets after it
-- has verified the caller's access token.

CREATE SCHEMA IF NOT EXISTS social;
REVOKE ALL ON SCHEMA social FROM PUBLIC;
REVOKE ALL ON SCHEMA social FROM anon, authenticated, authenticator, service_role;
COMMENT ON SCHEMA social IS
    'Private community data. Reached only through the FastAPI social module; never expose this schema in the Supabase Data API.';

-- ----------------------------------------------------------------------------
-- Roles. All NOLOGIN group roles: a migration must never contain a password.
-- Matching LOGIN roles (edu_social_login, edu_social_mod_login,
-- edu_social_worker_login) are created out of band, exactly like edu_api_login.
--
--   edu_social         student-facing social endpoints (/v1/social/*)
--   edu_social_mod     moderation and administration endpoints (/v1/social/moderation/*, /admin/*)
--   edu_social_worker  scheduled retention job only
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['edu_social', 'edu_social_mod', 'edu_social_worker'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', r);
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_roles
            WHERE rolname = r
              AND (rolbypassrls OR rolsuper OR rolcreaterole OR rolcreatedb OR rolcanlogin OR rolreplication)
        ) THEN
            RAISE EXCEPTION '% must be a plain NOLOGIN role without BYPASSRLS or admin attributes', r;
        END IF;
    END LOOP;
END $$;

GRANT USAGE ON SCHEMA social TO edu_social, edu_social_mod, edu_social_worker;

-- The learning API role must never reach social data. This is a no-op today
-- (it was never granted anything here); it is written down so the intent is in
-- the migration history and a test can assert it.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edu_api') THEN
        REVOKE ALL ON SCHEMA social FROM edu_api;
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- Actor identity. Same contract as the learning module: FastAPI runs
--   set_config('edu.actor_id', <verified uuid>, true)
-- inside the request's transaction. Defined again here (not reused from `app`)
-- so the social roles need no USAGE on the `app` schema.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.current_actor_id()
RETURNS uuid
LANGUAGE sql STABLE
SET search_path = ''
AS $$ SELECT NULLIF(current_setting('edu.actor_id', true), '')::uuid $$;
