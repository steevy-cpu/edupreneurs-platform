-- Mon Edupreneur 2.0 — core schema (22 private application tables)
--
-- Derived from docs/reference/schema-v0.2/migrations/0001_core_schema.sql.
-- Every deviation from that draft is listed in docs/SCHEMA_CHANGELOG.md and is
-- tagged in this file with "[v0.2 change Cnn]".
--
-- The `app` schema is PRIVATE. It is never listed in the Supabase Data API
-- "exposed schemas"; only the FastAPI service reads or writes it.
--
-- Integrity triggers live in the next migration; roles, grants and row-level
-- security policies in the one after that.

CREATE SCHEMA IF NOT EXISTS app;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
REVOKE ALL ON SCHEMA app FROM anon, authenticated;
COMMENT ON SCHEMA app IS
    'Private domain data. Reached only through FastAPI; never expose this schema in the Supabase Data API.';

-- ============================================================================
-- Actor identity
-- ============================================================================
-- FastAPI verifies the caller's access token, then — inside the request's
-- database transaction — runs  set_config('edu.actor_id', <verified uuid>, true).
-- The `true` makes the value transaction-local, so it disappears at
-- COMMIT/ROLLBACK and cannot leak to the next request on a pooled connection.
-- With no actor set this returns NULL and every "own row" policy denies.
--
-- This setting is NOT proof of identity by itself: any SQL session can set it.
-- It is only trustworthy because the API is the sole client of the role that
-- uses it. See docs/SECURITY.md.
CREATE FUNCTION app.current_actor_id()
RETURNS uuid
LANGUAGE sql STABLE
SET search_path = ''
AS $$ SELECT NULLIF(current_setting('edu.actor_id', true), '')::uuid $$;

-- ============================================================================
-- IDENTITY / ACCESS (2)
-- ============================================================================
CREATE TABLE app.learner_profiles (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE RESTRICT,
    grade_id uuid, -- FK added below, once app.grades exists
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

-- ============================================================================
-- CURRICULUM (7)
-- ============================================================================
-- [v0.2 change C13] Localised label maps must at least contain French ('fr'),
-- because the API falls back to French when a Creole label is missing.
CREATE TABLE app.grades (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE CHECK (code ~ '^[A-Z0-9]{2,8}$'),
    sort_order smallint NOT NULL UNIQUE CHECK (sort_order > 0),
    labels jsonb NOT NULL CHECK (jsonb_typeof(labels) = 'object' AND labels ? 'fr'),
    is_active boolean NOT NULL DEFAULT true
);
ALTER TABLE app.learner_profiles
    ADD CONSTRAINT learner_profiles_grade_fkey FOREIGN KEY (grade_id)
    REFERENCES app.grades(id) ON DELETE RESTRICT;

CREATE TABLE app.subjects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]{2,80}$'),
    labels jsonb NOT NULL CHECK (jsonb_typeof(labels) = 'object' AND labels ? 'fr'),
    is_active boolean NOT NULL DEFAULT true
);

CREATE TABLE app.courses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    grade_id uuid NOT NULL REFERENCES app.grades(id) ON DELETE RESTRICT,
    subject_id uuid NOT NULL REFERENCES app.subjects(id) ON DELETE RESTRICT,
    slug text NOT NULL CHECK (slug ~ '^[a-z0-9-]{2,80}$'),
    titles jsonb NOT NULL CHECK (jsonb_typeof(titles) = 'object' AND titles ? 'fr'),
    visibility text NOT NULL DEFAULT 'draft' CHECK (visibility IN ('draft','published','archived')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (grade_id, subject_id, slug)
);

CREATE TABLE app.units (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id uuid NOT NULL REFERENCES app.courses(id) ON DELETE RESTRICT,
    slug text NOT NULL CHECK (slug ~ '^[a-z0-9-]{2,80}$'),
    position integer NOT NULL CHECK (position > 0),
    titles jsonb NOT NULL CHECK (jsonb_typeof(titles) = 'object' AND titles ? 'fr'),
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

-- French and Haitian Creole are INDEPENDENT revisions of the same lesson.
-- [v0.2 change C05] created_by is NOT NULL: an unknown author would make the
-- "reviewer must not be the author" rule impossible to enforce.
CREATE TABLE app.lesson_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lesson_id uuid NOT NULL REFERENCES app.lessons(id) ON DELETE RESTRICT,
    revision integer NOT NULL CHECK (revision > 0),
    locale text NOT NULL CHECK (locale IN ('fr','ht')),
    title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    blocks jsonb NOT NULL CHECK (jsonb_typeof(blocks) = 'array'),
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','in_review','approved','rejected')),
    created_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
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

-- Each question belongs to exactly one lesson revision (and so one locale).
-- question_key lets us compare "the same question" across revisions.
-- answer_key ships to the device for OFFLINE PRACTICE; it is not exam-grade secret.
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

-- ============================================================================
-- PUBLICATION / PROVENANCE (6)
-- ============================================================================
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

-- The single "what students get right now" pointer per (pack_key, locale).
-- Moving the pointer in one transaction publishes a new release atomically.
CREATE TABLE app.pack_current (
    pack_key text NOT NULL,
    locale text NOT NULL,
    release_id uuid NOT NULL UNIQUE,
    switched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pack_key, locale),
    FOREIGN KEY (release_id, pack_key, locale)
        REFERENCES app.pack_releases(id, pack_key, locale) ON DELETE RESTRICT
);

-- ============================================================================
-- LEARNING + OFFLINE SYNC (5)
-- ============================================================================
-- These five tables are written ONLY by app.sync_apply_operation()
-- (migration 20261121000400). The student API role has SELECT on them, never
-- INSERT/UPDATE/DELETE. [v0.2 change C01]
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
    -- Untrusted display metadata from the phone's clock. Never used for ordering or scoring.
    client_recorded_at timestamptz,
    accepted_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (learner_id, op_id),
    FOREIGN KEY (question_revision_id, lesson_revision_id)
        REFERENCES app.question_revisions(id, lesson_revision_id) ON DELETE RESTRICT
);

-- One row per learner. Locking this row serialises that learner's sync
-- operations, which is what makes change versions gap-free and commit-ordered.
CREATE TABLE app.account_sync_state (
    learner_id uuid PRIMARY KEY REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    current_version bigint NOT NULL DEFAULT 0 CHECK (current_version >= 0)
);

-- Durable answer to "have I already processed this op_id, and what did I say?"
-- [v0.2 change C11] op_kind and canon_version record how payload_sha256 was produced.
CREATE TABLE app.sync_receipts (
    learner_id uuid NOT NULL REFERENCES app.learner_profiles(user_id) ON DELETE RESTRICT,
    op_id uuid NOT NULL,
    op_kind text NOT NULL CHECK (op_kind ~ '^[a-z_]{3,40}$'),
    canon_version text NOT NULL CHECK (canon_version ~ '^[a-z0-9-]{3,40}$'),
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

-- ============================================================================
-- OPERATIONS (2) — reserved for the future worker; the student API has no access.
-- ============================================================================
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
    actor_id uuid, -- deliberately no FK: audit retention must not block account deletion
    actor_kind text NOT NULL CHECK (actor_kind IN ('user','staff','worker','system')),
    action text NOT NULL CHECK (char_length(action) BETWEEN 3 AND 100),
    target_kind text,
    target_id uuid,
    outcome text NOT NULL CHECK (outcome IN ('allowed','denied','error')),
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- INDEXES (in addition to the PK / UNIQUE indexes above)
-- ============================================================================
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

-- [v0.2 change C12] Foreign keys that had no supporting index. Without these,
-- every delete of a referenced row (for example a future account-deletion
-- procedure removing an auth.users row) forces a full scan of the child table.
CREATE INDEX idx_staff_roles_granted_by ON app.staff_roles(granted_by) WHERE granted_by IS NOT NULL;
CREATE INDEX idx_lesson_revs_created_by ON app.lesson_revisions(created_by);
CREATE INDEX idx_lesson_revs_approved_by ON app.lesson_revisions(approved_by) WHERE approved_by IS NOT NULL;
CREATE INDEX idx_reviews_reviewer ON app.editorial_reviews(reviewer_id);
CREATE INDEX idx_pack_releases_created_by ON app.pack_releases(created_by) WHERE created_by IS NOT NULL;
CREATE INDEX idx_progress_lesson ON app.lesson_progress(lesson_id);
CREATE INDEX idx_progress_last_revision ON app.lesson_progress(last_revision_id) WHERE last_revision_id IS NOT NULL;
