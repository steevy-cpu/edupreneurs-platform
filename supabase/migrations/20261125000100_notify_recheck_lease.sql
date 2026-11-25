-- Mon Edupreneur 2.0 — notifications: re-check a lease just before delivery
--
-- Review finding L-2. notify.claim_due decides quiet hours once, at claim time. A
-- worker then attempts its claimed rows one after another, so an attempt can start
-- up to a lease later than the claim: inside a quiet window that began meanwhile,
-- or after the lease ran out. notify.recheck_lease is the worker's last question
-- before it hands a payload to an adapter:
--
--   'send'      the lease is still held, has not run out, and it is not quiet hours
--               for this learner on the database clock: deliver now;
--   'deferred'  quiet hours have started: the delivery goes back to 'pending' at the
--               end of the window, WITHOUT spending an attempt (attempt_count is
--               given back); the worker must not deliver;
--   'stale'     the lease token is not the current one, or the lease has run out:
--               nothing is written; the worker must not deliver. The next claim
--               records the lost lease, as before.
--
-- The clock is the database's, so the worker cannot choose the time. Executable by
-- edu_worker only (not by edu_api, edu_staff, PUBLIC, anon, authenticated).

CREATE FUNCTION notify.recheck_lease(p_outbox_id uuid, p_channel text, p_lease_token uuid)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_now timestamptz := clock_timestamp();
    v_delivery notify.deliveries%ROWTYPE;
    v_until timestamptz;
BEGIN
    IF p_outbox_id IS NULL OR p_channel IS NULL OR p_lease_token IS NULL THEN
        RAISE EXCEPTION 'notify.recheck_lease: outbox id, channel and lease token are required'
            USING ERRCODE = '22004';
    END IF;
    SELECT * INTO v_delivery FROM notify.deliveries d
    WHERE d.outbox_id = p_outbox_id AND d.channel = p_channel
    FOR UPDATE;
    IF NOT FOUND OR v_delivery.state <> 'leased' OR v_delivery.lease_token <> p_lease_token
       OR v_delivery.next_attempt_at IS NULL OR v_delivery.next_attempt_at <= v_now THEN
        RETURN 'stale';
    END IF;

    SELECT notify.quiet_until(v_now, o.recipient_id) INTO v_until
    FROM notify.outbox o WHERE o.id = p_outbox_id;
    IF v_until > v_now THEN
        UPDATE notify.deliveries SET state = 'pending', next_attempt_at = v_until, lease_token = NULL,
               attempt_count = attempt_count - 1, updated_at = v_now
        WHERE outbox_id = p_outbox_id AND channel = p_channel;
        RETURN 'deferred';
    END IF;
    RETURN 'send';
END;
$$;

REVOKE ALL ON FUNCTION notify.recheck_lease(uuid, text, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION notify.recheck_lease(uuid, text, uuid) TO edu_worker;
