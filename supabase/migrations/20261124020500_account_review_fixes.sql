-- Mon Edupreneur 2.0 — schema `account`: fixes from the independent review of 4699a8a
--
-- Overnight mission 2026-11-24, lane IDENTITY. Follow-up migration: the earlier
-- account migrations are merged on the integration branch and are not edited.
-- Nothing in schemas app, ops or staff is created, altered or granted.
--
--   H-1  advance_onboarding / export_own_data lock the caller's profile, so a
--        call racing an erasure waits and is refused instead of leaving the id.
--   M-1  erase_learner refuses when the session actor is the erased learner,
--        and runs the "id is nowhere" check AFTER writing its audit record.
--   M-2  the worker can no longer erase an arbitrary id: erase_learner is
--        owner-only again; edu_worker gets worker_process_deletion(request id),
--        which needs an OPEN deletion request and takes the user from it.
--        The staff path refuses an id that has no learner profile.
--   L-1  hook discovery ignores pg_* (temporary) schemas.
--   L-2  a registered schema whose hook has the wrong signature blocks; the
--        replication role is checked after every hook.
--   L-3  (part) the postcondition also covers unlogged tables and uuid[] columns.
--   L-4  lock order: sync row before profile, as app.sync_apply_operation.

CREATE OR REPLACE FUNCTION account.advance_onboarding(
    p_state text,
    p_onboarding_version integer,
    p_tour_version_seen integer DEFAULT NULL,
    p_tour_dismissed boolean DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_row account.onboarding_state%ROWTYPE;
    v_floor text;
    v_state text;
    v_version integer;
    v_tour integer;
    v_dismissed boolean;
    v_changed boolean;
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    IF (p_state IS NOT NULL AND account.onboarding_rank(p_state) IS NULL)
       OR p_onboarding_version IS NULL OR p_onboarding_version NOT BETWEEN 1 AND 10000
       OR (p_tour_version_seen IS NOT NULL AND p_tour_version_seen NOT BETWEEN 0 AND 10000) THEN
        RAISE EXCEPTION 'Malformed onboarding arguments' USING ERRCODE = '22023';
    END IF;
    -- Review H-1: LOCK the profile (shared). A call that arrives while this
    -- learner is being erased waits for the erasure and is then refused,
    -- instead of committing a row for an erased learner.
    PERFORM 1 FROM app.learner_profiles p WHERE p.user_id = v_actor FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Learner profile required' USING ERRCODE = '42501';
    END IF;

    -- Create the row if needed, then lock it: two devices reporting at the
    -- same moment are applied one after the other.
    INSERT INTO account.onboarding_state (user_id, onboarding_version)
    VALUES (v_actor, p_onboarding_version)
    ON CONFLICT (user_id) DO NOTHING;
    SELECT * INTO v_row FROM account.onboarding_state o WHERE o.user_id = v_actor FOR UPDATE;

    v_floor := account.onboarding_floor(v_actor);
    v_state := v_row.state;
    IF account.onboarding_rank(v_floor) > account.onboarding_rank(v_state) THEN
        v_state := v_floor;
    END IF;
    IF p_state IS NOT NULL AND account.onboarding_rank(p_state) > account.onboarding_rank(v_state) THEN
        v_state := p_state;
    END IF;
    v_version := greatest(v_row.onboarding_version, p_onboarding_version);
    v_tour := greatest(v_row.tour_version_seen, COALESCE(p_tour_version_seen, 0));
    v_dismissed := v_row.tour_dismissed OR COALESCE(p_tour_dismissed, false);

    v_changed := v_state <> v_row.state
        OR v_version <> v_row.onboarding_version
        OR v_tour <> v_row.tour_version_seen
        OR v_dismissed <> v_row.tour_dismissed;

    IF v_changed THEN
        UPDATE account.onboarding_state o
           SET state = v_state,
               onboarding_version = v_version,
               tour_version_seen = v_tour,
               tour_dismissed = v_dismissed,
               completed_at = CASE WHEN v_state = 'ready'
                                   THEN COALESCE(o.completed_at, now()) END,
               updated_at = now()
         WHERE o.user_id = v_actor
        RETURNING * INTO v_row;
    END IF;

    RETURN jsonb_build_object(
        'state', v_row.state,
        'onboarding_version', v_row.onboarding_version,
        'tour_version_seen', v_row.tour_version_seen,
        'tour_dismissed', v_row.tour_dismissed,
        'completed_at', v_row.completed_at,
        'updated_at', v_row.updated_at,
        'changed', v_changed);
END;
$$;

CREATE OR REPLACE FUNCTION account.export_own_data()
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
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

    -- Review H-1: lock the profile (shared) so an export cannot commit a record
    -- for a learner whose erasure is in flight.
    PERFORM 1 FROM app.learner_profiles p WHERE p.user_id = v_actor FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Learner profile required' USING ERRCODE = '42501';
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

CREATE OR REPLACE FUNCTION account.find_learner_references(p_user_id uuid)
RETURNS text[]
LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, pg_temp
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
        SELECT n.nspname, c.relname, a.attname,
               a.atttypid = 'pg_catalog.uuid[]'::pg_catalog.regtype AS is_array
        FROM pg_catalog.pg_attribute a
        JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE a.atttypid IN ('pg_catalog.uuid'::pg_catalog.regtype, 'pg_catalog.uuid[]'::pg_catalog.regtype)
          AND a.attnum > 0 AND NOT a.attisdropped
          AND c.relkind IN ('r', 'p') AND NOT c.relispartition
          AND c.relpersistence IN ('p', 'u')
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
        EXECUTE format(CASE WHEN v_col.is_array
                            THEN 'SELECT EXISTS (SELECT 1 FROM %I.%I WHERE $1 = ANY (%I))'
                            ELSE 'SELECT EXISTS (SELECT 1 FROM %I.%I WHERE %I = $1)' END,
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

CREATE OR REPLACE FUNCTION account.erase_learner(p_user_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
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
    -- Review M-1: the audit writer records the session's actor. If that were
    -- the learner being erased, the erasure record itself would keep the id.
    IF app.current_actor_id() IS NOT DISTINCT FROM p_user_id THEN
        RAISE EXCEPTION 'erase_learner cannot run with the erased learner as the session actor'
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
    -- Review L-4: same order as app.sync_apply_operation (sync row, then the
    -- profile through its foreign-key checks), so the two cannot deadlock.
    -- The sync row is locked again after the profile: a learner's very first
    -- sync may have created it while we waited for the profile.
    PERFORM 1 FROM app.account_sync_state s WHERE s.learner_id = p_user_id FOR UPDATE;
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
          AND n.nspname !~ '^pg_'  -- review L-1: a session's temporary schema is not a module
          AND NOT EXISTS (SELECT 1 FROM account.erasure_hooks h WHERE h.schema_name = n.nspname)
    LOOP
        RAISE EXCEPTION 'erasure blocked: %.erase_learner exists but schema % is not registered in account.erasure_hooks',
            v_hook.nspname, v_hook.nspname USING ERRCODE = '55000';
    END LOOP;

    FOR v_hook IN SELECT h.schema_name FROM account.erasure_hooks h ORDER BY h.position LOOP
        v_proc := to_regprocedure(format('%I.erase_learner(uuid)', v_hook.schema_name));
        IF v_proc IS NULL THEN
            -- Review L-2: a hook with another signature is a mistake, not an absence.
            IF EXISTS (SELECT 1 FROM pg_catalog.pg_proc p
                       JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                       WHERE n.nspname = v_hook.schema_name AND p.proname = 'erase_learner') THEN
                RAISE EXCEPTION 'erasure blocked: %.erase_learner exists but not with the signature (uuid)',
                    v_hook.schema_name USING ERRCODE = '55000';
            END IF;
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
        -- Review L-2: a hook must hand the session back with triggers ON.
        IF current_setting('session_replication_role') <> 'origin' THEN
            SET LOCAL session_replication_role = origin;
            RAISE EXCEPTION 'erasure blocked: %.erase_learner left session_replication_role changed',
                v_hook.schema_name USING ERRCODE = '55000';
        END IF;
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
    -- SET LOCAL lasts until the end of the CALLER'S transaction, not of this
    -- function. The setting is therefore put back on every path out of the
    -- window: explicitly after the last statement, and in the handler if any
    -- statement fails (the failed block is rolled back as a whole, which
    -- already restores the setting; the handler does not rely on that).
    BEGIN
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
    EXCEPTION WHEN OTHERS THEN
        SET LOCAL session_replication_role = origin;
        RAISE;
    END;
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

    -- A record that an erasure happened: numbers only, no target id. (The
    -- audit writer accepts a flat object of counts and codes, nothing else.)
    PERFORM account.audit_seam(
        'account.learner_erased', 'learner', NULL, 'allowed',
        jsonb_build_object(
            'practice_attempts', n_attempts,
            'sync_receipts', n_receipts,
            'change_feed_entries', n_feed,
            'lesson_progress', n_progress,
            'sync_states', n_sync_state,
            'learner_profiles', n_profile,
            'onboarding_states', n_onboarding,
            'export_requests', n_exports,
            'deletion_requests_cancelled', n_deletion_cancelled,
            'deletion_requests_processed', n_deletion_processed,
            'audit_events_deidentified', n_audit,
            'hooks_called', (SELECT count(*) FROM jsonb_each(v_hooks) h WHERE h.value <> '"absent"'::jsonb)));

    -- ---- 6. postcondition (review M-1: AFTER the audit record is written) ------------------------------------------------------
    v_left := account.find_learner_references(p_user_id);
    IF cardinality(v_left) > 0 THEN
        RAISE EXCEPTION 'erasure incomplete, nothing was erased: the id is still stored in %',
            array_to_string(v_left, ', ') USING ERRCODE = '55000';
    END IF;

    RETURN jsonb_build_object('erased', true, 'counts', v_counts, 'hooks', v_hooks);
END;
$$;

-- ============================================================================
-- M-2: executors
-- ============================================================================
-- The worker processes a learner's OWN open deletion request, named by the
-- request id. It never chooses a user id. No open request with that id: an
-- error, nothing erased, no audit event.
-- (A cooling-off period before a request may be processed is a PO-04
-- decision; none is applied.)
CREATE FUNCTION account.worker_process_deletion(p_request_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_user_id uuid;
BEGIN
    IF p_request_id IS NULL THEN
        RAISE EXCEPTION 'A deletion request id is required' USING ERRCODE = '22023';
    END IF;
    SELECT d.user_id INTO v_user_id
    FROM account.deletion_requests d
    WHERE d.id = p_request_id AND d.status = 'requested'
    FOR UPDATE;
    IF NOT FOUND OR v_user_id IS NULL THEN
        RAISE EXCEPTION 'No open deletion request with this id' USING ERRCODE = 'P0002';
    END IF;
    RETURN account.erase_learner(v_user_id);
END;
$$;

CREATE OR REPLACE FUNCTION account.staff_erase_learner(p_user_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    PERFORM staff.require_role('admin');
    IF p_user_id IS NULL
       OR NOT EXISTS (SELECT 1 FROM app.learner_profiles p WHERE p.user_id = p_user_id) THEN
        RAISE EXCEPTION 'No learner with this id' USING ERRCODE = 'P0002';
    END IF;
    RETURN account.erase_learner(p_user_id);
END;
$$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA account FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION account.erase_learner(uuid) FROM edu_worker;
GRANT EXECUTE ON FUNCTION account.worker_process_deletion(uuid) TO edu_worker;
-- account.erase_learner(uuid) is executable by its owner only. CREATE OR
-- REPLACE kept every other grant as it was.
