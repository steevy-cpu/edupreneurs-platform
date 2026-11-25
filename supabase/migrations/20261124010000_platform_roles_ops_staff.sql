-- Mon Edupreneur 2.0 — shared platform interface: staff and worker database
-- roles, the private schemas `ops` and `staff`, audit writes, staff role checks.
--
-- NOTHING IN SCHEMA `app` IS CREATED, ALTERED OR GRANTED HERE. The verified
-- structure test (supabase/tests/010_structure.sql) pins exact counts inside
-- `app`; new capabilities live in their own private schemas and reach the
-- existing `app` tables only through SECURITY DEFINER functions.
--
-- MODEL
--   edu_staff         NOLOGIN group role of the staff side of the API.
--   edu_staff_login   LOGIN role, member of edu_staff only   (EDU_STAFF_DATABASE_URL)
--   edu_worker        NOLOGIN group role of the background worker.
--   edu_worker_login  LOGIN role, member of edu_worker only  (EDU_WORKER_DATABASE_URL)
--   edu_api           unchanged. It gets nothing in `ops` or `staff`.
--
--   The two login roles are NOT created here, because a migration must not
--   contain a password. Locally scripts/local_stack.py creates them with random
--   passwords; in a hosted environment they are created out of band.
--
--   Neither new role has USAGE on schema `app`, nor any table privilege
--   anywhere. Everything they can do is one of the functions granted at the
--   end of a migration. Each such function is SECURITY DEFINER, owned by
--   postgres, pins an empty search_path, uses schema-qualified names only and
--   takes the actor from app.current_actor_id() — never from a parameter.
--
-- TRUST: as for edu_api, the transaction-local setting `edu.actor_id` is only
-- meaningful because the API (after verifying the access token) is the sole
-- client of these login roles. See docs/SECURITY.md.

-- ----------------------------------------------------------------------------
-- Group roles
-- ----------------------------------------------------------------------------
DO $$
DECLARE v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['edu_staff', 'edu_worker'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format(
                'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',
                v_role);
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_roles
            WHERE rolname = v_role
              AND (rolbypassrls OR rolsuper OR rolcreaterole OR rolcreatedb OR rolcanlogin OR rolreplication)
        ) THEN
            RAISE EXCEPTION '% must be a plain NOLOGIN role without BYPASSRLS or admin attributes', v_role;
        END IF;
    END LOOP;
END $$;

-- ----------------------------------------------------------------------------
-- Private schemas
-- ----------------------------------------------------------------------------
CREATE SCHEMA ops;
REVOKE ALL ON SCHEMA ops FROM PUBLIC;
REVOKE ALL ON SCHEMA ops FROM anon, authenticated;
COMMENT ON SCHEMA ops IS
    'Private operational functions (audit writes, later the job queue). Reached only by the staff API and the worker; never expose this schema in the Supabase Data API.';

CREATE SCHEMA staff;
REVOKE ALL ON SCHEMA staff FROM PUBLIC;
REVOKE ALL ON SCHEMA staff FROM anon, authenticated;
COMMENT ON SCHEMA staff IS
    'Private staff boundary (role checks, later the editorial workflow). Reached only by the staff API; never expose this schema in the Supabase Data API.';

GRANT USAGE ON SCHEMA ops TO edu_staff, edu_worker;
GRANT USAGE ON SCHEMA staff TO edu_staff;

-- ----------------------------------------------------------------------------
-- ops: who is writing?
-- ----------------------------------------------------------------------------
-- The kind of actor is derived from the DATABASE LOGIN of the session, which a
-- caller cannot choose: session_user is unaffected by SET ROLE and by SECURITY
-- DEFINER. 'USAGE' (not 'MEMBER') is deliberate: the role that created a group
-- holds an ADMIN-only membership in it, which must not count.
-- Internal: EXECUTE is granted to nobody.
CREATE FUNCTION ops.actor_kind_for(p_role name)
RETURNS text
LANGUAGE sql STABLE
SET search_path = ''
AS $$
    SELECT CASE
        WHEN pg_has_role(p_role, 'edu_staff', 'USAGE') THEN 'staff'
        WHEN pg_has_role(p_role, 'edu_worker', 'USAGE') THEN 'worker'
        WHEN pg_has_role(p_role, 'edu_api', 'USAGE') THEN 'user'
        ELSE 'system'
    END
$$;

-- Audit details are a small, flat bag of machine values: identifiers, codes,
-- numbers, timestamps. They are NOT a place for prose. The shape below makes it
-- structurally hard to store a learner's free text (an answer, a name, a
-- message): no nested objects, no whitespace in any string, short strings,
-- bounded total size. Errors never echo the rejected value.
-- Internal: EXECUTE is granted to nobody.
CREATE FUNCTION ops.check_audit_details(p_details jsonb)
RETURNS void
LANGUAGE plpgsql IMMUTABLE
SET search_path = ''
AS $$
DECLARE
    v_key text;
    v_value jsonb;
    v_item jsonb;
    v_keys integer := 0;
BEGIN
    IF p_details IS NULL OR jsonb_typeof(p_details) <> 'object' THEN
        RAISE EXCEPTION 'Audit details must be a JSON object' USING ERRCODE = '22023';
    END IF;
    IF octet_length(p_details::text) > 2048 THEN
        RAISE EXCEPTION 'Audit details are limited to 2048 bytes' USING ERRCODE = '22023';
    END IF;
    FOR v_key, v_value IN SELECT d.key, d.value FROM jsonb_each(p_details) AS d LOOP
        v_keys := v_keys + 1;
        IF v_keys > 24 THEN
            RAISE EXCEPTION 'Audit details are limited to 24 keys' USING ERRCODE = '22023';
        END IF;
        IF v_key !~ '^[a-z][a-z0-9_]{0,39}$' THEN
            RAISE EXCEPTION 'Audit detail keys must be short snake_case names' USING ERRCODE = '22023';
        END IF;
        CASE jsonb_typeof(v_value)
            WHEN 'null', 'boolean', 'number' THEN
                NULL;
            WHEN 'string' THEN
                IF (v_value #>> '{}') !~ '^[A-Za-z0-9_.:/{}+-]{0,120}$' THEN
                    RAISE EXCEPTION 'Audit detail strings must be short machine values (no free text)'
                        USING ERRCODE = '22023';
                END IF;
            WHEN 'array' THEN
                IF jsonb_array_length(v_value) > 24 THEN
                    RAISE EXCEPTION 'Audit detail arrays are limited to 24 items' USING ERRCODE = '22023';
                END IF;
                FOR v_item IN SELECT e.value FROM jsonb_array_elements(v_value) AS e LOOP
                    IF jsonb_typeof(v_item) IN ('boolean', 'number') THEN
                        CONTINUE;
                    END IF;
                    IF jsonb_typeof(v_item) <> 'string'
                       OR (v_item #>> '{}') !~ '^[A-Za-z0-9_.:/{}+-]{0,120}$' THEN
                        RAISE EXCEPTION 'Audit detail arrays may hold only short machine values'
                            USING ERRCODE = '22023';
                    END IF;
                END LOOP;
            ELSE
                RAISE EXCEPTION 'Audit details must be flat (no nested objects)' USING ERRCODE = '22023';
        END CASE;
    END LOOP;
END;
$$;

-- ----------------------------------------------------------------------------
-- ops.audit_write — the only way an audit event is written
-- ----------------------------------------------------------------------------
-- * actor_id   = app.current_actor_id()  (the verified, transaction-local actor)
-- * actor_kind = derived from the session's database login (see above)
-- Neither can be passed in. Rows land in app.audit_events, which stays
-- append-only (trigger no_edit_audit) and unreadable for every API role.
--
-- An audit row is part of the caller's transaction: if that transaction rolls
-- back, the row goes with it. A refusal that must be remembered ('denied') is
-- therefore written by the API in its own transaction, after the check.
--
-- EXECUTE: edu_staff, edu_worker. Definer functions of other private schemas
-- call it as their owner (postgres); actor_kind still reflects the real login.
CREATE FUNCTION ops.audit_write(
    p_action text,
    p_target_kind text,
    p_target_id uuid,
    p_outcome text,
    p_details jsonb DEFAULT '{}'::jsonb
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_kind text := ops.actor_kind_for(session_user);
    v_details jsonb := COALESCE(p_details, '{}'::jsonb);
    v_id uuid;
BEGIN
    -- "<area>.<verb>" style code, e.g. staff.access, lesson_revision.submit
    IF p_action IS NULL OR char_length(p_action) > 100
       OR p_action !~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+){1,5}$' THEN
        RAISE EXCEPTION 'Audit action must be a dotted lower-case code' USING ERRCODE = '22023';
    END IF;
    IF p_target_kind IS NOT NULL AND p_target_kind !~ '^[a-z][a-z0-9_]{1,39}$' THEN
        RAISE EXCEPTION 'Audit target kind must be a short snake_case name' USING ERRCODE = '22023';
    END IF;
    IF p_target_id IS NOT NULL AND p_target_kind IS NULL THEN
        RAISE EXCEPTION 'An audit target id needs a target kind' USING ERRCODE = '22023';
    END IF;
    IF p_outcome IS NULL OR p_outcome NOT IN ('allowed', 'denied', 'error') THEN
        RAISE EXCEPTION 'Audit outcome must be allowed, denied or error' USING ERRCODE = '22023';
    END IF;
    PERFORM ops.check_audit_details(v_details);
    -- Everything a staff session does must be attributable to a person.
    IF v_kind = 'staff' AND v_actor IS NULL THEN
        RAISE EXCEPTION 'A staff audit event needs a verified actor' USING ERRCODE = '42501';
    END IF;

    INSERT INTO app.audit_events (actor_id, actor_kind, action, target_kind, target_id, outcome, details)
    VALUES (v_actor, v_kind, p_action, p_target_kind, p_target_id, p_outcome, v_details)
    RETURNING id INTO v_id;
    RETURN v_id;
END;
$$;

-- ----------------------------------------------------------------------------
-- staff: role checks against app.staff_roles (active rows only)
-- ----------------------------------------------------------------------------
-- A misspelt role name must fail loudly instead of silently never matching.
-- The list mirrors the CHECK constraint on app.staff_roles.role.
-- Internal: EXECUTE is granted to nobody.
CREATE FUNCTION staff.check_role_names(p_roles text[])
RETURNS void
LANGUAGE plpgsql IMMUTABLE
SET search_path = ''
AS $$
BEGIN
    IF p_roles IS NULL OR cardinality(p_roles) = 0 THEN
        RAISE EXCEPTION 'At least one staff role must be named' USING ERRCODE = '22023';
    END IF;
    IF cardinality(p_roles) > 8
       OR NOT (p_roles <@ ARRAY['editor', 'reviewer', 'publisher', 'admin'])
       OR array_position(p_roles, NULL) IS NOT NULL THEN
        RAISE EXCEPTION 'Unknown staff role' USING ERRCODE = '22023';
    END IF;
END;
$$;

-- The caller's active roles, sorted. Empty for a learner or with no actor.
CREATE FUNCTION staff.actor_roles()
RETURNS text[]
LANGUAGE sql STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT COALESCE(array_agg(sr.role ORDER BY sr.role), ARRAY[]::text[])
    FROM app.staff_roles sr
    WHERE sr.user_id = app.current_actor_id() AND sr.is_active
$$;

-- Does the actor hold at least one of the named roles (active)?
CREATE FUNCTION staff.actor_has_role(VARIADIC p_roles text[])
RETURNS boolean
LANGUAGE plpgsql STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    PERFORM staff.check_role_names(p_roles);
    RETURN EXISTS (
        SELECT 1 FROM app.staff_roles sr
        WHERE sr.user_id = app.current_actor_id()
          AND sr.is_active
          AND sr.role = ANY (p_roles)
    );
END;
$$;

-- Returns the actor id, or raises 42501 (insufficient_privilege) unless the
-- actor holds one of the named roles. Every staff.* workflow function starts
-- with this call. The message never says which roles would have been enough.
CREATE FUNCTION staff.require_role(VARIADIC p_roles text[])
RETURNS uuid
LANGUAGE plpgsql STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
BEGIN
    PERFORM staff.check_role_names(p_roles);
    IF v_actor IS NULL OR NOT EXISTS (
        SELECT 1 FROM app.staff_roles sr
        WHERE sr.user_id = v_actor
          AND sr.is_active
          AND sr.role = ANY (p_roles)
    ) THEN
        RAISE EXCEPTION 'A staff role is required for this action' USING ERRCODE = '42501';
    END IF;
    RETURN v_actor;
END;
$$;

-- ----------------------------------------------------------------------------
-- Privileges: explicit, and nothing by default
-- ----------------------------------------------------------------------------
-- PostgreSQL lets PUBLIC execute every new function unless told otherwise, and
-- that default cannot be changed per schema. Every migration that creates a
-- function in `ops` or `staff` therefore ends with these REVOKEs, followed by
-- the exact GRANTs. supabase/tests/100_platform_structure.sql fails otherwise.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA ops FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA staff FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION ops.audit_write(text, text, uuid, text, jsonb) TO edu_staff, edu_worker;
GRANT EXECUTE ON FUNCTION staff.actor_roles() TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.actor_has_role(text[]) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.require_role(text[]) TO edu_staff;
