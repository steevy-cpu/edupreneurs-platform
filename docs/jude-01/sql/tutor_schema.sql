-- =============================================================================
-- Jude-01 — usage ledger and spending limits.  PROPOSAL, NOT A MIGRATION.
--
-- This file is deliberately NOT in supabase/migrations. It is applied only to
-- throwaway databases by tests/tutor_pg. Turning it into a migration is a
-- Jude-02 step that needs the owner's limits, the staff/worker roles (#4) and
-- the account-erasure orchestrator (#5).
--
-- Requires (already on main): schema "app", app.current_actor_id(), role edu_api.
--
-- DESIGN
--   * Money is bigint micro-USD (millionths of a US dollar). No floats.
--   * The API role gets NO table privilege here. It may only EXECUTE five
--     SECURITY DEFINER functions, which identify the learner themselves through
--     app.current_actor_id() — there is no learner_id parameter to forge.
--   * Every limit is checked and the hold recorded in ONE transaction, after
--     taking row locks in one fixed order:
--         global month counter -> learner month counter -> learner day counter
--     Two requests can therefore never both pass a check that only one fits.
--     Invariant:  spent_micro + reserved_micro <= limit   for every counter.
--   * What is stored: ids, counters, token counts, amounts, model and prompt
--     version, an outcome CODE. There is no column that could hold a student's
--     words or a model's answer, and "outcome" is constrained to a code shape.
-- =============================================================================

CREATE SCHEMA tutor;
REVOKE ALL ON SCHEMA tutor FROM PUBLIC;
COMMENT ON SCHEMA tutor IS
    'Jude usage ledger and budgets. No conversation text. Reached only through tutor.* functions.';

-- ---------------------------------------------------------------------------
-- Policy: one row. Starts PAUSED with every limit at zero, so applying this
-- schema enables nothing; the owner has to set limits and unpause deliberately.
-- ---------------------------------------------------------------------------
CREATE TABLE tutor.policy (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    paused boolean NOT NULL DEFAULT true,
    learner_daily_requests integer NOT NULL DEFAULT 0 CHECK (learner_daily_requests >= 0),
    learner_daily_micro bigint NOT NULL DEFAULT 0 CHECK (learner_daily_micro >= 0),
    learner_monthly_micro bigint NOT NULL DEFAULT 0 CHECK (learner_monthly_micro >= 0),
    global_monthly_micro bigint NOT NULL DEFAULT 0 CHECK (global_monthly_micro >= 0),
    max_concurrent_per_learner integer NOT NULL DEFAULT 1 CHECK (max_concurrent_per_learner >= 1),
    max_concurrent_global integer NOT NULL DEFAULT 20 CHECK (max_concurrent_global >= 1),
    reservation_ttl_s integer NOT NULL DEFAULT 120 CHECK (reservation_ttl_s >= 1),
    budget_timezone text NOT NULL DEFAULT 'America/Port-au-Prince',
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid
);
INSERT INTO tutor.policy DEFAULT VALUES;

-- ---------------------------------------------------------------------------
-- Prices: append-only. A price change is a new price_version, never an UPDATE,
-- so any ledger row can be re-costed from the version it names.
-- ---------------------------------------------------------------------------
CREATE TABLE tutor.price_versions (
    price_version text NOT NULL CHECK (price_version ~ '^[a-z0-9._-]{1,80}$'),
    model text NOT NULL CHECK (char_length(model) BETWEEN 1 AND 200),
    input_micro_per_mtok bigint NOT NULL CHECK (input_micro_per_mtok >= 0),
    output_micro_per_mtok bigint NOT NULL CHECK (output_micro_per_mtok >= 0),
    effective_from timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (price_version, model)
);

CREATE FUNCTION tutor.price_versions_are_immutable()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    RAISE EXCEPTION 'tutor.price_versions is append-only' USING ERRCODE = '55000';
END $$;

CREATE TRIGGER price_versions_immutable
    BEFORE UPDATE OR DELETE ON tutor.price_versions
    FOR EACH ROW EXECUTE FUNCTION tutor.price_versions_are_immutable();

-- ---------------------------------------------------------------------------
-- The ledger: one row per tutoring request that reached the budget.
-- learner_id has no foreign key on purpose (like app.audit_events.actor_id):
-- erasure is done by tutor.erase_learner(), called by the erasure orchestrator.
-- ---------------------------------------------------------------------------
CREATE TABLE tutor.usage_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    learner_id uuid NOT NULL,
    request_key uuid NOT NULL,
    status text NOT NULL CHECK (status IN ('reserved', 'settled', 'released', 'expired')),
    usage_day date NOT NULL,
    usage_month date NOT NULL,
    reserved_micro bigint NOT NULL CHECK (reserved_micro >= 0),
    spent_micro bigint NOT NULL DEFAULT 0 CHECK (spent_micro >= 0),
    input_tokens integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    attempts smallint NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    -- A code such as 'answered' or 'tutor_provider_timeout'. The CHECK makes it
    -- impossible to park free text (a question, an answer) in this column.
    outcome text CHECK (outcome ~ '^[a-z][a-z0-9_]{1,59}$'),
    provider text CHECK (provider ~ '^[a-z0-9._-]{1,40}$'),
    model text CHECK (model ~ '^[A-Za-z0-9._:/-]{1,200}$'),
    price_version text CHECK (price_version ~ '^[a-z0-9._-]{1,80}$'),
    prompt_version text CHECK (prompt_version ~ '^[a-z0-9._-]{1,80}$'),
    lesson_revision_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    finished_at timestamptz,
    UNIQUE (learner_id, request_key)
);
CREATE INDEX usage_requests_in_flight ON tutor.usage_requests (expires_at)
    WHERE status = 'reserved';
CREATE INDEX usage_requests_learner_in_flight ON tutor.usage_requests (learner_id)
    WHERE status = 'reserved';
CREATE INDEX usage_requests_created ON tutor.usage_requests (created_at);

CREATE TABLE tutor.budget_counters (
    scope text NOT NULL CHECK (scope IN ('global', 'learner')),
    -- The all-zero id stands for "everyone" on global rows (keeps the key simple).
    learner_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000',
    period_kind text NOT NULL CHECK (period_kind IN ('day', 'month')),
    period_start date NOT NULL,
    reserved_micro bigint NOT NULL DEFAULT 0 CHECK (reserved_micro >= 0),
    spent_micro bigint NOT NULL DEFAULT 0 CHECK (spent_micro >= 0),
    request_count integer NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    PRIMARY KEY (scope, learner_id, period_kind, period_start),
    CHECK ((scope = 'global') = (learner_id = '00000000-0000-0000-0000-000000000000'))
);

-- Privileged operations on the tutor. When the staff boundary (#4) is merged
-- these writes should go to app.audit_events instead; kept local so this
-- proposal stands alone.
CREATE TABLE tutor.admin_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid,
    action text NOT NULL CHECK (action ~ '^[a-z][a-z0-9_.]{2,79}$'),
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE tutor.policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE tutor.price_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE tutor.usage_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE tutor.budget_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE tutor.admin_audit ENABLE ROW LEVEL SECURITY;
-- No policies: with RLS on and no policy, a role that somehow got a table
-- privilege would still see nothing.

-- ---------------------------------------------------------------------------
-- Internal helpers (not granted to the API role)
-- ---------------------------------------------------------------------------
CREATE FUNCTION tutor._actor()
RETURNS uuid LANGUAGE plpgsql STABLE SET search_path = '' AS $$
DECLARE v_actor uuid := app.current_actor_id();
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'tutor: no authenticated learner in this transaction'
            USING ERRCODE = '42501';
    END IF;
    RETURN v_actor;
END $$;

-- The limit checks rely on each statement seeing what was committed by the
-- transaction that held the lock before it. That is READ COMMITTED behaviour.
CREATE FUNCTION tutor._require_read_committed()
RETURNS void LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'tutor budget functions must run at READ COMMITTED isolation'
            USING ERRCODE = '25001';
    END IF;
END $$;

-- Create the counter row if needed and lock it until the transaction ends.
CREATE FUNCTION tutor._lock_counter(p_scope text, p_learner uuid, p_kind text, p_start date)
RETURNS tutor.budget_counters LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE v_row tutor.budget_counters;
BEGIN
    INSERT INTO tutor.budget_counters (scope, learner_id, period_kind, period_start)
    VALUES (p_scope, p_learner, p_kind, p_start)
    ON CONFLICT DO NOTHING;
    SELECT * INTO STRICT v_row FROM tutor.budget_counters
    WHERE scope = p_scope AND learner_id = p_learner
      AND period_kind = p_kind AND period_start = p_start
    FOR UPDATE;
    RETURN v_row;
END $$;

-- Close a reservation: move its hold out of "reserved" and add what was spent.
-- The caller must already hold the three counter locks AND the request row lock.
CREATE FUNCTION tutor._finish(
    p_request tutor.usage_requests, p_status text, p_spent bigint, p_counts boolean
) RETURNS void LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE v_zero constant uuid := '00000000-0000-0000-0000-000000000000';
BEGIN
    UPDATE tutor.budget_counters
       SET reserved_micro = reserved_micro - p_request.reserved_micro,
           spent_micro = spent_micro + p_spent
     WHERE scope = 'global' AND learner_id = v_zero
       AND period_kind = 'month' AND period_start = p_request.usage_month;
    UPDATE tutor.budget_counters
       SET reserved_micro = reserved_micro - p_request.reserved_micro,
           spent_micro = spent_micro + p_spent
     WHERE scope = 'learner' AND learner_id = p_request.learner_id
       AND period_kind = 'month' AND period_start = p_request.usage_month;
    UPDATE tutor.budget_counters
       SET reserved_micro = reserved_micro - p_request.reserved_micro,
           spent_micro = spent_micro + p_spent,
           -- The request was counted when it was reserved; give that back if it
           -- does not count (provider failure, release).
           request_count = request_count - CASE WHEN p_counts THEN 0 ELSE 1 END
     WHERE scope = 'learner' AND learner_id = p_request.learner_id
       AND period_kind = 'day' AND period_start = p_request.usage_day;
    UPDATE tutor.usage_requests
       SET status = p_status, spent_micro = p_spent, finished_at = clock_timestamp()
     WHERE id = p_request.id;
END $$;

-- Lock the counters of one ledger row in the canonical order.
CREATE FUNCTION tutor._lock_counters_of(p_learner uuid, p_day date, p_month date)
RETURNS void LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    PERFORM tutor._lock_counter('global', '00000000-0000-0000-0000-000000000000', 'month', p_month);
    PERFORM tutor._lock_counter('learner', p_learner, 'month', p_month);
    PERFORM tutor._lock_counter('learner', p_learner, 'day', p_day);
END $$;

-- ---------------------------------------------------------------------------
-- API-callable functions
-- ---------------------------------------------------------------------------
CREATE FUNCTION tutor.is_paused()
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT paused FROM tutor.policy
$$;

-- Hold p_estimate_micro for the calling learner, or say which limit refused it.
-- outcome: reserved | paused | duplicate | in_progress | learner_concurrency |
--          global_concurrency | learner_daily_requests | learner_daily_budget |
--          learner_monthly_budget | global_budget
CREATE FUNCTION tutor.reserve(p_request_key uuid, p_estimate_micro bigint)
RETURNS TABLE (outcome text, reservation_id uuid, reserved_micro bigint, expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
#variable_conflict use_column
DECLARE
    v_actor uuid := tutor._actor();
    v_zero constant uuid := '00000000-0000-0000-0000-000000000000';
    v_policy tutor.policy;
    v_now timestamptz;
    v_day date;
    v_month date;
    v_global tutor.budget_counters;
    v_learner_month tutor.budget_counters;
    v_learner_day tutor.budget_counters;
    v_existing tutor.usage_requests;
    v_stale tutor.usage_requests;
    v_id uuid;
    v_expires timestamptz;
    v_refusal text;
BEGIN
    PERFORM tutor._require_read_committed();
    IF p_request_key IS NULL OR p_estimate_micro IS NULL OR p_estimate_micro < 0 THEN
        RAISE EXCEPTION 'tutor.reserve: invalid arguments' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO STRICT v_policy FROM tutor.policy;
    IF v_policy.paused THEN
        RETURN QUERY SELECT 'paused'::text, NULL::uuid, NULL::bigint, NULL::timestamptz;
        RETURN;
    END IF;

    v_now := clock_timestamp();
    v_day := (v_now AT TIME ZONE v_policy.budget_timezone)::date;
    v_month := date_trunc('month', v_day)::date;

    -- Fixed lock order. From here to COMMIT this learner's budget, and the
    -- global ceiling, cannot be changed by anyone else.
    v_global := tutor._lock_counter('global', v_zero, 'month', v_month);
    v_learner_month := tutor._lock_counter('learner', v_actor, 'month', v_month);
    v_learner_day := tutor._lock_counter('learner', v_actor, 'day', v_day);

    -- This learner's reservations that ran out of time: nobody settled them, so
    -- assume the provider billed the whole hold.
    FOR v_stale IN
        SELECT * FROM tutor.usage_requests u
        WHERE u.learner_id = v_actor AND u.status = 'reserved' AND u.expires_at <= v_now
        ORDER BY u.created_at
        FOR UPDATE
    LOOP
        PERFORM tutor._lock_counters_of(v_stale.learner_id, v_stale.usage_day, v_stale.usage_month);
        PERFORM tutor._finish(v_stale, 'expired', v_stale.reserved_micro, true);
        UPDATE tutor.usage_requests SET outcome = 'expired_unsettled' WHERE id = v_stale.id;
    END LOOP;
    -- Re-read the counters: the loop above may have changed them.
    v_global := tutor._lock_counter('global', v_zero, 'month', v_month);
    v_learner_month := tutor._lock_counter('learner', v_actor, 'month', v_month);
    v_learner_day := tutor._lock_counter('learner', v_actor, 'day', v_day);

    SELECT * INTO v_existing FROM tutor.usage_requests u
    WHERE u.learner_id = v_actor AND u.request_key = p_request_key
    FOR UPDATE;

    v_refusal := CASE
        WHEN v_existing.status = 'reserved' THEN 'in_progress'
        WHEN v_existing.status IN ('settled', 'expired') THEN 'duplicate'
        WHEN (SELECT count(*) FROM tutor.usage_requests u
              WHERE u.learner_id = v_actor AND u.status = 'reserved')
             >= v_policy.max_concurrent_per_learner THEN 'learner_concurrency'
        WHEN (SELECT count(*) FROM tutor.usage_requests u
              WHERE u.status = 'reserved' AND u.expires_at > v_now)
             >= v_policy.max_concurrent_global THEN 'global_concurrency'
        WHEN v_learner_day.request_count >= v_policy.learner_daily_requests
            THEN 'learner_daily_requests'
        WHEN v_learner_day.reserved_micro + v_learner_day.spent_micro + p_estimate_micro
             > v_policy.learner_daily_micro THEN 'learner_daily_budget'
        WHEN v_learner_month.reserved_micro + v_learner_month.spent_micro + p_estimate_micro
             > v_policy.learner_monthly_micro THEN 'learner_monthly_budget'
        WHEN v_global.reserved_micro + v_global.spent_micro + p_estimate_micro
             > v_policy.global_monthly_micro THEN 'global_budget'
    END;
    IF v_refusal IS NOT NULL THEN
        RETURN QUERY SELECT v_refusal, NULL::uuid, NULL::bigint, NULL::timestamptz;
        RETURN;
    END IF;

    v_expires := v_now + make_interval(secs => v_policy.reservation_ttl_s);
    IF v_existing.id IS NOT NULL THEN
        -- A released request (nothing was spent) may try again under the same key.
        UPDATE tutor.usage_requests
           SET status = 'reserved', usage_day = v_day, usage_month = v_month,
               reserved_micro = p_estimate_micro, spent_micro = 0, outcome = NULL,
               created_at = v_now, expires_at = v_expires, finished_at = NULL
         WHERE id = v_existing.id
        RETURNING id INTO v_id;
    ELSE
        INSERT INTO tutor.usage_requests
            (learner_id, request_key, status, usage_day, usage_month, reserved_micro,
             created_at, expires_at)
        VALUES (v_actor, p_request_key, 'reserved', v_day, v_month, p_estimate_micro,
                v_now, v_expires)
        RETURNING id INTO v_id;
    END IF;

    UPDATE tutor.budget_counters SET reserved_micro = budget_counters.reserved_micro + p_estimate_micro
     WHERE scope = 'global' AND learner_id = v_zero
       AND period_kind = 'month' AND period_start = v_month;
    UPDATE tutor.budget_counters SET reserved_micro = budget_counters.reserved_micro + p_estimate_micro
     WHERE scope = 'learner' AND learner_id = v_actor
       AND period_kind = 'month' AND period_start = v_month;
    UPDATE tutor.budget_counters
       SET reserved_micro = budget_counters.reserved_micro + p_estimate_micro,
           request_count = request_count + 1
     WHERE scope = 'learner' AND learner_id = v_actor
       AND period_kind = 'day' AND period_start = v_day;

    RETURN QUERY SELECT 'reserved'::text, v_id, p_estimate_micro, v_expires;
END $$;

-- Record what a reservation really cost. Returns settled | already_finished | not_found.
-- Calling it twice changes nothing the second time; calling it for a
-- reservation of another learner finds nothing.
CREATE FUNCTION tutor.settle(
    p_reservation_id uuid, p_spent_micro bigint, p_input_tokens integer,
    p_output_tokens integer, p_attempts integer, p_outcome text, p_counts_as_request boolean,
    p_provider text, p_model text, p_price_version text, p_prompt_version text,
    p_lesson_revision_id uuid
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_actor uuid := tutor._actor();
    v_request tutor.usage_requests;
BEGIN
    PERFORM tutor._require_read_committed();
    IF p_spent_micro IS NULL OR p_spent_micro < 0 THEN
        RAISE EXCEPTION 'tutor.settle: invalid amount' USING ERRCODE = '22023';
    END IF;
    -- Periods never change while a row is reserved, so an unlocked read is
    -- enough to know WHICH counters to lock; the row itself is re-read under lock.
    SELECT * INTO v_request FROM tutor.usage_requests
    WHERE id = p_reservation_id AND learner_id = v_actor;
    IF NOT FOUND THEN
        RETURN 'not_found';
    END IF;
    PERFORM tutor._lock_counters_of(v_request.learner_id, v_request.usage_day, v_request.usage_month);
    SELECT * INTO v_request FROM tutor.usage_requests
    WHERE id = p_reservation_id AND learner_id = v_actor
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'not_found';
    END IF;
    IF v_request.status <> 'reserved' THEN
        RETURN 'already_finished';
    END IF;
    PERFORM tutor._finish(v_request, 'settled', p_spent_micro, COALESCE(p_counts_as_request, true));
    UPDATE tutor.usage_requests
       SET input_tokens = COALESCE(p_input_tokens, 0),
           output_tokens = COALESCE(p_output_tokens, 0),
           attempts = COALESCE(p_attempts, 0),
           outcome = p_outcome, provider = p_provider, model = p_model,
           price_version = p_price_version, prompt_version = p_prompt_version,
           lesson_revision_id = p_lesson_revision_id
     WHERE id = v_request.id;
    RETURN 'settled';
END $$;

-- Give a hold back untouched (no provider call was made).
CREATE FUNCTION tutor.release(p_reservation_id uuid, p_outcome text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_actor uuid := tutor._actor();
    v_request tutor.usage_requests;
BEGIN
    PERFORM tutor._require_read_committed();
    SELECT * INTO v_request FROM tutor.usage_requests
    WHERE id = p_reservation_id AND learner_id = v_actor;
    IF NOT FOUND THEN
        RETURN 'not_found';
    END IF;
    PERFORM tutor._lock_counters_of(v_request.learner_id, v_request.usage_day, v_request.usage_month);
    SELECT * INTO v_request FROM tutor.usage_requests
    WHERE id = p_reservation_id AND learner_id = v_actor
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'not_found';
    END IF;
    IF v_request.status <> 'reserved' THEN
        RETURN 'already_finished';
    END IF;
    PERFORM tutor._finish(v_request, 'released', 0, false);
    UPDATE tutor.usage_requests SET outcome = p_outcome WHERE id = v_request.id;
    RETURN 'released';
END $$;

-- The calling learner's own counters. No parameter: nobody else's can be asked for.
CREATE FUNCTION tutor.my_usage()
RETURNS TABLE (day_requests integer, day_micro bigint, month_micro bigint,
               daily_requests_limit integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
#variable_conflict use_column
DECLARE
    v_actor uuid := tutor._actor();
    v_policy tutor.policy;
    v_day date;
BEGIN
    SELECT * INTO STRICT v_policy FROM tutor.policy;
    v_day := (clock_timestamp() AT TIME ZONE v_policy.budget_timezone)::date;
    RETURN QUERY
    SELECT COALESCE(d.request_count, 0),
           COALESCE(d.spent_micro + d.reserved_micro, 0),
           COALESCE(m.spent_micro + m.reserved_micro, 0),
           v_policy.learner_daily_requests
    FROM (SELECT 1) one
    LEFT JOIN tutor.budget_counters d
           ON d.scope = 'learner' AND d.learner_id = v_actor
          AND d.period_kind = 'day' AND d.period_start = v_day
    LEFT JOIN tutor.budget_counters m
           ON m.scope = 'learner' AND m.learner_id = v_actor
          AND m.period_kind = 'month' AND m.period_start = date_trunc('month', v_day)::date;
END $$;

-- ---------------------------------------------------------------------------
-- Privileged functions (NOT granted to the API role; for a worker / staff role)
-- ---------------------------------------------------------------------------

-- Charge reservations nobody settled in time. Run by a scheduled job.
CREATE FUNCTION tutor.expire_stale(p_limit integer DEFAULT 500)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_candidate record;
    v_request tutor.usage_requests;
    v_count integer := 0;
BEGIN
    PERFORM tutor._require_read_committed();
    -- One sweeper at a time; a second call simply does nothing.
    IF NOT pg_try_advisory_xact_lock(hashtext('tutor.expire_stale')) THEN
        RETURN 0;
    END IF;
    FOR v_candidate IN
        SELECT id, learner_id, usage_day, usage_month FROM tutor.usage_requests
        WHERE status = 'reserved' AND expires_at <= clock_timestamp()
        ORDER BY usage_month, learner_id, usage_day, id
        LIMIT p_limit
    LOOP
        PERFORM tutor._lock_counters_of(
            v_candidate.learner_id, v_candidate.usage_day, v_candidate.usage_month);
        SELECT * INTO v_request FROM tutor.usage_requests
        WHERE id = v_candidate.id AND status = 'reserved' AND expires_at <= clock_timestamp()
        FOR UPDATE;
        IF FOUND THEN
            PERFORM tutor._finish(v_request, 'expired', v_request.reserved_micro, true);
            UPDATE tutor.usage_requests SET outcome = 'expired_unsettled' WHERE id = v_request.id;
            v_count := v_count + 1;
        END IF;
    END LOOP;
    RETURN v_count;
END $$;

CREATE FUNCTION tutor.set_paused(p_paused boolean, p_actor uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    UPDATE tutor.policy SET paused = p_paused, updated_at = now(), updated_by = p_actor;
    INSERT INTO tutor.admin_audit (actor_id, action, details)
    VALUES (p_actor, 'tutor.kill_switch.set', jsonb_build_object('paused', p_paused));
END $$;

-- Remove everything that names a learner. Aggregate (global) totals stay: they
-- contain no personal data and the spending ceiling must not forget money spent.
CREATE FUNCTION tutor.erase_learner(p_learner uuid, p_actor uuid)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_request tutor.usage_requests;
    v_deleted integer;
BEGIN
    PERFORM tutor._require_read_committed();
    -- In-flight holds become spend first (the provider may still bill them).
    FOR v_request IN
        SELECT * FROM tutor.usage_requests
        WHERE learner_id = p_learner AND status = 'reserved'
        ORDER BY usage_month, usage_day, id
    LOOP
        PERFORM tutor._lock_counters_of(
            v_request.learner_id, v_request.usage_day, v_request.usage_month);
        SELECT * INTO v_request FROM tutor.usage_requests
        WHERE id = v_request.id AND status = 'reserved' FOR UPDATE;
        IF FOUND THEN
            PERFORM tutor._finish(v_request, 'expired', v_request.reserved_micro, true);
        END IF;
    END LOOP;
    DELETE FROM tutor.usage_requests WHERE learner_id = p_learner;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    DELETE FROM tutor.budget_counters WHERE scope = 'learner' AND learner_id = p_learner;
    -- The audit row records THAT an erasure happened, not whose.
    INSERT INTO tutor.admin_audit (actor_id, action, details)
    VALUES (p_actor, 'tutor.learner.erase', jsonb_build_object('rows', v_deleted));
    RETURN v_deleted;
END $$;

-- Retention: drop finished ledger rows older than the owner's retention period.
CREATE FUNCTION tutor.purge_older_than(p_cutoff timestamptz, p_actor uuid)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_deleted integer;
BEGIN
    DELETE FROM tutor.usage_requests WHERE status <> 'reserved' AND created_at < p_cutoff;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    INSERT INTO tutor.admin_audit (actor_id, action, details)
    VALUES (p_actor, 'tutor.usage.purge', jsonb_build_object('rows', v_deleted));
    RETURN v_deleted;
END $$;

-- ---------------------------------------------------------------------------
-- Privileges: the API role may call five functions and touch no table.
-- ---------------------------------------------------------------------------
REVOKE ALL ON ALL TABLES IN SCHEMA tutor FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA tutor FROM PUBLIC;
GRANT USAGE ON SCHEMA tutor TO edu_api;
GRANT EXECUTE ON FUNCTION tutor.is_paused() TO edu_api;
GRANT EXECUTE ON FUNCTION tutor.reserve(uuid, bigint) TO edu_api;
GRANT EXECUTE ON FUNCTION tutor.settle(uuid, bigint, integer, integer, integer, text, boolean,
                                       text, text, text, text, uuid) TO edu_api;
GRANT EXECUTE ON FUNCTION tutor.release(uuid, text) TO edu_api;
GRANT EXECUTE ON FUNCTION tutor.my_usage() TO edu_api;
