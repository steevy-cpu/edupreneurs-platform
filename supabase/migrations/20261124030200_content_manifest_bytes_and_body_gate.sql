-- Content lane, follow-up to 20261124030100 (independent review, findings H2 and L5).
--
-- content.record_release_manifest is the first staff-callable path that moves a
-- pack release to 'ready'. The review found that it
--   (a) recorded a manifest hash and byte length ASSERTED by the caller,
--       unrelated to the manifest document it was shown;
--   (b) never looked at the lesson bodies, so a body with an unknown block
--       type or an asset reference in a non-contract shape was finalised, and
--       that asset reference was invisible to the attachment (rights) check;
--   (c) leaked raw constraint errors (23514, 22003) for negative or
--       overflowing byte counts (L5).
--
-- This migration replaces the function. The merged migration is not edited.
--
-- SIGNATURE CHANGE (deliberate, unavoidable for (a)):
--     before  content.record_release_manifest(uuid, jsonb, bytea, bigint)
--     now     content.record_release_manifest(uuid, bytea)
-- The second argument is now THE MANIFEST'S BYTES, exactly as stored
-- (canonical JSON). The function computes sha256 and the length from those
-- bytes and then parses the same bytes; no caller-asserted hash or size exists
-- any more. The old signature is dropped so that no trusting path remains.
-- No API route calls either signature; callers are this lane's tests only.
--
-- What the database still cannot do (unchanged, documented in the lane doc):
-- it cannot read object storage, so it cannot re-hash lesson objects, and it
-- does not run the full Python validators (text rules, limits, the math
-- grammar, table budgets). The body gate below closes the STRUCTURAL hole -
-- unknown block types, unknown properties, mis-shaped asset references - so
-- that every asset reference is seen by the rights gate.

-- ----------------------------------------------------------------------------
-- Can this lesson body be fully accounted for by the content contract?
--   * a non-empty array of objects;
--   * every block 'type' is one of the nine known types;
--   * a block has no property its type does not define (mirrors
--     additionalProperties:false of lesson-blocks.schema.json / .v2.schema.json);
--   * 'asset' appears only on math / image / audio blocks (that follows from the
--     property lists), is mandatory on image and audio, and is always an object
--     whose 'sha256' is a string of 64 lower-case hex digits.
-- It does NOT validate texts, limits or semantics (the builder does).
-- ----------------------------------------------------------------------------
CREATE FUNCTION content.blocks_accountable(p_blocks jsonb)
RETURNS boolean
LANGUAGE sql IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT CASE
        WHEN p_blocks IS NULL OR jsonb_typeof(p_blocks) <> 'array' OR jsonb_array_length(p_blocks) = 0 THEN false
        ELSE NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_blocks) AS b(block)
            WHERE CASE
                WHEN jsonb_typeof(b.block) <> 'object' THEN true
                WHEN jsonb_typeof(b.block -> 'type') IS DISTINCT FROM 'string' THEN true
                WHEN NOT (
                    ARRAY(SELECT jsonb_object_keys(b.block)) <@ (CASE b.block ->> 'type'
                        WHEN 'heading' THEN ARRAY['key', 'type', 'text']
                        WHEN 'paragraph' THEN ARRAY['key', 'type', 'text']
                        WHEN 'example' THEN ARRAY['key', 'type', 'title', 'steps']
                        WHEN 'callout' THEN ARRAY['key', 'type', 'tone', 'text']
                        WHEN 'math' THEN ARRAY['key', 'type', 'notation', 'source', 'alt', 'asset']
                        WHEN 'image' THEN ARRAY['key', 'type', 'asset', 'alt', 'caption']
                        WHEN 'list' THEN ARRAY['key', 'type', 'style', 'items']
                        WHEN 'table' THEN ARRAY['key', 'type', 'caption', 'columns', 'rows', 'row_headers']
                        WHEN 'audio' THEN ARRAY['key', 'type', 'asset', 'duration_ms', 'title', 'transcript']
                        ELSE ARRAY[]::text[]  -- unknown type: nothing is allowed, 'type' itself included
                    END)
                ) THEN true
                WHEN (b.block ->> 'type') IN ('image', 'audio') AND NOT (b.block ? 'asset') THEN true
                WHEN (b.block ? 'asset') AND (
                        jsonb_typeof(b.block -> 'asset') IS DISTINCT FROM 'object'
                     OR jsonb_typeof(b.block #> '{asset,sha256}') IS DISTINCT FROM 'string'
                     OR (b.block #>> '{asset,sha256}') !~ '^[0-9a-f]{64}$') THEN true
                ELSE false
            END
        )
    END
$$;

DROP FUNCTION content.record_release_manifest(uuid, jsonb, bytea, bigint);

-- Record the REAL manifest of a release and move it 'building' -> 'ready', in
-- one transaction. p_manifest is the manifest's bytes as written by
-- scripts/build_pack.py (packs/<pack_key>/<locale>/<revision>/manifest.json).
CREATE FUNCTION content.record_release_manifest(
    p_release_id uuid,
    p_manifest bytea)
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
    v_doc jsonb;
    v_sha bytea;
    v_bytes bigint;
BEGIN
    v_actor := content.staff_gate('publisher', 'admin');
    -- The stored manifest is a canonical JSON object: it starts with '{' and
    -- ends with '}' (no byte-order mark, no trailing line break).
    IF p_release_id IS NULL OR p_manifest IS NULL
       OR octet_length(p_manifest) NOT BETWEEN 2 AND 1048576 THEN
        RAISE EXCEPTION 'Malformed manifest record' USING ERRCODE = '22023';
    END IF;
    IF get_byte(p_manifest, 0) <> 123
       OR get_byte(p_manifest, octet_length(p_manifest) - 1) <> 125 THEN
        RAISE EXCEPTION 'Malformed manifest record' USING ERRCODE = '22023';
    END IF;
    -- Hash and length are COMPUTED here from the very bytes that are parsed
    -- below; nothing the caller asserts about them is used.
    v_sha := sha256(p_manifest);
    v_bytes := octet_length(p_manifest);
    BEGIN
        v_doc := convert_from(p_manifest, 'UTF8')::jsonb;
    EXCEPTION WHEN OTHERS THEN
        -- invalid UTF-8, a NUL, text that is not JSON, nesting too deep, ...
        RAISE EXCEPTION 'Malformed manifest record' USING ERRCODE = '22023';
    END;
    IF v_doc IS NULL OR jsonb_typeof(v_doc) <> 'object' THEN
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
        IF v_doc ->> 'manifest_version' IS DISTINCT FROM 'pack-manifest-1'
           OR jsonb_typeof(v_doc -> 'lessons') IS DISTINCT FROM 'array'
           OR jsonb_typeof(v_doc -> 'assets') IS DISTINCT FROM 'array'
           OR jsonb_typeof(v_doc -> 'pack') IS DISTINCT FROM 'object'
           OR jsonb_typeof(v_doc -> 'totals') IS DISTINCT FROM 'object'
           OR jsonb_typeof(v_doc -> 'content_format') IS DISTINCT FROM 'number' THEN
            RAISE EXCEPTION 'Malformed manifest' USING ERRCODE = '22023';
        END IF;
        -- No property the contract does not know (pack-manifest.v1.schema.json).
        IF (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(v_doc) AS k) IS DISTINCT FROM
               ARRAY['assets', 'content_format', 'lessons', 'manifest_version', 'pack', 'totals']
           OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(v_doc -> 'pack') AS k) IS DISTINCT FROM
               ARRAY['locale', 'pack_key', 'release_id', 'revision']
           OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(v_doc -> 'totals') AS k) IS DISTINCT FROM
               ARRAY['assets', 'lesson_bytes', 'lessons', 'optional_asset_bytes', 'questions', 'required_asset_bytes']
           OR EXISTS (SELECT 1 FROM jsonb_each(v_doc -> 'totals') AS t(name, value)
                      WHERE jsonb_typeof(t.value) <> 'number')
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(v_doc -> 'lessons') AS l(item)
                      WHERE jsonb_typeof(l.item) <> 'object'
                         OR jsonb_typeof(l.item -> 'bytes') IS DISTINCT FROM 'number')
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(v_doc -> 'assets') AS a(item)
                      WHERE jsonb_typeof(a.item) <> 'object'
                         OR jsonb_typeof(a.item -> 'bytes') IS DISTINCT FROM 'number') THEN
            RAISE EXCEPTION 'Malformed manifest' USING ERRCODE = '22023';
        END IF;
        v_format := (v_doc ->> 'content_format')::smallint;
        v_lesson_bytes := (v_doc #>> '{totals,lesson_bytes}')::bigint;
        v_required_bytes := (v_doc #>> '{totals,required_asset_bytes}')::bigint;
        v_optional_bytes := (v_doc #>> '{totals,optional_asset_bytes}')::bigint;
        v_lessons := (v_doc #>> '{totals,lessons}')::integer;
        v_questions := (v_doc #>> '{totals,questions}')::integer;
        v_assets := (v_doc #>> '{totals,assets}')::integer;
        -- Every count and size inside the contract's limits (500 lessons of at most
        -- 262 144 bytes, 2000 assets of at most 2 000 000 bytes): a negative, zero,
        -- fractional or overflowing value is a clean 22023, never a constraint error.
        IF v_format IS NULL
           OR v_lessons IS NULL OR v_lessons NOT BETWEEN 1 AND 500
           OR v_questions IS NULL OR v_questions NOT BETWEEN 0 AND 50000
           OR v_assets IS NULL OR v_assets NOT BETWEEN 0 AND 2000
           OR v_lesson_bytes IS NULL OR v_lesson_bytes NOT BETWEEN 1 AND 131072000
           OR v_required_bytes IS NULL OR v_required_bytes NOT BETWEEN 0 AND 4000000000
           OR v_optional_bytes IS NULL OR v_optional_bytes NOT BETWEEN 0 AND 4000000000
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(v_doc -> 'lessons') AS l(item)
                      WHERE (l.item ->> 'bytes')::bigint NOT BETWEEN 1 AND 262144)
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(v_doc -> 'assets') AS a(item)
                      WHERE (a.item ->> 'bytes')::bigint NOT BETWEEN 1 AND 2000000) THEN
            RAISE EXCEPTION 'Malformed manifest' USING ERRCODE = '22023';
        END IF;

        IF (v_doc #>> '{pack,release_id}')::uuid IS DISTINCT FROM v_release.id
           OR v_doc #>> '{pack,pack_key}' IS DISTINCT FROM v_release.pack_key
           OR v_doc #>> '{pack,locale}' IS DISTINCT FROM v_release.locale
           OR (v_doc #>> '{pack,revision}')::integer IS DISTINCT FROM v_release.revision THEN
            RAISE EXCEPTION 'Manifest describes a different pack release' USING ERRCODE = '22023';
        END IF;

        -- The ordered lesson list must be exactly the release's items.
        IF EXISTS (
            (SELECT (l.item ->> 'position')::integer, (l.item ->> 'revision_id')::uuid
               FROM jsonb_array_elements(v_doc -> 'lessons') AS l(item)
             EXCEPT
             SELECT pi.position, pi.lesson_revision_id
               FROM app.pack_items pi WHERE pi.pack_release_id = v_release.id)
            UNION ALL
            (SELECT pi.position, pi.lesson_revision_id
               FROM app.pack_items pi WHERE pi.pack_release_id = v_release.id
             EXCEPT
             SELECT (l.item ->> 'position')::integer, (l.item ->> 'revision_id')::uuid
               FROM jsonb_array_elements(v_doc -> 'lessons') AS l(item))
        ) OR jsonb_array_length(v_doc -> 'lessons') <>
             (SELECT count(*) FROM app.pack_items pi WHERE pi.pack_release_id = v_release.id) THEN
            RAISE EXCEPTION 'Manifest lessons do not match the items of the pack release'
                USING ERRCODE = '22023';
        END IF;

        -- THE BODY GATE. This function is what makes a release 'ready', so it
        -- refuses every lesson body it cannot fully account for: a block type
        -- outside the nine known ones, a property the block type does not have
        -- (a remote 'src', ...), or an asset reference that is not an object
        -- with a 64-hex sha256. Without this, such a body would not be seen by
        -- the attachment (rights) check just below.
        IF EXISTS (
            SELECT 1
            FROM app.pack_items pi
            JOIN app.lesson_revisions lr ON lr.id = pi.lesson_revision_id
            WHERE pi.pack_release_id = v_release.id
              AND NOT content.blocks_accountable(lr.blocks)
        ) THEN
            RAISE EXCEPTION 'A packed lesson body has a block or an asset reference outside the content contract'
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
               FROM jsonb_array_elements(v_doc -> 'assets') AS a(item)
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
               FROM jsonb_array_elements(v_doc -> 'assets') AS a(item))
        ) THEN
            RAISE EXCEPTION 'Manifest assets do not match the assets recorded for this pack'
                USING ERRCODE = '22023';
        END IF;

        IF v_assets IS DISTINCT FROM jsonb_array_length(v_doc -> 'assets')
           OR v_lessons IS DISTINCT FROM jsonb_array_length(v_doc -> 'lessons')
           OR v_required_bytes IS DISTINCT FROM (
               SELECT COALESCE(sum((a.item ->> 'bytes')::bigint), 0)
               FROM jsonb_array_elements(v_doc -> 'assets') AS a(item)
               WHERE (a.item ->> 'required')::boolean)
           OR v_optional_bytes IS DISTINCT FROM (
               SELECT COALESCE(sum((a.item ->> 'bytes')::bigint), 0)
               FROM jsonb_array_elements(v_doc -> 'assets') AS a(item)
               WHERE NOT (a.item ->> 'required')::boolean)
           OR v_lesson_bytes IS DISTINCT FROM (
               SELECT COALESCE(sum((l.item ->> 'bytes')::bigint), 0)
               FROM jsonb_array_elements(v_doc -> 'lessons') AS l(item))
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

    v_total := v_bytes + v_lesson_bytes + v_required_bytes + v_optional_bytes;
    v_key := 'packs/' || v_release.pack_key || '/' || v_release.locale || '/'
             || v_release.revision || '/manifest.json';

    -- app.protect_finalized_pack_release still applies (non-empty, rights cleared).
    UPDATE app.pack_releases
       SET status = 'ready', manifest_object_key = v_key,
           manifest_sha256 = v_sha, compressed_bytes = v_total
     WHERE id = v_release.id;

    INSERT INTO content.pack_manifests (
        pack_release_id, manifest_version, content_format, manifest_sha256, manifest_bytes,
        lesson_count, question_count, asset_count, lesson_bytes, required_asset_bytes,
        optional_asset_bytes, recorded_by)
    VALUES (
        v_release.id, 'pack-manifest-1', v_format, v_sha, v_bytes,
        v_lessons, v_questions, v_assets, v_lesson_bytes, v_required_bytes,
        v_optional_bytes, v_actor);

    PERFORM content.audit('content.pack.manifest_recorded', 'pack_release', v_release.id,
        jsonb_build_object(
            'manifest_sha256', encode(v_sha, 'hex'),
            'content_format', v_format,
            'total_bytes', v_total));
    RETURN jsonb_build_object(
        'release_id', v_release.id, 'status', 'ready', 'manifest_object_key', v_key,
        'manifest_sha256', encode(v_sha, 'hex'), 'content_format', v_format,
        'total_bytes', v_total);
END;
$$;

ALTER FUNCTION content.blocks_accountable(jsonb) OWNER TO postgres;
ALTER FUNCTION content.record_release_manifest(uuid, bytea) OWNER TO postgres;

-- Same privileges as before: nothing for PUBLIC or the Data API roles; the staff
-- API role may execute the four staff write functions and nothing else.
REVOKE ALL ON FUNCTION content.blocks_accountable(jsonb) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION content.record_release_manifest(uuid, bytea) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION content.record_release_manifest(uuid, bytea) TO edu_staff;
