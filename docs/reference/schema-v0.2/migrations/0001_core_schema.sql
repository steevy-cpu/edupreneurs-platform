-- Mon Edupreneur 2.0 / PostgreSQL / Supabase-owned project
-- v0.2 / DRAFT FOR REVIEW / 2026-11-21
-- Creates exactly 22 private application tables. No production deployment authorized.
-- Designed for Supabase Auth's auth.users; run on an Edupreneur-owned STAGING project.
-- IMPORTANT: app is NOT listed in Supabase Data API "Exposed schemas".
-- No raw student data, credentials, model prompts, or billing secrets should be seeded.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
REVOKE ALL ON SCHEMA app FROM anon, authenticated;

-- Actor identity is set ONLY by a trusted API after JWT verification and inside a DB transaction.
-- If absent, return NULL and let RLS deny private access.
CREATE OR REPLACE FUNCTION app.current_actor_id()
RETURNS uuid LANGUAGE sql STABLE SET search_path = ''
AS $$ SELECT NULLIF(current_setting('edu.actor_id', true), '')::uuid $$;

-- ========================================================================
-- IDENTITY / ACCESS (2)
-- ========================================================================
CREATE TABLE app.learner_profiles (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE RESTRICT,
    grade_id uuid, -- FK added below when grades is created
    preferred_locale text NOT NULL DEFAULT 'fr' CHECK (preferred_locale IN ('fr', 'ht')),
    display_name text CHECK (display_name IS NULL OR char_length(display_name) BETWEEN 1 AND 80),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.staff_roles (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    role text NOT NULL CHECK (role IN ('editor','reviewer','publisher','admin')),
    granted_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    is_active boolean NOT NULL DEFAULT true,
    granted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role)
);

-- ========================================================================
-- CURRICULUM (7)
-- ========================================================================
CREATE TABLE app.grades (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE CHECK (code ~ '^[A-Z0-9]{2,8}$'),
    sort_order smallint NOT NULL UNIQUE CHECK (sort_order > 0),
    labels jsonb NOT NULL CHECK (jsonb_typeof(labels) = 'object'),
    is_active boolean NOT NULL DEFAULT true
);
ALTER TABLE app.learner_profiles
    ADD CONSTRAINT learner_profiles_grade_fkey FOREIGN KEY (grade_id)
    REFERENCES app.grades(id) ON DELETE RESTRICT;

CREATE TABLE app.subjects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]{2,80}$'),
    labels jsonb NOT NULL CHECK (jsonb_typeof(labels) = 'object'),
    is_active boolean NOT NULL DEFAULT true
);

CREATE TABLE app.courses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    grade_id uuid NOT NULL REFERENCES app.grades(id) ON DELETE RESTRICT,
    subject_id uuid NOT NULL REFERENCES app.subjects(id) ON DELETE RESTRICT,
    slug text NOT NULL CHECK (slug ~ '^[a-z0-9-]{2,80}$'),
    titles jsonb NOT NULL CHECK (jsonb_typeof(titles) = 'object'),
    visibility text NOT NULL DEFAULT 'draft' CHECK (visibility IN ('draft','published','archived')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (grade_id, subject_id, slug)
);

CREATE TABLE app.units (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id uuid NOT NULL REFERENCES app.courses(id) ON DELETE RESTRICT,
    slug text NOT NULL CHECK (slug ~ '^[a-z0-9-]{2,80}$'),
    position integer NOT NULL CHECK (position > 0),
    titles jsonb NOT NULL CHECK (jsonb_typeof(titles) = 'object'),
    UNIQUE (course_id, slug),
    UNIQUE (course_id, position)
);

CREATE TABLE app.lessons (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
    slug text NOT NULL CHECK (slug ~ '^[a-z0-9-]{2,80}$'),
    position integer NOT NULL CHECK (position > 0),
    is_active boolean NOT NULL DEFAULT true,
    UNIQUE (unit_id, slug),
    UNIQUE (unit_id, position)
);

CREATE TABLE app.lesson_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lesson_id uuid NOT NULL REFERENCES app.lessons(id) ON DELETE RESTRICT,
    revision integer NOT NULL CHECK (revision > 0),
    locale text NOT NULL CHECK (locale IN ('fr','ht')),
    title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    blocks jsonb NOT NULL CHECK (jsonb_typeof(blocks) = 'array'),
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','in_review','approved','rejected')),
    created_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    approved_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (lesson_id, locale, revision),
    UNIQUE (id, lesson_id),
    CHECK (
        (status = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
        OR (status <> 'approved' AND approved_by IS NULL AND approved_at IS NULL)
    )
);

-- Every question revision belongs to the exact lesson/locale/version that contains it.
-- A stable question_key permits comparison of the same concept across revisions.
-- answer_key is acceptable for offline PRACTICE; high-stakes exams are separate.
CREATE TABLE app.question_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lesson_revision_id uuid NOT NULL REFERENCES app.lesson_revisions(id) ON DELETE RESTRICT,
    question_key text NOT NULL CHECK (question_key ~ '^[a-z0-9_-]{1,80}$'),
    position integer NOT NULL CHECK (position > 0),
    kind text NOT NULL CHECK (kind IN ('mcq','numeric','short_text','matching')),
    prompt jsonb NOT NULL CHECK (jsonb_typeof(prompt) = 'object'),
    response_spec jsonb NOT NULL CHECK (jsonb_typeof(response_spec) = 'object'),
    answer_key jsonb NOT NULL CHECK (jsonb_typeof(answer_key) = 'object'),
    explanation jsonb NOT NULL CHECK (jsonb_typeof(explanation) = 'object'),
    UNIQUE (lesson_revision_id, question_key),
    UNIQUE (lesson_revision_id, position),
    UNIQUE (id, lesson_revision_id)
);

-- ========================================================================
-- PUBLICATION / PROVENANCE (6)
-- ========================================================================
CREATE TABLE app.content_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_title text NOT NULL CHECK (char_length(source_title) BETWEEN 1 AND 240),
    source_uri text,
    rights_status text NOT NULL DEFAULT 'unverified'
        CHECK (rights_status IN ('unverified','cleared','restricted','blocked')),
    rights_notes text,
    verified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.lesson_revision_sources (
    lesson_revision_id uuid NOT NULL REFERENCES app.lesson_revisions(id) ON DELETE RESTRICT,
    source_id uuid NOT NULL REFERENCES app.content_sources(id) ON DELETE RESTRICT,
    PRIMARY KEY (lesson_revision_id, source_id)
);

CREATE TABLE app.editorial_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lesson_revision_id uuid NOT NULL REFERENCES app.lesson_revisions(id) ON DELETE RESTRICT,
    reviewer_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    verdict text NOT NULL CHECK (verdict IN ('approved','rejected','changes_requested')),
    notes text,
    reviewed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.pack_releases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pack_key text NOT NULL CHECK (pack_key ~ '^[a-z0-9_-]{3,100}$'),
    revision integer NOT NULL CHECK (revision > 0),
    locale text NOT NULL CHECK (locale IN ('fr','ht')),
    status text NOT NULL DEFAULT 'building'
        CHECK (status IN ('building','ready','active','retired','revoked')),
    manifest_object_key text,
    manifest_sha256 bytea,
    compressed_bytes bigint CHECK (compressed_bytes IS NULL OR compressed_bytes >= 0),
    created_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    released_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (pack_key, locale, revision),
    UNIQUE (id, pack_key, locale),
    CHECK (manifest_sha256 IS NULL OR octet_length(manifest_sha256) = 32),
    CHECK (status = 'building' OR (
        manifest_object_key IS NOT NULL AND
        manifest_sha256 IS NOT NULL AND
        compressed_bytes IS NOT NULL
    )),
    CHECK (status NOT IN ('active', 'retired') OR released_at IS NOT NULL)
);

CREATE TABLE app.pack_items (
    pack_release_id uuid NOT NULL REFERENCES app.pack_releases(id) ON DELETE RESTRICT,
    lesson_revision_id uuid NOT NULL REFERENCES app.lesson_revisions(id) ON DELETE RESTRICT,
    position integer NOT NULL CHECK (position > 0),
    PRIMARY KEY (pack_release_id, lesson_revision_id),
    UNIQUE (pack_release_id, position)
);

-- The only active pack pointer for a given pack_key / locale.
-- Switching this pointer in one DB transaction makes publication atomic for new readers.
CREATE TABLE app.pack_current (
    pack_key text NOT NULL,
    locale text NOT NULL,
    release_id uuid NOT NULL UNIQUE,
    switched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pack_key, locale),
    FOREIGN KEY (release_id, pack_key, locale)
        REFERENCES app.pack_releases(id, pack_key, locale) ON DELETE RESTRICT
);

-- ========================================================================
-- LEARNING + OFFLINE SYNC (5)
-- ========================================================================
CREATE TABLE app.lesson_progress (
    learner_id uuid NOT NULL REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    lesson_id uuid NOT NULL REFERENCES app.lessons(id) ON DELETE RESTRICT,
    last_revision_id uuid,
    completed_at timestamptz,
    last_block_key text,
    last_opened_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    last_change_version bigint CHECK (last_change_version IS NULL OR last_change_version > 0),
    PRIMARY KEY (learner_id, lesson_id),
    FOREIGN KEY (last_revision_id, lesson_id)
        REFERENCES app.lesson_revisions(id, lesson_id) ON DELETE RESTRICT
);

CREATE TABLE app.practice_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    learner_id uuid NOT NULL REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    op_id uuid NOT NULL,
    lesson_revision_id uuid NOT NULL,
    question_revision_id uuid NOT NULL,
    response jsonb NOT NULL CHECK (jsonb_typeof(response) = 'object'),
    score numeric(5,4) CHECK (score IS NULL OR (score >= 0 AND score <= 1)),
    scoring_version text,
    client_recorded_at timestamptz,
    accepted_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (learner_id, op_id),
    FOREIGN KEY (question_revision_id, lesson_revision_id)
        REFERENCES app.question_revisions(id, lesson_revision_id) ON DELETE RESTRICT
);

CREATE TABLE app.account_sync_state (
    learner_id uuid PRIMARY KEY REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    current_version bigint NOT NULL DEFAULT 0 CHECK (current_version >= 0)
);

CREATE TABLE app.sync_receipts (
    learner_id uuid NOT NULL REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    op_id uuid NOT NULL,
    payload_sha256 bytea NOT NULL CHECK (octet_length(payload_sha256) = 32),
    result_code text NOT NULL CHECK (result_code IN ('accepted','rejected')),
    result jsonb NOT NULL CHECK (jsonb_typeof(result) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (learner_id, op_id)
);

CREATE TABLE app.account_change_feed (
    learner_id uuid NOT NULL REFERENCES app.account_sync_state(learner_id) ON DELETE RESTRICT,
    version bigint NOT NULL CHECK (version > 0),
    entity_type text NOT NULL CHECK (entity_type IN ('lesson_progress','practice_attempt')),
    entity_id uuid NOT NULL,
    change_data jsonb NOT NULL CHECK (jsonb_typeof(change_data) = 'object'),
    is_tombstone boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (learner_id, version)
);

-- Called from the SAME transaction as canonical operation, receipt and feed insert.
-- Per-learner upsert locks the counter row, creating commit-consistent order per learner.
CREATE OR REPLACE FUNCTION app.next_change_version(p_learner_id uuid)
RETURNS bigint LANGUAGE plpgsql VOLATILE SET search_path = ''
AS $$
DECLARE v_next bigint;
BEGIN
    IF p_learner_id IS DISTINCT FROM app.current_actor_id() THEN
        RAISE EXCEPTION 'Actor mismatch' USING ERRCODE = '42501';
    END IF;
    INSERT INTO app.account_sync_state (learner_id, current_version)
      VALUES (p_learner_id, 1)
      ON CONFLICT (learner_id)
      DO UPDATE SET current_version = app.account_sync_state.current_version + 1
      RETURNING current_version INTO v_next;
    RETURN v_next;
END;
$$;

-- ========================================================================
-- OPERATIONS (2)
-- ========================================================================
CREATE TABLE app.background_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL CHECK (kind ~ '^[a-z0-9_]{3,60}$'),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','leased','completed','dead','cancelled')),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
    idempotency_key text UNIQUE,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 20),
    run_after timestamptz NOT NULL DEFAULT now(),
    lease_until timestamptz,
    leased_by text,
    error_class text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status <> 'leased' OR (lease_until IS NOT NULL AND leased_by IS NOT NULL))
);

CREATE TABLE app.audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid, -- deliberately no FK: audit retention needn't block account deletion
    actor_kind text NOT NULL CHECK (actor_kind IN ('user','staff','worker','system')),
    action text NOT NULL CHECK (char_length(action) BETWEEN 3 AND 100),
    target_kind text,
    target_id uuid,
    outcome text NOT NULL CHECK (outcome IN ('allowed','denied','error')),
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ========================================================================
-- CRITICAL INDEXES (in addition to PK/UNIQUE indexes)
-- ========================================================================
CREATE INDEX idx_profiles_grade ON app.learner_profiles(grade_id);
CREATE INDEX idx_courses_subject ON app.courses(subject_id, grade_id);
CREATE INDEX idx_lesson_revs_published ON app.lesson_revisions(lesson_id, locale, revision DESC)
    WHERE status = 'approved';
CREATE INDEX idx_sources_source ON app.lesson_revision_sources(source_id);
CREATE INDEX idx_reviews_revision ON app.editorial_reviews(lesson_revision_id, reviewed_at DESC);
CREATE INDEX idx_pack_items_revision ON app.pack_items(lesson_revision_id);
CREATE INDEX idx_attempts_learner_time ON app.practice_attempts(learner_id, accepted_at DESC);
CREATE INDEX idx_attempts_question ON app.practice_attempts(question_revision_id);
CREATE INDEX idx_receipts_created ON app.sync_receipts(created_at);
CREATE INDEX idx_feed_created ON app.account_change_feed(learner_id, created_at);
CREATE INDEX idx_jobs_ready ON app.background_jobs(status, run_after)
    WHERE status IN ('queued','leased');
CREATE INDEX idx_audit_target ON app.audit_events(target_kind, target_id, created_at DESC);

-- ========================================================================
-- IMMUTABILITY GUARDS / PUBLISH VALIDATION
-- ========================================================================
CREATE OR REPLACE FUNCTION app.protect_approved_lesson_revision()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_has_approved_review boolean;
DECLARE v_has_cleared_source boolean;
DECLARE v_has_uncleared_source boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'approved' OR EXISTS (
            SELECT 1 FROM app.pack_items WHERE lesson_revision_id = OLD.id
        ) THEN RAISE EXCEPTION 'Approved/packed lesson revisions are immutable'; END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'approved' OR EXISTS (
        SELECT 1 FROM app.pack_items WHERE lesson_revision_id = OLD.id
    ) THEN RAISE EXCEPTION 'Approved/packed lesson revisions are immutable'; END IF;

    -- A submitted review freezes the exact content/question snapshot.
    -- If edits are necessary, create a new revision and obtain a fresh review.
    IF EXISTS (SELECT 1 FROM app.editorial_reviews WHERE lesson_revision_id = OLD.id) AND (
        NEW.blocks IS DISTINCT FROM OLD.blocks OR NEW.title IS DISTINCT FROM OLD.title OR
        NEW.locale IS DISTINCT FROM OLD.locale OR NEW.revision IS DISTINCT FROM OLD.revision OR
        NEW.lesson_id IS DISTINCT FROM OLD.lesson_id
    ) THEN RAISE EXCEPTION 'Reviewed content cannot be modified; create a new revision'; END IF;

    IF NEW.status = 'approved' THEN
        SELECT COALESCE((
            SELECT (r.verdict = 'approved' AND sr.is_active IS TRUE
                    AND sr.role IN ('reviewer','admin')
                    AND r.reviewer_id = NEW.approved_by
                    AND (OLD.created_by IS NULL OR r.reviewer_id <> OLD.created_by))
            FROM app.editorial_reviews r
            LEFT JOIN app.staff_roles sr ON sr.user_id = r.reviewer_id
                    AND sr.role IN ('reviewer','admin')
            WHERE r.lesson_revision_id = OLD.id
            ORDER BY r.reviewed_at DESC, r.id DESC LIMIT 1
        ), false) INTO v_has_approved_review;
        SELECT EXISTS (
            SELECT 1 FROM app.lesson_revision_sources lrs
            JOIN app.content_sources s ON s.id = lrs.source_id
            WHERE lrs.lesson_revision_id = OLD.id AND s.rights_status = 'cleared'
        ) INTO v_has_cleared_source;
        SELECT EXISTS (
            SELECT 1 FROM app.lesson_revision_sources lrs
            JOIN app.content_sources s ON s.id = lrs.source_id
            WHERE lrs.lesson_revision_id = OLD.id AND s.rights_status <> 'cleared'
        ) INTO v_has_uncleared_source;
        IF NOT v_has_approved_review OR NOT v_has_cleared_source OR v_has_uncleared_source THEN
            RAISE EXCEPTION 'Authorized independent review and all sources cleared required';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_approved_lesson_revision
BEFORE UPDATE OR DELETE ON app.lesson_revisions
FOR EACH ROW EXECUTE FUNCTION app.protect_approved_lesson_revision();

CREATE OR REPLACE FUNCTION app.protect_question_revision()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_parent_id uuid;
BEGIN
    v_parent_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.lesson_revision_id
                         ELSE NEW.lesson_revision_id END;
    IF EXISTS (SELECT 1 FROM app.lesson_revisions
               WHERE id = v_parent_id AND status = 'approved') OR
       EXISTS (SELECT 1 FROM app.pack_items WHERE lesson_revision_id = v_parent_id) OR
       EXISTS (SELECT 1 FROM app.editorial_reviews WHERE lesson_revision_id = v_parent_id)
    THEN RAISE EXCEPTION 'Questions in reviewed/approved/packed lessons are immutable'; END IF;
    IF TG_OP = 'UPDATE' AND NEW.lesson_revision_id <> OLD.lesson_revision_id THEN
        RAISE EXCEPTION 'Question cannot move to another lesson revision';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_question_revision
BEFORE INSERT OR UPDATE OR DELETE ON app.question_revisions
FOR EACH ROW EXECUTE FUNCTION app.protect_question_revision();

-- Freeze source attribution once a human has reviewed a revision.
CREATE OR REPLACE FUNCTION app.protect_reviewed_source_links()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_old uuid; v_new uuid;
BEGIN
    IF TG_OP IN ('UPDATE','DELETE') THEN v_old := OLD.lesson_revision_id; END IF;
    IF TG_OP IN ('UPDATE','INSERT') THEN v_new := NEW.lesson_revision_id; END IF;
    IF EXISTS (SELECT 1 FROM app.lesson_revisions lr
               WHERE lr.id IN (v_old, v_new) AND lr.status = 'approved') OR
       EXISTS (SELECT 1 FROM app.editorial_reviews r
               WHERE r.lesson_revision_id IN (v_old, v_new)) OR
       EXISTS (SELECT 1 FROM app.pack_items pi
               WHERE pi.lesson_revision_id IN (v_old, v_new)) THEN
        RAISE EXCEPTION 'Reviewed source references cannot be modified';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_reviewed_source_links
BEFORE INSERT OR UPDATE OR DELETE ON app.lesson_revision_sources
FOR EACH ROW EXECUTE FUNCTION app.protect_reviewed_source_links();

-- Source licensing may be revoked later, but historical source identity cannot change.
CREATE OR REPLACE FUNCTION app.protect_used_source_details()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF TG_OP = 'DELETE' AND EXISTS (
       SELECT 1 FROM app.lesson_revision_sources WHERE source_id = OLD.id
    ) THEN RAISE EXCEPTION 'Referenced sources cannot be deleted'; END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.source_title IS DISTINCT FROM OLD.source_title OR
        NEW.source_uri IS DISTINCT FROM OLD.source_uri
    ) AND EXISTS (
        SELECT 1 FROM app.lesson_revision_sources lrs
        JOIN app.lesson_revisions lr ON lr.id = lrs.lesson_revision_id
        WHERE lrs.source_id = OLD.id AND (
            lr.status = 'approved' OR
            EXISTS (SELECT 1 FROM app.editorial_reviews r WHERE r.lesson_revision_id = lr.id)
        )
    ) THEN RAISE EXCEPTION 'Source identity used in reviewed material is immutable'; END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_used_source_details
BEFORE UPDATE OR DELETE ON app.content_sources
FOR EACH ROW EXECUTE FUNCTION app.protect_used_source_details();

CREATE OR REPLACE FUNCTION app.validate_editorial_review()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_created_by uuid; v_status text;
BEGIN
    SELECT created_by, status INTO v_created_by, v_status
    FROM app.lesson_revisions WHERE id = NEW.lesson_revision_id FOR UPDATE;
    IF v_status = 'approved' OR EXISTS (
      SELECT 1 FROM app.pack_items WHERE lesson_revision_id = NEW.lesson_revision_id
    ) THEN RAISE EXCEPTION 'Cannot review a finalized lesson revision'; END IF;
    IF v_created_by IS NOT NULL AND v_created_by = NEW.reviewer_id THEN
        RAISE EXCEPTION 'Author cannot review own lesson';
    END IF;
    IF NOT EXISTS (
       SELECT 1 FROM app.staff_roles sr
       WHERE sr.user_id = NEW.reviewer_id AND sr.is_active
         AND sr.role IN ('reviewer','admin')
    ) THEN RAISE EXCEPTION 'Reviewer role required'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER validate_editorial_review
BEFORE INSERT ON app.editorial_reviews
FOR EACH ROW EXECUTE FUNCTION app.validate_editorial_review();

CREATE OR REPLACE FUNCTION app.validate_pack_item()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_status text; v_locale text; v_revision_status text; v_revision_locale text;
BEGIN
    SELECT status, locale INTO v_status, v_locale
      FROM app.pack_releases WHERE id = NEW.pack_release_id FOR UPDATE;
    IF v_status IS DISTINCT FROM 'building' THEN
        RAISE EXCEPTION 'Cannot modify items of a finalized pack';
    END IF;
    SELECT status, locale INTO v_revision_status, v_revision_locale
      FROM app.lesson_revisions WHERE id = NEW.lesson_revision_id;
    IF v_revision_status IS DISTINCT FROM 'approved' OR v_revision_locale <> v_locale THEN
        RAISE EXCEPTION 'Pack items must be approved and match pack locale';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER validate_pack_item
BEFORE INSERT OR UPDATE ON app.pack_items
FOR EACH ROW EXECUTE FUNCTION app.validate_pack_item();

CREATE OR REPLACE FUNCTION app.protect_pack_item_delete()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF (SELECT status FROM app.pack_releases WHERE id = OLD.pack_release_id FOR UPDATE)
        <> 'building' THEN
        RAISE EXCEPTION 'Cannot remove finalized pack items';
    END IF;
    RETURN OLD;
END;
$$;
CREATE TRIGGER protect_pack_item_delete
BEFORE DELETE ON app.pack_items
FOR EACH ROW EXECUTE FUNCTION app.protect_pack_item_delete();

CREATE OR REPLACE FUNCTION app.protect_finalized_pack_release()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'building' THEN
            RAISE EXCEPTION 'Finalized packs must be retained or revoked';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status <> 'building' AND (
        NEW.pack_key IS DISTINCT FROM OLD.pack_key OR
        NEW.locale IS DISTINCT FROM OLD.locale OR
        NEW.revision IS DISTINCT FROM OLD.revision OR
        NEW.manifest_object_key IS DISTINCT FROM OLD.manifest_object_key OR
        NEW.manifest_sha256 IS DISTINCT FROM OLD.manifest_sha256 OR
        NEW.compressed_bytes IS DISTINCT FROM OLD.compressed_bytes OR
        NEW.created_by IS DISTINCT FROM OLD.created_by OR
        NEW.created_at IS DISTINCT FROM OLD.created_at OR
        (OLD.released_at IS NOT NULL AND NEW.released_at IS DISTINCT FROM OLD.released_at)
    ) THEN RAISE EXCEPTION 'Finalized pack contents are immutable'; END IF;
    IF OLD.status = 'revoked' AND NEW.status <> OLD.status THEN
        RAISE EXCEPTION 'Cannot restore revoked pack';
    END IF;
    IF (OLD.status = 'building' AND NEW.status NOT IN ('building','ready','revoked')) OR
       (OLD.status = 'ready' AND NEW.status NOT IN ('ready','active','revoked')) OR
       (OLD.status = 'active' AND NEW.status NOT IN ('active','retired','revoked')) OR
       (OLD.status = 'retired' AND NEW.status NOT IN ('retired','active','revoked')) THEN
        RAISE EXCEPTION 'Invalid pack lifecycle transition';
    END IF;
    IF NEW.status IN ('ready','active') AND NOT EXISTS (
        SELECT 1 FROM app.pack_items WHERE pack_release_id = NEW.id
    ) THEN RAISE EXCEPTION 'Empty packs cannot be finalized'; END IF;
    IF NEW.status IN ('ready','active') AND EXISTS (
        SELECT 1 FROM app.pack_items pi
        JOIN app.lesson_revision_sources lrs ON lrs.lesson_revision_id = pi.lesson_revision_id
        JOIN app.content_sources s ON s.id = lrs.source_id
        WHERE pi.pack_release_id = NEW.id AND s.rights_status <> 'cleared'
    ) THEN RAISE EXCEPTION 'Pack includes content with uncleared rights'; END IF;
    IF NEW.status IN ('retired','revoked') AND EXISTS (
        SELECT 1 FROM app.pack_current pc WHERE pc.release_id = OLD.id
    ) THEN RAISE EXCEPTION 'Switch current pointer before retiring/revoking pack'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_finalized_pack_release
BEFORE UPDATE OR DELETE ON app.pack_releases
FOR EACH ROW EXECUTE FUNCTION app.protect_finalized_pack_release();

CREATE OR REPLACE FUNCTION app.validate_pack_current()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM app.pack_releases r
        WHERE r.id = NEW.release_id AND r.pack_key = NEW.pack_key
          AND r.locale = NEW.locale AND r.status = 'active'
    ) THEN RAISE EXCEPTION 'Current pointer requires matching active pack'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER validate_pack_current
BEFORE INSERT OR UPDATE ON app.pack_current
FOR EACH ROW EXECUTE FUNCTION app.validate_pack_current();

CREATE OR REPLACE FUNCTION app.prevent_append_only_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    RAISE EXCEPTION 'Append-only records cannot be updated or deleted';
END;
$$;
CREATE TRIGGER no_edit_attempts BEFORE UPDATE OR DELETE ON app.practice_attempts
    FOR EACH ROW EXECUTE FUNCTION app.prevent_append_only_change();
CREATE TRIGGER no_edit_receipts BEFORE UPDATE OR DELETE ON app.sync_receipts
    FOR EACH ROW EXECUTE FUNCTION app.prevent_append_only_change();
CREATE TRIGGER no_edit_changes BEFORE UPDATE OR DELETE ON app.account_change_feed
    FOR EACH ROW EXECUTE FUNCTION app.prevent_append_only_change();
CREATE TRIGGER no_edit_audit BEFORE UPDATE OR DELETE ON app.audit_events
    FOR EACH ROW EXECUTE FUNCTION app.prevent_append_only_change();
CREATE TRIGGER no_edit_reviews BEFORE UPDATE OR DELETE ON app.editorial_reviews
    FOR EACH ROW EXECUTE FUNCTION app.prevent_append_only_change();

-- Default-deny RLS, including accidental grants. Additional narrowly-scoped API
-- role and policies are defined in 0002. A table owner still bypasses RLS unless
-- FORCE RLS applies; never use owner/service_role for normal user operations.
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'app' LOOP
    EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY', t.tablename);
  END LOOP;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA app REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA app REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

COMMENT ON SCHEMA app IS 'Private domain data. Use FastAPI with reviewed authz; never expose this schema in Supabase Data API.';
COMMIT;
