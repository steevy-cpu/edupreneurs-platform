-- Mon Edupreneur 2.0 — leaderboard: independent-review fixes (LB-1 .. LB-7)
--
-- Final verification 2026-11-25. Changes ONLY by CREATE OR REPLACE and one new
-- table; the original migration (20261124060100) is untouched.
--
--   LB-1  Privacy. A minimum cohort size K is enforced IN SQL, failing closed.
--         Rank and size are read ONLY from the latest snapshot; nothing is
--         recomputed live, so another member's opt-in / opt-out / staff grant
--         is not observable until the next refresh. The refresh applies K too.
--   LB-2  Refresh takes the cohort row FOR SHARE; withdraw and erase_learner
--         take it FOR UPDATE: a withdrawal is never resurrected by a refresh.
--   LB-3  my_standing is O(1) (no per-row helper calls); refresh is set-based.
--   LB-6  Scoring uses an allow-list of ledger source kinds.
--   LB-7  A closed period returns the caller's frozen snapshot Gold.
--   LB-4  (cohort block behind the cohorts flag) is enforced by the API layer.
--
-- BLOCKED_BY_OWNER: the value of K (default 5 is a conservative placeholder).

-- ============================================================================
-- Settings: one row, owner-only (RLS without policy, no grant to anyone)
-- ============================================================================
CREATE TABLE leaderboard.config (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    -- No rank and no cohort size is ever shown for a cohort smaller than this.
    -- BLOCKED_BY_OWNER: the real value is a policy decision.
    min_cohort_size integer NOT NULL DEFAULT 5 CHECK (min_cohort_size BETWEEN 1 AND 10000),
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO leaderboard.config DEFAULT VALUES;
ALTER TABLE leaderboard.config ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON leaderboard.config FROM PUBLIC, anon, authenticated, service_role;
COMMENT ON TABLE leaderboard.config IS
    'Private settings (one row). min_cohort_size: smaller cohorts get no rank and no size. Owner only.';

-- ============================================================================
-- LB-6: allow-list of source kinds
-- ============================================================================
CREATE OR REPLACE FUNCTION leaderboard.period_gold(p_learner_id uuid, p_starts_on date, p_ends_on date)
RETURNS bigint
LANGUAGE sql STABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT GREATEST(COALESCE(sum(l.amount), 0), 0)::bigint
    FROM rewards.ledger l
    WHERE l.learner_id = p_learner_id
      AND l.source_kind IN ('question_first_correct', 'lesson_first_completed', 'achievement', 'reversal')
      AND (p_starts_on IS NULL OR l.accepted_day BETWEEN p_starts_on AND p_ends_on)
$$;

-- ============================================================================
-- LB-2: withdraw / erase serialise against refresh
-- ============================================================================
CREATE OR REPLACE FUNCTION leaderboard.withdraw(p_cohort_id uuid, p_learner_id uuid)
RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_changed boolean;
BEGIN
    -- Waits for an in-flight refresh (which holds the row FOR SHARE) and then
    -- deletes what it wrote; a refresh that starts later sees the opt-out.
    PERFORM 1 FROM leaderboard.cohorts c WHERE c.id = p_cohort_id FOR UPDATE;
    UPDATE leaderboard.memberships SET opted_out_at = now()
     WHERE cohort_id = p_cohort_id AND learner_id = p_learner_id AND opted_out_at IS NULL;
    v_changed := FOUND;
    DELETE FROM leaderboard.snapshots
     WHERE cohort_id = p_cohort_id AND learner_id = p_learner_id;
    RETURN v_changed;
END;
$$;

CREATE OR REPLACE FUNCTION leaderboard.erase_learner(p_user_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_snapshots bigint;
    v_memberships bigint;
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'Learner id required' USING ERRCODE = '22023';
    END IF;
    -- Fixed lock order (by id) so two erasures cannot deadlock.
    PERFORM 1 FROM leaderboard.cohorts c
     WHERE c.id IN (SELECT m.cohort_id FROM leaderboard.memberships m WHERE m.learner_id = p_user_id)
     ORDER BY c.id FOR UPDATE;
    WITH gone AS (DELETE FROM leaderboard.snapshots WHERE learner_id = p_user_id RETURNING 1)
        SELECT count(*) INTO v_snapshots FROM gone;
    WITH gone AS (DELETE FROM leaderboard.memberships WHERE learner_id = p_user_id RETURNING 1)
        SELECT count(*) INTO v_memberships FROM gone;
    RETURN jsonb_build_object(
        'schema', 'leaderboard',
        'deleted', jsonb_build_object('snapshots', v_snapshots, 'memberships', v_memberships));
END;
$$;

-- ============================================================================
-- Refresh: locked (LB-2), set-based (LB-3), minimum cohort size (LB-1)
-- ============================================================================
CREATE OR REPLACE FUNCTION leaderboard.refresh_snapshot(p_cohort_id uuid, p_period text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_p record;
    v_run leaderboard.snapshot_runs%ROWTYPE;
    v_now timestamptz := clock_timestamp();
    v_members integer;
    v_min integer;
BEGIN
    IF p_cohort_id IS NULL THEN
        RAISE EXCEPTION 'Cohort required' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_p FROM leaderboard.resolve_period(p_period);
    -- FOR SHARE: many refreshes may run together, but withdraw, erase and enroll
    -- (FOR UPDATE) wait for this one to commit, and a refresh that starts after
    -- them reads their result.
    PERFORM 1 FROM leaderboard.cohorts c WHERE c.id = p_cohort_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown cohort' USING ERRCODE = '22023';
    END IF;
    -- One refresh at a time per (cohort, period); key namespace 54060.
    PERFORM pg_advisory_xact_lock(54060, hashtext(p_cohort_id::text || ':' || v_p.period_key));
    -- Fail closed: a missing setting row means the default 5.
    v_min := COALESCE((SELECT g.min_cohort_size FROM leaderboard.config g), 5);

    INSERT INTO leaderboard.periods (period_key, kind, starts_on, ends_on)
    VALUES (v_p.period_key, v_p.kind, v_p.starts_on, v_p.ends_on)
    ON CONFLICT (period_key) DO NOTHING;

    SELECT * INTO v_run FROM leaderboard.snapshot_runs r
     WHERE r.period_key = v_p.period_key AND r.cohort_id = p_cohort_id;
    IF FOUND AND v_run.frozen_at IS NOT NULL THEN
        RETURN jsonb_build_object('period', v_p.period_key, 'cohort_id', p_cohort_id,
                                  'members', v_run.member_count, 'computed_at', v_run.computed_at,
                                  'frozen', true, 'recomputed', false);
    END IF;

    DELETE FROM leaderboard.snapshots s
     WHERE s.period_key = v_p.period_key AND s.cohort_id = p_cohort_id;

    INSERT INTO leaderboard.snapshot_runs (period_key, cohort_id, computed_at, member_count, frozen_at)
    VALUES (v_p.period_key, p_cohort_id, v_now, 0, NULL)
    ON CONFLICT (period_key, cohort_id) DO UPDATE SET computed_at = EXCLUDED.computed_at;

    WITH scored AS (
        SELECT m.learner_id, g.gold,
               -- Non-identifying and different for every period and cohort, so
               -- nobody is "always first" among equals.
               sha256(convert_to(p_cohort_id::text || ':' || v_p.period_key || ':' || m.learner_id::text, 'UTF8')) AS tie_key
        FROM leaderboard.memberships m
        CROSS JOIN LATERAL (
            SELECT GREATEST(COALESCE(sum(l.amount), 0), 0)::bigint AS gold
            FROM rewards.ledger l
            WHERE l.learner_id = m.learner_id
              AND l.source_kind IN ('question_first_correct', 'lesson_first_completed', 'achievement', 'reversal')
              AND (v_p.starts_on IS NULL OR l.accepted_day BETWEEN v_p.starts_on AND v_p.ends_on)
        ) g
        WHERE m.cohort_id = p_cohort_id AND m.opted_out_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM app.staff_roles s WHERE s.user_id = m.learner_id)
          AND EXISTS (SELECT 1 FROM auth.users u WHERE u.id = m.learner_id AND u.deleted_at IS NULL)
    ), total AS (
        SELECT count(*) AS n FROM scored
    )
    INSERT INTO leaderboard.snapshots (period_key, cohort_id, learner_id, gold, rank, tie_order, computed_at)
    SELECT v_p.period_key, p_cohort_id, sc.learner_id, sc.gold,
           (rank() OVER (ORDER BY sc.gold DESC))::integer,
           (row_number() OVER (ORDER BY sc.gold DESC, sc.tie_key))::integer,
           v_now
    FROM scored sc CROSS JOIN total t
    -- LB-1: below the minimum no row, hence no rank and no size, is written.
    WHERE t.n >= v_min;
    GET DIAGNOSTICS v_members = ROW_COUNT;

    UPDATE leaderboard.snapshot_runs r
       SET member_count = v_members,
           frozen_at = CASE WHEN v_p.is_closed THEN v_now END
     WHERE r.period_key = v_p.period_key AND r.cohort_id = p_cohort_id;

    RETURN jsonb_build_object('period', v_p.period_key, 'cohort_id', p_cohort_id,
                              'members', v_members, 'computed_at', v_now,
                              'frozen', v_p.is_closed, 'recomputed', true,
                              'minimum_cohort_size', v_min);
END;
$$;

-- ============================================================================
-- Learner read: own standing; rank and size ONLY from the latest snapshot
-- ============================================================================
-- Constant work per call: one membership row, one run row, one snapshot row
-- (all by key), one ledger sum for the caller. Nothing is derived from other
-- members at read time, so their opt-out, staff grant or erasure is invisible
-- until the next refresh. The caller's own row is checked live: a withdrawn,
-- erased, staff or deleted caller gets no cohort block at once.
CREATE OR REPLACE FUNCTION leaderboard.my_standing(p_period text)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_p record;
    v_m leaderboard.memberships%ROWTYPE;
    v_min integer := COALESCE((SELECT g.min_cohort_size FROM leaderboard.config g), 5);
    v_cohort jsonb;
    v_live bigint;
    v_gold bigint;
    v_snap_gold bigint;
    v_snap_rank integer;
    v_rank integer;
    v_size integer;
    v_count integer;
    v_computed timestamptz;
    v_frozen boolean := false;
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'Not authenticated' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_p FROM leaderboard.resolve_period(p_period);
    v_live := leaderboard.period_gold(v_actor, v_p.starts_on, v_p.ends_on);
    v_gold := v_live;

    SELECT * INTO v_m FROM leaderboard.memberships m
     WHERE m.learner_id = v_actor AND m.opted_out_at IS NULL;
    IF FOUND AND leaderboard.is_rankable(v_actor) THEN
        SELECT r.computed_at, r.frozen_at IS NOT NULL, r.member_count
          INTO v_computed, v_frozen, v_count
          FROM leaderboard.snapshot_runs r
         WHERE r.period_key = v_p.period_key AND r.cohort_id = v_m.cohort_id;
        v_frozen := COALESCE(v_frozen, false);
        SELECT s.gold, s.rank INTO v_snap_gold, v_snap_rank
          FROM leaderboard.snapshots s
         WHERE s.period_key = v_p.period_key AND s.cohort_id = v_m.cohort_id
           AND s.learner_id = v_actor;
        -- LB-1: rank and size only when the SNAPSHOT of that moment held at least K.
        IF v_snap_gold IS NOT NULL AND v_count >= v_min THEN
            v_rank := v_snap_rank;
            v_size := v_count;
        END IF;
        -- LB-7: a closed period shows the frozen figure, not the live sum.
        IF v_p.is_closed AND v_frozen AND v_snap_gold IS NOT NULL THEN
            v_gold := v_snap_gold;
        END IF;
        v_cohort := jsonb_build_object(
            'cohort_id', v_m.cohort_id,
            'pseudonym', leaderboard.display_pseudonym(v_m.pseudonym_id, v_m.pseudonym_suffix),
            'rank', v_rank,
            'size', v_size,
            'snapshot_gold', v_snap_gold,
            'computed_at', v_computed,
            'frozen', v_frozen);
    END IF;

    RETURN jsonb_build_object(
        'period', v_p.period_key,
        'kind', v_p.kind,
        'starts_on', v_p.starts_on,
        'ends_on', v_p.ends_on,
        'closed', v_p.is_closed,
        'gold', v_gold,
        'cohort', v_cohort);
END;
$$;

-- Grants are unchanged: CREATE OR REPLACE keeps them. Restated for the new table only.
REVOKE ALL ON ALL TABLES IN SCHEMA leaderboard FROM PUBLIC, anon, authenticated;
