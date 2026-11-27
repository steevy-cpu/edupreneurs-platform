-- Mon Edupreneur 2.0 — leaderboard: private rank and opt-in synthetic cohorts
--
-- Overnight mission 2026-11-24, lane LEADERBOARD (F14, depends on the Gold
-- ledger of the rewards lane).
--
-- PRIVACY POSITION (the learners are minors)
--   * There is NO public or global ranking in any code path. A rank exists
--     only inside one cohort, and only for learners with an explicit opt-in
--     row. Unknown consent = not a member.
--   * No real name, no profile display name, no e-mail is stored in or
--     returned from this schema. The only label is a PSEUDONYM assigned by the
--     server from the allow-list below — never text typed by a user.
--   * Every cohort is SYNTHETIC tonight (CHECK constraint).
--   * A score is computed ONLY from rewards.ledger (server-verified Gold),
--     never from a client number or a profile column.
--
-- BLOCKED_BY_OWNER: who may consent for a minor, whether real children are
-- ever shown a ranking, the pseudonym policy, and every Gold amount (PO-09).
--
-- Nothing is created in schema app, rewards, ops or staff. This schema only
-- READS rewards.ledger, app.staff_roles and auth.users through its own
-- definer functions, takes no rewards lock and adds no trigger anywhere else.

CREATE SCHEMA leaderboard;
REVOKE ALL ON SCHEMA leaderboard FROM PUBLIC;
REVOKE ALL ON SCHEMA leaderboard FROM anon, authenticated;
COMMENT ON SCHEMA leaderboard IS
    'Private. Opt-in, pseudonymous, cohort-scoped Gold ranking. Reached only through FastAPI; never expose this schema in the Supabase Data API.';

-- ============================================================================
-- Pseudonym allow-list (generated, neutral, never user-typed)
-- ============================================================================
CREATE TABLE leaderboard.pseudonym_pool (
    id smallint PRIMARY KEY,
    name text NOT NULL UNIQUE CHECK (name ~ '^[A-Z][a-z]+ [A-Z][a-z]+$')
);

INSERT INTO leaderboard.pseudonym_pool (id, name)
SELECT (row_number() OVER (ORDER BY n.ord, q.ord))::smallint, n.word || ' ' || q.word
FROM unnest(ARRAY[
        'Colibri','Palmier','Mangue','Corail','Dauphin','Tortue','Flamant','Hibiscus',
        'Papillon','Cocotier','Lambi','Soleil','Montagne','Nuage','Lune','Perroquet',
        'Bambou','Citron','Goyave','Ananas','Tambour','Voilier','Lagon','Canari'
     ]) WITH ORDINALITY AS n(word, ord)
CROSS JOIN unnest(ARRAY[
        'Agile','Calme','Sage','Brave','Rapide','Tranquille','Habile','Solide',
        'Jaune','Rouge','Orange','Turquoise','Aimable','Juste','Libre','Modeste',
        'Noble','Tenace','Utile','Vivace','Jeune','Riche','Rose','Mauve'
     ]) WITH ORDINALITY AS q(word, ord);

-- ============================================================================
-- Periods
-- ============================================================================
-- 'all'         all-time
-- 'YYYY-MM-DD'  the Haiti-calendar week (Monday..Sunday) starting that Monday
-- A row appears the first time a snapshot is computed for the period.
CREATE TABLE leaderboard.periods (
    period_key text PRIMARY KEY CHECK (period_key = 'all' OR period_key ~ '^\d{4}-\d{2}-\d{2}$'),
    kind text NOT NULL CHECK (kind IN ('all_time', 'week')),
    starts_on date,
    ends_on date,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((kind = 'all_time' AND period_key = 'all' AND starts_on IS NULL AND ends_on IS NULL)
        OR (kind = 'week' AND starts_on IS NOT NULL AND ends_on = starts_on + 6
            AND period_key = to_char(starts_on, 'YYYY-MM-DD')
            AND extract(isodow FROM starts_on) = 1))
);

-- ============================================================================
-- Cohorts (synthetic) and memberships (explicit opt-in)
-- ============================================================================
CREATE TABLE leaderboard.cohorts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL CHECK (kind IN ('class', 'school')),
    -- A machine code, not a school or class name.
    code text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9][a-z0-9_-]{2,39}$'),
    -- BLOCKED_BY_OWNER: no real class or school may be enrolled yet.
    is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic),
    created_by uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE leaderboard.memberships (
    cohort_id uuid NOT NULL REFERENCES leaderboard.cohorts(id) ON DELETE RESTRICT,
    learner_id uuid NOT NULL REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    -- The consent record. A member is a row with opted_out_at IS NULL.
    opted_in_at timestamptz NOT NULL,
    opted_out_at timestamptz,
    pseudonym_id smallint NOT NULL REFERENCES leaderboard.pseudonym_pool(id) ON DELETE RESTRICT,
    -- 0 = the bare name; n > 0 = "<name> n" once a cohort outgrows the pool.
    pseudonym_suffix smallint NOT NULL DEFAULT 0 CHECK (pseudonym_suffix BETWEEN 0 AND 999),
    PRIMARY KEY (cohort_id, learner_id),
    CONSTRAINT memberships_pseudonym_unique_in_cohort UNIQUE (cohort_id, pseudonym_id, pseudonym_suffix),
    CHECK (opted_out_at IS NULL OR opted_out_at >= opted_in_at)
);
-- A learner is ranked in at most ONE cohort at a time ("my cohort").
CREATE UNIQUE INDEX memberships_one_active_cohort ON leaderboard.memberships (learner_id)
    WHERE opted_out_at IS NULL;

-- ============================================================================
-- Snapshots
-- ============================================================================
-- One row per (period, cohort) computation. frozen_at is set when the snapshot
-- was taken after the period ended: it is then never recomputed.
CREATE TABLE leaderboard.snapshot_runs (
    period_key text NOT NULL REFERENCES leaderboard.periods(period_key) ON DELETE RESTRICT,
    cohort_id uuid NOT NULL REFERENCES leaderboard.cohorts(id) ON DELETE RESTRICT,
    computed_at timestamptz NOT NULL,
    member_count integer NOT NULL CHECK (member_count >= 0),
    frozen_at timestamptz,
    PRIMARY KEY (period_key, cohort_id)
);

CREATE TABLE leaderboard.snapshots (
    period_key text NOT NULL,
    cohort_id uuid NOT NULL,
    learner_id uuid NOT NULL REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    gold bigint NOT NULL CHECK (gold >= 0),
    -- Competition rank at computation time (1, 1, 3).
    rank integer NOT NULL CHECK (rank >= 1),
    -- Unique display order; inside a tie it follows a hash, not an identity.
    tie_order integer NOT NULL CHECK (tie_order >= rank),
    computed_at timestamptz NOT NULL,
    PRIMARY KEY (period_key, cohort_id, learner_id),
    CONSTRAINT snapshots_order_unique UNIQUE (period_key, cohort_id, tie_order),
    CONSTRAINT snapshots_run_fkey FOREIGN KEY (period_key, cohort_id)
        REFERENCES leaderboard.snapshot_runs(period_key, cohort_id) ON DELETE RESTRICT,
    CONSTRAINT snapshots_member_fkey FOREIGN KEY (cohort_id, learner_id)
        REFERENCES leaderboard.memberships(cohort_id, learner_id) ON DELETE RESTRICT
);
CREATE INDEX idx_snapshots_learner ON leaderboard.snapshots (learner_id);

-- RLS on everything, and NO policy: only the definer functions below (owner
-- postgres) ever read or write these tables.
ALTER TABLE leaderboard.pseudonym_pool ENABLE ROW LEVEL SECURITY;
ALTER TABLE leaderboard.periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE leaderboard.cohorts ENABLE ROW LEVEL SECURITY;
ALTER TABLE leaderboard.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE leaderboard.snapshot_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE leaderboard.snapshots ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- Internal helpers (EXECUTE granted to nobody)
-- ============================================================================
-- 'all' | 'week' (the current Haiti week) | 'YYYY-MM-DD' (a Monday, not in the
-- future). Anything else: 22023, without repeating the rejected value.
CREATE FUNCTION leaderboard.resolve_period(p_period text)
RETURNS TABLE (period_key text, kind text, starts_on date, ends_on date, is_closed boolean)
LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_today date := rewards.haiti_day(now());
    v_this_monday date := date_trunc('week', v_today::timestamp)::date;
    v_start date;
BEGIN
    IF p_period = 'all' THEN
        RETURN QUERY SELECT 'all'::text, 'all_time'::text, NULL::date, NULL::date, false;
        RETURN;
    END IF;
    IF p_period = 'week' THEN
        v_start := v_this_monday;
    ELSIF p_period ~ '^\d{4}-\d{2}-\d{2}$' THEN
        BEGIN
            v_start := p_period::date;
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION 'Unknown period' USING ERRCODE = '22023';
        END;
    END IF;
    IF v_start IS NULL OR extract(isodow FROM v_start) <> 1
       OR v_start > v_this_monday OR v_start < DATE '2026-01-05' THEN
        RAISE EXCEPTION 'Unknown period' USING ERRCODE = '22023';
    END IF;
    RETURN QUERY SELECT to_char(v_start, 'YYYY-MM-DD'), 'week'::text, v_start, v_start + 6,
                        (v_start + 6) < v_today;
END;
$$;

-- An account may be ranked only if it never held a staff role (active or not)
-- and its auth account still exists and is not soft-deleted.
CREATE FUNCTION leaderboard.is_rankable(p_learner_id uuid)
RETURNS boolean
LANGUAGE sql STABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT NOT EXISTS (SELECT 1 FROM app.staff_roles s WHERE s.user_id = p_learner_id)
       AND EXISTS (SELECT 1 FROM auth.users u WHERE u.id = p_learner_id AND u.deleted_at IS NULL)
$$;

-- "Gold earned by learning" in a period: awards and their reversals, dated by
-- accepted_day. Staff `adjustment` rows do NOT count. Never negative.
CREATE FUNCTION leaderboard.period_gold(p_learner_id uuid, p_starts_on date, p_ends_on date)
RETURNS bigint
LANGUAGE sql STABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT GREATEST(COALESCE(sum(l.amount), 0), 0)::bigint
    FROM rewards.ledger l
    WHERE l.learner_id = p_learner_id
      AND l.source_kind <> 'adjustment'
      AND (p_starts_on IS NULL OR l.accepted_day BETWEEN p_starts_on AND p_ends_on)
$$;

CREATE FUNCTION leaderboard.display_pseudonym(p_pseudonym_id smallint, p_suffix smallint)
RETURNS text
LANGUAGE sql STABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT p.name || CASE WHEN p_suffix > 0 THEN ' ' || p_suffix::text ELSE '' END
    FROM leaderboard.pseudonym_pool p WHERE p.id = p_pseudonym_id
$$;

-- The rows of a snapshot that may be shown RIGHT NOW: the learner is still an
-- opted-in member and still rankable. Opt-out, erasure and a staff grant
-- therefore take effect on the next read, not at the next refresh.
CREATE FUNCTION leaderboard.visible_rows(p_cohort_id uuid, p_period_key text)
RETURNS TABLE (learner_id uuid, gold bigint, tie_order integer, pseudonym text)
LANGUAGE sql STABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT s.learner_id, s.gold, s.tie_order,
           leaderboard.display_pseudonym(m.pseudonym_id, m.pseudonym_suffix)
    FROM leaderboard.snapshots s
    JOIN leaderboard.memberships m
      ON m.cohort_id = s.cohort_id AND m.learner_id = s.learner_id AND m.opted_out_at IS NULL
    WHERE s.cohort_id = p_cohort_id AND s.period_key = p_period_key
      AND leaderboard.is_rankable(s.learner_id)
$$;

-- ============================================================================
-- Membership (internal: the caller-facing wrappers come with the cohort view)
-- ============================================================================
CREATE FUNCTION leaderboard.enroll(p_cohort_id uuid, p_learner_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    c_max_members CONSTANT integer := 10000;
    v_existing leaderboard.memberships%ROWTYPE;
    v_count integer;
    v_pool integer;
    v_pid smallint;
    v_suffix smallint;
BEGIN
    IF p_cohort_id IS NULL OR p_learner_id IS NULL THEN
        RAISE EXCEPTION 'Cohort and learner required' USING ERRCODE = '22023';
    END IF;
    -- Serialises pseudonym assignment inside the cohort.
    PERFORM 1 FROM leaderboard.cohorts c WHERE c.id = p_cohort_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown cohort' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.learner_profiles lp WHERE lp.user_id = p_learner_id)
       OR NOT leaderboard.is_rankable(p_learner_id) THEN
        RAISE EXCEPTION 'Account cannot join a cohort' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_existing FROM leaderboard.memberships m
     WHERE m.cohort_id = p_cohort_id AND m.learner_id = p_learner_id;
    IF FOUND THEN
        IF v_existing.opted_out_at IS NOT NULL THEN
            -- A new opt-in: new consent instant, same reserved pseudonym.
            UPDATE leaderboard.memberships SET opted_in_at = now(), opted_out_at = NULL
             WHERE cohort_id = p_cohort_id AND learner_id = p_learner_id;
        END IF;
    ELSE
        SELECT count(*) INTO v_count FROM leaderboard.memberships m WHERE m.cohort_id = p_cohort_id;
        IF v_count >= c_max_members THEN
            RAISE EXCEPTION 'Cohort is full' USING ERRCODE = '22023';
        END IF;
        SELECT count(*) INTO v_pool FROM leaderboard.pseudonym_pool;
        SELECT p.id, s.n::smallint INTO v_pid, v_suffix
        FROM leaderboard.pseudonym_pool p
        CROSS JOIN generate_series(0, v_count / v_pool) AS s(n)
        WHERE NOT EXISTS (SELECT 1 FROM leaderboard.memberships m
                          WHERE m.cohort_id = p_cohort_id AND m.pseudonym_id = p.id
                            AND m.pseudonym_suffix = s.n)
        ORDER BY s.n, random()
        LIMIT 1;
        INSERT INTO leaderboard.memberships (cohort_id, learner_id, opted_in_at, pseudonym_id, pseudonym_suffix)
        VALUES (p_cohort_id, p_learner_id, now(), v_pid, v_suffix);
    END IF;

    RETURN (SELECT jsonb_build_object(
                'cohort_id', m.cohort_id,
                'pseudonym', leaderboard.display_pseudonym(m.pseudonym_id, m.pseudonym_suffix),
                'opted_in_at', m.opted_in_at)
            FROM leaderboard.memberships m
            WHERE m.cohort_id = p_cohort_id AND m.learner_id = p_learner_id);
END;
$$;

-- Opt-out: the consent row keeps both instants; the learner's snapshot rows in
-- that cohort are DELETED (frozen periods included: revocation wins).
CREATE FUNCTION leaderboard.withdraw(p_cohort_id uuid, p_learner_id uuid)
RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_changed boolean;
BEGIN
    UPDATE leaderboard.memberships SET opted_out_at = now()
     WHERE cohort_id = p_cohort_id AND learner_id = p_learner_id AND opted_out_at IS NULL;
    v_changed := FOUND;
    DELETE FROM leaderboard.snapshots
     WHERE cohort_id = p_cohort_id AND learner_id = p_learner_id;
    RETURN v_changed;
END;
$$;

-- ============================================================================
-- Snapshot refresh
-- ============================================================================
-- Rebuilds the snapshot of one cohort for one period from rewards.ledger alone.
-- Idempotent: the same ledger and memberships give the same rows. A period
-- that has ended is computed ONCE more (the closing snapshot) and then frozen.
CREATE FUNCTION leaderboard.refresh_snapshot(p_cohort_id uuid, p_period text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_p record;
    v_run leaderboard.snapshot_runs%ROWTYPE;
    v_now timestamptz := clock_timestamp();
    v_members integer;
BEGIN
    IF p_cohort_id IS NULL THEN
        RAISE EXCEPTION 'Cohort required' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_p FROM leaderboard.resolve_period(p_period);
    IF NOT EXISTS (SELECT 1 FROM leaderboard.cohorts c WHERE c.id = p_cohort_id) THEN
        RAISE EXCEPTION 'Unknown cohort' USING ERRCODE = '22023';
    END IF;
    -- One refresh at a time per (cohort, period); key namespace 54060.
    PERFORM pg_advisory_xact_lock(54060, hashtext(p_cohort_id::text || ':' || v_p.period_key));

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
        SELECT m.learner_id,
               leaderboard.period_gold(m.learner_id, v_p.starts_on, v_p.ends_on) AS gold,
               -- Non-identifying and different for every period and cohort, so
               -- nobody is "always first" among equals.
               sha256(convert_to(p_cohort_id::text || ':' || v_p.period_key || ':' || m.learner_id::text, 'UTF8')) AS tie_key
        FROM leaderboard.memberships m
        WHERE m.cohort_id = p_cohort_id AND m.opted_out_at IS NULL
          AND leaderboard.is_rankable(m.learner_id)
    )
    INSERT INTO leaderboard.snapshots (period_key, cohort_id, learner_id, gold, rank, tie_order, computed_at)
    SELECT v_p.period_key, p_cohort_id, sc.learner_id, sc.gold,
           (rank() OVER (ORDER BY sc.gold DESC))::integer,
           (row_number() OVER (ORDER BY sc.gold DESC, sc.tie_key))::integer,
           v_now
    FROM scored sc;
    GET DIAGNOSTICS v_members = ROW_COUNT;

    UPDATE leaderboard.snapshot_runs r
       SET member_count = v_members,
           frozen_at = CASE WHEN v_p.is_closed THEN v_now END
     WHERE r.period_key = v_p.period_key AND r.cohort_id = p_cohort_id;

    RETURN jsonb_build_object('period', v_p.period_key, 'cohort_id', p_cohort_id,
                              'members', v_members, 'computed_at', v_now,
                              'frozen', v_p.is_closed, 'recomputed', true);
END;
$$;

-- ============================================================================
-- Learner read: the caller's own standing, and nobody else's
-- ============================================================================
-- The actor comes from the verified transaction setting, never a parameter.
-- `gold` is the caller's own live sum for the period. `cohort` is non-NULL
-- only for an opted-in, rankable caller; rank and size come from the latest
-- snapshot re-ranked over the rows that are still visible.
CREATE FUNCTION leaderboard.my_standing(p_period text)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_p record;
    v_m leaderboard.memberships%ROWTYPE;
    v_cohort jsonb;
    v_gold bigint;
    v_rank integer;
    v_size integer;
    v_computed timestamptz;
    v_frozen boolean;
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'Not authenticated' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_p FROM leaderboard.resolve_period(p_period);

    SELECT * INTO v_m FROM leaderboard.memberships m
     WHERE m.learner_id = v_actor AND m.opted_out_at IS NULL;
    IF FOUND AND leaderboard.is_rankable(v_actor) THEN
        SELECT r.computed_at, r.frozen_at IS NOT NULL INTO v_computed, v_frozen
          FROM leaderboard.snapshot_runs r
         WHERE r.period_key = v_p.period_key AND r.cohort_id = v_m.cohort_id;
        SELECT v.gold INTO v_gold FROM leaderboard.visible_rows(v_m.cohort_id, v_p.period_key) v
         WHERE v.learner_id = v_actor;
        IF v_gold IS NOT NULL THEN
            SELECT 1 + count(*) FILTER (WHERE v.gold > v_gold), count(*)
              INTO v_rank, v_size
              FROM leaderboard.visible_rows(v_m.cohort_id, v_p.period_key) v;
        END IF;
        v_cohort := jsonb_build_object(
            'cohort_id', v_m.cohort_id,
            'pseudonym', leaderboard.display_pseudonym(v_m.pseudonym_id, v_m.pseudonym_suffix),
            'rank', v_rank,
            'size', v_size,
            'snapshot_gold', v_gold,
            'computed_at', v_computed,
            'frozen', COALESCE(v_frozen, false));
    END IF;

    RETURN jsonb_build_object(
        'period', v_p.period_key,
        'kind', v_p.kind,
        'starts_on', v_p.starts_on,
        'ends_on', v_p.ends_on,
        'closed', v_p.is_closed,
        'gold', leaderboard.period_gold(v_actor, v_p.starts_on, v_p.ends_on),
        'cohort', v_cohort);
END;
$$;

-- ============================================================================
-- Erasure hook (called by the account orchestrator; EXECUTE granted to nobody)
-- ============================================================================
CREATE FUNCTION leaderboard.erase_learner(p_user_id uuid)
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
-- Privileges: edu_api may call exactly ONE function and touch no table.
-- ============================================================================
REVOKE ALL ON ALL TABLES IN SCHEMA leaderboard FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA leaderboard FROM PUBLIC, anon, authenticated;

GRANT USAGE ON SCHEMA leaderboard TO edu_api;
GRANT EXECUTE ON FUNCTION leaderboard.my_standing(text) TO edu_api;
