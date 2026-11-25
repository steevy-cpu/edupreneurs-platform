-- Mon Edupreneur 2.0 — schema `account`: wiring to the shared platform interface (B1)
--
-- Overnight mission 2026-11-24, lane IDENTITY. Needs the staff lane's
-- 20261124010000_platform_roles_ops_staff.sql (roles edu_staff / edu_worker,
-- ops.audit_write, staff.require_role).
--
--   1. account.audit_seam() now writes through ops.audit_write().
--   2. The erasure orchestrator gets its two executors:
--        * edu_worker — EXECUTE on account.erase_learner(uuid);
--        * a staff ADMINISTRATOR — account.staff_erase_learner(uuid), which
--          calls staff.require_role('admin') before anything else.
--      Nobody else: not edu_api (a learner cannot erase anyone, themselves
--      included — they file a request), not another staff role, not a staff
--      session without a verified actor, not the Data API roles.
--
-- Nothing in schemas app, ops or staff is created, altered or granted.

-- ============================================================================
-- 1. Audit
-- ============================================================================
-- Same signature and same call sites as before. The event is written in the
-- caller's transaction and rolls back with it.
--
-- WHAT CALLERS MAY PASS (ruling R-03): ids, enum codes, field NAMES and
-- numbers. Never a display name, an answer or any other value typed by a
-- person. Every call site in this schema passes literals, a row id, a list of
-- column names chosen by this code, or counts.
--
-- Attribution is decided by ops.audit_write, not here: the actor is
-- app.current_actor_id() and the actor kind comes from the database login
-- (learner API -> 'user', staff API -> 'staff', worker -> 'worker').
CREATE OR REPLACE FUNCTION account.audit_seam(
    p_action text,
    p_target_kind text,
    p_target_id uuid,
    p_outcome text,
    p_details jsonb DEFAULT '{}'::jsonb
)
RETURNS uuid
LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    RETURN ops.audit_write(p_action, p_target_kind, p_target_id, p_outcome, p_details);
END;
$$;

-- ============================================================================
-- 2. Erasure executors
-- ============================================================================
-- A staff administrator erases a learner (for example on a request that did
-- not come through the app). The role check is the first statement; the
-- erasure itself is the same function the worker runs, with the same refusals
-- (it will not erase an account that has staff records, so an administrator
-- cannot erase themselves or a colleague through it).
CREATE FUNCTION account.staff_erase_learner(p_user_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    PERFORM staff.require_role('admin');
    RETURN account.erase_learner(p_user_id);
END;
$$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA account FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA account TO edu_worker, edu_staff;
GRANT EXECUTE ON FUNCTION account.erase_learner(uuid) TO edu_worker;
GRANT EXECUTE ON FUNCTION account.staff_erase_learner(uuid) TO edu_staff;
-- edu_worker and edu_staff get nothing else in this schema: no table
-- privilege, no other function. edu_api's grants are unchanged.
