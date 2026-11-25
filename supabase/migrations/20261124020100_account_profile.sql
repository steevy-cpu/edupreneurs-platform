-- Mon Edupreneur 2.0 — schema `account`: the learner edits their own profile
--
-- Overnight mission 2026-11-24, lane IDENTITY (slice 1).
--
-- RULES THIS FILE FOLLOWS
--   * Nothing is created, altered, granted or dropped in schema `app`. The
--     student API role still has NO UPDATE privilege on app.learner_profiles;
--     a profile is edited only through account.update_own_profile(), a
--     SECURITY DEFINER function that can touch nothing but the caller's row.
--   * The actor is ALWAYS app.current_actor_id(). No function here takes a
--     user-id parameter.
--   * Every function pins search_path = pg_catalog, pg_temp and uses schema-qualified names.
--   * EXECUTE is revoked from PUBLIC / anon / authenticated and then granted
--     to exactly the role that needs it.
--   * No consent, age or retention rule exists here (PO-04 is not decided).
--
-- The schema is PRIVATE: it is not listed in the Supabase Data API schemas and
-- the Data API roles hold nothing in it (supabase/tests/120_account_structure.sql).

CREATE SCHEMA account;
REVOKE ALL ON SCHEMA account FROM PUBLIC;
REVOKE ALL ON SCHEMA account FROM anon, authenticated;
COMMENT ON SCHEMA account IS
    'Private. Learner self-service: profile edit, onboarding state, account lifecycle. Reached only through FastAPI.';

GRANT USAGE ON SCHEMA account TO edu_api;

-- ============================================================================
-- Audit seam  >>> B1 SEAM (identity lane) — the ONE place to wire the audit <<<
-- ============================================================================
-- Every audited action in this schema calls account.audit_seam(). Until the
-- staff lane's ops.audit_write() exists in the database this function records
-- NOTHING and returns NULL. When B1 is merged, a follow-up migration replaces
-- this body (CREATE OR REPLACE, same signature) with:
--
--     RETURN ops.audit_write(p_action, p_target_kind, p_target_id, p_outcome, p_details);
--
-- No call site changes. Callers must never put a display name, an answer or
-- any other free text into p_details: field NAMES and counts only.
CREATE FUNCTION account.audit_seam(
    p_action text,
    p_target_kind text,
    p_target_id uuid,
    p_outcome text,
    p_details jsonb DEFAULT '{}'::jsonb
)
RETURNS uuid
LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    -- NOT WIRED YET (ops.audit_write arrives with the staff lane, B1).
    RETURN NULL;
END;
$$;

-- ============================================================================
-- Slice 1 — profile edit
-- ============================================================================
-- p_patch is a JSON object with any of:
--     "grade_code"        string   must name an existing, ACTIVE grade
--     "preferred_locale"  "fr" | "ht"
--     "display_name"      string (already trimmed, NFC, 1..80 characters, no
--                         control characters or line breaks) or null to clear
-- A key that is absent is left unchanged. Unknown keys are an error.
--
-- Returns  {"status":"ok","changed":[...field names...]}
--      or  {"status":"rejected","code":"grade_not_available" | "invalid_display_name"}
-- Malformed arguments raise 22023; a missing actor or profile raises 42501.
--
-- The display name is a PRIVATE study setting shown only to its owner. It is
-- never a public name (Platform-00 doc 04 §4.1) and its value is never audited.
CREATE FUNCTION account.update_own_profile(p_patch jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := app.current_actor_id();
    v_profile record;
    v_grade_id uuid;
    v_locale text;
    v_name text;
    v_changed text[] := ARRAY[]::text[];
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    IF p_patch IS NULL OR jsonb_typeof(p_patch) <> 'object' OR p_patch = '{}'::jsonb
       OR octet_length(p_patch::text) > 2048 THEN
        RAISE EXCEPTION 'Malformed profile patch' USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_object_keys(p_patch) AS k
        WHERE k NOT IN ('grade_code', 'preferred_locale', 'display_name')
    ) THEN
        RAISE EXCEPTION 'Unknown profile field' USING ERRCODE = '22023';
    END IF;

    -- Lock the caller's own row. NO KEY UPDATE does not block the sync
    -- function, whose inserts only need a KEY SHARE lock on the profile.
    SELECT p.grade_id, p.preferred_locale, p.display_name INTO v_profile
    FROM app.learner_profiles p
    WHERE p.user_id = v_actor
    FOR NO KEY UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Learner profile required' USING ERRCODE = '42501';
    END IF;
    v_grade_id := v_profile.grade_id;
    v_locale := v_profile.preferred_locale;
    v_name := v_profile.display_name;

    IF p_patch ? 'grade_code' THEN
        IF jsonb_typeof(p_patch -> 'grade_code') <> 'string' THEN
            RAISE EXCEPTION 'grade_code must be a string' USING ERRCODE = '22023';
        END IF;
        SELECT g.id INTO v_grade_id
        FROM app.grades g
        WHERE g.code = p_patch ->> 'grade_code' AND g.is_active;
        IF NOT FOUND THEN
            -- Unknown and inactive give the same answer on purpose.
            RETURN jsonb_build_object('status', 'rejected', 'code', 'grade_not_available');
        END IF;
        IF v_grade_id IS DISTINCT FROM v_profile.grade_id THEN
            v_changed := array_append(v_changed, 'grade_code'::text);
        END IF;
    END IF;

    IF p_patch ? 'preferred_locale' THEN
        IF jsonb_typeof(p_patch -> 'preferred_locale') <> 'string'
           OR p_patch ->> 'preferred_locale' NOT IN ('fr', 'ht') THEN
            RAISE EXCEPTION 'preferred_locale must be fr or ht' USING ERRCODE = '22023';
        END IF;
        v_locale := p_patch ->> 'preferred_locale';
        IF v_locale IS DISTINCT FROM v_profile.preferred_locale THEN
            v_changed := array_append(v_changed, 'preferred_locale'::text);
        END IF;
    END IF;

    IF p_patch ? 'display_name' THEN
        IF jsonb_typeof(p_patch -> 'display_name') NOT IN ('string', 'null') THEN
            RAISE EXCEPTION 'display_name must be a string or null' USING ERRCODE = '22023';
        END IF;
        v_name := p_patch ->> 'display_name';
        -- Defence in depth: the API has already trimmed, normalised and
        -- validated the value; a non-canonical one is refused, not repaired.
        IF v_name IS NOT NULL AND (
               char_length(v_name) NOT BETWEEN 1 AND 80
            OR v_name IS NOT NFC NORMALIZED
            OR v_name ~ U&'[\0001-\001F\007F-\009F\2028\2029]'
            OR v_name ~ '^\s' OR v_name ~ '\s$'
        ) THEN
            RETURN jsonb_build_object('status', 'rejected', 'code', 'invalid_display_name');
        END IF;
        IF v_name IS DISTINCT FROM v_profile.display_name THEN
            v_changed := array_append(v_changed, 'display_name'::text);
        END IF;
    END IF;

    IF cardinality(v_changed) = 0 THEN
        -- A repeated request changes nothing: no write, no audit record.
        RETURN jsonb_build_object('status', 'ok', 'changed', '[]'::jsonb);
    END IF;

    UPDATE app.learner_profiles
       SET grade_id = v_grade_id,
           preferred_locale = v_locale,
           display_name = v_name,
           updated_at = now()
     WHERE user_id = v_actor;

    -- Who (the actor, taken by the audit writer) and WHICH fields. Never values.
    PERFORM account.audit_seam(
        'account.profile_updated', 'learner_profile', v_actor, 'allowed',
        jsonb_build_object('fields', to_jsonb(v_changed)));

    RETURN jsonb_build_object('status', 'ok', 'changed', to_jsonb(v_changed));
END;
$$;

-- ============================================================================
-- Privileges: PostgreSQL lets PUBLIC execute new functions by default, and
-- that default cannot be changed per schema. Revoke, then grant by name.
-- ============================================================================
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA account FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION account.update_own_profile(jsonb) TO edu_api;
-- audit_seam is internal: only the definer functions of this schema (running
-- as their owner) call it.
