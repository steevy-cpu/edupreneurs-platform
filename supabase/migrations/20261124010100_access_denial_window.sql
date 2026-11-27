-- Mon Edupreneur 2.0 — bound on persisted "access denied" audit events.
--
-- PROBLEM: every refused request on a staff route appended one row to
-- app.audit_events. Any signed-in account (every learner) can repeat a refused
-- call, so the audit table could be grown without limit.
--
-- RULE: at most ONE persisted `staff.access` / `denied` event per actor per
-- 60-second window. Further refusals inside the window are only counted; the
-- next persisted event reports that count as `suppressed_before`, so the audit
-- trail still shows that (and roughly how hard) an account kept trying.
-- Storage is one small row per account that was ever refused.
--
-- Nothing in schema `app` is created, altered or granted here.

CREATE TABLE ops.access_denial_windows (
    -- Deliberately no FK to auth.users: like audit rows, this must never block
    -- account deletion. ops.erase_learner() removes the row.
    actor_id uuid PRIMARY KEY,
    window_started_at timestamptz NOT NULL DEFAULT now(),
    suppressed integer NOT NULL DEFAULT 0 CHECK (suppressed >= 0)
);
ALTER TABLE ops.access_denial_windows ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE ops.access_denial_windows FROM PUBLIC, anon, authenticated;
COMMENT ON TABLE ops.access_denial_windows IS
    'One row per account that was refused on a staff route: start of the current 60 s window and the number of refusals not written to the audit log since. No policy, no grant: written only by ops.audit_access_denied().';

-- Records a refusal for the transaction's actor. Returns the id of the audit
-- event, or NULL when the refusal fell inside the current window and was only
-- counted. The caller must commit this in its own transaction (the API does),
-- because the refusal itself is then reported to the client as an error.
-- EXECUTE: edu_staff.
CREATE FUNCTION ops.audit_access_denied(p_details jsonb DEFAULT '{}'::jsonb)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_details jsonb := COALESCE(p_details, '{}'::jsonb);
    v_started timestamptz;
    v_suppressed integer;
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'A refusal can only be recorded for a verified actor' USING ERRCODE = '42501';
    END IF;

    INSERT INTO ops.access_denial_windows (actor_id, window_started_at, suppressed)
    VALUES (v_actor, now(), 0)
    ON CONFLICT (actor_id) DO NOTHING;
    IF FOUND THEN
        RETURN ops.audit_write('staff.access', NULL, NULL, 'denied', v_details);
    END IF;

    -- The row lock serialises concurrent refusals of the same account.
    SELECT w.window_started_at, w.suppressed INTO v_started, v_suppressed
    FROM ops.access_denial_windows w
    WHERE w.actor_id = v_actor
    FOR UPDATE;

    IF v_started > now() - interval '60 seconds' THEN
        UPDATE ops.access_denial_windows SET suppressed = suppressed + 1 WHERE actor_id = v_actor;
        RETURN NULL;
    END IF;

    UPDATE ops.access_denial_windows
    SET window_started_at = now(), suppressed = 0
    WHERE actor_id = v_actor;
    IF v_suppressed > 0 THEN
        v_details := v_details || jsonb_build_object('suppressed_before', v_suppressed);
    END IF;
    RETURN ops.audit_write('staff.access', NULL, NULL, 'denied', v_details);
END;
$$;

-- Erasure hook (cross-domain convention): removes what `ops` stores per
-- account. Audit events are NOT touched here: whether and when they are erased
-- or anonymised is a retention decision that has not been taken.
-- EXECUTE: nobody (called by the account-erasure orchestrator as owner).
CREATE FUNCTION ops.erase_learner(p_user_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_windows integer;
BEGIN
    DELETE FROM ops.access_denial_windows WHERE actor_id = p_user_id;
    GET DIAGNOSTICS v_windows = ROW_COUNT;
    RETURN jsonb_build_object('access_denial_windows', v_windows);
END;
$$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA ops FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION ops.audit_write(text, text, uuid, text, jsonb) TO edu_staff, edu_worker;
GRANT EXECUTE ON FUNCTION ops.audit_access_denied(jsonb) TO edu_staff;
