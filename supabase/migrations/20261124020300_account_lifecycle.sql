-- Mon Edupreneur 2.0 — schema `account`: account lifecycle mechanics
--
-- Overnight mission 2026-11-24, lane IDENTITY (slice 3). SYNTHETIC USERS ONLY:
-- the API routes that reach this are behind EDU_ACCOUNT_LIFECYCLE_ENABLED,
-- which defaults to off, and PO-04 (personal data, consent, minors, retention)
-- is not decided.
--
-- WHAT IS HERE
--   * account.deletion_requests / account.export_requests — a learner's own
--     requests (requested, cancelled, processed). NO retention period, grace
--     period or deadline is stored or implied: none has been decided.
--     A deletion request deletes nothing by itself.
--   * account.export_own_data() — the caller's own data as one JSON document.
--   * account.erase_learner(uuid) — the erasure orchestrator. EXECUTE IS
--     GRANTED TO NOBODY in this migration (see the B1 seam at the end).
--
-- Same rules as the two previous migrations of this schema: nothing in schema
-- `app` is created, altered, granted or dropped; learner-facing functions take
-- the actor from app.current_actor_id() and have no user-id parameter; every
-- function pins an empty search_path.

-- ============================================================================
-- Requests
-- ============================================================================
CREATE TABLE account.deletion_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- NULL once processed: the row that remains says "a deletion request was
    -- carried out at this time" and identifies nobody.
    user_id uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    status text NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested', 'cancelled', 'processed')),
    requested_at timestamptz NOT NULL DEFAULT now(),
    cancelled_at timestamptz,
    processed_at timestamptz,
    CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL)),
    CHECK ((status = 'processed') = (processed_at IS NOT NULL)),
    CHECK ((status = 'processed') = (user_id IS NULL))
);
-- At most one open request per learner.
CREATE UNIQUE INDEX deletion_requests_one_open
    ON account.deletion_requests (user_id) WHERE status = 'requested';
CREATE INDEX deletion_requests_user
    ON account.deletion_requests (user_id, requested_at DESC) WHERE user_id IS NOT NULL;

CREATE TABLE account.export_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    -- Today an export is produced in the same transaction that records it, so
    -- rows are written as 'processed'. 'requested' and 'cancelled' exist for a
    -- later asynchronous path (large exports built by the worker).
    status text NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested', 'cancelled', 'processed')),
    requested_at timestamptz NOT NULL DEFAULT now(),
    cancelled_at timestamptz,
    processed_at timestamptz,
    CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL)),
    CHECK ((status = 'processed') = (processed_at IS NOT NULL))
);
CREATE INDEX export_requests_user ON account.export_requests (user_id, requested_at DESC);

ALTER TABLE account.deletion_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE account.export_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON account.deletion_requests, account.export_requests FROM PUBLIC, anon, authenticated;
GRANT SELECT ON account.deletion_requests, account.export_requests TO edu_api;
CREATE POLICY deletion_requests_select_own ON account.deletion_requests
    FOR SELECT TO edu_api USING (user_id = (SELECT app.current_actor_id()));
CREATE POLICY export_requests_select_own ON account.export_requests
    FOR SELECT TO edu_api USING (user_id = (SELECT app.current_actor_id()));

-- The caller's most recent deletion request and most recent export (or nulls).
CREATE FUNCTION account.get_own_requests()
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    RETURN jsonb_build_object(
        'deletion_request', (
            SELECT jsonb_build_object('id', d.id, 'status', d.status, 'requested_at', d.requested_at,
                                      'cancelled_at', d.cancelled_at)
            FROM account.deletion_requests d
            WHERE d.user_id = v_actor
            ORDER BY d.requested_at DESC, d.id DESC LIMIT 1),
        'last_export', (
            SELECT jsonb_build_object('id', e.id, 'status', e.status, 'requested_at', e.requested_at,
                                      'processed_at', e.processed_at)
            FROM account.export_requests e
            WHERE e.user_id = v_actor
            ORDER BY e.requested_at DESC, e.id DESC LIMIT 1));
END;
$$;

-- Ask for the caller's own account to be deleted. Idempotent: while a request
-- is open, asking again returns that same request. Nothing is deleted here.
CREATE FUNCTION account.request_deletion()
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_row account.deletion_requests%ROWTYPE;
    v_created boolean := false;
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    -- Serialise this learner's lifecycle calls on their profile row.
    PERFORM 1 FROM app.learner_profiles p WHERE p.user_id = v_actor FOR NO KEY UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Learner profile required' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_row FROM account.deletion_requests d
    WHERE d.user_id = v_actor AND d.status = 'requested';
    IF NOT FOUND THEN
        INSERT INTO account.deletion_requests (user_id) VALUES (v_actor) RETURNING * INTO v_row;
        v_created := true;
        PERFORM account.audit_seam(
            'account.deletion_requested', 'deletion_request', v_row.id, 'allowed', '{}'::jsonb);
    END IF;
    RETURN jsonb_build_object(
        'created', v_created,
        'deletion_request', jsonb_build_object(
            'id', v_row.id, 'status', v_row.status, 'requested_at', v_row.requested_at,
            'cancelled_at', v_row.cancelled_at));
END;
$$;

-- Withdraw the caller's open deletion request. Idempotent: with no open
-- request it changes nothing and returns the most recent request, if any.
CREATE FUNCTION account.cancel_deletion_request()
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_row account.deletion_requests%ROWTYPE;
    v_cancelled boolean := false;
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    PERFORM 1 FROM app.learner_profiles p WHERE p.user_id = v_actor FOR NO KEY UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Learner profile required' USING ERRCODE = '42501';
    END IF;
    UPDATE account.deletion_requests d
       SET status = 'cancelled', cancelled_at = now()
     WHERE d.user_id = v_actor AND d.status = 'requested'
    RETURNING * INTO v_row;
    IF FOUND THEN
        v_cancelled := true;
        PERFORM account.audit_seam(
            'account.deletion_cancelled', 'deletion_request', v_row.id, 'allowed', '{}'::jsonb);
    ELSE
        SELECT * INTO v_row FROM account.deletion_requests d
        WHERE d.user_id = v_actor
        ORDER BY d.requested_at DESC, d.id DESC LIMIT 1;
    END IF;
    RETURN jsonb_build_object(
        'cancelled', v_cancelled,
        'deletion_request', CASE WHEN v_row.id IS NULL THEN NULL ELSE jsonb_build_object(
            'id', v_row.id, 'status', v_row.status, 'requested_at', v_row.requested_at,
            'cancelled_at', v_row.cancelled_at) END);
END;
$$;

-- ============================================================================
-- Export
-- ============================================================================
-- The caller's own profile, onboarding state, lesson progress and practice
-- attempts as one JSON document, and a record that the export was produced.
--
-- BOUNDED: at most 2000 progress rows and the 2000 most recent attempts.
-- `counts` gives the true totals and `truncated` says which list was cut; a
-- complete export for a very active learner needs the asynchronous path that
-- is designed but not built.
--
-- NOT INCLUDED: sync receipts and the change feed (technical copies of the
-- same attempts and completions), and anything held by other modules.
CREATE FUNCTION account.export_own_data()
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    c_max_rows CONSTANT integer := 2000;
    v_actor uuid := app.current_actor_id();
    v_profile jsonb;
    v_onboarding jsonb;
    v_progress jsonb;
    v_attempts jsonb;
    v_progress_total bigint;
    v_attempts_total bigint;
    v_export_id uuid;
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;

    SELECT jsonb_build_object(
               'grade_code', g.code,
               'preferred_locale', p.preferred_locale,
               'display_name', p.display_name,
               'created_at', p.created_at,
               'updated_at', p.updated_at)
      INTO v_profile
    FROM app.learner_profiles p
    LEFT JOIN app.grades g ON g.id = p.grade_id
    WHERE p.user_id = v_actor;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Learner profile required' USING ERRCODE = '42501';
    END IF;

    SELECT jsonb_build_object(
               'state', o.state,
               'onboarding_version', o.onboarding_version,
               'tour_version_seen', o.tour_version_seen,
               'tour_dismissed', o.tour_dismissed,
               'completed_at', o.completed_at,
               'created_at', o.created_at,
               'updated_at', o.updated_at)
      INTO v_onboarding
    FROM account.onboarding_state o
    WHERE o.user_id = v_actor;

    SELECT count(*) INTO v_progress_total FROM app.lesson_progress lp WHERE lp.learner_id = v_actor;
    SELECT COALESCE(jsonb_agg(item ORDER BY ord), '[]'::jsonb) INTO v_progress
    FROM (
        SELECT jsonb_build_object(
                   'lesson_id', lp.lesson_id,
                   'last_revision_id', lp.last_revision_id,
                   'completed_at', lp.completed_at,
                   'last_opened_at', lp.last_opened_at,
                   'updated_at', lp.updated_at) AS item,
               row_number() OVER (ORDER BY lp.updated_at DESC, lp.lesson_id) AS ord
        FROM app.lesson_progress lp
        WHERE lp.learner_id = v_actor
        ORDER BY lp.updated_at DESC, lp.lesson_id
        LIMIT c_max_rows
    ) AS t;

    SELECT count(*) INTO v_attempts_total FROM app.practice_attempts a WHERE a.learner_id = v_actor;
    SELECT COALESCE(jsonb_agg(item ORDER BY ord), '[]'::jsonb) INTO v_attempts
    FROM (
        SELECT jsonb_build_object(
                   'id', a.id,
                   'lesson_revision_id', a.lesson_revision_id,
                   'question_revision_id', a.question_revision_id,
                   'response', a.response,
                   'score', a.score,
                   'scoring_version', a.scoring_version,
                   'client_recorded_at', a.client_recorded_at,
                   'accepted_at', a.accepted_at) AS item,
               row_number() OVER (ORDER BY a.accepted_at DESC, a.id) AS ord
        FROM app.practice_attempts a
        WHERE a.learner_id = v_actor
        ORDER BY a.accepted_at DESC, a.id
        LIMIT c_max_rows
    ) AS t;

    INSERT INTO account.export_requests (user_id, status, processed_at)
    VALUES (v_actor, 'processed', now())
    RETURNING id INTO v_export_id;
    PERFORM account.audit_seam(
        'account.data_exported', 'export_request', v_export_id, 'allowed',
        jsonb_build_object('lesson_progress', v_progress_total, 'practice_attempts', v_attempts_total));

    RETURN jsonb_build_object(
        'format', 'mep-account-export-1',
        'export_id', v_export_id,
        'generated_at', now(),
        'user_id', v_actor,
        'profile', v_profile,
        'onboarding', v_onboarding,
        'lesson_progress', v_progress,
        'practice_attempts', v_attempts,
        'counts', jsonb_build_object(
            'lesson_progress', v_progress_total, 'practice_attempts', v_attempts_total),
        'limits', jsonb_build_object(
            'lesson_progress', c_max_rows, 'practice_attempts', c_max_rows),
        'truncated', jsonb_build_object(
            'lesson_progress', v_progress_total > c_max_rows,
            'practice_attempts', v_attempts_total > c_max_rows));
END;
$$;

-- ============================================================================
-- Erasure
-- ============================================================================
-- Design, options considered and what is proven: docs/overnight-2026-11-24/lanes/identity.md.
--
-- Cross-domain convention (mission plan §3): every schema that stores
-- per-learner rows ships  <schema>.erase_learner(p_user_id uuid) RETURNS jsonb
-- with EXECUTE granted to nobody. The orchestrator below calls the hooks whose
-- schema is REGISTERED here, in `position` order (dependants first). A hook
-- found in a schema that is not registered stops the erasure: a new module
-- cannot be skipped silently, and an unknown function is never run as owner.
CREATE TABLE account.erasure_hooks (
    schema_name text PRIMARY KEY CHECK (schema_name ~ '^[a-z_][a-z0-9_]{0,62}$'),
    position integer NOT NULL UNIQUE CHECK (position > 0),
    note text
);
ALTER TABLE account.erasure_hooks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON account.erasure_hooks FROM PUBLIC, anon, authenticated;
-- No grant and no policy: only the owner reads or changes the registry.
INSERT INTO account.erasure_hooks (schema_name, position, note) VALUES
    ('notify',      10, 'outbox, device tokens'),
    ('leaderboard', 20, 'ranks derive from rewards: before rewards'),
    ('rewards',     30, 'ledger, streaks'),
    ('vocab',       40, 'word-of-the-day progress'),
    ('billing',     50, 'entitlement grants');

-- Every place (schema.table.column) outside Supabase-managed schemas where a
-- uuid column still holds this id. Used as the orchestrator's postcondition.
CREATE FUNCTION account.find_learner_references(p_user_id uuid)
RETURNS text[]
LANGUAGE plpgsql STABLE
SET search_path = ''
AS $$
DECLARE
    v_col record;
    v_hit boolean;
    v_found text[] := ARRAY[]::text[];
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'A user id is required' USING ERRCODE = '22023';
    END IF;
    FOR v_col IN
        SELECT n.nspname, c.relname, a.attname
        FROM pg_catalog.pg_attribute a
        JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE a.atttypid = 'pg_catalog.uuid'::pg_catalog.regtype
          AND a.attnum > 0 AND NOT a.attisdropped
          AND c.relkind IN ('r', 'p') AND NOT c.relispartition
          AND c.relpersistence = 'p'
          AND n.nspname !~ '^pg_'
          -- Schemas owned by Supabase services. Auth data (auth.users and its
          -- sessions, identities ...) is removed by Supabase Auth, not here.
          AND n.nspname NOT IN (
              'information_schema', 'auth', 'storage', 'realtime', '_realtime', 'vault',
              'extensions', 'graphql', 'graphql_public', 'pgbouncer', 'net', 'cron',
              'supabase_functions', 'supabase_migrations', 'pgsodium', 'pgsodium_masks',
              '_analytics', '_supavisor', 'pgmq', 'pgtle')
        ORDER BY n.nspname, c.relname, a.attnum
    LOOP
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.%I WHERE %I = $1)',
                       v_col.nspname, v_col.relname, v_col.attname)
           INTO v_hit USING p_user_id;
        IF v_hit THEN
            v_found := array_append(
                v_found, format('%s.%s.%s', v_col.nspname, v_col.relname, v_col.attname));
        END IF;
    END LOOP;
    RETURN v_found;
END;
$$;

-- Erase one learner's data from every application schema.
--
-- HOW THE APPEND-ONLY TABLES ARE HANDLED. app.practice_attempts,
-- app.sync_receipts, app.account_change_feed and app.audit_events carry a
-- BEFORE UPDATE OR DELETE trigger that refuses every change. This function does
-- not drop, disable or alter those triggers. For the few statements that remove
-- THIS learner's rows it sets session_replication_role = replica, a
-- transaction-local setting of THIS session under which ordinary triggers do
-- not fire, and sets it back to origin immediately afterwards. No catalog row
-- changes, so every other session keeps the full protection at every moment.
-- Only the function owner may change that setting; a caller cannot.
--
-- Because foreign-key enforcement is also trigger-based, the replica window
-- contains ONLY deletes from the three leaf tables and the audit de-identifying
-- update; before it opens, the function proves that no other table references
-- the rows about to go. Parent rows (progress, sync state, profile) are deleted
-- AFTER the window with all foreign keys enforced, so any row the function did
-- not know about aborts the whole erasure.
--
-- FAILS CLOSED: any error, an unregistered hook, a leftover reference, or a
-- remaining uuid column equal to the id rolls back everything.
--
-- Out of scope: the auth.users row and the rest of the Auth schema belong to
-- Supabase Auth. Disable or delete the Auth account FIRST or immediately after:
-- a still-valid access token would otherwise create a fresh, empty profile on
-- its next request.
CREATE FUNCTION account.erase_learner(p_user_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_self_owner oid;
    v_hook record;
    v_proc pg_catalog.regprocedure;
    v_hook_result jsonb;
    v_hooks jsonb := '{}'::jsonb;
    v_fk record;
    v_blocked boolean;
    v_left text[];
    n_onboarding bigint; n_exports bigint; n_deletion_cancelled bigint; n_deletion_processed bigint;
    n_feed bigint; n_receipts bigint; n_attempts bigint; n_audit bigint;
    n_progress bigint; n_sync_state bigint; n_profile bigint;
    v_counts jsonb;
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'A user id is required' USING ERRCODE = '22023';
    END IF;
    -- Foreign keys must be live for everything outside the short window below.
    IF current_setting('session_replication_role') <> 'origin' THEN
        RAISE EXCEPTION 'erase_learner must start with session_replication_role = origin'
            USING ERRCODE = '55000';
    END IF;
    -- Staff accounts author and approve content; erasing one is a different,
    -- undesigned procedure.
    IF EXISTS (SELECT 1 FROM app.staff_roles sr
               WHERE sr.user_id = p_user_id OR sr.granted_by = p_user_id) THEN
        RAISE EXCEPTION 'erase_learner refuses an account that has staff records'
            USING ERRCODE = '55000';
    END IF;

    -- Lock the learner. A concurrent sync for this learner waits here and then
    -- fails cleanly (its profile is gone); other learners are not blocked.
    PERFORM 1 FROM app.learner_profiles p WHERE p.user_id = p_user_id FOR UPDATE;
    PERFORM 1 FROM app.account_sync_state s WHERE s.learner_id = p_user_id FOR UPDATE;

    -- ---- 1. hooks of the other schemas ------------------------------------
    SELECT p.proowner INTO v_self_owner
    FROM pg_catalog.pg_proc p
    WHERE p.oid = 'account.erase_learner(uuid)'::pg_catalog.regprocedure;

    FOR v_hook IN
        SELECT n.nspname
        FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
        WHERE p.proname = 'erase_learner' AND n.nspname <> 'account'
          AND NOT EXISTS (SELECT 1 FROM account.erasure_hooks h WHERE h.schema_name = n.nspname)
    LOOP
        RAISE EXCEPTION 'erasure blocked: %.erase_learner exists but schema % is not registered in account.erasure_hooks',
            v_hook.nspname, v_hook.nspname USING ERRCODE = '55000';
    END LOOP;

    FOR v_hook IN SELECT h.schema_name FROM account.erasure_hooks h ORDER BY h.position LOOP
        v_proc := to_regprocedure(format('%I.erase_learner(uuid)', v_hook.schema_name));
        IF v_proc IS NULL THEN
            v_hooks := v_hooks || jsonb_build_object(v_hook.schema_name, 'absent');
            CONTINUE;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_proc p
            WHERE p.oid = v_proc AND p.proowner = v_self_owner
              AND p.prorettype = 'pg_catalog.jsonb'::pg_catalog.regtype
        ) THEN
            RAISE EXCEPTION 'erasure blocked: %.erase_learner(uuid) must return jsonb and be owned by the migration owner',
                v_hook.schema_name USING ERRCODE = '55000';
        END IF;
        EXECUTE format('SELECT %I.erase_learner($1)', v_hook.schema_name)
           INTO v_hook_result USING p_user_id;
        v_hooks := v_hooks || jsonb_build_object(
            v_hook.schema_name, COALESCE(v_hook_result, '{}'::jsonb));
    END LOOP;

    -- ---- 2. this schema's own rows ----------------------------------------
    DELETE FROM account.onboarding_state o WHERE o.user_id = p_user_id;
    GET DIAGNOSTICS n_onboarding = ROW_COUNT;
    DELETE FROM account.export_requests e WHERE e.user_id = p_user_id;
    GET DIAGNOSTICS n_exports = ROW_COUNT;
    DELETE FROM account.deletion_requests d WHERE d.user_id = p_user_id AND d.status = 'cancelled';
    GET DIAGNOSTICS n_deletion_cancelled = ROW_COUNT;
    -- The open request is carried out: keep the fact, drop the identity.
    UPDATE account.deletion_requests d
       SET status = 'processed', processed_at = now(), user_id = NULL
     WHERE d.user_id = p_user_id AND d.status = 'requested';
    GET DIAGNOSTICS n_deletion_processed = ROW_COUNT;

    -- ---- 3. nothing else may reference the append-only rows about to go ------
    -- Lock those rows first: a concurrent insert of a row that references one
    -- of them (in any schema) now waits for us, and fails its own foreign-key
    -- check once the row is gone, instead of slipping in between the check
    -- below and the window. (A row lock fires no trigger.)
    PERFORM 1 FROM app.practice_attempts a WHERE a.learner_id = p_user_id FOR UPDATE;
    PERFORM 1 FROM app.sync_receipts r WHERE r.learner_id = p_user_id FOR UPDATE;
    PERFORM 1 FROM app.account_change_feed f WHERE f.learner_id = p_user_id FOR UPDATE;
    FOR v_fk IN
        SELECT k.conname,
               k.conrelid::pg_catalog.regclass AS child,
               k.confrelid::pg_catalog.regclass AS parent,
               (SELECT string_agg(format('c.%I = p.%I', ca.attname, pa.attname), ' AND ')
                FROM unnest(k.conkey, k.confkey) AS cols(child_att, parent_att)
                JOIN pg_catalog.pg_attribute ca
                  ON ca.attrelid = k.conrelid AND ca.attnum = cols.child_att
                JOIN pg_catalog.pg_attribute pa
                  ON pa.attrelid = k.confrelid AND pa.attnum = cols.parent_att) AS join_on
        FROM pg_catalog.pg_constraint k
        WHERE k.contype = 'f'
          AND k.confrelid IN ('app.practice_attempts'::pg_catalog.regclass,
                              'app.sync_receipts'::pg_catalog.regclass,
                              'app.account_change_feed'::pg_catalog.regclass)
    LOOP
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s c JOIN %s p ON %s WHERE p.learner_id = $1)',
                       v_fk.child, v_fk.parent, v_fk.join_on)
           INTO v_blocked USING p_user_id;
        IF v_blocked THEN
            RAISE EXCEPTION 'erasure blocked: % still references this learner''s rows in % (constraint %); its erase_learner hook must remove them first',
                v_fk.child, v_fk.parent, v_fk.conname USING ERRCODE = '55000';
        END IF;
    END LOOP;

    -- ---- 4. the window: this session only, this transaction only -------------
    SET LOCAL session_replication_role = replica;

    DELETE FROM app.account_change_feed f WHERE f.learner_id = p_user_id;
    GET DIAGNOSTICS n_feed = ROW_COUNT;
    DELETE FROM app.sync_receipts r WHERE r.learner_id = p_user_id;
    GET DIAGNOSTICS n_receipts = ROW_COUNT;
    DELETE FROM app.practice_attempts a WHERE a.learner_id = p_user_id;
    GET DIAGNOSTICS n_attempts = ROW_COUNT;
    -- Audit history is kept; what identifies the learner in it is removed.
    UPDATE app.audit_events e
       SET actor_id = CASE WHEN e.actor_id = p_user_id THEN NULL ELSE e.actor_id END,
           target_id = CASE WHEN e.target_id = p_user_id THEN NULL ELSE e.target_id END,
           details = CASE WHEN position(p_user_id::text IN e.details::text) > 0
                          THEN jsonb_build_object('redacted', true) ELSE e.details END
     WHERE e.actor_id = p_user_id OR e.target_id = p_user_id
        OR position(p_user_id::text IN e.details::text) > 0;
    GET DIAGNOSTICS n_audit = ROW_COUNT;

    SET LOCAL session_replication_role = origin;
    IF current_setting('session_replication_role') <> 'origin' THEN
        RAISE EXCEPTION 'session_replication_role was not restored' USING ERRCODE = 'XX000';
    END IF;

    -- ---- 5. parents, with every trigger and foreign key enforced -------------
    DELETE FROM app.lesson_progress lp WHERE lp.learner_id = p_user_id;
    GET DIAGNOSTICS n_progress = ROW_COUNT;
    DELETE FROM app.account_sync_state s WHERE s.learner_id = p_user_id;
    GET DIAGNOSTICS n_sync_state = ROW_COUNT;
    DELETE FROM app.learner_profiles p WHERE p.user_id = p_user_id;
    GET DIAGNOSTICS n_profile = ROW_COUNT;

    -- ---- 6. postcondition ------------------------------------------------------
    v_left := account.find_learner_references(p_user_id);
    IF cardinality(v_left) > 0 THEN
        RAISE EXCEPTION 'erasure incomplete, nothing was erased: the id is still stored in %',
            array_to_string(v_left, ', ') USING ERRCODE = '55000';
    END IF;

    v_counts := jsonb_build_object(
        'account.onboarding_state', n_onboarding,
        'account.export_requests', n_exports,
        'account.deletion_requests_cancelled', n_deletion_cancelled,
        'account.deletion_requests_processed', n_deletion_processed,
        'app.account_change_feed', n_feed,
        'app.sync_receipts', n_receipts,
        'app.practice_attempts', n_attempts,
        'app.audit_events_deidentified', n_audit,
        'app.lesson_progress', n_progress,
        'app.account_sync_state', n_sync_state,
        'app.learner_profiles', n_profile);

    -- A record that an erasure happened: counts only, no target id.
    PERFORM account.audit_seam(
        'account.learner_erased', 'learner', NULL, 'allowed',
        jsonb_build_object('counts', v_counts));

    RETURN jsonb_build_object('erased', true, 'counts', v_counts, 'hooks', v_hooks);
END;
$$;

-- ============================================================================
-- Privileges
-- ============================================================================
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA account FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION account.get_own_requests() TO edu_api;
GRANT EXECUTE ON FUNCTION account.request_deletion() TO edu_api;
GRANT EXECUTE ON FUNCTION account.cancel_deletion_request() TO edu_api;
GRANT EXECUTE ON FUNCTION account.export_own_data() TO edu_api;

-- >>> B1 SEAM (identity lane) — the erasure executor <<<
-- account.erase_learner(uuid) and account.find_learner_references(uuid) are
-- executable by NOBODY but the owner. When the staff lane's roles exist (B1),
-- a follow-up migration in this lane's block adds, and tests under the real roles:
--
--     GRANT USAGE ON SCHEMA account TO edu_worker;
--     GRANT EXECUTE ON FUNCTION account.erase_learner(uuid) TO edu_worker;
--     -- and, for a staff administrator, a wrapper that first calls
--     -- staff.require_role('admin') and then account.erase_learner(p_user_id).
--
-- together with the audit wiring described in 20261124020100_account_profile.sql.
-- It must never be granted to edu_api.
