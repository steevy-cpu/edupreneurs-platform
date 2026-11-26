-- Content lane, final-verification finding NF-2: content.attach_asset and
-- content.detach_asset checked the staff role only, so another editor or an admin
-- could change the asset list of someone else's draft revision (same class as
-- M-B2-1 for lesson drafts on the staff branch).
--
-- Rule: only the revision's author (app.lesson_revisions.created_by =
-- app.current_actor_id()) attaches or detaches assets, admins included; anyone
-- else gets SQLSTATE 42501. An unknown revision is now refused (22023) by detach
-- as well, as attach already did. CREATE OR REPLACE keeps owner and grants
-- (EXECUTE to edu_staff only); they are restated below.

CREATE OR REPLACE FUNCTION content.attach_asset(p_revision_id uuid, p_sha256 bytea)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid;
    v_source uuid;
    v_author uuid;
BEGIN
    v_actor := content.staff_gate('editor', 'admin');
    IF p_revision_id IS NULL OR p_sha256 IS NULL OR octet_length(p_sha256) <> 32 THEN
        RAISE EXCEPTION 'Malformed asset attachment' USING ERRCODE = '22023';
    END IF;
    SELECT a.source_id INTO v_source FROM content.assets a WHERE a.sha256 = p_sha256;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown asset' USING ERRCODE = '22023';
    END IF;
    SELECT lr.created_by INTO v_author FROM app.lesson_revisions lr WHERE lr.id = p_revision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown lesson revision' USING ERRCODE = '22023';
    END IF;
    -- Only the author of a draft changes it, admins included (as for lesson drafts).
    IF v_author IS DISTINCT FROM v_actor THEN
        RAISE EXCEPTION 'Only the author of a lesson revision changes its assets'
            USING ERRCODE = '42501';
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

CREATE OR REPLACE FUNCTION content.detach_asset(p_revision_id uuid, p_sha256 bytea)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid;
    v_removed integer;
    v_author uuid;
BEGIN
    v_actor := content.staff_gate('editor', 'admin');
    IF p_revision_id IS NULL OR p_sha256 IS NULL OR octet_length(p_sha256) <> 32 THEN
        RAISE EXCEPTION 'Malformed asset attachment' USING ERRCODE = '22023';
    END IF;
    SELECT lr.created_by INTO v_author FROM app.lesson_revisions lr WHERE lr.id = p_revision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown lesson revision' USING ERRCODE = '22023';
    END IF;
    IF v_author IS DISTINCT FROM v_actor THEN
        RAISE EXCEPTION 'Only the author of a lesson revision changes its assets'
            USING ERRCODE = '42501';
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

ALTER FUNCTION content.attach_asset(uuid, bytea) OWNER TO postgres;
ALTER FUNCTION content.detach_asset(uuid, bytea) OWNER TO postgres;
REVOKE ALL ON FUNCTION content.attach_asset(uuid, bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION content.detach_asset(uuid, bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION content.attach_asset(uuid, bytea) TO edu_staff;
GRANT EXECUTE ON FUNCTION content.detach_asset(uuid, bytea) TO edu_staff;
