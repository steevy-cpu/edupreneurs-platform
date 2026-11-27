-- Fixes from the independent review of B2 (staff-b2-review, findings M-B2-1 and L-B2-2).
--
-- M-B2-1: `staff.require_author` let any active admin through. An admin could
-- replace the content of somebody else's draft while `created_by` stayed the
-- original editor, and then pass "reviewer is not the author" on words nobody
-- else had read. From now on ONLY the author changes a draft, attaches or
-- detaches its sources, or submits it. An admin who wants different content
-- writes a new revision and is then its author (and cannot review it).
--
-- L-B2-2: `staff.build_pack` refused the same revision twice but accepted two
-- revisions of the same lesson, which left it unclear what learners receive.
--
-- CREATE OR REPLACE keeps the owner (postgres) and the existing grants; the
-- signatures, SECURITY DEFINER / search_path settings and audit events are
-- unchanged.

-- Internal helper (not SECURITY DEFINER, EXECUTE granted to nobody), called by
-- update_revision, attach_source, detach_source and submit_revision.
CREATE OR REPLACE FUNCTION staff.require_author(p_revision app.lesson_revisions, p_actor uuid)
RETURNS void
LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF p_actor IS NULL OR p_revision.created_by IS DISTINCT FROM p_actor THEN
        RAISE EXCEPTION 'not_the_author' USING ERRCODE = '42501';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION staff.build_pack(p_pack_key text, p_locale text, p_revision_ids uuid[])
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'publisher', 'admin');
    v_revision integer;
    v_id uuid;
    v_manifest text;
    v_count integer := COALESCE(cardinality(p_revision_ids), 0);
BEGIN
    IF p_pack_key IS NULL OR p_pack_key !~ '^[a-z0-9_-]{3,100}$' THEN
        RAISE EXCEPTION 'pack_key_invalid' USING ERRCODE = 'ED422';
    END IF;
    IF p_locale IS NULL OR p_locale NOT IN ('fr', 'ht') THEN
        RAISE EXCEPTION 'locale_invalid' USING ERRCODE = 'ED422';
    END IF;
    IF v_count = 0 OR v_count > 500 OR array_position(p_revision_ids, NULL) IS NOT NULL THEN
        RAISE EXCEPTION 'pack_items_invalid' USING ERRCODE = 'ED422';
    END IF;
    IF (SELECT count(DISTINCT u.id) FROM unnest(p_revision_ids) AS u(id)) <> v_count THEN
        RAISE EXCEPTION 'pack_items_duplicated' USING ERRCODE = 'ED422';
    END IF;
    IF EXISTS (SELECT 1 FROM unnest(p_revision_ids) AS u(id)
               WHERE NOT EXISTS (SELECT 1 FROM app.lesson_revisions r WHERE r.id = u.id)) THEN
        RAISE EXCEPTION 'revision_not_found' USING ERRCODE = 'ED404';
    END IF;
    -- One lesson appears once in a pack. A pack has a single locale (the item
    -- trigger refuses revisions in another language), so this is "one revision
    -- per lesson and locale". lesson_id of a revision never changes.
    IF EXISTS (SELECT 1 FROM unnest(p_revision_ids) AS u(id)
               JOIN app.lesson_revisions r ON r.id = u.id
               GROUP BY r.lesson_id HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'pack_lesson_duplicated' USING ERRCODE = 'ED422';
    END IF;

    PERFORM staff.lock_pack(p_pack_key, p_locale);
    SELECT COALESCE(max(p.revision), 0) + 1 INTO v_revision
    FROM app.pack_releases p WHERE p.pack_key = p_pack_key AND p.locale = p_locale;
    INSERT INTO app.pack_releases (pack_key, revision, locale, created_by)
    VALUES (p_pack_key, v_revision, p_locale, v_actor)
    RETURNING id INTO v_id;
    INSERT INTO app.pack_items (pack_release_id, lesson_revision_id, position)
    SELECT v_id, u.id, u.n::integer FROM unnest(p_revision_ids) WITH ORDINALITY AS u(id, n) ORDER BY u.n;

    SELECT jsonb_build_object(
               'pack_key', p_pack_key, 'locale', p_locale, 'revision', v_revision,
               'items', jsonb_agg(u.id ORDER BY u.n))::text
    INTO v_manifest
    FROM unnest(p_revision_ids) WITH ORDINALITY AS u(id, n);
    UPDATE app.pack_releases
    SET status = 'ready',
        manifest_object_key = format('packs/%s/%s/%s/manifest.json', p_pack_key, p_locale, v_revision),
        manifest_sha256 = sha256(convert_to(v_manifest, 'UTF8')),
        compressed_bytes = octet_length(convert_to(v_manifest, 'UTF8'))
    WHERE id = v_id;

    PERFORM ops.audit_write('pack_release.build', 'pack_release', v_id, 'allowed',
        jsonb_build_object('locale', p_locale, 'revision', v_revision, 'items', v_count));
    RETURN v_id;
END;
$$;

-- Same closing statement as the earlier staff migrations: nothing in `staff`
-- is callable by PUBLIC, anon or authenticated. Grants to edu_staff are kept.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA staff FROM PUBLIC, anon, authenticated;
