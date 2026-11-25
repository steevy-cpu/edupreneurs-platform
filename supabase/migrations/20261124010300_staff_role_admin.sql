-- Mon Edupreneur 2.0 — administration of staff roles (schema `staff`).
--
-- Who holds which staff role lives in app.staff_roles. Until now only the
-- database owner could change it. These functions let an `admin` do it, with
-- three rules that hold whatever the API does:
--
--   1. Only an active admin grants or revokes roles.
--   2. Nobody grants a role to themselves — not even an admin (an admin who
--      wants to review content must be given `reviewer` by another admin).
--   3. The last active admin cannot be revoked: staff administration can never
--      lock itself out through the API. (An admin MAY give up their own admin
--      role while another active admin remains.)
--
-- Revoking deactivates the row (is_active = false); the row itself is kept, as
-- is every audit event. All role changes are serialised by one advisory lock,
-- so two admins revoking each other at the same moment cannot both succeed.
--
-- BOOTSTRAP: the very first admin of an environment cannot come from here. It
-- is inserted once by the database owner (see docs, "first admin").
--
-- Nothing in schema `app` is created, altered or granted here.

-- Internal: one writer at a time for role changes. EXECUTE granted to nobody.
CREATE FUNCTION staff.lock_role_changes()
RETURNS void
LANGUAGE sql
SET search_path = ''
AS $$
    SELECT pg_advisory_xact_lock(hashtextextended('staff.role_changes', 0))
$$;

-- Internal: the target must be a real, permanent sign-in account.
CREATE FUNCTION staff.check_role_target(p_user_id uuid, p_role text)
RETURNS void
LANGUAGE plpgsql STABLE
SET search_path = ''
AS $$
BEGIN
    IF p_role IS NULL OR p_role NOT IN ('editor', 'reviewer', 'publisher', 'admin') THEN
        RAISE EXCEPTION 'role_invalid' USING ERRCODE = 'ED422';
    END IF;
    IF p_user_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM auth.users u
        WHERE u.id = p_user_id AND u.deleted_at IS NULL AND NOT COALESCE(u.is_anonymous, false)
    ) THEN
        RAISE EXCEPTION 'user_not_found' USING ERRCODE = 'ED404';
    END IF;
END;
$$;

-- Gives p_user_id the role (or reactivates it). Returns true when something
-- changed; granting a role that is already active is a no-op without an audit
-- event.
CREATE FUNCTION staff.grant_role(p_user_id uuid, p_role text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := staff.require_role('admin');
BEGIN
    PERFORM staff.check_role_target(p_user_id, p_role);
    IF p_user_id = v_actor THEN
        RAISE EXCEPTION 'cannot_grant_to_self' USING ERRCODE = '42501';
    END IF;
    PERFORM staff.lock_role_changes();
    -- The lock may have waited for another admin's change: am I still an admin?
    v_actor := staff.require_role('admin');
    IF EXISTS (SELECT 1 FROM app.staff_roles sr
               WHERE sr.user_id = p_user_id AND sr.role = p_role AND sr.is_active) THEN
        RETURN false;
    END IF;
    INSERT INTO app.staff_roles (user_id, role, granted_by, is_active, granted_at)
    VALUES (p_user_id, p_role, v_actor, true, now())
    ON CONFLICT (user_id, role)
    DO UPDATE SET is_active = true, granted_by = EXCLUDED.granted_by, granted_at = EXCLUDED.granted_at;
    PERFORM ops.audit_write('staff_role.grant', 'user', p_user_id, 'allowed',
        jsonb_build_object('role', p_role));
    RETURN true;
END;
$$;

-- Deactivates the role. Returns true when something changed.
CREATE FUNCTION staff.revoke_role(p_user_id uuid, p_role text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := staff.require_role('admin');
    v_active boolean;
BEGIN
    IF p_role IS NULL OR p_role NOT IN ('editor', 'reviewer', 'publisher', 'admin') THEN
        RAISE EXCEPTION 'role_invalid' USING ERRCODE = 'ED422';
    END IF;
    PERFORM staff.lock_role_changes();
    v_actor := staff.require_role('admin');
    SELECT sr.is_active INTO v_active
    FROM app.staff_roles sr WHERE sr.user_id = p_user_id AND sr.role = p_role FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'role_not_assigned' USING ERRCODE = 'ED404';
    END IF;
    IF NOT v_active THEN
        RETURN false;
    END IF;
    IF p_role = 'admin' AND NOT EXISTS (
        SELECT 1 FROM app.staff_roles sr
        WHERE sr.role = 'admin' AND sr.is_active AND sr.user_id <> p_user_id
    ) THEN
        RAISE EXCEPTION 'last_admin' USING ERRCODE = 'ED409';
    END IF;
    UPDATE app.staff_roles SET is_active = false WHERE user_id = p_user_id AND role = p_role;
    PERFORM ops.audit_write('staff_role.revoke', 'user', p_user_id, 'allowed',
        jsonb_build_object('role', p_role));
    RETURN true;
END;
$$;

-- Every role assignment, active or not (ids only: no e-mail addresses).
CREATE FUNCTION staff.list_role_assignments(p_limit integer)
RETURNS jsonb
LANGUAGE plpgsql STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := staff.require_role('admin');
    v_limit integer := LEAST(GREATEST(COALESCE(p_limit, 200), 1), 500);
BEGIN
    RETURN COALESCE((
        SELECT jsonb_agg(to_jsonb(x) ORDER BY x.user_id, x.role)
        FROM (
            SELECT sr.user_id, sr.role, sr.is_active, sr.granted_by, sr.granted_at
            FROM app.staff_roles sr
            ORDER BY sr.user_id, sr.role
            LIMIT v_limit
        ) AS x), '[]'::jsonb);
END;
$$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA staff FROM PUBLIC, anon, authenticated;
-- REVOKE ... ON ALL FUNCTIONS leaves existing grants to edu_staff in place
-- (it names only PUBLIC, anon, authenticated); only the new ones are added.
GRANT EXECUTE ON FUNCTION staff.grant_role(uuid, text) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.revoke_role(uuid, text) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.list_role_assignments(integer) TO edu_staff;
