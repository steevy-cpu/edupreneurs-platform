-- Mon Edupreneur 2.0 — hardening after the independent security review of the
-- shared platform interface (findings H1, M2, L1, L4; director ruling R-03).
--
-- H1. With `SET search_path = ''` PostgreSQL still resolves an unqualified TYPE
-- name through the session's temporary schema first. A session that can run SQL
-- of its choice on an API login could create a temporary domain called `text`
-- or `uuid` whose CHECK calls a temporary function, and a SECURITY DEFINER
-- function using that type name would then run that code as its owner.
-- Two independent measures:
--
--   (a) Nobody but the owner may create temporary objects in this database.
--       This closes the class for EVERY definer function, including the
--       verified ones in schema `app`, without touching them.
--   (b) Every function in `ops` and `staff` searches pg_catalog FIRST and the
--       temporary schema explicitly LAST (`pg_catalog, pg_temp`). Everything
--       that is not in pg_catalog stays schema-qualified, as before.
--
-- From here on, every new definer function is created with
--   SET search_path = pg_catalog, pg_temp
--
-- Nothing in schema `app` is created, altered or granted here.

-- ----------------------------------------------------------------------------
-- (a) No temporary objects for anyone but the database owner
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
    -- Supabase's own client roles never need temporary objects here either.
    EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM anon, authenticated, authenticator, service_role',
                   current_database());
END $$;

-- ----------------------------------------------------------------------------
-- L1. A superuser session is 'system', never 'staff'
-- ----------------------------------------------------------------------------
-- pg_has_role() is true for a superuser whatever the group, so maintenance
-- sessions were labelled 'staff' and could not write an audit event without an
-- actor. Superusers are recognised first.
CREATE OR REPLACE FUNCTION ops.actor_kind_for(p_role name)
RETURNS text
LANGUAGE sql STABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT CASE
        WHEN (SELECT r.rolsuper FROM pg_catalog.pg_roles r WHERE r.rolname = p_role) THEN 'system'
        WHEN pg_has_role(p_role, 'edu_staff', 'USAGE') THEN 'staff'
        WHEN pg_has_role(p_role, 'edu_worker', 'USAGE') THEN 'worker'
        WHEN pg_has_role(p_role, 'edu_api', 'USAGE') THEN 'user'
        ELSE 'system'
    END
$$;

-- L4. Lets a service check, on its own connection, which kind of login it
-- really has ('staff', 'worker', 'user' or 'system'), so that a pool pointed at
-- the wrong database login refuses to work instead of working differently.
-- EXECUTE: edu_staff, edu_worker.
CREATE FUNCTION ops.session_kind()
RETURNS text
LANGUAGE sql STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT ops.actor_kind_for(session_user)
$$;

-- ----------------------------------------------------------------------------
-- M2. Audit details: shorter strings
-- ----------------------------------------------------------------------------
-- THE CHECK BELOW IS A STRUCTURAL GUARD, NOT A PRIVACY FILTER. It cannot tell
-- an identifier from a one-word answer, a name, a phone number or a date of
-- birth. CALLERS MUST NEVER PASS A VALUE TYPED BY A LEARNER (answers, names,
-- messages, search terms) in the action, the target kind or the details —
-- only ids, enum codes, numbers and server-made timestamps.
--
-- String values are limited to 64 characters (enough for a uuid, a code or a
-- timestamp). The single exception is the key `route`, which may hold a route
-- template of up to 120 characters.
CREATE OR REPLACE FUNCTION ops.check_audit_details(p_details jsonb)
RETURNS void
LANGUAGE plpgsql IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_key text;
    v_value jsonb;
    v_item jsonb;
    v_keys integer := 0;
    v_max integer;
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
                v_max := 64;
                IF v_key = 'route' THEN
                    v_max := 120;
                END IF;
                IF (v_value #>> '{}') !~ '^[A-Za-z0-9_.:/{}+-]*$' OR char_length(v_value #>> '{}') > v_max THEN
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
                       OR (v_item #>> '{}') !~ '^[A-Za-z0-9_.:/{}+-]{0,64}$' THEN
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

COMMENT ON FUNCTION ops.audit_write(text, text, uuid, text, jsonb) IS
    'The only way an audit event is written. Actor and actor kind come from the session, never from the caller. NEVER pass a value typed by a learner (answer, name, message) in action, target kind or details: only ids, enum codes, numbers and server-made timestamps. The input checks are a structural guard, not a privacy filter.';

-- ----------------------------------------------------------------------------
-- (b) pg_catalog first, pg_temp last — for every function in ops and staff
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_function regprocedure;
BEGIN
    FOR v_function IN
        SELECT p.oid::regprocedure
        FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname IN ('ops', 'staff')
    LOOP
        EXECUTE format('ALTER FUNCTION %s SET search_path = pg_catalog, pg_temp', v_function);
    END LOOP;
END $$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA ops FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION ops.session_kind() TO edu_staff, edu_worker;
