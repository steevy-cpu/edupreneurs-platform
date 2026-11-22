-- Mon Edupreneur 2.0 — integrity guards (triggers)
--
-- Derived from the trigger section of the v0.2 draft 0001_core_schema.sql.
-- Deviations are tagged "[v0.2 change Cnn]" and explained in
-- docs/SCHEMA_CHANGELOG.md.
--
-- WHY TRIGGERS: these rules must hold no matter which future service writes
-- the tables (staff API, pack worker, a person in a SQL console). They are the
-- database's last line of defence, not a substitute for API authorization.
--
-- WHY SECURITY DEFINER: a guard has to see every relevant row. If it ran with
-- the caller's privileges, row-level security could hide a review or a pack
-- item from it and the guard would wrongly pass. Each definer function has an
-- empty search_path and fully qualified names so it cannot be tricked into
-- calling look-alike objects, and none of them is callable directly (EXECUTE is
-- revoked from everyone at the end of this file; triggers still fire).
--
-- CONCURRENCY: guards that check "no review exists yet" take a row lock on the
-- parent lesson revision first. Without it, two transactions could each pass
-- their check and then both commit (a write-skew race). [v0.2 change C08]

-- ----------------------------------------------------------------------------
-- Lesson revisions
-- ----------------------------------------------------------------------------
-- [v0.2 change C02] The draft only guarded UPDATE/DELETE, so a row could be
-- INSERTed already 'approved' with no review at all. New rows must be drafts.
CREATE FUNCTION app.guard_lesson_revision_insert()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF NEW.status <> 'draft' OR NEW.approved_by IS NOT NULL OR NEW.approved_at IS NOT NULL THEN
        RAISE EXCEPTION 'Lesson revisions must be created as unapproved drafts';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_lesson_revision_insert
BEFORE INSERT ON app.lesson_revisions
FOR EACH ROW EXECUTE FUNCTION app.guard_lesson_revision_insert();

CREATE FUNCTION app.protect_approved_lesson_revision()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_latest_verdict text;
    v_latest_reviewer uuid;
    v_has_cleared_source boolean;
    v_has_uncleared_source boolean;
BEGIN
    IF OLD.status = 'approved' OR EXISTS (
        SELECT 1 FROM app.pack_items WHERE lesson_revision_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'Approved/packed lesson revisions are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    -- [v0.2 change C05] Authorship is fixed at creation. Otherwise an author
    -- could reassign the draft to someone else and then "independently" review it.
    IF NEW.id IS DISTINCT FROM OLD.id OR
       NEW.created_by IS DISTINCT FROM OLD.created_by OR
       NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'Lesson revision identity and authorship cannot be changed';
    END IF;

    -- A submitted review freezes the exact content snapshot that was reviewed.
    -- Corrections need a new revision and a fresh review.
    IF EXISTS (SELECT 1 FROM app.editorial_reviews WHERE lesson_revision_id = OLD.id) AND (
        NEW.blocks IS DISTINCT FROM OLD.blocks OR NEW.title IS DISTINCT FROM OLD.title OR
        NEW.locale IS DISTINCT FROM OLD.locale OR NEW.revision IS DISTINCT FROM OLD.revision OR
        NEW.lesson_id IS DISTINCT FROM OLD.lesson_id
    ) THEN
        RAISE EXCEPTION 'Reviewed content cannot be modified; create a new revision';
    END IF;

    IF NEW.status = 'approved' THEN
        -- The LATEST review decides. [v0.2 change C06] The draft joined
        -- staff_roles into this query; a reviewer holding two roles produced two
        -- rows and LIMIT 1 could pick an inactive one. Role is now a separate EXISTS.
        SELECT r.verdict, r.reviewer_id INTO v_latest_verdict, v_latest_reviewer
        FROM app.editorial_reviews r
        WHERE r.lesson_revision_id = OLD.id
        ORDER BY r.reviewed_at DESC, r.id DESC
        LIMIT 1;

        IF v_latest_verdict IS DISTINCT FROM 'approved'
           OR v_latest_reviewer IS DISTINCT FROM NEW.approved_by
           OR v_latest_reviewer = OLD.created_by
           OR NOT EXISTS (
               SELECT 1 FROM app.staff_roles sr
               WHERE sr.user_id = v_latest_reviewer AND sr.is_active
                 AND sr.role IN ('reviewer','admin')
           ) THEN
            RAISE EXCEPTION 'Approval requires the latest review to be an approval by an active, independent reviewer';
        END IF;

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
        IF NOT v_has_cleared_source OR v_has_uncleared_source THEN
            RAISE EXCEPTION 'Approval requires at least one source and all sources rights-cleared';
        END IF;

        -- [v0.2 change C07] The approval time is the server's, not the caller's.
        NEW.approved_at := now();
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_approved_lesson_revision
BEFORE UPDATE OR DELETE ON app.lesson_revisions
FOR EACH ROW EXECUTE FUNCTION app.protect_approved_lesson_revision();

-- ----------------------------------------------------------------------------
-- Questions inside a lesson revision
-- ----------------------------------------------------------------------------
CREATE FUNCTION app.protect_question_revision()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_parent_id uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.lesson_revision_id <> OLD.lesson_revision_id THEN
        RAISE EXCEPTION 'Question cannot move to another lesson revision';
    END IF;
    v_parent_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.lesson_revision_id
                        ELSE NEW.lesson_revision_id END;
    -- Serialise against a concurrent review/approval of the parent. [C08]
    PERFORM 1 FROM app.lesson_revisions WHERE id = v_parent_id FOR SHARE;
    IF EXISTS (SELECT 1 FROM app.lesson_revisions
               WHERE id = v_parent_id AND status = 'approved') OR
       EXISTS (SELECT 1 FROM app.pack_items WHERE lesson_revision_id = v_parent_id) OR
       EXISTS (SELECT 1 FROM app.editorial_reviews WHERE lesson_revision_id = v_parent_id)
    THEN
        RAISE EXCEPTION 'Questions in reviewed/approved/packed lessons are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_question_revision
BEFORE INSERT OR UPDATE OR DELETE ON app.question_revisions
FOR EACH ROW EXECUTE FUNCTION app.protect_question_revision();

-- ----------------------------------------------------------------------------
-- Source attribution
-- ----------------------------------------------------------------------------
-- Freeze the list of sources once a human has reviewed a revision.
CREATE FUNCTION app.protect_reviewed_source_links()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_old uuid; v_new uuid;
BEGIN
    IF TG_OP IN ('UPDATE','DELETE') THEN v_old := OLD.lesson_revision_id; END IF;
    IF TG_OP IN ('UPDATE','INSERT') THEN v_new := NEW.lesson_revision_id; END IF;
    -- Serialise against a concurrent review/approval of the parent(s). [C08]
    PERFORM 1 FROM app.lesson_revisions lr
     WHERE lr.id IN (v_old, v_new) ORDER BY lr.id FOR SHARE;
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

-- A source's licensing status may change later (rights can be withdrawn), but
-- the identity of a source that reviewed material cites cannot be rewritten.
CREATE FUNCTION app.protect_used_source_details()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF TG_OP = 'DELETE' AND EXISTS (
       SELECT 1 FROM app.lesson_revision_sources WHERE source_id = OLD.id
    ) THEN RAISE EXCEPTION 'Referenced sources cannot be deleted'; END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.id IS DISTINCT FROM OLD.id OR
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

-- ----------------------------------------------------------------------------
-- Editorial reviews
-- ----------------------------------------------------------------------------
CREATE FUNCTION app.validate_editorial_review()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_created_by uuid; v_status text;
BEGIN
    -- Locks the revision so reviews, content edits and approval are serialised.
    SELECT created_by, status INTO v_created_by, v_status
    FROM app.lesson_revisions WHERE id = NEW.lesson_revision_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Lesson revision does not exist';
    END IF;
    IF v_status = 'approved' OR EXISTS (
      SELECT 1 FROM app.pack_items WHERE lesson_revision_id = NEW.lesson_revision_id
    ) THEN RAISE EXCEPTION 'Cannot review a finalized lesson revision'; END IF;
    IF v_created_by = NEW.reviewer_id THEN
        RAISE EXCEPTION 'Author cannot review own lesson';
    END IF;
    IF NOT EXISTS (
       SELECT 1 FROM app.staff_roles sr
       WHERE sr.user_id = NEW.reviewer_id AND sr.is_active
         AND sr.role IN ('reviewer','admin')
    ) THEN RAISE EXCEPTION 'Reviewer role required'; END IF;
    -- [v0.2 change C07] Approval looks at the LATEST review, so the review time
    -- must be the server's clock. A caller-supplied time could be future-dated
    -- to keep an old approval "latest" after a later rejection.
    NEW.reviewed_at := clock_timestamp();
    RETURN NEW;
END;
$$;
CREATE TRIGGER validate_editorial_review
BEFORE INSERT ON app.editorial_reviews
FOR EACH ROW EXECUTE FUNCTION app.validate_editorial_review();

-- ----------------------------------------------------------------------------
-- Pack releases, items and the "current" pointer
-- ----------------------------------------------------------------------------
-- [v0.2 change C03] As with lesson revisions, a release could be INSERTed
-- directly as 'active', skipping the empty-pack and rights checks below.
CREATE FUNCTION app.guard_pack_release_insert()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF NEW.status <> 'building' OR NEW.released_at IS NOT NULL THEN
        RAISE EXCEPTION 'Pack releases must be created in building state';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_pack_release_insert
BEFORE INSERT ON app.pack_releases
FOR EACH ROW EXECUTE FUNCTION app.guard_pack_release_insert();

CREATE FUNCTION app.validate_pack_item()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_status text; v_locale text; v_revision_status text; v_revision_locale text;
BEGIN
    -- [v0.2 change C04] On UPDATE the draft only checked the NEW release, so an
    -- item could be moved OUT of a finalized pack into a building one.
    IF TG_OP = 'UPDATE' AND (
        NEW.pack_release_id IS DISTINCT FROM OLD.pack_release_id OR
        NEW.lesson_revision_id IS DISTINCT FROM OLD.lesson_revision_id
    ) THEN
        RAISE EXCEPTION 'Pack items cannot be moved; delete and re-add while the pack is building';
    END IF;
    SELECT status, locale INTO v_status, v_locale
      FROM app.pack_releases WHERE id = NEW.pack_release_id FOR UPDATE;
    IF v_status IS DISTINCT FROM 'building' THEN
        RAISE EXCEPTION 'Cannot modify items of a finalized pack';
    END IF;
    SELECT status, locale INTO v_revision_status, v_revision_locale
      FROM app.lesson_revisions WHERE id = NEW.lesson_revision_id;
    IF v_revision_status IS DISTINCT FROM 'approved' OR v_revision_locale IS DISTINCT FROM v_locale THEN
        RAISE EXCEPTION 'Pack items must be approved and match pack locale';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER validate_pack_item
BEFORE INSERT OR UPDATE ON app.pack_items
FOR EACH ROW EXECUTE FUNCTION app.validate_pack_item();

CREATE FUNCTION app.protect_pack_item_delete()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF (SELECT status FROM app.pack_releases WHERE id = OLD.pack_release_id FOR UPDATE)
        IS DISTINCT FROM 'building' THEN
        RAISE EXCEPTION 'Cannot remove finalized pack items';
    END IF;
    RETURN OLD;
END;
$$;
CREATE TRIGGER protect_pack_item_delete
BEFORE DELETE ON app.pack_items
FOR EACH ROW EXECUTE FUNCTION app.protect_pack_item_delete();

CREATE FUNCTION app.protect_finalized_pack_release()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'building' THEN
            RAISE EXCEPTION 'Finalized packs must be retained or revoked';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id THEN
        RAISE EXCEPTION 'Pack release identity cannot be changed';
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
    -- [v0.2 change C07] The first activation time is stamped by the server.
    IF NEW.status = 'active' AND OLD.released_at IS NULL THEN
        NEW.released_at := now();
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_finalized_pack_release
BEFORE UPDATE OR DELETE ON app.pack_releases
FOR EACH ROW EXECUTE FUNCTION app.protect_finalized_pack_release();

CREATE FUNCTION app.validate_pack_current()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    -- [v0.2 change C08] FOR SHARE blocks a concurrent retire/revoke of this
    -- release until we commit, so the pointer can never end up on a dead pack.
    IF NOT EXISTS (
        SELECT 1 FROM app.pack_releases r
        WHERE r.id = NEW.release_id AND r.pack_key = NEW.pack_key
          AND r.locale = NEW.locale AND r.status = 'active'
        FOR SHARE
    ) THEN RAISE EXCEPTION 'Current pointer requires matching active pack'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER validate_pack_current
BEFORE INSERT OR UPDATE ON app.pack_current
FOR EACH ROW EXECUTE FUNCTION app.validate_pack_current();

-- ----------------------------------------------------------------------------
-- Append-only history
-- ----------------------------------------------------------------------------
CREATE FUNCTION app.prevent_append_only_change()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
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

-- Trigger functions are invoked by the trigger machinery, never called by hand.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC, anon, authenticated;
