-- Mon Edupreneur 2.0 — background job queue for the worker (schema `ops`).
--
-- The table app.background_jobs has existed since the core schema, reserved for
-- "the future worker" and granted to nobody. These SECURITY DEFINER functions
-- are the only way in: the worker login (edu_worker) holds no table privilege.
--
-- DELIVERY MODEL: at-least-once, with a lease.
--   * claim_jobs leases ready jobs with FOR UPDATE SKIP LOCKED, so two workers
--     never get the same job, and counts the attempt at that moment.
--   * A worker that dies simply stops renewing its lease. When the lease has
--     run out, the next claim takes the job again (one more attempt).
--   * complete / fail / heartbeat only act for the worker that holds the lease.
--     A worker that lost its lease gets `false` back and must stop.
--   * A failed attempt goes back to the queue with exponential backoff
--     (5 s, 10 s, 20 s … capped at 15 min). After max_attempts the job is 'dead'
--     and an audit event `job.dead` is written.
-- Handlers must therefore be idempotent.
--
-- PRIVACY: a payload carries identifiers and codes only — never a learner's
-- text. On failure only an error CLASS name is stored; no message, no payload
-- dump, no stack trace.
--
-- Nothing in schema `app` is created, altered or granted here. No schedule is
-- installed: nothing runs unless a worker process is started.

-- Internal: argument checks shared by the functions below.
CREATE FUNCTION ops.check_worker_id(p_worker_id text)
RETURNS void
LANGUAGE plpgsql IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF p_worker_id IS NULL OR p_worker_id !~ '^[A-Za-z0-9_.:-]{3,100}$' THEN
        RAISE EXCEPTION 'Worker id must be 3-100 characters of [A-Za-z0-9_.:-]' USING ERRCODE = '22023';
    END IF;
END;
$$;

CREATE FUNCTION ops.check_lease_seconds(p_lease_seconds integer)
RETURNS void
LANGUAGE plpgsql IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF p_lease_seconds IS NULL OR p_lease_seconds NOT BETWEEN 1 AND 3600 THEN
        RAISE EXCEPTION 'Lease must be between 1 and 3600 seconds' USING ERRCODE = '22023';
    END IF;
END;
$$;

-- Delay before attempt number (p_attempts + 1): 5 s doubling, capped at 15 min.
CREATE FUNCTION ops.job_backoff(p_attempts integer)
RETURNS interval
LANGUAGE sql IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT make_interval(secs => LEAST(900, 5 * power(2, LEAST(GREATEST(p_attempts, 1), 20) - 1)))
$$;

-- ----------------------------------------------------------------------------
-- Enqueue (idempotent when a key is given)
-- ----------------------------------------------------------------------------
-- Returns the job id. With p_idempotency_key, a second call with the same key
-- returns the id of the FIRST job and changes nothing — whatever its state.
-- EXECUTE: edu_worker, edu_staff. Other schemas' definer functions call it as
-- owner.
CREATE FUNCTION ops.enqueue_job(
    p_kind text,
    p_payload jsonb DEFAULT '{}'::jsonb,
    p_idempotency_key text DEFAULT NULL,
    p_run_after timestamptz DEFAULT NULL,
    p_max_attempts integer DEFAULT 5
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_payload jsonb := COALESCE(p_payload, '{}'::jsonb);
    v_id uuid;
BEGIN
    IF p_kind IS NULL OR p_kind !~ '^[a-z0-9_]{3,60}$' THEN
        RAISE EXCEPTION 'Job kind must be 3-60 characters of [a-z0-9_]' USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(v_payload) <> 'object' OR octet_length(v_payload::text) > 8192 THEN
        RAISE EXCEPTION 'Job payload must be a JSON object of at most 8192 bytes' USING ERRCODE = '22023';
    END IF;
    IF p_idempotency_key IS NOT NULL AND p_idempotency_key !~ '^[A-Za-z0-9_.:/-]{1,200}$' THEN
        RAISE EXCEPTION 'Idempotency key must be 1-200 characters of [A-Za-z0-9_.:/-]' USING ERRCODE = '22023';
    END IF;
    IF p_max_attempts IS NULL OR p_max_attempts NOT BETWEEN 1 AND 20 THEN
        RAISE EXCEPTION 'max_attempts must be between 1 and 20' USING ERRCODE = '22023';
    END IF;

    INSERT INTO app.background_jobs (kind, payload, idempotency_key, run_after, max_attempts)
    VALUES (p_kind, v_payload, p_idempotency_key, COALESCE(p_run_after, now()), p_max_attempts)
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id INTO v_id;
    IF v_id IS NULL THEN
        SELECT j.id INTO v_id FROM app.background_jobs j WHERE j.idempotency_key = p_idempotency_key;
    END IF;
    RETURN v_id;
END;
$$;

-- ----------------------------------------------------------------------------
-- Claim
-- ----------------------------------------------------------------------------
-- Leases up to p_limit jobs of the given kinds to p_worker_id for
-- p_lease_seconds: jobs that are due, and jobs whose previous lease ran out
-- (their worker is presumed dead). Each claim counts as one attempt. A job whose
-- lease ran out on its LAST attempt is not handed out again: it becomes 'dead'.
-- p_worker_id must be unique per worker PROCESS (it is the fencing token).
-- EXECUTE: edu_worker.
CREATE FUNCTION ops.claim_jobs(
    p_worker_id text, p_kinds text[], p_limit integer, p_lease_seconds integer
)
RETURNS TABLE (
    job_id uuid, kind text, payload jsonb, attempt integer, max_attempts integer, lease_until timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_dead record;
BEGIN
    PERFORM ops.check_worker_id(p_worker_id);
    PERFORM ops.check_lease_seconds(p_lease_seconds);
    IF p_kinds IS NULL OR cardinality(p_kinds) NOT BETWEEN 1 AND 50 THEN
        RAISE EXCEPTION 'Between 1 and 50 job kinds must be named' USING ERRCODE = '22023';
    END IF;
    IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN
        RAISE EXCEPTION 'Limit must be between 1 and 100' USING ERRCODE = '22023';
    END IF;

    FOR v_dead IN
        WITH expired AS (
            SELECT j.id FROM app.background_jobs j
            WHERE j.status = 'leased' AND j.lease_until < now()
              AND j.attempts >= j.max_attempts AND j.kind = ANY (p_kinds)
            ORDER BY j.id
            FOR UPDATE SKIP LOCKED
        )
        UPDATE app.background_jobs j
        SET status = 'dead', error_class = 'LeaseExpired', lease_until = NULL, leased_by = NULL,
            updated_at = now()
        FROM expired WHERE j.id = expired.id
        RETURNING j.id, j.kind, j.attempts
    LOOP
        PERFORM ops.audit_write('job.dead', 'background_job', v_dead.id, 'error',
            jsonb_build_object('kind', v_dead.kind, 'attempts', v_dead.attempts,
                               'error_class', 'LeaseExpired'));
    END LOOP;

    RETURN QUERY
    WITH picked AS (
        SELECT j.id FROM app.background_jobs j
        WHERE j.kind = ANY (p_kinds)
          AND ((j.status = 'queued' AND j.run_after <= now())
            OR (j.status = 'leased' AND j.lease_until < now()))
        ORDER BY j.run_after, j.created_at, j.id
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE app.background_jobs j
    SET status = 'leased', attempts = j.attempts + 1, leased_by = p_worker_id,
        lease_until = now() + make_interval(secs => p_lease_seconds), updated_at = now()
    FROM picked WHERE j.id = picked.id
    RETURNING j.id, j.kind, j.payload, j.attempts, j.max_attempts, j.lease_until;
END;
$$;

-- ----------------------------------------------------------------------------
-- Heartbeat, complete, fail — only for the worker that holds the lease
-- ----------------------------------------------------------------------------
-- Extends the lease. false = the lease is no longer yours: stop working on it.
CREATE FUNCTION ops.heartbeat_job(p_job_id uuid, p_worker_id text, p_lease_seconds integer)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    PERFORM ops.check_worker_id(p_worker_id);
    PERFORM ops.check_lease_seconds(p_lease_seconds);
    UPDATE app.background_jobs j
    SET lease_until = now() + make_interval(secs => p_lease_seconds), updated_at = now()
    WHERE j.id = p_job_id AND j.status = 'leased' AND j.leased_by = p_worker_id;
    RETURN FOUND;
END;
$$;

-- Marks the job done. false = the lease was lost (the job was, or will be,
-- handed to another worker); nothing is changed.
CREATE FUNCTION ops.complete_job(p_job_id uuid, p_worker_id text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    PERFORM ops.check_worker_id(p_worker_id);
    UPDATE app.background_jobs j
    SET status = 'completed', lease_until = NULL, leased_by = NULL, error_class = NULL,
        updated_at = now()
    WHERE j.id = p_job_id AND j.status = 'leased' AND j.leased_by = p_worker_id;
    RETURN FOUND;
END;
$$;

-- Records a failed attempt. Returns the new status: 'queued' (will be retried
-- after the backoff), 'dead' (no attempts left; audited), or NULL when the
-- lease was lost. Only the error CLASS is stored.
CREATE FUNCTION ops.fail_job(p_job_id uuid, p_worker_id text, p_error_class text)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_job record;
    v_error text := p_error_class;
BEGIN
    PERFORM ops.check_worker_id(p_worker_id);
    -- Never lose a failure over a badly formed class name, and never store text.
    IF v_error IS NULL OR v_error !~ '^[A-Za-z_][A-Za-z0-9_.]{0,63}$' THEN
        v_error := 'UnnamedError';
    END IF;
    SELECT j.id, j.kind, j.attempts, j.max_attempts INTO v_job
    FROM app.background_jobs j
    WHERE j.id = p_job_id AND j.status = 'leased' AND j.leased_by = p_worker_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF v_job.attempts >= v_job.max_attempts THEN
        UPDATE app.background_jobs
        SET status = 'dead', error_class = v_error, lease_until = NULL, leased_by = NULL, updated_at = now()
        WHERE id = p_job_id;
        PERFORM ops.audit_write('job.dead', 'background_job', p_job_id, 'error',
            jsonb_build_object('kind', v_job.kind, 'attempts', v_job.attempts, 'error_class', v_error));
        RETURN 'dead';
    END IF;
    UPDATE app.background_jobs
    SET status = 'queued', error_class = v_error, lease_until = NULL, leased_by = NULL,
        run_after = now() + ops.job_backoff(v_job.attempts), updated_at = now()
    WHERE id = p_job_id;
    RETURN 'queued';
END;
$$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA ops FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION ops.enqueue_job(text, jsonb, text, timestamptz, integer) TO edu_worker, edu_staff;
GRANT EXECUTE ON FUNCTION ops.claim_jobs(text, text[], integer, integer) TO edu_worker;
GRANT EXECUTE ON FUNCTION ops.heartbeat_job(uuid, text, integer) TO edu_worker;
GRANT EXECUTE ON FUNCTION ops.complete_job(uuid, text) TO edu_worker;
GRANT EXECUTE ON FUNCTION ops.fail_job(uuid, text, text) TO edu_worker;
