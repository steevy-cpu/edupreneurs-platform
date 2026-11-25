-- Mon Edupreneur 2.0 — Word of the Day: wiring to the shared staff boundary (B1)
--
-- Needs 20261124010000_platform_roles_ops_staff.sql (roles edu_staff and
-- edu_worker, staff.require_role, ops.audit_write).
--
-- 1. The two seams of 20261124040200 get their final bodies:
--      vocab._require_staff -> staff.require_role
--      vocab._audit         -> ops.audit_write
--    After this migration nothing in schema `vocab` reads app.staff_roles for an
--    ACCESS decision or inserts into app.audit_events itself. (The integrity
--    triggers keep their own independent "reviewer holds an active role" check:
--    they must hold for every writer, whatever the access layer does.)
-- 2. EXECUTE on the staff-facing functions goes to edu_staff, and on the
--    schedule fill to edu_worker. Neither role gets a table privilege.
--
-- AUDIT CONTENT (ruling R-03): the callers pass identifiers, dates, numbers and
-- values of closed lists only — never a term, a definition, a note or any other
-- text a person typed. ops.audit_write additionally refuses free text by shape.

CREATE OR REPLACE FUNCTION vocab._require_staff(VARIADIC p_roles text[])
RETURNS uuid
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    -- Raises 42501 unless the verified actor holds one of the roles (active).
    RETURN staff.require_role(VARIADIC p_roles);
END;
$$;

CREATE OR REPLACE FUNCTION vocab._audit(
    p_action text, p_target_kind text, p_target_id uuid, p_details jsonb DEFAULT '{}'::jsonb)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    -- Same transaction as the change it describes: both commit or neither does.
    -- actor = app.current_actor_id(); actor_kind = derived from the session's
    -- database login by ops.audit_write (edu_staff_login -> 'staff').
    PERFORM ops.audit_write(p_action, p_target_kind, p_target_id, 'allowed',
                            COALESCE(p_details, '{}'::jsonb));
END;
$$;

-- CREATE OR REPLACE keeps existing privileges, but be explicit all the same.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA vocab FROM PUBLIC, anon, authenticated;

GRANT USAGE ON SCHEMA vocab TO edu_staff, edu_worker;

GRANT EXECUTE ON FUNCTION vocab.register_source(text, text, text, text) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.set_source_rights(uuid, text, text) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.create_word(text) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.create_draft(uuid, text, text, text, text, text, text, text, uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.update_draft(uuid, text, text, text, text, text, text, uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.set_audio(uuid, text, integer, bytea, text, integer, uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.remove_audio(uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.submit_revision(uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.review_revision(uuid, text, text) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.review_queue() TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.schedule_word(date, uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.unschedule_date(date) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.calendar(date, integer) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.staff_ensure_assignments(date, integer) TO edu_staff;
GRANT EXECUTE ON FUNCTION vocab.retire_word(uuid) TO edu_staff;

-- The background worker records upcoming days; it holds no staff role and
-- reaches nothing else in this schema.
GRANT EXECUTE ON FUNCTION vocab.ensure_assignments(date, integer) TO edu_worker;

-- edu_api is unchanged: vocab.daily_word(text) only.
