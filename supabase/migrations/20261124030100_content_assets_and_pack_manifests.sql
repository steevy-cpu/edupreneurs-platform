-- Mon Edupreneur 2.0 — schema `content`: asset metadata, revision/asset links,
-- recorded pack manifests (overnight lane CONTENT, Platform-00 M-05 / M-06).
--
-- RULES THIS FILE FOLLOWS (docs/overnight-2026-11-24/00-PLAN.md, section 3)
--   * Nothing is created, altered or granted in schema `app`. The foreign keys
--     below live in schema `content`; they only REFERENCE app tables.
--   * `content` is PRIVATE: no grant to PUBLIC, anon, authenticated,
--     authenticator, service_role or edu_api. Row-level security is enabled on
--     every table and there is NO policy, so even a role that were granted
--     table privileges by mistake would read nothing.
--   * No learner read or write path exists. Learners keep reading content only
--     through app.* and its policies, exactly as before.
--   * Every function pins `search_path = pg_catalog, pg_temp` (ruling R-03) and
--     schema-qualifies every non-catalog object. Only the four staff write
--     functions are executable by anyone but the owner, and only by edu_staff.
--     They reach the staff boundary (staff.require_role, ops.audit_write)
--     through ONE marked seam.
--
-- THE RIGHTS GATE, WITHOUT TOUCHING `app`
--   An asset names the content source it comes from (app.content_sources).
--   content.revision_assets carries that same source_id and two foreign keys:
--     (asset_sha256, source_id)       -> content.assets(sha256, source_id)
--     (lesson_revision_id, source_id) -> app.lesson_revision_sources
--   So an asset can only be attached to a revision that CITES the asset's
--   source, and that citation cannot be removed while the asset is attached.
--   The existing, verified guards in `app` then do the rest, unchanged:
--     - approval requires every cited source to be rights-cleared
--       (app.protect_approved_lesson_revision);
--     - a pack cannot be finalized while a cited source is not cleared
--       (app.protect_finalized_pack_release).
--   Attachments freeze at the first editorial review, like source citations do,
--   so nothing can be attached to a reviewed or approved revision afterwards.

CREATE SCHEMA content;
REVOKE ALL ON SCHEMA content FROM PUBLIC;
REVOKE ALL ON SCHEMA content FROM anon, authenticated, service_role;
COMMENT ON SCHEMA content IS
    'Private: asset metadata and pack manifests. Never expose in the Supabase Data API; no learner access.';

-- ============================================================================
-- Pure helpers (IMMUTABLE; used by CHECK constraints and by the functions below)
-- ============================================================================
-- Storage key of an asset: derived from its hash, so the key can never point
-- at different bytes. 'assets/sha256/ab/abcdef…'
CREATE FUNCTION content.asset_object_key(p_sha256 bytea)
RETURNS text
LANGUAGE sql IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT 'assets/sha256/' || substr(encode(p_sha256, 'hex'), 1, 2) || '/' || encode(p_sha256, 'hex')
$$;

-- {"fr": "...", "ht": "..."}: at least one locale, only known locales, each a
-- bounded single-line plain text (no control characters, no tag opener).
CREATE FUNCTION content.is_locale_text_map(p_value jsonb, p_max_length integer)
RETURNS boolean
LANGUAGE sql IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT CASE
        WHEN p_value IS NULL OR jsonb_typeof(p_value) <> 'object' OR p_value = '{}'::jsonb THEN false
        ELSE NOT EXISTS (
            SELECT 1 FROM jsonb_each(p_value) AS e(locale, body)
            WHERE e.locale NOT IN ('fr', 'ht')
               OR jsonb_typeof(e.body) <> 'string'
               OR char_length(e.body #>> '{}') NOT BETWEEN 1 AND p_max_length
               OR (e.body #>> '{}') ~ '[\x01-\x1f\x7f]'
               OR (e.body #>> '{}') ~ '<[A-Za-z/!?]'
        )
    END
$$;

-- Smallest content format able to carry a lesson body: 1 when every block is a
-- format-1 block, otherwise 2. Mirrors edu_api.content.formats.required_format.
-- (Block validity itself is checked by the pack builder, not by the database.)
CREATE FUNCTION content.blocks_required_format(p_blocks jsonb)
RETURNS smallint
LANGUAGE sql IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT CASE
        WHEN p_blocks IS NULL OR jsonb_typeof(p_blocks) <> 'array' THEN NULL
        WHEN EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_blocks) AS b(block)
            WHERE COALESCE(b.block ->> 'type', '') NOT IN ('heading', 'paragraph', 'example', 'callout')
        ) THEN 2
        ELSE 1
    END::smallint
$$;

-- Hashes of the assets a lesson body references (image, audio, pre-rendered math).
CREATE FUNCTION content.block_asset_hashes(p_blocks jsonb)
RETURNS SETOF text
LANGUAGE sql IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT DISTINCT b.block #>> '{asset,sha256}'
    FROM jsonb_array_elements(
        CASE WHEN jsonb_typeof(p_blocks) = 'array' THEN p_blocks ELSE '[]'::jsonb END) AS b(block)
    WHERE jsonb_typeof(b.block) = 'object'
      AND jsonb_typeof(b.block -> 'asset') = 'object'
      AND (b.block #>> '{asset,sha256}') IS NOT NULL
$$;

-- ============================================================================
-- Tables (3)
-- ============================================================================
-- One row per distinct file. The SHA-256 of the bytes IS the identity: the same
-- picture used by ten lessons is one row and one object in storage.
-- Limits mirror packages/contracts/content/lesson-blocks.v2.schema.json.
CREATE TABLE content.assets (
    sha256 bytea PRIMARY KEY CHECK (octet_length(sha256) = 32),
    object_key text NOT NULL UNIQUE,
    bytes bigint NOT NULL,
    mime text NOT NULL
        CHECK (mime IN ('image/webp', 'image/png', 'image/jpeg', 'audio/mp4', 'audio/mpeg')),
    width integer,
    height integer,
    duration_ms integer,
    -- Default alternative text per locale. The alt text a learner actually gets
    -- is the one in the reviewed block; this one describes the file itself.
    alt_text jsonb NOT NULL,
    -- Rights / provenance: every asset comes from exactly one recorded source.
    source_id uuid NOT NULL REFERENCES app.content_sources(id) ON DELETE RESTRICT,
    created_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sha256, source_id),
    CONSTRAINT assets_object_key_is_content_addressed
        CHECK (object_key = content.asset_object_key(sha256)),
    CONSTRAINT assets_alt_text_per_locale
        CHECK (content.is_locale_text_map(alt_text, 300)),
    CONSTRAINT assets_image_shape CHECK (
        mime NOT LIKE 'image/%' OR (
            width IS NOT NULL AND width BETWEEN 1 AND 1600 AND
            height IS NOT NULL AND height BETWEEN 1 AND 1600 AND
            duration_ms IS NULL AND bytes BETWEEN 1 AND 200000)),
    CONSTRAINT assets_audio_shape CHECK (
        mime NOT LIKE 'audio/%' OR (
            width IS NULL AND height IS NULL AND
            duration_ms IS NOT NULL AND duration_ms BETWEEN 1 AND 600000 AND
            bytes BETWEEN 1 AND 2000000))
);

-- Which lesson revision uses which asset. source_id is redundant on purpose:
-- it is what the two composite foreign keys (the rights gate) hang on.
CREATE TABLE content.revision_assets (
    lesson_revision_id uuid NOT NULL REFERENCES app.lesson_revisions(id) ON DELETE RESTRICT,
    asset_sha256 bytea NOT NULL,
    source_id uuid NOT NULL,
    attached_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    attached_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (lesson_revision_id, asset_sha256),
    CONSTRAINT revision_assets_asset_with_its_source
        FOREIGN KEY (asset_sha256, source_id)
        REFERENCES content.assets (sha256, source_id) ON DELETE RESTRICT,
    CONSTRAINT revision_assets_source_is_cited_by_revision
        FOREIGN KEY (lesson_revision_id, source_id)
        REFERENCES app.lesson_revision_sources (lesson_revision_id, source_id) ON DELETE RESTRICT
);

-- The REAL manifest of a pack release: one row, written once, in the same
-- transaction that moves the release from 'building' to 'ready'. A release
-- without a row here has no verified manifest (the seed releases, for example,
-- carry labelled placeholder digests).
CREATE TABLE content.pack_manifests (
    pack_release_id uuid PRIMARY KEY REFERENCES app.pack_releases(id) ON DELETE RESTRICT,
    manifest_version text NOT NULL CHECK (manifest_version = 'pack-manifest-1'),
    content_format smallint NOT NULL CHECK (content_format IN (1, 2)),
    manifest_sha256 bytea NOT NULL CHECK (octet_length(manifest_sha256) = 32),
    manifest_bytes bigint NOT NULL CHECK (manifest_bytes BETWEEN 1 AND 1048576),
    lesson_count integer NOT NULL CHECK (lesson_count > 0),
    question_count integer NOT NULL CHECK (question_count >= 0),
    asset_count integer NOT NULL CHECK (asset_count >= 0),
    lesson_bytes bigint NOT NULL CHECK (lesson_bytes > 0),
    required_asset_bytes bigint NOT NULL CHECK (required_asset_bytes >= 0),
    optional_asset_bytes bigint NOT NULL CHECK (optional_asset_bytes >= 0),
    recorded_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    recorded_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_assets_source ON content.assets(source_id);
CREATE INDEX idx_assets_created_by ON content.assets(created_by);
CREATE INDEX idx_revision_assets_asset ON content.revision_assets(asset_sha256, source_id);
CREATE INDEX idx_revision_assets_citation ON content.revision_assets(lesson_revision_id, source_id);
CREATE INDEX idx_revision_assets_attached_by ON content.revision_assets(attached_by);
CREATE INDEX idx_pack_manifests_recorded_by ON content.pack_manifests(recorded_by);

ALTER TABLE content.assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE content.revision_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE content.pack_manifests ENABLE ROW LEVEL SECURITY;
-- Deliberately NO policy: default deny for every role that is not the owner.

-- ============================================================================
-- Integrity guards (triggers). Like the guards in `app`, they hold for every
-- writer, including the owner in a SQL console.
-- ============================================================================
CREATE FUNCTION content.protect_asset()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RETURN OLD; -- attached assets are protected by the foreign key (RESTRICT)
    END IF;
    IF NEW.sha256 IS DISTINCT FROM OLD.sha256 OR
       NEW.object_key IS DISTINCT FROM OLD.object_key OR
       NEW.bytes IS DISTINCT FROM OLD.bytes OR
       NEW.mime IS DISTINCT FROM OLD.mime OR
       NEW.width IS DISTINCT FROM OLD.width OR
       NEW.height IS DISTINCT FROM OLD.height OR
       NEW.duration_ms IS DISTINCT FROM OLD.duration_ms OR
       NEW.created_by IS DISTINCT FROM OLD.created_by OR
       NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'Asset identity and intrinsic metadata are immutable';
    END IF;
    -- What a reviewer saw must not change afterwards.
    IF (NEW.alt_text IS DISTINCT FROM OLD.alt_text OR NEW.source_id IS DISTINCT FROM OLD.source_id)
       AND EXISTS (
           SELECT 1 FROM content.revision_assets ra
           JOIN app.lesson_revisions lr ON lr.id = ra.lesson_revision_id
           WHERE ra.asset_sha256 = OLD.sha256 AND (
               lr.status = 'approved' OR
               EXISTS (SELECT 1 FROM app.editorial_reviews r WHERE r.lesson_revision_id = lr.id) OR
               EXISTS (SELECT 1 FROM app.pack_items pi WHERE pi.lesson_revision_id = lr.id))
       ) THEN
        RAISE EXCEPTION 'Assets used in reviewed material are immutable';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_asset
BEFORE UPDATE OR DELETE ON content.assets
FOR EACH ROW EXECUTE FUNCTION content.protect_asset();

-- Freeze the asset list once a human has reviewed a revision (same rule and
-- same locking as app.protect_reviewed_source_links).
CREATE FUNCTION content.guard_revision_asset()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE v_revision uuid;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Asset attachments cannot be edited; detach and attach again';
    END IF;
    v_revision := CASE WHEN TG_OP = 'DELETE' THEN OLD.lesson_revision_id
                       ELSE NEW.lesson_revision_id END;
    -- Serialise against a concurrent review/approval of the parent revision.
    PERFORM 1 FROM app.lesson_revisions lr WHERE lr.id = v_revision FOR SHARE;
    IF EXISTS (SELECT 1 FROM app.lesson_revisions lr
               WHERE lr.id = v_revision AND lr.status = 'approved') OR
       EXISTS (SELECT 1 FROM app.editorial_reviews r WHERE r.lesson_revision_id = v_revision) OR
       EXISTS (SELECT 1 FROM app.pack_items pi WHERE pi.lesson_revision_id = v_revision) THEN
        RAISE EXCEPTION 'Assets of reviewed/approved/packed lesson revisions are frozen';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_revision_asset
BEFORE INSERT OR UPDATE OR DELETE ON content.revision_assets
FOR EACH ROW EXECUTE FUNCTION content.guard_revision_asset();

-- A manifest row must describe the release exactly as `app` stores it, and is
-- written once.
CREATE FUNCTION content.guard_pack_manifest()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE v_release record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Recorded pack manifests are append-only';
    END IF;
    SELECT r.status, r.manifest_sha256, r.compressed_bytes INTO v_release
    FROM app.pack_releases r WHERE r.id = NEW.pack_release_id FOR SHARE;
    IF NOT FOUND OR v_release.status = 'building' THEN
        RAISE EXCEPTION 'A manifest can only be recorded for a finalized pack release';
    END IF;
    IF v_release.manifest_sha256 IS DISTINCT FROM NEW.manifest_sha256 OR
       v_release.compressed_bytes IS DISTINCT FROM
           (NEW.manifest_bytes + NEW.lesson_bytes + NEW.required_asset_bytes + NEW.optional_asset_bytes) THEN
        RAISE EXCEPTION 'Recorded manifest does not match the pack release';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_pack_manifest
BEFORE INSERT OR UPDATE OR DELETE ON content.pack_manifests
FOR EACH ROW EXECUTE FUNCTION content.guard_pack_manifest();

-- ============================================================================
-- Read helpers for other server-side code (no grant yet)
-- ============================================================================
CREATE FUNCTION content.revision_required_format(p_revision_id uuid)
RETURNS smallint
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT GREATEST(
        content.blocks_required_format(lr.blocks),
        CASE WHEN EXISTS (
            SELECT 1 FROM app.question_revisions q
            WHERE q.lesson_revision_id = lr.id AND q.kind <> 'mcq') THEN 2 ELSE 1 END
    )::smallint
    FROM app.lesson_revisions lr WHERE lr.id = p_revision_id
$$;

-- Highest required format among the items of a release; NULL for an empty or
-- unknown release. Meant for the future "may this release be served to a
-- format-1 client / be made current" check.
CREATE FUNCTION content.release_required_format(p_release_id uuid)
RETURNS smallint
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT max(content.revision_required_format(pi.lesson_revision_id))::smallint
    FROM app.pack_items pi WHERE pi.pack_release_id = p_release_id
$$;

-- ############################################################################
-- #  STAFF SEAM - the ONLY two functions that mention the staff lane.         #
-- #  staff.require_role and ops.audit_write come from migration               #
-- #  20261124010000 (staff lane, B1). No role check, no write; no audit       #
-- #  trail, no write: both run inside the caller's transaction.               #
-- ############################################################################
CREATE FUNCTION content.staff_gate(VARIADIC p_roles text[])
RETURNS uuid
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE v_actor uuid;
BEGIN
    v_actor := staff.require_role(VARIADIC p_roles);
    -- Belt and braces: the gate's answer must be the transaction's verified actor.
    IF v_actor IS NULL OR v_actor IS DISTINCT FROM app.current_actor_id() THEN
        RAISE EXCEPTION 'Staff role required' USING ERRCODE = '42501';
    END IF;
    RETURN v_actor;
END;
$$;

-- Details passed here are ids, hashes, enum codes and numbers only (ruling R-03):
-- never alt text, titles or any other typed text.
CREATE FUNCTION content.audit(
    p_action text, p_target_kind text, p_target_id uuid, p_details jsonb)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    PERFORM ops.audit_write(p_action, p_target_kind, p_target_id, 'allowed', p_details);
END;
$$;
-- ############################ end of the staff seam #########################

-- ============================================================================
-- Staff write path (SECURITY DEFINER, owner postgres, EXECUTE granted to edu_staff only)
-- The actor is never a parameter: it comes from the staff gate.
-- ============================================================================
-- Record the metadata of an uploaded file. Idempotent for identical metadata.
CREATE FUNCTION content.register_asset(
    p_sha256 bytea,
    p_bytes bigint,
    p_mime text,
    p_width integer,
    p_height integer,
    p_duration_ms integer,
    p_alt_text jsonb,
    p_source_id uuid)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid;
    v_existing content.assets%ROWTYPE;
BEGIN
    v_actor := content.staff_gate('editor', 'admin');
    IF p_sha256 IS NULL OR octet_length(p_sha256) <> 32 OR p_bytes IS NULL OR p_mime IS NULL
       OR p_alt_text IS NULL OR p_source_id IS NULL OR char_length(p_mime) > 40
       OR pg_column_size(p_alt_text) > 4096 THEN
        RAISE EXCEPTION 'Malformed asset registration' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.content_sources s WHERE s.id = p_source_id) THEN
        RAISE EXCEPTION 'Unknown content source' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_existing FROM content.assets a WHERE a.sha256 = p_sha256;
    IF FOUND THEN
        IF v_existing.bytes IS DISTINCT FROM p_bytes OR v_existing.mime IS DISTINCT FROM p_mime
           OR v_existing.width IS DISTINCT FROM p_width OR v_existing.height IS DISTINCT FROM p_height
           OR v_existing.duration_ms IS DISTINCT FROM p_duration_ms
           OR v_existing.source_id IS DISTINCT FROM p_source_id THEN
            RAISE EXCEPTION 'This asset is already registered with different metadata'
                USING ERRCODE = '23505';
        END IF;
        RETURN jsonb_build_object(
            'sha256', encode(p_sha256, 'hex'), 'object_key', v_existing.object_key, 'created', false);
    END IF;

    -- Shape, limits, mime allow-list and alt text are enforced by the table's constraints.
    INSERT INTO content.assets (
        sha256, object_key, bytes, mime, width, height, duration_ms, alt_text, source_id, created_by)
    VALUES (
        p_sha256, content.asset_object_key(p_sha256), p_bytes, p_mime, p_width, p_height,
        p_duration_ms, p_alt_text, p_source_id, v_actor);

    PERFORM content.audit('content.asset.register', 'content_asset', NULL, jsonb_build_object(
        'sha256', encode(p_sha256, 'hex'), 'mime', p_mime, 'bytes', p_bytes, 'source_id', p_source_id));
    RETURN jsonb_build_object(
        'sha256', encode(p_sha256, 'hex'),
        'object_key', content.asset_object_key(p_sha256),
        'created', true);
END;
$$;

-- Say that a DRAFT revision uses an asset. The revision must already cite the
-- asset's source; the triggers refuse reviewed, approved and packed revisions.
CREATE FUNCTION content.attach_asset(p_revision_id uuid, p_sha256 bytea)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid;
    v_source uuid;
BEGIN
    v_actor := content.staff_gate('editor', 'admin');
    IF p_revision_id IS NULL OR p_sha256 IS NULL OR octet_length(p_sha256) <> 32 THEN
        RAISE EXCEPTION 'Malformed asset attachment' USING ERRCODE = '22023';
    END IF;
    SELECT a.source_id INTO v_source FROM content.assets a WHERE a.sha256 = p_sha256;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown asset' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.lesson_revisions lr WHERE lr.id = p_revision_id) THEN
        RAISE EXCEPTION 'Unknown lesson revision' USING ERRCODE = '22023';
    END IF;
    IF EXISTS (SELECT 1 FROM content.revision_assets ra
               WHERE ra.lesson_revision_id = p_revision_id AND ra.asset_sha256 = p_sha256) THEN
        RETURN jsonb_build_object('attached', false);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.lesson_revision_sources lrs
                   WHERE lrs.lesson_revision_id = p_revision_id AND lrs.source_id = v_source) THEN
        RAISE EXCEPTION 'The lesson revision must cite the asset''s source before the asset is attached'
            USING ERRCODE = '23503';
    END IF;

    INSERT INTO content.revision_assets (lesson_revision_id, asset_sha256, source_id, attached_by)
    VALUES (p_revision_id, p_sha256, v_source, v_actor);

    PERFORM content.audit('content.asset.attach', 'lesson_revision', p_revision_id,
        jsonb_build_object('sha256', encode(p_sha256, 'hex')));
    RETURN jsonb_build_object('attached', true);
END;
$$;

CREATE FUNCTION content.detach_asset(p_revision_id uuid, p_sha256 bytea)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE v_removed integer;
BEGIN
    PERFORM content.staff_gate('editor', 'admin');
    IF p_revision_id IS NULL OR p_sha256 IS NULL OR octet_length(p_sha256) <> 32 THEN
        RAISE EXCEPTION 'Malformed asset attachment' USING ERRCODE = '22023';
    END IF;
    DELETE FROM content.revision_assets ra
     WHERE ra.lesson_revision_id = p_revision_id AND ra.asset_sha256 = p_sha256;
    GET DIAGNOSTICS v_removed = ROW_COUNT;
    IF v_removed > 0 THEN
        PERFORM content.audit('content.asset.detach', 'lesson_revision', p_revision_id,
            jsonb_build_object('sha256', encode(p_sha256, 'hex')));
    END IF;
    RETURN jsonb_build_object('detached', v_removed > 0);
END;
$$;

-- Record the REAL manifest of a release and move it 'building' -> 'ready', in
-- one transaction. The database cannot read object storage, so it cannot
-- re-hash lesson blobs; what it CAN check against its own tables, it does:
-- the pack identity, the ordered list of lesson revisions, the set of assets
-- with their sizes and types, and the declared content format.
-- p_manifest is the parsed manifest document produced by scripts/build_pack.py;
-- p_manifest_sha256 / p_manifest_bytes describe its canonical bytes.
CREATE FUNCTION content.record_release_manifest(
    p_release_id uuid,
    p_manifest jsonb,
    p_manifest_sha256 bytea,
    p_manifest_bytes bigint)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid;
    v_release record;
    v_format smallint;
    v_required smallint;
    v_lesson_bytes bigint;
    v_required_bytes bigint;
    v_optional_bytes bigint;
    v_lessons integer;
    v_questions integer;
    v_assets integer;
    v_total bigint;
    v_key text;
BEGIN
    v_actor := content.staff_gate('publisher', 'admin');
    IF p_release_id IS NULL OR p_manifest IS NULL OR jsonb_typeof(p_manifest) <> 'object'
       OR pg_column_size(p_manifest) > 1048576
       OR p_manifest_sha256 IS NULL OR octet_length(p_manifest_sha256) <> 32
       OR p_manifest_bytes IS NULL OR p_manifest_bytes NOT BETWEEN 1 AND 1048576 THEN
        RAISE EXCEPTION 'Malformed manifest record' USING ERRCODE = '22023';
    END IF;

    SELECT r.id, r.pack_key, r.locale, r.revision, r.status INTO v_release
    FROM app.pack_releases r WHERE r.id = p_release_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown pack release' USING ERRCODE = '22023';
    END IF;
    IF v_release.status <> 'building' THEN
        RAISE EXCEPTION 'A manifest can only be recorded while the pack release is building'
            USING ERRCODE = '55000';
    END IF;

    -- Everything read out of the caller's JSON is inside this block: a wrong
    -- type or a malformed uuid becomes one clean "malformed manifest" error.
    BEGIN
        IF p_manifest ->> 'manifest_version' IS DISTINCT FROM 'pack-manifest-1'
           OR jsonb_typeof(p_manifest -> 'lessons') IS DISTINCT FROM 'array'
           OR jsonb_typeof(p_manifest -> 'assets') IS DISTINCT FROM 'array'
           OR jsonb_typeof(p_manifest -> 'pack') IS DISTINCT FROM 'object'
           OR jsonb_typeof(p_manifest -> 'totals') IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'Malformed manifest' USING ERRCODE = '22023';
        END IF;
        v_format := (p_manifest ->> 'content_format')::smallint;
        v_lesson_bytes := (p_manifest #>> '{totals,lesson_bytes}')::bigint;
        v_required_bytes := (p_manifest #>> '{totals,required_asset_bytes}')::bigint;
        v_optional_bytes := (p_manifest #>> '{totals,optional_asset_bytes}')::bigint;
        v_lessons := (p_manifest #>> '{totals,lessons}')::integer;
        v_questions := (p_manifest #>> '{totals,questions}')::integer;
        v_assets := (p_manifest #>> '{totals,assets}')::integer;

        IF (p_manifest #>> '{pack,release_id}')::uuid IS DISTINCT FROM v_release.id
           OR p_manifest #>> '{pack,pack_key}' IS DISTINCT FROM v_release.pack_key
           OR p_manifest #>> '{pack,locale}' IS DISTINCT FROM v_release.locale
           OR (p_manifest #>> '{pack,revision}')::integer IS DISTINCT FROM v_release.revision THEN
            RAISE EXCEPTION 'Manifest describes a different pack release' USING ERRCODE = '22023';
        END IF;

        -- The ordered lesson list must be exactly the release's items.
        IF EXISTS (
            (SELECT (l.item ->> 'position')::integer, (l.item ->> 'revision_id')::uuid
               FROM jsonb_array_elements(p_manifest -> 'lessons') AS l(item)
             EXCEPT
             SELECT pi.position, pi.lesson_revision_id
               FROM app.pack_items pi WHERE pi.pack_release_id = v_release.id)
            UNION ALL
            (SELECT pi.position, pi.lesson_revision_id
               FROM app.pack_items pi WHERE pi.pack_release_id = v_release.id
             EXCEPT
             SELECT (l.item ->> 'position')::integer, (l.item ->> 'revision_id')::uuid
               FROM jsonb_array_elements(p_manifest -> 'lessons') AS l(item))
        ) OR jsonb_array_length(p_manifest -> 'lessons') <>
             (SELECT count(*) FROM app.pack_items pi WHERE pi.pack_release_id = v_release.id) THEN
            RAISE EXCEPTION 'Manifest lessons do not match the items of the pack release'
                USING ERRCODE = '22023';
        END IF;

        -- Every asset a packed lesson references must be attached to that lesson
        -- revision (and therefore covered by the rights gate).
        IF EXISTS (
            SELECT 1
            FROM app.pack_items pi
            JOIN app.lesson_revisions lr ON lr.id = pi.lesson_revision_id
            CROSS JOIN LATERAL content.block_asset_hashes(lr.blocks) AS h(hex)
            WHERE pi.pack_release_id = v_release.id
              AND NOT EXISTS (
                  SELECT 1 FROM content.revision_assets ra
                  WHERE ra.lesson_revision_id = lr.id AND encode(ra.asset_sha256, 'hex') = h.hex)
        ) THEN
            RAISE EXCEPTION 'A packed lesson references an asset that is not attached to it'
                USING ERRCODE = '22023';
        END IF;

        -- The asset list must be exactly the referenced assets, with the sizes
        -- and types this database recorded for them.
        IF EXISTS (
            (SELECT a.item ->> 'sha256', (a.item ->> 'bytes')::bigint, a.item ->> 'mime',
                    (a.item ->> 'required')::boolean
               FROM jsonb_array_elements(p_manifest -> 'assets') AS a(item)
             EXCEPT
             SELECT encode(s.sha256, 'hex'), s.bytes, s.mime, s.mime LIKE 'image/%'
               FROM app.pack_items pi
               JOIN app.lesson_revisions lr ON lr.id = pi.lesson_revision_id
               CROSS JOIN LATERAL content.block_asset_hashes(lr.blocks) AS h(hex)
               JOIN content.assets s ON encode(s.sha256, 'hex') = h.hex
              WHERE pi.pack_release_id = v_release.id)
            UNION ALL
            (SELECT encode(s.sha256, 'hex'), s.bytes, s.mime, s.mime LIKE 'image/%'
               FROM app.pack_items pi
               JOIN app.lesson_revisions lr ON lr.id = pi.lesson_revision_id
               CROSS JOIN LATERAL content.block_asset_hashes(lr.blocks) AS h(hex)
               JOIN content.assets s ON encode(s.sha256, 'hex') = h.hex
              WHERE pi.pack_release_id = v_release.id
             EXCEPT
             SELECT a.item ->> 'sha256', (a.item ->> 'bytes')::bigint, a.item ->> 'mime',
                    (a.item ->> 'required')::boolean
               FROM jsonb_array_elements(p_manifest -> 'assets') AS a(item))
        ) THEN
            RAISE EXCEPTION 'Manifest assets do not match the assets recorded for this pack'
                USING ERRCODE = '22023';
        END IF;

        IF v_assets IS DISTINCT FROM jsonb_array_length(p_manifest -> 'assets')
           OR v_lessons IS DISTINCT FROM jsonb_array_length(p_manifest -> 'lessons')
           OR v_required_bytes IS DISTINCT FROM (
               SELECT COALESCE(sum((a.item ->> 'bytes')::bigint), 0)
               FROM jsonb_array_elements(p_manifest -> 'assets') AS a(item)
               WHERE (a.item ->> 'required')::boolean)
           OR v_optional_bytes IS DISTINCT FROM (
               SELECT COALESCE(sum((a.item ->> 'bytes')::bigint), 0)
               FROM jsonb_array_elements(p_manifest -> 'assets') AS a(item)
               WHERE NOT (a.item ->> 'required')::boolean)
           OR v_lesson_bytes IS DISTINCT FROM (
               SELECT COALESCE(sum((l.item ->> 'bytes')::bigint), 0)
               FROM jsonb_array_elements(p_manifest -> 'lessons') AS l(item))
           OR v_questions IS DISTINCT FROM (
               SELECT count(*)::integer FROM app.pack_items pi
               JOIN app.question_revisions q ON q.lesson_revision_id = pi.lesson_revision_id
               WHERE pi.pack_release_id = v_release.id) THEN
            RAISE EXCEPTION 'Manifest totals are inconsistent' USING ERRCODE = '22023';
        END IF;
    EXCEPTION
        -- failed casts of caller-supplied text (uuid, integer, boolean)
        WHEN invalid_text_representation OR numeric_value_out_of_range THEN
            RAISE EXCEPTION 'Malformed manifest' USING ERRCODE = '22023';
    END;

    -- The negotiation rule: a pack never contains content above its declared format.
    IF v_format IS NULL OR v_format NOT IN (1, 2) THEN
        RAISE EXCEPTION 'Unsupported content format' USING ERRCODE = '22023';
    END IF;
    v_required := content.release_required_format(v_release.id);
    IF v_required IS NULL THEN
        RAISE EXCEPTION 'Empty packs cannot be finalized' USING ERRCODE = '22023';
    END IF;
    IF v_required > v_format THEN
        RAISE EXCEPTION 'Pack declares content format % but contains format-% content', v_format, v_required
            USING ERRCODE = '22023';
    END IF;

    v_total := p_manifest_bytes + v_lesson_bytes + v_required_bytes + v_optional_bytes;
    v_key := 'packs/' || v_release.pack_key || '/' || v_release.locale || '/'
             || v_release.revision || '/manifest.json';

    -- app.protect_finalized_pack_release still applies (non-empty, rights cleared).
    UPDATE app.pack_releases
       SET status = 'ready', manifest_object_key = v_key,
           manifest_sha256 = p_manifest_sha256, compressed_bytes = v_total
     WHERE id = v_release.id;

    INSERT INTO content.pack_manifests (
        pack_release_id, manifest_version, content_format, manifest_sha256, manifest_bytes,
        lesson_count, question_count, asset_count, lesson_bytes, required_asset_bytes,
        optional_asset_bytes, recorded_by)
    VALUES (
        v_release.id, 'pack-manifest-1', v_format, p_manifest_sha256, p_manifest_bytes,
        v_lessons, v_questions, v_assets, v_lesson_bytes, v_required_bytes,
        v_optional_bytes, v_actor);

    PERFORM content.audit('content.pack.manifest_recorded', 'pack_release', v_release.id,
        jsonb_build_object(
            'manifest_sha256', encode(p_manifest_sha256, 'hex'),
            'content_format', v_format,
            'total_bytes', v_total));
    RETURN jsonb_build_object(
        'release_id', v_release.id, 'status', 'ready', 'manifest_object_key', v_key,
        'manifest_sha256', encode(p_manifest_sha256, 'hex'), 'content_format', v_format,
        'total_bytes', v_total);
END;
$$;

-- No erase_learner() hook: this schema stores no per-learner row. created_by,
-- attached_by and recorded_by are staff accounts.

-- Functions are created executable by PUBLIC by default; take that away, then
-- grant exactly the staff write path to the staff API role. edu_staff gets no
-- table privilege: it can only go through the four audited functions.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA content FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON ALL TABLES IN SCHEMA content FROM PUBLIC, anon, authenticated, service_role;
GRANT USAGE ON SCHEMA content TO edu_staff;
GRANT EXECUTE ON FUNCTION content.register_asset(bytea, bigint, text, integer, integer, integer, jsonb, uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION content.attach_asset(uuid, bytea) TO edu_staff;
GRANT EXECUTE ON FUNCTION content.detach_asset(uuid, bytea) TO edu_staff;
GRANT EXECUTE ON FUNCTION content.record_release_manifest(uuid, jsonb, bytea, bigint) TO edu_staff;
