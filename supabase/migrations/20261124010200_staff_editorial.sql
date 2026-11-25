-- Mon Edupreneur 2.0 — editorial workflow for the staff API (schema `staff`).
--
-- Every write to the existing content tables goes through one of the
-- SECURITY DEFINER functions below. Each of them
--   1. starts with staff.require_role(...) (actor = app.current_actor_id()),
--   2. validates and bounds its inputs,
--   3. writes with schema-qualified SQL, and
--   4. records one audit event through ops.audit_write.
--
-- THE EXISTING TRIGGERS IN `app` REMAIN THE ENFORCEMENT OF RECORD for the
-- editorial rules (drafts only on insert, reviewer is not the author, reviewed
-- and approved content is immutable, rights-cleared sources, pack lifecycle).
-- These functions deliberately do NOT re-implement those rules: when a rule is
-- broken the trigger raises (SQLSTATE P0001) and the API turns the trigger's
-- message into a 409. The functions only add what no trigger knows: who may
-- act (roles, authorship) and which step comes next in the workflow.
--
-- ERRORS raised here use SQLSTATE class 'ED' with a machine code as message:
--   ED404  the named object does not exist            -> HTTP 404
--   ED409  not possible in the current state          -> HTTP 409
--   ED422  the input is not acceptable                -> HTTP 422
--   42501  not allowed for this actor                 -> HTTP 403
--
-- Nothing in schema `app` is created, altered or granted here.

-- ----------------------------------------------------------------------------
-- Internal helpers (EXECUTE granted to nobody)
-- ----------------------------------------------------------------------------
-- Inserts the questions of one revision. Shape is validated by the API against
-- packages/contracts/content/question-mcq.schema.json; the checks here are the
-- database's own floor: bounded size, supported kind, a correct choice that is
-- one of the offered choices.
CREATE FUNCTION staff.insert_questions(p_revision_id uuid, p_questions jsonb)
RETURNS integer
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_question jsonb;
    v_position integer := 0;
BEGIN
    IF p_questions IS NULL OR jsonb_typeof(p_questions) <> 'array' THEN
        RAISE EXCEPTION 'questions_invalid' USING ERRCODE = 'ED422';
    END IF;
    IF jsonb_array_length(p_questions) > 50 OR octet_length(p_questions::text) > 131072 THEN
        RAISE EXCEPTION 'questions_too_large' USING ERRCODE = 'ED422';
    END IF;
    FOR v_question IN SELECT e.value FROM jsonb_array_elements(p_questions) WITH ORDINALITY AS e(value, n) ORDER BY e.n LOOP
        v_position := v_position + 1;
        IF jsonb_typeof(v_question) <> 'object' THEN
            RAISE EXCEPTION 'questions_invalid' USING ERRCODE = 'ED422';
        END IF;
        IF (v_question ->> 'kind') IS DISTINCT FROM 'mcq' THEN
            RAISE EXCEPTION 'question_kind_unsupported' USING ERRCODE = 'ED422';
        END IF;
        IF COALESCE(jsonb_typeof(v_question #> '{response_spec,choices}'), '') <> 'array'
           OR (v_question #>> '{answer_key,correct_choice_id}') IS NULL
           OR NOT EXISTS (
               SELECT 1 FROM jsonb_array_elements(v_question #> '{response_spec,choices}') AS c
               WHERE c.value ->> 'id' = v_question #>> '{answer_key,correct_choice_id}'
           ) THEN
            RAISE EXCEPTION 'question_correct_choice_missing' USING ERRCODE = 'ED422';
        END IF;
        INSERT INTO app.question_revisions
            (lesson_revision_id, question_key, position, kind, prompt, response_spec, answer_key, explanation)
        VALUES (p_revision_id, v_question ->> 'question_key', v_position, 'mcq',
                v_question -> 'prompt', v_question -> 'response_spec',
                v_question -> 'answer_key', v_question -> 'explanation');
    END LOOP;
    RETURN v_position;
END;
$$;

CREATE FUNCTION staff.check_revision_content(p_title text, p_blocks jsonb)
RETURNS void
LANGUAGE plpgsql IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF p_title IS NULL OR char_length(p_title) NOT BETWEEN 1 AND 200 THEN
        RAISE EXCEPTION 'title_invalid' USING ERRCODE = 'ED422';
    END IF;
    IF p_blocks IS NULL OR jsonb_typeof(p_blocks) <> 'array'
       OR jsonb_array_length(p_blocks) NOT BETWEEN 1 AND 200 THEN
        RAISE EXCEPTION 'blocks_invalid' USING ERRCODE = 'ED422';
    END IF;
    IF octet_length(p_blocks::text) > 262144 THEN
        RAISE EXCEPTION 'blocks_too_large' USING ERRCODE = 'ED422';
    END IF;
END;
$$;

-- Locks a revision row and returns it; ED404 when it does not exist.
CREATE FUNCTION staff.lock_revision(p_revision_id uuid)
RETURNS app.lesson_revisions
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_row app.lesson_revisions;
BEGIN
    SELECT * INTO v_row FROM app.lesson_revisions r WHERE r.id = p_revision_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'revision_not_found' USING ERRCODE = 'ED404';
    END IF;
    RETURN v_row;
END;
$$;

-- Content of a revision may be changed by its author only (an admin may too).
-- This keeps "the reviewer is not the author" meaningful: nobody else's words
-- end up under the author's name.
CREATE FUNCTION staff.require_author(p_revision app.lesson_revisions, p_actor uuid)
RETURNS void
LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF p_revision.created_by IS DISTINCT FROM p_actor AND NOT EXISTS (
        SELECT 1 FROM app.staff_roles sr
        WHERE sr.user_id = p_actor AND sr.is_active AND sr.role = 'admin'
    ) THEN
        RAISE EXCEPTION 'not_the_author' USING ERRCODE = '42501';
    END IF;
END;
$$;

-- One writer at a time per (pack_key, locale): release numbering and the
-- current pointer are decided under this transaction-scoped advisory lock.
CREATE FUNCTION staff.lock_pack(p_pack_key text, p_locale text)
RETURNS void
LANGUAGE sql
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT pg_advisory_xact_lock(hashtextextended('staff.pack:' || p_pack_key || ':' || p_locale, 0))
$$;

CREATE FUNCTION staff.revision_json(p_revision_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT jsonb_build_object(
        'id', r.id, 'lesson_id', r.lesson_id, 'revision', r.revision, 'locale', r.locale,
        'title', r.title, 'status', r.status, 'blocks', r.blocks,
        'created_by', r.created_by, 'created_at', r.created_at,
        'approved_by', r.approved_by, 'approved_at', r.approved_at,
        'questions', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'id', q.id, 'question_key', q.question_key, 'position', q.position, 'kind', q.kind,
                'prompt', q.prompt, 'response_spec', q.response_spec,
                'answer_key', q.answer_key, 'explanation', q.explanation) ORDER BY q.position)
            FROM app.question_revisions q WHERE q.lesson_revision_id = r.id), '[]'::jsonb),
        'sources', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'id', s.id, 'source_title', s.source_title, 'source_uri', s.source_uri,
                'rights_status', s.rights_status) ORDER BY s.created_at, s.id)
            FROM app.lesson_revision_sources lrs
            JOIN app.content_sources s ON s.id = lrs.source_id
            WHERE lrs.lesson_revision_id = r.id), '[]'::jsonb),
        'reviews', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'id', v.id, 'reviewer_id', v.reviewer_id, 'verdict', v.verdict,
                'notes', v.notes, 'reviewed_at', v.reviewed_at) ORDER BY v.reviewed_at, v.id)
            FROM app.editorial_reviews v WHERE v.lesson_revision_id = r.id), '[]'::jsonb))
    FROM app.lesson_revisions r
    WHERE r.id = p_revision_id
$$;

CREATE FUNCTION staff.pack_release_json(p_release_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT jsonb_build_object(
        'id', p.id, 'pack_key', p.pack_key, 'locale', p.locale, 'revision', p.revision,
        'status', p.status, 'created_by', p.created_by, 'created_at', p.created_at,
        'released_at', p.released_at, 'manifest_sha256', encode(p.manifest_sha256, 'hex'),
        'is_current', EXISTS (SELECT 1 FROM app.pack_current pc WHERE pc.release_id = p.id),
        'items', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'position', i.position, 'lesson_revision_id', i.lesson_revision_id,
                'lesson_id', r.lesson_id, 'title', r.title) ORDER BY i.position)
            FROM app.pack_items i
            JOIN app.lesson_revisions r ON r.id = i.lesson_revision_id
            WHERE i.pack_release_id = p.id), '[]'::jsonb))
    FROM app.pack_releases p
    WHERE p.id = p_release_id
$$;

-- ----------------------------------------------------------------------------
-- Lessons and draft revisions
-- ----------------------------------------------------------------------------
-- A new, empty lesson at the end of an existing unit. It is invisible to
-- learners until one of its revisions is in a current pack.
CREATE FUNCTION staff.create_lesson(p_unit_id uuid, p_slug text)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'admin');
    v_position integer;
    v_id uuid;
BEGIN
    IF p_slug IS NULL OR p_slug !~ '^[a-z0-9-]{2,80}$' THEN
        RAISE EXCEPTION 'slug_invalid' USING ERRCODE = 'ED422';
    END IF;
    PERFORM 1 FROM app.units u WHERE u.id = p_unit_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unit_not_found' USING ERRCODE = 'ED404';
    END IF;
    IF EXISTS (SELECT 1 FROM app.lessons l WHERE l.unit_id = p_unit_id AND l.slug = p_slug) THEN
        RAISE EXCEPTION 'lesson_slug_taken' USING ERRCODE = 'ED409';
    END IF;
    SELECT COALESCE(max(l.position), 0) + 1 INTO v_position FROM app.lessons l WHERE l.unit_id = p_unit_id;
    INSERT INTO app.lessons (unit_id, slug, position) VALUES (p_unit_id, p_slug, v_position)
    RETURNING id INTO v_id;
    PERFORM ops.audit_write('lesson.create', 'lesson', v_id, 'allowed',
        jsonb_build_object('unit_id', p_unit_id, 'position', v_position));
    RETURN v_id;
END;
$$;

-- A new DRAFT revision (next revision number of that lesson and language),
-- authored by the actor.
CREATE FUNCTION staff.create_revision(
    p_lesson_id uuid, p_locale text, p_title text, p_blocks jsonb, p_questions jsonb
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'admin');
    v_revision integer;
    v_id uuid;
    v_questions integer;
BEGIN
    IF p_locale IS NULL OR p_locale NOT IN ('fr', 'ht') THEN
        RAISE EXCEPTION 'locale_invalid' USING ERRCODE = 'ED422';
    END IF;
    PERFORM staff.check_revision_content(p_title, p_blocks);
    PERFORM 1 FROM app.lessons l WHERE l.id = p_lesson_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'lesson_not_found' USING ERRCODE = 'ED404';
    END IF;
    SELECT COALESCE(max(r.revision), 0) + 1 INTO v_revision
    FROM app.lesson_revisions r WHERE r.lesson_id = p_lesson_id AND r.locale = p_locale;
    INSERT INTO app.lesson_revisions (lesson_id, revision, locale, title, blocks, created_by)
    VALUES (p_lesson_id, v_revision, p_locale, p_title, p_blocks, v_actor)
    RETURNING id INTO v_id;
    v_questions := staff.insert_questions(v_id, COALESCE(p_questions, '[]'::jsonb));
    PERFORM ops.audit_write('lesson_revision.create', 'lesson_revision', v_id, 'allowed',
        jsonb_build_object('lesson_id', p_lesson_id, 'locale', p_locale,
                           'revision', v_revision, 'questions', v_questions));
    RETURN v_id;
END;
$$;

-- Replace title, blocks and questions of a draft. Author (or admin) only.
-- Not while it is waiting in the review queue; reviewed/approved/packed
-- revisions are refused by the triggers.
CREATE FUNCTION staff.update_revision(
    p_revision_id uuid, p_title text, p_blocks jsonb, p_questions jsonb
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'admin');
    v_row app.lesson_revisions := staff.lock_revision(p_revision_id);
    v_questions integer;
BEGIN
    PERFORM staff.require_author(v_row, v_actor);
    PERFORM staff.check_revision_content(p_title, p_blocks);
    IF v_row.status = 'in_review' THEN
        RAISE EXCEPTION 'revision_in_review' USING ERRCODE = 'ED409';
    END IF;
    UPDATE app.lesson_revisions SET title = p_title, blocks = p_blocks WHERE id = p_revision_id;
    DELETE FROM app.question_revisions WHERE lesson_revision_id = p_revision_id;
    v_questions := staff.insert_questions(p_revision_id, COALESCE(p_questions, '[]'::jsonb));
    PERFORM ops.audit_write('lesson_revision.update', 'lesson_revision', p_revision_id, 'allowed',
        jsonb_build_object('questions', v_questions));
END;
$$;

-- ----------------------------------------------------------------------------
-- Sources (provenance and rights)
-- ----------------------------------------------------------------------------
-- A new source always starts 'unverified'.
CREATE FUNCTION staff.create_source(p_title text, p_uri text)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'admin');
    v_id uuid;
BEGIN
    IF p_title IS NULL OR char_length(p_title) NOT BETWEEN 1 AND 240 THEN
        RAISE EXCEPTION 'source_title_invalid' USING ERRCODE = 'ED422';
    END IF;
    IF p_uri IS NOT NULL AND (char_length(p_uri) > 2000 OR p_uri !~ '^https?://[^[:space:]]+$') THEN
        RAISE EXCEPTION 'source_uri_invalid' USING ERRCODE = 'ED422';
    END IF;
    INSERT INTO app.content_sources (source_title, source_uri) VALUES (p_title, p_uri)
    RETURNING id INTO v_id;
    PERFORM ops.audit_write('content_source.create', 'content_source', v_id, 'allowed');
    RETURN v_id;
END;
$$;

-- The rights decision on a source. Admin only: an author cannot clear the
-- rights of the material they want to publish.
CREATE FUNCTION staff.set_source_rights(p_source_id uuid, p_status text, p_notes text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('admin');
    v_previous text;
BEGIN
    IF p_status IS NULL OR p_status NOT IN ('unverified', 'cleared', 'restricted', 'blocked') THEN
        RAISE EXCEPTION 'rights_status_invalid' USING ERRCODE = 'ED422';
    END IF;
    IF p_notes IS NOT NULL AND char_length(p_notes) > 2000 THEN
        RAISE EXCEPTION 'rights_notes_too_long' USING ERRCODE = 'ED422';
    END IF;
    SELECT s.rights_status INTO v_previous FROM app.content_sources s WHERE s.id = p_source_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source_not_found' USING ERRCODE = 'ED404';
    END IF;
    UPDATE app.content_sources
    SET rights_status = p_status, rights_notes = p_notes, verified_at = now()
    WHERE id = p_source_id;
    PERFORM ops.audit_write('content_source.set_rights', 'content_source', p_source_id, 'allowed',
        jsonb_build_object('from_status', v_previous, 'to_status', p_status));
END;
$$;

CREATE FUNCTION staff.attach_source(p_revision_id uuid, p_source_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'admin');
    v_row app.lesson_revisions := staff.lock_revision(p_revision_id);
BEGIN
    PERFORM staff.require_author(v_row, v_actor);
    IF NOT EXISTS (SELECT 1 FROM app.content_sources s WHERE s.id = p_source_id) THEN
        RAISE EXCEPTION 'source_not_found' USING ERRCODE = 'ED404';
    END IF;
    IF v_row.status = 'in_review' THEN
        RAISE EXCEPTION 'revision_in_review' USING ERRCODE = 'ED409';
    END IF;
    INSERT INTO app.lesson_revision_sources (lesson_revision_id, source_id)
    VALUES (p_revision_id, p_source_id)
    ON CONFLICT DO NOTHING;
    PERFORM ops.audit_write('lesson_revision.attach_source', 'lesson_revision', p_revision_id, 'allowed',
        jsonb_build_object('source_id', p_source_id));
END;
$$;

CREATE FUNCTION staff.detach_source(p_revision_id uuid, p_source_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'admin');
    v_row app.lesson_revisions := staff.lock_revision(p_revision_id);
BEGIN
    PERFORM staff.require_author(v_row, v_actor);
    IF v_row.status = 'in_review' THEN
        RAISE EXCEPTION 'revision_in_review' USING ERRCODE = 'ED409';
    END IF;
    DELETE FROM app.lesson_revision_sources
    WHERE lesson_revision_id = p_revision_id AND source_id = p_source_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source_not_attached' USING ERRCODE = 'ED404';
    END IF;
    PERFORM ops.audit_write('lesson_revision.detach_source', 'lesson_revision', p_revision_id, 'allowed',
        jsonb_build_object('source_id', p_source_id));
END;
$$;

-- ----------------------------------------------------------------------------
-- Review
-- ----------------------------------------------------------------------------
-- draft -> in_review. Author (or admin) only.
CREATE FUNCTION staff.submit_revision(p_revision_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'admin');
    v_row app.lesson_revisions := staff.lock_revision(p_revision_id);
BEGIN
    PERFORM staff.require_author(v_row, v_actor);
    IF v_row.status <> 'draft' THEN
        RAISE EXCEPTION 'revision_not_draft' USING ERRCODE = 'ED409';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM app.lesson_revision_sources lrs WHERE lrs.lesson_revision_id = p_revision_id) THEN
        RAISE EXCEPTION 'revision_has_no_source' USING ERRCODE = 'ED409';
    END IF;
    UPDATE app.lesson_revisions SET status = 'in_review' WHERE id = p_revision_id;
    PERFORM ops.audit_write('lesson_revision.submit', 'lesson_revision', p_revision_id, 'allowed',
        jsonb_build_object('from_status', 'draft', 'to_status', 'in_review'));
END;
$$;

-- One review of a revision that is in the queue.
--   approved           -> the revision becomes 'approved' (approved_by = the reviewer)
--   rejected           -> 'rejected'
--   changes_requested  -> 'rejected' as well: a review freezes the content it
--                         looked at, so corrections need a NEW revision.
-- "The reviewer is not the author", "the reviewer holds an active reviewer or
-- admin role" and "all sources are rights-cleared" are enforced by the triggers
-- on app.editorial_reviews and app.lesson_revisions, not here.
CREATE FUNCTION staff.review_revision(p_revision_id uuid, p_verdict text, p_notes text)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('reviewer', 'admin');
    v_row app.lesson_revisions := staff.lock_revision(p_revision_id);
    v_review uuid;
    v_status text;
BEGIN
    IF p_verdict IS NULL OR p_verdict NOT IN ('approved', 'rejected', 'changes_requested') THEN
        RAISE EXCEPTION 'verdict_invalid' USING ERRCODE = 'ED422';
    END IF;
    IF p_notes IS NOT NULL AND char_length(p_notes) > 4000 THEN
        RAISE EXCEPTION 'review_notes_too_long' USING ERRCODE = 'ED422';
    END IF;
    IF v_row.status <> 'in_review' THEN
        RAISE EXCEPTION 'revision_not_in_review' USING ERRCODE = 'ED409';
    END IF;
    INSERT INTO app.editorial_reviews (lesson_revision_id, reviewer_id, verdict, notes)
    VALUES (p_revision_id, v_actor, p_verdict, p_notes)
    RETURNING id INTO v_review;
    IF p_verdict = 'approved' THEN
        v_status := 'approved';
        UPDATE app.lesson_revisions
        SET status = 'approved', approved_by = v_actor, approved_at = now()
        WHERE id = p_revision_id;
    ELSE
        v_status := 'rejected';
        UPDATE app.lesson_revisions SET status = 'rejected' WHERE id = p_revision_id;
    END IF;
    PERFORM ops.audit_write('lesson_revision.review', 'lesson_revision', p_revision_id, 'allowed',
        jsonb_build_object('verdict', p_verdict, 'from_status', 'in_review',
                           'to_status', v_status, 'review_id', v_review));
    RETURN v_review;
END;
$$;

-- ----------------------------------------------------------------------------
-- Reading (any active staff role)
-- ----------------------------------------------------------------------------
CREATE FUNCTION staff.get_revision(p_revision_id uuid)
RETURNS jsonb
LANGUAGE plpgsql STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'reviewer', 'publisher', 'admin');
    v_out jsonb := staff.revision_json(p_revision_id);
BEGIN
    IF v_out IS NULL THEN
        RAISE EXCEPTION 'revision_not_found' USING ERRCODE = 'ED404';
    END IF;
    RETURN v_out;
END;
$$;

-- Summaries, newest first. p_status NULL = every status; 'draft' = drafts,
-- 'in_review' = the review queue. p_mine = only revisions written by the actor.
CREATE FUNCTION staff.list_revisions(p_status text, p_mine boolean, p_limit integer)
RETURNS jsonb
LANGUAGE plpgsql STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'reviewer', 'publisher', 'admin');
    v_limit integer := LEAST(GREATEST(COALESCE(p_limit, 50), 1), 200);
BEGIN
    IF p_status IS NOT NULL AND p_status NOT IN ('draft', 'in_review', 'approved', 'rejected') THEN
        RAISE EXCEPTION 'status_invalid' USING ERRCODE = 'ED422';
    END IF;
    RETURN COALESCE((
        SELECT jsonb_agg(to_jsonb(x) ORDER BY x.created_at DESC, x.revision DESC, x.id)
        FROM (
            SELECT r.id, r.lesson_id, r.revision, r.locale, r.title, r.status,
                   r.created_by, r.created_at, r.approved_by, r.approved_at
            FROM app.lesson_revisions r
            WHERE (p_status IS NULL OR r.status = p_status)
              AND (NOT COALESCE(p_mine, false) OR r.created_by = v_actor)
            ORDER BY r.created_at DESC, r.revision DESC, r.id
            LIMIT v_limit
        ) AS x), '[]'::jsonb);
END;
$$;

CREATE FUNCTION staff.list_sources(p_limit integer)
RETURNS jsonb
LANGUAGE plpgsql STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'reviewer', 'publisher', 'admin');
    v_limit integer := LEAST(GREATEST(COALESCE(p_limit, 50), 1), 200);
BEGIN
    RETURN COALESCE((
        SELECT jsonb_agg(to_jsonb(x) ORDER BY x.created_at DESC, x.id)
        FROM (
            SELECT s.id, s.source_title, s.source_uri, s.rights_status, s.rights_notes,
                   s.verified_at, s.created_at
            FROM app.content_sources s
            ORDER BY s.created_at DESC, s.id
            LIMIT v_limit
        ) AS x), '[]'::jsonb);
END;
$$;

-- ----------------------------------------------------------------------------
-- Packs: build, release, roll back
-- ----------------------------------------------------------------------------
-- Builds the next release of (pack_key, locale) from approved revisions, in the
-- given order, and finalises it as 'ready'. The triggers refuse revisions that
-- are not approved or are in another language, empty packs and uncleared rights.
--
-- MANIFEST: no pack file is produced or stored tonight. The manifest columns
-- are filled with a deterministic description of the release's contents
-- (object key by convention, SHA-256 and byte length of the canonical item
-- list) so that a release is identifiable and its contents verifiable.
CREATE FUNCTION staff.build_pack(p_pack_key text, p_locale text, p_revision_ids uuid[])
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

-- Makes p_release_id the release learners get: activate it, move the current
-- pointer, retire the release it replaces — one transaction, one audit event.
-- Internal: shared by release_pack and rollback_pack. EXECUTE granted to nobody.
CREATE FUNCTION staff.switch_current_pack(p_release app.pack_releases, p_action text)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_previous uuid;
BEGIN
    SELECT pc.release_id INTO v_previous
    FROM app.pack_current pc
    WHERE pc.pack_key = p_release.pack_key AND pc.locale = p_release.locale;

    UPDATE app.pack_releases SET status = 'active' WHERE id = p_release.id;
    INSERT INTO app.pack_current (pack_key, locale, release_id)
    VALUES (p_release.pack_key, p_release.locale, p_release.id)
    ON CONFLICT (pack_key, locale)
    DO UPDATE SET release_id = EXCLUDED.release_id, switched_at = now();
    IF v_previous IS NOT NULL AND v_previous <> p_release.id THEN
        UPDATE app.pack_releases SET status = 'retired' WHERE id = v_previous;
    END IF;

    PERFORM ops.audit_write(p_action, 'pack_release', p_release.id, 'allowed',
        jsonb_build_object('locale', p_release.locale, 'revision', p_release.revision,
                           'previous_release_id', v_previous));
    RETURN jsonb_build_object('release_id', p_release.id, 'previous_release_id', v_previous);
END;
$$;

-- Publish a 'ready' release. Publisher (or admin) only.
CREATE FUNCTION staff.release_pack(p_release_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('publisher', 'admin');
    v_release app.pack_releases;
BEGIN
    SELECT * INTO v_release FROM app.pack_releases p WHERE p.id = p_release_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'pack_release_not_found' USING ERRCODE = 'ED404';
    END IF;
    PERFORM staff.lock_pack(v_release.pack_key, v_release.locale);
    SELECT * INTO v_release FROM app.pack_releases p WHERE p.id = p_release_id FOR UPDATE;
    IF v_release.status <> 'ready' THEN
        RAISE EXCEPTION 'pack_release_not_ready' USING ERRCODE = 'ED409';
    END IF;
    RETURN staff.switch_current_pack(v_release, 'pack_release.release');
END;
$$;

-- Go back to an earlier, 'retired' release of the same pack. One audited action.
CREATE FUNCTION staff.rollback_pack(p_release_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('publisher', 'admin');
    v_release app.pack_releases;
BEGIN
    SELECT * INTO v_release FROM app.pack_releases p WHERE p.id = p_release_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'pack_release_not_found' USING ERRCODE = 'ED404';
    END IF;
    PERFORM staff.lock_pack(v_release.pack_key, v_release.locale);
    SELECT * INTO v_release FROM app.pack_releases p WHERE p.id = p_release_id FOR UPDATE;
    IF v_release.status <> 'retired' THEN
        RAISE EXCEPTION 'pack_release_not_retired' USING ERRCODE = 'ED409';
    END IF;
    RETURN staff.switch_current_pack(v_release, 'pack_release.rollback');
END;
$$;

CREATE FUNCTION staff.get_pack_release(p_release_id uuid)
RETURNS jsonb
LANGUAGE plpgsql STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'reviewer', 'publisher', 'admin');
    v_out jsonb := staff.pack_release_json(p_release_id);
BEGIN
    IF v_out IS NULL THEN
        RAISE EXCEPTION 'pack_release_not_found' USING ERRCODE = 'ED404';
    END IF;
    RETURN v_out;
END;
$$;

-- Releases, newest first; optionally of one pack_key and/or language.
CREATE FUNCTION staff.list_pack_releases(p_pack_key text, p_locale text, p_limit integer)
RETURNS jsonb
LANGUAGE plpgsql STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_actor uuid := staff.require_role('editor', 'reviewer', 'publisher', 'admin');
    v_limit integer := LEAST(GREATEST(COALESCE(p_limit, 50), 1), 200);
BEGIN
    RETURN COALESCE((
        SELECT jsonb_agg(staff.pack_release_json(x.id) ORDER BY x.created_at DESC, x.revision DESC, x.id)
        FROM (
            SELECT p.id, p.created_at, p.revision
            FROM app.pack_releases p
            WHERE (p_pack_key IS NULL OR p.pack_key = p_pack_key)
              AND (p_locale IS NULL OR p.locale = p_locale)
            ORDER BY p.created_at DESC, p.revision DESC, p.id
            LIMIT v_limit
        ) AS x), '[]'::jsonb);
END;
$$;

-- ----------------------------------------------------------------------------
-- Privileges
-- ----------------------------------------------------------------------------
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA staff FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION staff.actor_roles() TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.actor_has_role(text[]) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.require_role(text[]) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.create_lesson(uuid, text) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.create_revision(uuid, text, text, jsonb, jsonb) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.update_revision(uuid, text, jsonb, jsonb) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.create_source(text, text) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.set_source_rights(uuid, text, text) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.attach_source(uuid, uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.detach_source(uuid, uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.submit_revision(uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.review_revision(uuid, text, text) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.get_revision(uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.list_revisions(text, boolean, integer) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.list_sources(integer) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.build_pack(text, text, uuid[]) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.release_pack(uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.rollback_pack(uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.get_pack_release(uuid) TO edu_staff;
GRANT EXECUTE ON FUNCTION staff.list_pack_releases(text, text, integer) TO edu_staff;
