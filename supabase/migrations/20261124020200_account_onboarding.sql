-- Mon Edupreneur 2.0 — schema `account`: onboarding state (server side of F15)
--
-- Overnight mission 2026-11-24, lane IDENTITY (slice 2).
--
-- Same rules as 20261124020100_account_profile.sql: nothing in schema `app`
-- is created or changed; the actor is always app.current_actor_id(); every
-- function pins an empty search_path; EXECUTE is granted by name.
--
-- NO CONSENT IS COLLECTED OR INFERRED (PO-04 is not decided). Onboarding
-- stores only "how far through the introduction is this learner". None of its
-- values is, or may be read as, a consent answer; a feature that needs consent
-- must treat consent as unknown = not granted, whatever this table says.

-- ============================================================================
-- Onboarding state
-- ============================================================================
-- One row per learner, created on the first write. The state only ever moves
-- FORWARD:  new -> profile_selected -> downloads_informed -> ready.
-- Nothing in onboarding deletes, resets or even reads a learner's answers.
--
-- This is NOT a consent record. `tour_dismissed` means "do not show the
-- product tour again", nothing else.
CREATE TABLE account.onboarding_state (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE RESTRICT,
    state text NOT NULL DEFAULT 'new'
        CHECK (state IN ('new', 'profile_selected', 'downloads_informed', 'ready')),
    -- Highest version of the onboarding flow any of the learner's devices has reported.
    onboarding_version integer NOT NULL CHECK (onboarding_version BETWEEN 1 AND 10000),
    -- Highest version of the product tour the learner has seen (0 = none).
    tour_version_seen integer NOT NULL DEFAULT 0 CHECK (tour_version_seen BETWEEN 0 AND 10000),
    tour_dismissed boolean NOT NULL DEFAULT false,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (completed_at IS NULL OR state = 'ready')
);
ALTER TABLE account.onboarding_state ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON account.onboarding_state FROM PUBLIC, anon, authenticated;
GRANT SELECT ON account.onboarding_state TO edu_api;
CREATE POLICY onboarding_select_own ON account.onboarding_state
    FOR SELECT TO edu_api USING (user_id = (SELECT app.current_actor_id()));

CREATE FUNCTION account.onboarding_rank(p_state text)
RETURNS integer
LANGUAGE sql IMMUTABLE
SET search_path = ''
AS $$
    SELECT CASE p_state
        WHEN 'new' THEN 0
        WHEN 'profile_selected' THEN 1
        WHEN 'downloads_informed' THEN 2
        WHEN 'ready' THEN 3
    END
$$;

-- What the server already knows about a learner, whatever the onboarding row
-- says (or if there is none). This is the "returning learner" rule:
--   * a learner whose work the server has accepted is `ready` — they were
--     using the app before this flow existed, or finished it on another device;
--   * a learner who has a grade has at least `profile_selected`.
-- Derived from usage facts only. It infers no consent and no age.
CREATE FUNCTION account.onboarding_floor(p_user_id uuid)
RETURNS text
LANGUAGE sql STABLE
SET search_path = ''
AS $$
    SELECT CASE
        WHEN EXISTS (SELECT 1 FROM app.account_sync_state s
                     WHERE s.learner_id = p_user_id AND s.current_version > 0) THEN 'ready'
        WHEN EXISTS (SELECT 1 FROM app.learner_profiles p
                     WHERE p.user_id = p_user_id AND p.grade_id IS NOT NULL) THEN 'profile_selected'
        ELSE 'new'
    END
$$;

-- The caller's effective onboarding state (read-only; creates no row).
CREATE FUNCTION account.get_own_onboarding()
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_row account.onboarding_state%ROWTYPE;
    v_floor text;
    v_state text;
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    v_floor := account.onboarding_floor(v_actor);
    SELECT * INTO v_row FROM account.onboarding_state o WHERE o.user_id = v_actor;
    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'state', v_floor, 'onboarding_version', 0, 'tour_version_seen', 0,
            'tour_dismissed', false, 'completed_at', NULL, 'updated_at', NULL);
    END IF;
    v_state := CASE WHEN account.onboarding_rank(v_floor) > account.onboarding_rank(v_row.state)
                    THEN v_floor ELSE v_row.state END;
    RETURN jsonb_build_object(
        'state', v_state,
        'onboarding_version', v_row.onboarding_version,
        'tour_version_seen', v_row.tour_version_seen,
        'tour_dismissed', v_row.tour_dismissed,
        'completed_at', v_row.completed_at,
        'updated_at', v_row.updated_at);
END;
$$;

-- Report progress through onboarding. Every argument MERGES MONOTONICALLY with
-- what is stored, so the call is idempotent and safe to replay in any order
-- from any number of devices:
--     state               never moves backwards (NULL = "no state to report")
--     onboarding_version  greatest of stored and reported
--     tour_version_seen   greatest of stored and reported (NULL = unchanged)
--     tour_dismissed      once true, stays true (NULL = unchanged)
-- A stale or repeated request is ACCEPTED and changes nothing.
--
-- Version rule: a higher onboarding_version never moves the state back. A
-- learner who is `ready` stays `ready` after an app upgrade; a newer flow may
-- only add optional, non-blocking steps (shown through the tour fields).
CREATE FUNCTION account.advance_onboarding(
    p_state text,
    p_onboarding_version integer,
    p_tour_version_seen integer DEFAULT NULL,
    p_tour_dismissed boolean DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
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
    IF NOT EXISTS (SELECT 1 FROM app.learner_profiles p WHERE p.user_id = v_actor) THEN
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

-- ============================================================================
-- Privileges
-- ============================================================================
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA account FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION account.get_own_onboarding() TO edu_api;
GRANT EXECUTE ON FUNCTION account.advance_onboarding(text, integer, integer, boolean) TO edu_api;
-- onboarding_rank and onboarding_floor are internal: only the definer functions
-- above (running as their owner) call them.
