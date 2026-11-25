-- Mon Edupreneur 2.0 — notifications: a server-owned outbox (Platform-00 M-12)
--
-- NOTHING IN THIS MIGRATION SENDS ANYTHING. There is no push provider, no
-- e-mail, no SMS and no device-token table. The schema records WHAT should be
-- told to a learner and the state of each delivery attempt; the only adapter
-- that exists is a dummy one that writes to an in-memory sink in tests.
--
-- Decision status: notification policy and quiet hours are product decision
-- PO-10 (BLOCKED_BY_OWNER). The values in notify.policy and notify.kinds are
-- SYNTHETIC defaults taken from Platform-00's recommendation.
--
-- MODEL
--   notify.kinds              allow-list of notification kinds and their category
--   notify.policy             one row: platform quiet hours, retry bounds
--   notify.preferences        per learner: push opt-in, muted categories, own quiet hours
--   notify.outbox             one row per event for one recipient: kind + reference ids
--   notify.deliveries         one row per (event, worker-delivered channel): state machine
--   notify.delivery_attempts  append-only log of every attempt
--
-- RULES
--   * Rows carry a kind and reference ids only. No column can hold free text:
--     every text column is an allow-list, ids are UUIDs, the dedupe key is
--     stored as a SHA-256 digest. The app renders the words in the learner's
--     language from the kind and the ids.
--   * Only server code creates a notification: notify.enqueue() is executable
--     by NOBODY but the owner. The student API role (edu_api) can read the
--     caller's own in-app rows and preferences, and change the caller's own
--     preferences through notify.set_preferences(). Nothing else.
--   * "Push" is off until the learner turns it on (consent unknown = not
--     granted, PO-04), and is never attempted inside quiet hours, which are
--     evaluated in the product time zone America/Port-au-Prince.
--   * Nothing is created in schema app. Foreign keys point at
--     app.learner_profiles so a notification can only exist for a real learner;
--     notify.erase_learner() removes a learner's rows before account erasure.
--
-- WORKER SEAM: notify.claim_due() and notify.record_attempt() are for a
-- delivery worker. The worker role (edu_worker) is delivered by another
-- migration block and does not exist here, so EXECUTE is granted to nobody.
-- The single GRANT line to add later is marked "SEAM(notify-worker-role)" below.

CREATE SCHEMA notify;
REVOKE ALL ON SCHEMA notify FROM PUBLIC;
REVOKE ALL ON SCHEMA notify FROM anon, authenticated;
COMMENT ON SCHEMA notify IS
    'Private notification outbox. Server-written only. Not exposed through the Data API.';

-- ----------------------------------------------------------------------------
-- Reference data
-- ----------------------------------------------------------------------------
CREATE TABLE notify.kinds (
    kind text PRIMARY KEY CHECK (kind ~ '^[a-z][a-z0-9_]{2,40}$'),
    category text NOT NULL CHECK (category IN ('learning', 'reminders', 'account')),
    is_active boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE notify.kinds IS
    'Allow-list of notification kinds. Service messages only (PO-10): there is no marketing category.';

INSERT INTO notify.kinds (kind, category) VALUES
    ('daily_word_available', 'learning'),
    ('sync_reminder', 'reminders'),
    ('entitlement_expiring', 'account');

CREATE TABLE notify.policy (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    -- SYNTHETIC default (PO-10): no push between 21:00 and 06:00 Haiti time.
    quiet_start time NOT NULL DEFAULT '21:00',
    quiet_end time NOT NULL DEFAULT '06:00',
    max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 10),
    backoff_base_seconds integer NOT NULL DEFAULT 60 CHECK (backoff_base_seconds BETWEEN 1 AND 3600),
    backoff_cap_seconds integer NOT NULL DEFAULT 3600 CHECK (backoff_cap_seconds BETWEEN 1 AND 86400),
    CHECK (backoff_cap_seconds >= backoff_base_seconds),
    CHECK (quiet_start <> quiet_end)
);
COMMENT ON TABLE notify.policy IS
    'Single row of platform-wide notification policy. Synthetic defaults pending PO-10.';
INSERT INTO notify.policy DEFAULT VALUES;

-- ----------------------------------------------------------------------------
-- Per-learner preferences
-- ----------------------------------------------------------------------------
CREATE TABLE notify.preferences (
    learner_id uuid PRIMARY KEY REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    -- Off until the learner turns it on. No row at all also means "off".
    push_enabled boolean NOT NULL DEFAULT false,
    muted_categories text[] NOT NULL DEFAULT '{}'
        CHECK (muted_categories <@ ARRAY['learning', 'reminders', 'account']::text[]
               AND cardinality(muted_categories) <= 3),
    -- The learner's OWN quiet window, in addition to the platform's. Both or neither.
    quiet_start time,
    quiet_end time,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((quiet_start IS NULL) = (quiet_end IS NULL)),
    CHECK (quiet_start IS NULL OR quiet_start <> quiet_end)
);

-- ----------------------------------------------------------------------------
-- "Reference ids only": the shape every outbox row's refs must have
-- ----------------------------------------------------------------------------
-- An object of at most 4 entries; every key is on a fixed allow-list and every
-- value is a canonical lower-case UUID string. Nothing a person could read.
CREATE FUNCTION notify.refs_are_ids(p_refs jsonb)
RETURNS boolean
LANGUAGE sql IMMUTABLE
SET search_path = ''
AS $$
    SELECT CASE
        WHEN p_refs IS NULL OR jsonb_typeof(p_refs) <> 'object' THEN false
        ELSE (SELECT count(*) FROM jsonb_object_keys(p_refs)) <= 4
             AND NOT EXISTS (
                 SELECT 1 FROM jsonb_each(p_refs) e
                 WHERE e.key NOT IN ('word_id', 'lesson_id', 'unit_id', 'course_id',
                                     'subject_id', 'grant_id')
                    OR jsonb_typeof(e.value) <> 'string'
                    OR (e.value #>> '{}') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
             )
    END
$$;

-- ----------------------------------------------------------------------------
-- The outbox
-- ----------------------------------------------------------------------------
CREATE TABLE notify.outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    recipient_id uuid NOT NULL REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    kind text NOT NULL REFERENCES notify.kinds(kind) ON DELETE RESTRICT,
    refs jsonb NOT NULL DEFAULT '{}' CHECK (notify.refs_are_ids(refs)),
    -- Channel policy. 'in_app' = listed by GET /v1/notifications (pull only).
    -- 'push' = handed to a delivery worker, subject to preferences and quiet hours.
    channels text[] NOT NULL DEFAULT '{in_app}'
        CHECK (cardinality(channels) BETWEEN 1 AND 2
               AND channels <@ ARRAY['in_app', 'push']::text[]),
    deliver_after timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    -- SHA-256 of the producer's dedupe key: the same event is never enqueued twice.
    dedupe_hash bytea NOT NULL CHECK (octet_length(dedupe_hash) = 32),
    -- 'pending' while a worker-delivered channel is not finished; else 'settled'.
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'settled')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (expires_at IS NULL OR expires_at > deliver_after),
    UNIQUE (recipient_id, kind, dedupe_hash)
);
CREATE INDEX idx_outbox_recipient_feed ON notify.outbox (recipient_id, deliver_after DESC, seq DESC);
CREATE INDEX idx_outbox_kind ON notify.outbox (kind);

CREATE TABLE notify.deliveries (
    outbox_id uuid NOT NULL REFERENCES notify.outbox(id) ON DELETE RESTRICT,
    channel text NOT NULL CHECK (channel IN ('push')),
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'leased', 'delivered', 'failed', 'suppressed', 'expired')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    -- pending: earliest next attempt. leased: when the lease runs out.
    next_attempt_at timestamptz,
    lease_token uuid,
    last_error_code text CHECK (last_error_code IN (
        'transient', 'timeout', 'provider_unavailable', 'rejected', 'adapter_error',
        'lease_expired', 'max_attempts', 'push_not_enabled', 'category_muted', 'kind_inactive')),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (outbox_id, channel),
    CHECK ((state IN ('pending', 'leased')) = (next_attempt_at IS NOT NULL)),
    CHECK ((state = 'leased') = (lease_token IS NOT NULL))
);
CREATE INDEX idx_deliveries_due ON notify.deliveries (channel, next_attempt_at)
    WHERE state IN ('pending', 'leased');

CREATE TABLE notify.delivery_attempts (
    outbox_id uuid NOT NULL,
    channel text NOT NULL,
    attempt_no integer NOT NULL CHECK (attempt_no > 0),
    outcome text NOT NULL CHECK (outcome IN ('delivered', 'retry', 'failed', 'lease_lost')),
    error_code text CHECK (error_code IN (
        'transient', 'timeout', 'provider_unavailable', 'rejected', 'adapter_error',
        'lease_expired', 'max_attempts')),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (outbox_id, channel, attempt_no),
    FOREIGN KEY (outbox_id, channel) REFERENCES notify.deliveries(outbox_id, channel) ON DELETE RESTRICT
);

-- ----------------------------------------------------------------------------
-- Quiet hours (product time zone: America/Port-au-Prince, daylight saving included)
-- ----------------------------------------------------------------------------
-- If p_at falls inside the daily local window [p_start, p_end) return the
-- instant that window ends; otherwise NULL. A window may wrap midnight.
CREATE FUNCTION notify.window_end(p_at timestamptz, p_start time, p_end time)
RETURNS timestamptz
LANGUAGE plpgsql STABLE
SET search_path = ''
AS $$
DECLARE
    v_local timestamp := p_at AT TIME ZONE 'America/Port-au-Prince';
    v_time time := v_local::time;
    v_day date := v_local::date;
    v_end timestamptz;
BEGIN
    IF p_at IS NULL OR p_start IS NULL OR p_end IS NULL OR p_start = p_end THEN
        RETURN NULL;
    END IF;
    IF p_start < p_end THEN
        IF v_time >= p_start AND v_time < p_end THEN
            v_end := (v_day + p_end) AT TIME ZONE 'America/Port-au-Prince';
        END IF;
    ELSIF v_time >= p_start THEN
        v_end := ((v_day + 1) + p_end) AT TIME ZONE 'America/Port-au-Prince';
    ELSIF v_time < p_end THEN
        v_end := (v_day + p_end) AT TIME ZONE 'America/Port-au-Prince';
    END IF;
    -- A clock change can make a computed end fall at or before p_at; never go backwards.
    IF v_end IS NOT NULL AND v_end <= p_at THEN
        v_end := p_at + interval '1 hour';
    END IF;
    RETURN v_end;
END;
$$;

-- The first instant at or after p_at when a push to this learner is allowed:
-- outside the platform window AND outside the learner's own window.
-- Returns p_at itself when p_at is not in quiet hours.
CREATE FUNCTION notify.quiet_until(p_at timestamptz, p_recipient uuid)
RETURNS timestamptz
LANGUAGE plpgsql STABLE
SET search_path = ''
AS $$
DECLARE
    v_policy notify.policy%ROWTYPE;
    v_own_start time;
    v_own_end time;
    v_at timestamptz := p_at;
    v_end timestamptz;
BEGIN
    SELECT * INTO STRICT v_policy FROM notify.policy;
    SELECT quiet_start, quiet_end INTO v_own_start, v_own_end
    FROM notify.preferences WHERE learner_id = p_recipient;
    -- Bounded: two windows can chain at most a few times. If the two windows
    -- together cover the whole day the result is simply "later", every time.
    FOR i IN 1..4 LOOP
        v_end := notify.window_end(v_at, v_policy.quiet_start, v_policy.quiet_end);
        IF v_end IS NULL THEN
            v_end := notify.window_end(v_at, v_own_start, v_own_end);
        END IF;
        EXIT WHEN v_end IS NULL;
        v_at := v_end;
    END LOOP;
    RETURN v_at;
END;
$$;

-- ----------------------------------------------------------------------------
-- Producer entry point — the ONLY way a notification is created
-- ----------------------------------------------------------------------------
-- Returns the outbox id: the new row's, or the existing row's when the same
-- (recipient, kind, dedupe key) was already enqueued (idempotent).
CREATE FUNCTION notify.enqueue(
    p_recipient uuid,
    p_kind text,
    p_refs jsonb,
    p_dedupe_key text,
    p_channels text[] DEFAULT ARRAY['in_app'],
    p_deliver_after timestamptz DEFAULT NULL,
    p_expires_at timestamptz DEFAULT NULL
)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_now timestamptz := now();
    v_after timestamptz := COALESCE(p_deliver_after, v_now);
    v_channels text[];
    v_hash bytea;
    v_id uuid;
BEGIN
    IF p_recipient IS NULL OR p_kind IS NULL OR p_refs IS NULL OR p_channels IS NULL THEN
        RAISE EXCEPTION 'notify.enqueue: recipient, kind, refs and channels are required'
            USING ERRCODE = '22004';
    END IF;
    IF p_dedupe_key IS NULL OR char_length(p_dedupe_key) NOT BETWEEN 1 AND 200 THEN
        RAISE EXCEPTION 'notify.enqueue: dedupe key must be 1..200 characters'
            USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM notify.kinds k WHERE k.kind = p_kind AND k.is_active) THEN
        RAISE EXCEPTION 'notify.enqueue: unknown or inactive kind' USING ERRCODE = '22023';
    END IF;
    IF NOT notify.refs_are_ids(p_refs) THEN
        RAISE EXCEPTION 'notify.enqueue: refs must be reference ids only' USING ERRCODE = '22023';
    END IF;
    IF v_after > v_now + interval '90 days' THEN
        RAISE EXCEPTION 'notify.enqueue: deliver_after is too far in the future'
            USING ERRCODE = '22023';
    END IF;
    IF p_expires_at IS NOT NULL AND p_expires_at <= v_after THEN
        RAISE EXCEPTION 'notify.enqueue: expires_at must be after deliver_after'
            USING ERRCODE = '22023';
    END IF;
    SELECT array_agg(DISTINCT c ORDER BY c) INTO v_channels FROM unnest(p_channels) AS c;
    IF v_channels IS NULL OR NOT v_channels <@ ARRAY['in_app', 'push']::text[] THEN
        RAISE EXCEPTION 'notify.enqueue: unknown channel' USING ERRCODE = '22023';
    END IF;

    v_hash := sha256(convert_to(p_dedupe_key, 'UTF8'));

    INSERT INTO notify.outbox (recipient_id, kind, refs, channels, deliver_after, expires_at,
                               dedupe_hash, state)
    VALUES (p_recipient, p_kind, p_refs, v_channels, v_after, p_expires_at, v_hash,
            CASE WHEN 'push' = ANY (v_channels) THEN 'pending' ELSE 'settled' END)
    ON CONFLICT (recipient_id, kind, dedupe_hash) DO NOTHING
    RETURNING id INTO v_id;

    IF v_id IS NULL THEN
        SELECT o.id INTO STRICT v_id FROM notify.outbox o
        WHERE o.recipient_id = p_recipient AND o.kind = p_kind AND o.dedupe_hash = v_hash;
        RETURN v_id;
    END IF;

    IF 'push' = ANY (v_channels) THEN
        INSERT INTO notify.deliveries (outbox_id, channel, state, next_attempt_at)
        VALUES (v_id, 'push', 'pending', v_after);
    END IF;
    RETURN v_id;
END;
$$;

-- ----------------------------------------------------------------------------
-- Delivery worker: claim and report
-- ----------------------------------------------------------------------------
CREATE TYPE notify.claimed AS (
    outbox_id uuid,
    channel text,
    lease_token uuid,
    attempt_no integer,
    recipient_id uuid,
    kind text,
    refs jsonb
);

CREATE FUNCTION notify._settle(p_outbox_id uuid)
RETURNS void
LANGUAGE sql SECURITY DEFINER
SET search_path = ''
AS $$
    UPDATE notify.outbox o SET state = 'settled'
    WHERE o.id = p_outbox_id AND o.state = 'pending'
      AND NOT EXISTS (SELECT 1 FROM notify.deliveries d
                      WHERE d.outbox_id = o.id AND d.state IN ('pending', 'leased'));
$$;

-- Internal: the clock is a parameter so that quiet hours, leases and backoff can
-- be tested at exact instants. NEVER grant this to a role; grant claim_due().
CREATE FUNCTION notify._claim_due_at(
    p_channel text, p_limit integer, p_lease_seconds integer, p_now timestamptz
)
RETURNS SETOF notify.claimed
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_policy notify.policy%ROWTYPE;
    v_row record;
    v_pref notify.preferences%ROWTYPE;
    v_until timestamptz;
    v_token uuid;
    v_leased integer := 0;
    v_attempts integer;
    v_out notify.claimed;
BEGIN
    IF p_channel IS DISTINCT FROM 'push' THEN
        RAISE EXCEPTION 'notify.claim_due: unknown channel' USING ERRCODE = '22023';
    END IF;
    IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN
        RAISE EXCEPTION 'notify.claim_due: limit must be 1..100' USING ERRCODE = '22023';
    END IF;
    IF p_lease_seconds IS NULL OR p_lease_seconds NOT BETWEEN 5 AND 900 THEN
        RAISE EXCEPTION 'notify.claim_due: lease must be 5..900 seconds' USING ERRCODE = '22023';
    END IF;
    IF p_now IS NULL THEN
        RAISE EXCEPTION 'notify.claim_due: clock is required' USING ERRCODE = '22004';
    END IF;
    SELECT * INTO STRICT v_policy FROM notify.policy;

    FOR v_row IN
        SELECT d.outbox_id, d.state, d.attempt_count,
               o.recipient_id, o.kind, o.refs, o.expires_at, k.category, k.is_active
        FROM notify.deliveries d
        JOIN notify.outbox o ON o.id = d.outbox_id
        JOIN notify.kinds k ON k.kind = o.kind
        WHERE d.channel = p_channel
          AND d.state IN ('pending', 'leased')
          AND d.next_attempt_at <= p_now
        ORDER BY d.next_attempt_at, d.outbox_id
        LIMIT p_limit * 10
        FOR UPDATE OF d SKIP LOCKED
    LOOP
        v_attempts := v_row.attempt_count;

        -- A lease that ran out: the worker that held it never reported back.
        IF v_row.state = 'leased' THEN
            INSERT INTO notify.delivery_attempts (outbox_id, channel, attempt_no, outcome, error_code, recorded_at)
            VALUES (v_row.outbox_id, p_channel, v_attempts, 'lease_lost', 'lease_expired', p_now);
            IF v_attempts >= v_policy.max_attempts THEN
                UPDATE notify.deliveries SET state = 'failed', next_attempt_at = NULL, lease_token = NULL,
                       last_error_code = 'lease_expired', updated_at = p_now
                WHERE outbox_id = v_row.outbox_id AND channel = p_channel;
                PERFORM notify._settle(v_row.outbox_id);
                CONTINUE;
            END IF;
        END IF;

        IF v_row.expires_at IS NOT NULL AND v_row.expires_at <= p_now THEN
            UPDATE notify.deliveries SET state = 'expired', next_attempt_at = NULL, lease_token = NULL,
                   updated_at = p_now
            WHERE outbox_id = v_row.outbox_id AND channel = p_channel;
            PERFORM notify._settle(v_row.outbox_id);
            CONTINUE;
        END IF;

        -- Preferences are read at delivery time, not at enqueue time.
        SELECT * INTO v_pref FROM notify.preferences WHERE learner_id = v_row.recipient_id;
        IF NOT FOUND OR NOT v_pref.push_enabled
           OR v_row.category = ANY (v_pref.muted_categories) OR NOT v_row.is_active THEN
            UPDATE notify.deliveries SET state = 'suppressed', next_attempt_at = NULL, lease_token = NULL,
                   last_error_code = CASE
                       WHEN NOT v_row.is_active THEN 'kind_inactive'
                       WHEN v_pref.learner_id IS NULL OR NOT v_pref.push_enabled THEN 'push_not_enabled'
                       ELSE 'category_muted' END,
                   updated_at = p_now
            WHERE outbox_id = v_row.outbox_id AND channel = p_channel;
            PERFORM notify._settle(v_row.outbox_id);
            CONTINUE;
        END IF;

        -- Quiet hours: put it off without spending an attempt.
        v_until := notify.quiet_until(p_now, v_row.recipient_id);
        IF v_until > p_now THEN
            UPDATE notify.deliveries SET state = 'pending', next_attempt_at = v_until, lease_token = NULL,
                   updated_at = p_now
            WHERE outbox_id = v_row.outbox_id AND channel = p_channel;
            CONTINUE;
        END IF;

        v_token := gen_random_uuid();
        UPDATE notify.deliveries SET state = 'leased', attempt_count = v_attempts + 1,
               next_attempt_at = p_now + make_interval(secs => p_lease_seconds),
               lease_token = v_token, updated_at = p_now
        WHERE outbox_id = v_row.outbox_id AND channel = p_channel;

        v_out := (v_row.outbox_id, p_channel, v_token, v_attempts + 1,
                  v_row.recipient_id, v_row.kind, v_row.refs);
        RETURN NEXT v_out;
        v_leased := v_leased + 1;
        EXIT WHEN v_leased >= p_limit;
    END LOOP;
    RETURN;
END;
$$;

CREATE FUNCTION notify.claim_due(
    p_channel text, p_limit integer DEFAULT 20, p_lease_seconds integer DEFAULT 60
)
RETURNS SETOF notify.claimed
LANGUAGE sql SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT * FROM notify._claim_due_at(p_channel, p_limit, p_lease_seconds, clock_timestamp());
$$;

-- Internal twin of record_attempt() with an explicit clock (tests only).
-- Returns the delivery's new state, or 'stale' when the lease token is not the
-- current one (the lease ran out and somebody else holds it): nothing is written.
CREATE FUNCTION notify._record_attempt_at(
    p_outbox_id uuid, p_channel text, p_lease_token uuid, p_outcome text,
    p_error_code text, p_now timestamptz
)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_policy notify.policy%ROWTYPE;
    v_delivery notify.deliveries%ROWTYPE;
    v_state text;
    v_outcome text := p_outcome;
    v_error text := p_error_code;
    v_delay integer;
BEGIN
    IF p_outbox_id IS NULL OR p_channel IS NULL OR p_lease_token IS NULL OR p_now IS NULL THEN
        RAISE EXCEPTION 'notify.record_attempt: outbox id, channel and lease token are required'
            USING ERRCODE = '22004';
    END IF;
    IF p_outcome IS NULL OR p_outcome NOT IN ('delivered', 'retry', 'failed') THEN
        RAISE EXCEPTION 'notify.record_attempt: outcome must be delivered, retry or failed'
            USING ERRCODE = '22023';
    END IF;
    IF p_outcome = 'delivered' THEN
        v_error := NULL;
    ELSIF v_error IS NULL OR v_error NOT IN ('transient', 'timeout', 'provider_unavailable',
                                             'rejected', 'adapter_error') THEN
        RAISE EXCEPTION 'notify.record_attempt: an allow-listed error code is required'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT v_policy FROM notify.policy;

    SELECT * INTO v_delivery FROM notify.deliveries d
    WHERE d.outbox_id = p_outbox_id AND d.channel = p_channel
    FOR UPDATE;
    IF NOT FOUND OR v_delivery.state <> 'leased' OR v_delivery.lease_token <> p_lease_token THEN
        RETURN 'stale';
    END IF;

    IF v_outcome = 'retry' AND v_delivery.attempt_count >= v_policy.max_attempts THEN
        v_outcome := 'failed';
    END IF;

    INSERT INTO notify.delivery_attempts (outbox_id, channel, attempt_no, outcome, error_code, recorded_at)
    VALUES (p_outbox_id, p_channel, v_delivery.attempt_count, v_outcome, v_error, p_now);

    IF v_outcome = 'delivered' THEN
        v_state := 'delivered';
        UPDATE notify.deliveries SET state = 'delivered', next_attempt_at = NULL, lease_token = NULL,
               last_error_code = NULL, updated_at = p_now
        WHERE outbox_id = p_outbox_id AND channel = p_channel;
    ELSIF v_outcome = 'failed' THEN
        v_state := 'failed';
        UPDATE notify.deliveries SET state = 'failed', next_attempt_at = NULL, lease_token = NULL,
               last_error_code = CASE WHEN p_outcome = 'retry' THEN 'max_attempts' ELSE v_error END,
               updated_at = p_now
        WHERE outbox_id = p_outbox_id AND channel = p_channel;
    ELSE
        -- Bounded exponential backoff: base * 2^(attempt-1), never above the cap.
        v_delay := LEAST(v_policy.backoff_cap_seconds::numeric,
                         v_policy.backoff_base_seconds::numeric * power(2::numeric, v_delivery.attempt_count - 1))::integer;
        v_state := 'pending';
        UPDATE notify.deliveries SET state = 'pending',
               next_attempt_at = p_now + make_interval(secs => v_delay), lease_token = NULL,
               last_error_code = v_error, updated_at = p_now
        WHERE outbox_id = p_outbox_id AND channel = p_channel;
    END IF;

    PERFORM notify._settle(p_outbox_id);
    RETURN v_state;
END;
$$;

CREATE FUNCTION notify.record_attempt(
    p_outbox_id uuid, p_channel text, p_lease_token uuid, p_outcome text,
    p_error_code text DEFAULT NULL
)
RETURNS text
LANGUAGE sql SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT notify._record_attempt_at(p_outbox_id, p_channel, p_lease_token, p_outcome,
                                     p_error_code, clock_timestamp());
$$;

-- ----------------------------------------------------------------------------
-- Learner: change my own preferences (the actor is never a parameter)
-- ----------------------------------------------------------------------------
CREATE FUNCTION notify.set_preferences(
    p_push_enabled boolean, p_muted_categories text[], p_quiet_start time, p_quiet_end time
)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_muted text[];
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'notify.set_preferences: no verified actor' USING ERRCODE = '42501';
    END IF;
    IF p_push_enabled IS NULL OR p_muted_categories IS NULL THEN
        RAISE EXCEPTION 'notify.set_preferences: push_enabled and muted_categories are required'
            USING ERRCODE = '22004';
    END IF;
    IF cardinality(p_muted_categories) > 10 THEN
        RAISE EXCEPTION 'notify.set_preferences: too many categories' USING ERRCODE = '22023';
    END IF;
    SELECT COALESCE(array_agg(DISTINCT c ORDER BY c), '{}') INTO v_muted
    FROM unnest(p_muted_categories) AS c;
    IF NOT v_muted <@ ARRAY['learning', 'reminders', 'account']::text[] THEN
        RAISE EXCEPTION 'notify.set_preferences: unknown category' USING ERRCODE = '22023';
    END IF;
    IF (p_quiet_start IS NULL) <> (p_quiet_end IS NULL) OR p_quiet_start = p_quiet_end THEN
        RAISE EXCEPTION 'notify.set_preferences: quiet hours need two different times, or none'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO notify.preferences AS p (learner_id, push_enabled, muted_categories, quiet_start, quiet_end)
    VALUES (v_actor, p_push_enabled, v_muted, p_quiet_start, p_quiet_end)
    ON CONFLICT (learner_id) DO UPDATE
        SET push_enabled = EXCLUDED.push_enabled,
            muted_categories = EXCLUDED.muted_categories,
            quiet_start = EXCLUDED.quiet_start,
            quiet_end = EXCLUDED.quiet_end,
            updated_at = now();
END;
$$;

-- ----------------------------------------------------------------------------
-- Erasure hook (cross-domain convention): remove everything about one learner
-- ----------------------------------------------------------------------------
CREATE FUNCTION notify.erase_learner(p_user_id uuid)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_attempts bigint;
    v_deliveries bigint;
    v_outbox bigint;
    v_preferences bigint;
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'notify.erase_learner: user id is required' USING ERRCODE = '22004';
    END IF;
    DELETE FROM notify.delivery_attempts a USING notify.outbox o
    WHERE a.outbox_id = o.id AND o.recipient_id = p_user_id;
    GET DIAGNOSTICS v_attempts = ROW_COUNT;
    DELETE FROM notify.deliveries d USING notify.outbox o
    WHERE d.outbox_id = o.id AND o.recipient_id = p_user_id;
    GET DIAGNOSTICS v_deliveries = ROW_COUNT;
    DELETE FROM notify.outbox o WHERE o.recipient_id = p_user_id;
    GET DIAGNOSTICS v_outbox = ROW_COUNT;
    DELETE FROM notify.preferences p WHERE p.learner_id = p_user_id;
    GET DIAGNOSTICS v_preferences = ROW_COUNT;
    RETURN jsonb_build_object('schema', 'notify', 'outbox', v_outbox, 'deliveries', v_deliveries,
                              'delivery_attempts', v_attempts, 'preferences', v_preferences);
END;
$$;

-- ----------------------------------------------------------------------------
-- Row-level security and privileges
-- ----------------------------------------------------------------------------
ALTER TABLE notify.kinds ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE notify.delivery_attempts ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA notify FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA notify FROM PUBLIC, anon, authenticated;
-- PostgreSQL lets PUBLIC execute new functions by default; take that away from
-- every function here, then grant back exactly what is intended.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA notify FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TYPE notify.claimed FROM PUBLIC;

-- The student API: read reference data, the caller's own preferences and the
-- caller's own in-app rows; change the caller's own preferences. No table write.
GRANT USAGE ON SCHEMA notify TO edu_api;
GRANT SELECT ON notify.kinds, notify.policy, notify.preferences TO edu_api;
GRANT SELECT (id, seq, recipient_id, kind, refs, channels, deliver_after, expires_at, state, created_at)
    ON notify.outbox TO edu_api;
GRANT EXECUTE ON FUNCTION notify.set_preferences(boolean, text[], time, time) TO edu_api;

CREATE POLICY kinds_read ON notify.kinds FOR SELECT TO edu_api USING (true);
CREATE POLICY policy_read ON notify.policy FOR SELECT TO edu_api USING (true);
CREATE POLICY preferences_select_own ON notify.preferences
    FOR SELECT TO edu_api USING (learner_id = (SELECT app.current_actor_id()));
-- Own rows only, only the in-app channel, only once due and while not expired.
CREATE POLICY outbox_select_own_in_app ON notify.outbox
    FOR SELECT TO edu_api
    USING (recipient_id = (SELECT app.current_actor_id())
           AND 'in_app' = ANY (channels)
           AND deliver_after <= now()
           AND (expires_at IS NULL OR expires_at > now()));

-- Deliberately NO grant to anybody on: notify.enqueue, notify.claim_due,
-- notify.record_attempt, notify.erase_learner, the internal _ functions,
-- notify.deliveries, notify.delivery_attempts.
--
-- SEAM(notify-worker-role): once the staff lane's roles exist, a LATER migration
-- in this block adds exactly:
--   GRANT USAGE ON SCHEMA notify TO edu_worker;
--   GRANT EXECUTE ON FUNCTION notify.claim_due(text, integer, integer) TO edu_worker;
--   GRANT EXECUTE ON FUNCTION notify.record_attempt(uuid, text, uuid, text, text) TO edu_worker;
-- Producers (vocab, billing, ...) call notify.enqueue from their own definer
-- functions, which run as the owner and therefore need no grant.
