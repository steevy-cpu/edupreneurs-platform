-- Mon Edupreneur 2.0 — Word of the Day: functions (learner read, schedule, staff workflow)
--
-- Every function here is SECURITY DEFINER, owned by the migration owner
-- (postgres), pins an empty search_path, uses schema-qualified names only and
-- takes the actor from app.current_actor_id() — never from a parameter.
--
-- EXECUTE (see the end of this file):
--   edu_api  -> vocab.daily_word(text) ONLY.
--   nobody   -> everything else. The staff workflow functions are complete and
--               tested at SQL level, but no login role can call them until the
--               staff lane's `edu_staff` role exists; a later migration in this
--               lane's block grants them and swaps the two seams below.
--
-- CLOCK: functions that the API can reach take NO time parameter. The single
-- time seam is vocab.daily_word_at(locale, p_now), which nobody may execute
-- (tests call it as the owner).

-- ============================================================================
-- SEAM 1/2 — staff role check.
-- TEMPORARY BODY: reads app.staff_roles directly for the verified actor.
-- After the staff lane's B1 is merged the body becomes
--     RETURN staff.require_role(VARIADIC p_roles);
-- Nothing else in this file checks roles (the integrity triggers keep their
-- own independent reviewer check on purpose).
-- ============================================================================
CREATE FUNCTION vocab._require_staff(VARIADIC p_roles text[])
RETURNS uuid
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_actor uuid := app.current_actor_id();
BEGIN
    IF v_actor IS NULL OR NOT EXISTS (
        SELECT 1 FROM app.staff_roles sr
        WHERE sr.user_id = v_actor AND sr.is_active AND sr.role = ANY (p_roles)
    ) THEN
        RAISE EXCEPTION 'Staff role required' USING ERRCODE = '42501';
    END IF;
    RETURN v_actor;
END;
$$;

-- ============================================================================
-- SEAM 2/2 — audit write.
-- TEMPORARY BODY: appends to app.audit_events directly (allowed decisions only;
-- a refused call raises and leaves no row — refusals are audited by the staff
-- API boundary once it exists). After B1 the body becomes
--     PERFORM ops.audit_write(p_action, p_target_kind, p_target_id, 'allowed', p_details);
-- p_details carries identifiers, dates and enumerated values only — never
-- free text.
-- ============================================================================
CREATE FUNCTION vocab._audit(
    p_action text, p_target_kind text, p_target_id uuid, p_details jsonb DEFAULT '{}'::jsonb)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    INSERT INTO app.audit_events (actor_id, actor_kind, action, target_kind, target_id, outcome, details)
    VALUES (app.current_actor_id(), 'staff', p_action, p_target_kind, p_target_id, 'allowed',
            COALESCE(p_details, '{}'::jsonb));
END;
$$;

-- ============================================================================
-- Internal helpers
-- ============================================================================
-- All writers of the schedule take this transaction-level lock first, so two
-- concurrent runs (two workers, a worker and a person) queue up instead of
-- racing; the second one then sees what the first one committed.
CREATE FUNCTION vocab._lock_schedule()
RETURNS void
LANGUAGE sql VOLATILE
SET search_path = ''
AS $$ SELECT pg_advisory_xact_lock(hashtextextended('vocab.daily_assignments', 0)) $$;

-- The revision a NEW assignment of this word would use in one locale: the
-- highest approved revision whose source is rights-cleared. NULL if none.
CREATE FUNCTION vocab._assignable_revision(p_word_id uuid, p_locale text)
RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT r.id
    FROM vocab.word_revisions r
    JOIN vocab.sources s ON s.id = r.source_id
    WHERE r.word_id = p_word_id AND r.locale = p_locale
      AND r.status = 'approved' AND s.rights_status = 'cleared'
    ORDER BY r.revision DESC
    LIMIT 1
$$;

-- Give one date its word: a French row (required) and a Creole row when an
-- approved Creole revision exists. Locales that already have a row are left
-- alone. Returns the number of rows written. The guard trigger still decides
-- whether the date may be written at all.
CREATE FUNCTION vocab._assign_word(p_date date, p_word_id uuid, p_via text)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_locale text;
    v_revision uuid;
    v_written integer := 0;
BEGIN
    IF vocab._assignable_revision(p_word_id, 'fr') IS NULL THEN
        RAISE EXCEPTION 'The word has no approved, rights-cleared French revision'
            USING ERRCODE = '23514';
    END IF;
    FOREACH v_locale IN ARRAY ARRAY['fr','ht'] LOOP
        v_revision := vocab._assignable_revision(p_word_id, v_locale);
        CONTINUE WHEN v_revision IS NULL;
        CONTINUE WHEN EXISTS (SELECT 1 FROM vocab.daily_assignments a
                              WHERE a.haiti_date = p_date AND a.locale = v_locale);
        INSERT INTO vocab.daily_assignments (haiti_date, locale, word_id, word_revision_id, assigned_via, assigned_by)
        VALUES (p_date, v_locale, p_word_id, v_revision, p_via, app.current_actor_id());
        v_written := v_written + 1;
    END LOOP;
    RETURN v_written;
END;
$$;

-- ============================================================================
-- The schedule: vocab.ensure_assignments
-- ============================================================================
-- Idempotently fills the UNASSIGNED dates of [p_from, p_from + p_days) that
-- are today or later, and RECORDS them, so the word of a day is a stored fact
-- and never a formula over the current word list.
--
-- Order (deterministic): the active word used least recently — never used
-- first, then the oldest "most recent date" over the whole schedule, past and
-- future — then the oldest word, then the stable id.
-- For a FUTURE date that already has its French row, a missing Creole row is
-- added when an approved translation of THE SAME word now exists; a FUTURE
-- date whose word became unusable (retired / rights withdrawn) is freed and
-- chosen again. An opened day (today) is only ever filled when it has no row
-- at all, and is otherwise never touched.
-- Running it twice, or concurrently, gives the same schedule: see _lock_schedule.
-- Returns the rows it created (none when there was nothing to do).
CREATE FUNCTION vocab.ensure_assignments(p_from date, p_days integer)
RETURNS TABLE (haiti_date date, locale text, word_id uuid, word_revision_id uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
#variable_conflict use_column
DECLARE
    v_today date;
    v_date date;
    v_word uuid;
    v_started timestamptz;
BEGIN
    IF p_from IS NULL OR p_days IS NULL OR p_days < 1 OR p_days > 62 THEN
        RAISE EXCEPTION 'p_from is required and p_days must be between 1 and 62'
            USING ERRCODE = '22023';
    END IF;
    PERFORM vocab._lock_schedule();
    -- Read the clock AFTER the lock: we may have waited.
    v_started := clock_timestamp();
    v_today := vocab.haiti_date(v_started);

    FOR v_date IN
        SELECT d::date FROM generate_series(
            GREATEST(p_from, v_today)::timestamp,
            LEAST(p_from + p_days - 1, v_today + 366)::timestamp,
            interval '1 day') AS d
    LOOP
        SELECT a.word_id INTO v_word
        FROM vocab.daily_assignments a WHERE a.haiti_date = v_date LIMIT 1;
        IF FOUND THEN
            -- An opened day is never touched, whatever it holds.
            CONTINUE WHEN v_date <= v_today;
            -- A FUTURE day whose French row can no longer be shown (word
            -- retired, or rights withdrawn since it was scheduled) is a hole
            -- in waiting: free it and choose again below.
            IF NOT EXISTS (
                SELECT 1
                FROM vocab.daily_assignments a
                JOIN vocab.words w ON w.id = a.word_id
                JOIN vocab.word_revisions r ON r.id = a.word_revision_id
                JOIN vocab.sources s ON s.id = r.source_id
                WHERE a.haiti_date = v_date AND a.locale = 'fr'
                  AND w.is_active AND s.rights_status = 'cleared'
            ) THEN
                DELETE FROM vocab.daily_assignments a WHERE a.haiti_date = v_date;
                v_word := NULL;
            END IF;
        END IF;
        IF v_word IS NULL THEN
            SELECT w.id INTO v_word
            FROM vocab.words w
            WHERE w.is_active AND vocab._assignable_revision(w.id, 'fr') IS NOT NULL
            ORDER BY (SELECT max(a.haiti_date) FROM vocab.daily_assignments a
                      WHERE a.word_id = w.id) NULLS FIRST,
                     w.created_at, w.id
            LIMIT 1;
            EXIT WHEN NOT FOUND; -- empty pool: nothing is invented
        END IF;
        -- Writes the French row and/or a missing Creole row of the same word.
        PERFORM vocab._assign_word(v_date, v_word, 'auto');
    END LOOP;

    RETURN QUERY
    SELECT a.haiti_date, a.locale, a.word_id, a.word_revision_id
    FROM vocab.daily_assignments a
    WHERE a.assigned_at >= v_started AND a.assigned_via = 'auto'
      AND a.haiti_date BETWEEN p_from AND p_from + p_days - 1
    ORDER BY a.haiti_date, a.locale;
END;
$$;

-- ============================================================================
-- Learner read
-- ============================================================================
-- INTERNAL (nobody may execute it): the word of the Haiti date that contains
-- p_now. Zero rows when that date has no usable word.
-- Visibility rule, all in one place: the row must be assigned to exactly that
-- date, its revision approved, and the text's rights still cleared. A date in
-- the future, a draft, a submitted or a rejected revision can never be
-- returned because nothing here looks at any other date or status.
-- Missing (or rights-withdrawn) translation -> the French row of the same day.
-- A recording is included only while its own rights are cleared.
CREATE FUNCTION vocab.daily_word_at(p_locale text, p_now timestamptz)
RETURNS TABLE (
    haiti_date date,
    requested_locale text,
    locale text,
    is_fallback_locale boolean,
    word_id uuid,
    word_revision_id uuid,
    revision integer,
    term text,
    pronunciation text,
    part_of_speech text,
    definition text,
    example text,
    gloss text,
    audio_asset_id uuid,
    audio_mime_type text,
    audio_byte_size integer,
    audio_duration_ms integer,
    audio_sha256 text,
    valid_until timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
#variable_conflict use_column
DECLARE
    v_date date;
BEGIN
    IF p_locale IS NULL OR p_locale NOT IN ('fr','ht') OR p_now IS NULL THEN
        RAISE EXCEPTION 'Unsupported locale' USING ERRCODE = '22023';
    END IF;
    v_date := vocab.haiti_date(p_now);
    RETURN QUERY
    SELECT a.haiti_date,
           p_locale,
           a.locale,
           a.locale <> p_locale,
           r.word_id,
           r.id,
           r.revision,
           r.term,
           r.pronunciation,
           r.part_of_speech,
           r.definition,
           r.example,
           r.gloss,
           au.id,
           au.mime_type,
           au.byte_size,
           au.duration_ms,
           encode(au.sha256, 'hex'),
           vocab.haiti_day_start(a.haiti_date + 1)
    FROM vocab.daily_assignments a
    JOIN vocab.word_revisions r ON r.id = a.word_revision_id AND r.status = 'approved'
    JOIN vocab.sources s ON s.id = r.source_id AND s.rights_status = 'cleared'
    LEFT JOIN (
        SELECT x.id, x.word_revision_id, x.mime_type, x.byte_size, x.duration_ms, x.sha256
        FROM vocab.audio_assets x
        JOIN vocab.sources xs ON xs.id = x.source_id AND xs.rights_status = 'cleared'
    ) au ON au.word_revision_id = r.id
    WHERE a.haiti_date = v_date AND a.locale IN (p_locale, 'fr')
    ORDER BY (a.locale = p_locale) DESC
    LIMIT 1;
END;
$$;

-- The ONLY vocab function the student API may execute. No time parameter:
-- "today" is the server's. A connection without a verified actor gets nothing.
CREATE FUNCTION vocab.daily_word(p_locale text)
RETURNS TABLE (
    haiti_date date,
    requested_locale text,
    locale text,
    is_fallback_locale boolean,
    word_id uuid,
    word_revision_id uuid,
    revision integer,
    term text,
    pronunciation text,
    part_of_speech text,
    definition text,
    example text,
    gloss text,
    audio_asset_id uuid,
    audio_mime_type text,
    audio_byte_size integer,
    audio_duration_ms integer,
    audio_sha256 text,
    valid_until timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF app.current_actor_id() IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY SELECT * FROM vocab.daily_word_at(p_locale, now());
END;
$$;

-- ============================================================================
-- Erasure hook (plan §3). This schema stores NO per-learner row: opening the
-- word records nothing. View/history tracking is deliberately not built
-- (it needs a consent decision, PO-04).
-- ============================================================================
CREATE FUNCTION vocab.erase_learner(p_user_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$ SELECT '{}'::jsonb $$;

-- ============================================================================
-- STAFF WORKFLOW (awaiting staff wiring; EXECUTE granted to nobody)
-- Roles — recorded choice, see docs/overnight-2026-11-24/lanes/vocab.md:
--   write / submit a word, register a source ........ editor, admin
--   review ............................................ reviewer, admin (never the author)
--   rights decision, schedule, retire, run the fill ... publisher, admin
-- SQLSTATEs the future routes map: 42501 forbidden, P0002 not found,
-- 22023 invalid argument, 23514 / 23505 / P0001 rule violated.
-- ============================================================================
CREATE FUNCTION vocab.register_source(
    p_source_title text, p_source_uri text, p_licence text, p_rights_notes text DEFAULT NULL)
RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_actor uuid := vocab._require_staff('editor', 'publisher', 'admin'); v_id uuid;
BEGIN
    INSERT INTO vocab.sources (source_title, source_uri, licence, rights_notes, created_by)
    VALUES (p_source_title, p_source_uri, p_licence, p_rights_notes, v_actor)
    RETURNING id INTO v_id;
    PERFORM vocab._audit('vocab.source.register', 'vocab_source', v_id);
    RETURN v_id;
END;
$$;

CREATE FUNCTION vocab.set_source_rights(p_source_id uuid, p_rights_status text, p_rights_notes text DEFAULT NULL)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    PERFORM vocab._require_staff('publisher', 'admin');
    UPDATE vocab.sources s
       SET rights_status = p_rights_status,
           rights_notes = COALESCE(p_rights_notes, s.rights_notes)
     WHERE s.id = p_source_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Source not found' USING ERRCODE = 'P0002';
    END IF;
    PERFORM vocab._audit('vocab.source.rights', 'vocab_source', p_source_id,
                         jsonb_build_object('rights_status', p_rights_status));
END;
$$;

CREATE FUNCTION vocab.create_word(p_slug text)
RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_actor uuid := vocab._require_staff('editor', 'admin'); v_id uuid;
BEGIN
    INSERT INTO vocab.words (slug, created_by) VALUES (p_slug, v_actor) RETURNING id INTO v_id;
    PERFORM vocab._audit('vocab.word.create', 'vocab_word', v_id);
    RETURN v_id;
END;
$$;

-- A new DRAFT revision of a word in one locale. The revision number is the
-- next one for (word, locale); the word row is locked while it is computed.
CREATE FUNCTION vocab.create_draft(
    p_word_id uuid, p_locale text, p_term text, p_pronunciation text, p_part_of_speech text,
    p_definition text, p_example text, p_gloss text, p_source_id uuid)
RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_actor uuid := vocab._require_staff('editor', 'admin'); v_id uuid; v_next integer;
BEGIN
    PERFORM 1 FROM vocab.words w WHERE w.id = p_word_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Word not found' USING ERRCODE = 'P0002';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM vocab.sources s WHERE s.id = p_source_id) THEN
        RAISE EXCEPTION 'Source not found' USING ERRCODE = 'P0002';
    END IF;
    SELECT COALESCE(max(r.revision), 0) + 1 INTO v_next
    FROM vocab.word_revisions r WHERE r.word_id = p_word_id AND r.locale = p_locale;
    INSERT INTO vocab.word_revisions (
        word_id, locale, revision, term, pronunciation, part_of_speech,
        definition, example, gloss, source_id, created_by)
    VALUES (p_word_id, p_locale, v_next, p_term, p_pronunciation, p_part_of_speech,
            p_definition, p_example, p_gloss, p_source_id, v_actor)
    RETURNING id INTO v_id;
    PERFORM vocab._audit('vocab.revision.create', 'vocab_word_revision', v_id,
                         jsonb_build_object('word_id', p_word_id, 'locale', p_locale, 'revision', v_next));
    RETURN v_id;
END;
$$;

-- Lock a revision and insist the caller wrote it. Only the AUTHOR may change a
-- draft: if a second person could rewrite it, that person could then review
-- "someone else's" text that is really their own.
CREATE FUNCTION vocab._own_revision_for_update(p_revision_id uuid, p_actor uuid)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_author uuid;
BEGIN
    SELECT r.created_by INTO v_author
    FROM vocab.word_revisions r WHERE r.id = p_revision_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Word revision not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_author <> p_actor THEN
        RAISE EXCEPTION 'Only the author can change this draft' USING ERRCODE = '42501';
    END IF;
END;
$$;

CREATE FUNCTION vocab.update_draft(
    p_revision_id uuid, p_term text, p_pronunciation text, p_part_of_speech text,
    p_definition text, p_example text, p_gloss text, p_source_id uuid)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_actor uuid := vocab._require_staff('editor', 'admin');
BEGIN
    PERFORM vocab._own_revision_for_update(p_revision_id, v_actor);
    IF NOT EXISTS (SELECT 1 FROM vocab.sources s WHERE s.id = p_source_id) THEN
        RAISE EXCEPTION 'Source not found' USING ERRCODE = 'P0002';
    END IF;
    -- The trigger refuses this unless the revision is still a draft.
    UPDATE vocab.word_revisions r
       SET term = p_term, pronunciation = p_pronunciation, part_of_speech = p_part_of_speech,
           definition = p_definition, example = p_example, gloss = p_gloss, source_id = p_source_id
     WHERE r.id = p_revision_id;
    PERFORM vocab._audit('vocab.revision.update', 'vocab_word_revision', p_revision_id);
END;
$$;

-- Attach (or replace) the METADATA of a recording on the caller's own draft.
CREATE FUNCTION vocab.set_audio(
    p_revision_id uuid, p_object_key text, p_byte_size integer, p_sha256 bytea,
    p_mime_type text, p_duration_ms integer, p_source_id uuid)
RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_actor uuid := vocab._require_staff('editor', 'admin'); v_id uuid;
BEGIN
    PERFORM vocab._own_revision_for_update(p_revision_id, v_actor);
    IF NOT EXISTS (SELECT 1 FROM vocab.sources s WHERE s.id = p_source_id) THEN
        RAISE EXCEPTION 'Source not found' USING ERRCODE = 'P0002';
    END IF;
    DELETE FROM vocab.audio_assets a WHERE a.word_revision_id = p_revision_id;
    INSERT INTO vocab.audio_assets (
        word_revision_id, object_key, byte_size, sha256, mime_type, duration_ms, source_id, created_by)
    VALUES (p_revision_id, p_object_key, p_byte_size, p_sha256, p_mime_type, p_duration_ms,
            p_source_id, v_actor)
    RETURNING id INTO v_id;
    PERFORM vocab._audit('vocab.audio.set', 'vocab_word_revision', p_revision_id,
                         jsonb_build_object('audio_asset_id', v_id, 'byte_size', p_byte_size));
    RETURN v_id;
END;
$$;

CREATE FUNCTION vocab.remove_audio(p_revision_id uuid)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_actor uuid := vocab._require_staff('editor', 'admin');
BEGIN
    PERFORM vocab._own_revision_for_update(p_revision_id, v_actor);
    DELETE FROM vocab.audio_assets a WHERE a.word_revision_id = p_revision_id;
    PERFORM vocab._audit('vocab.audio.remove', 'vocab_word_revision', p_revision_id);
END;
$$;

CREATE FUNCTION vocab.submit_revision(p_revision_id uuid)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_actor uuid := vocab._require_staff('editor', 'admin');
BEGIN
    PERFORM vocab._own_revision_for_update(p_revision_id, v_actor);
    IF NOT EXISTS (SELECT 1 FROM vocab.word_revisions r
                   WHERE r.id = p_revision_id AND r.status = 'draft') THEN
        RAISE EXCEPTION 'Only a draft can be submitted' USING ERRCODE = '23514';
    END IF;
    UPDATE vocab.word_revisions r SET status = 'in_review' WHERE r.id = p_revision_id;
    PERFORM vocab._audit('vocab.revision.submit', 'vocab_word_revision', p_revision_id);
END;
$$;

-- One step for the reviewer: record the verdict (append-only) and move the
-- revision. The triggers enforce independence, the reviewer role and the
-- rights gate again, whatever this function does.
CREATE FUNCTION vocab.review_revision(p_revision_id uuid, p_verdict text, p_notes text DEFAULT NULL)
RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_actor uuid := vocab._require_staff('reviewer', 'admin'); v_review uuid;
BEGIN
    IF p_verdict IS NULL OR p_verdict NOT IN ('approved', 'rejected') THEN
        RAISE EXCEPTION 'Verdict must be approved or rejected' USING ERRCODE = '22023';
    END IF;
    PERFORM 1 FROM vocab.word_revisions r WHERE r.id = p_revision_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Word revision not found' USING ERRCODE = 'P0002';
    END IF;
    INSERT INTO vocab.reviews (word_revision_id, reviewer_id, verdict, notes)
    VALUES (p_revision_id, v_actor, p_verdict, p_notes)
    RETURNING id INTO v_review;
    IF p_verdict = 'approved' THEN
        UPDATE vocab.word_revisions r
           SET status = 'approved', approved_by = v_actor, approved_at = now()
         WHERE r.id = p_revision_id;
    ELSE
        UPDATE vocab.word_revisions r SET status = 'rejected' WHERE r.id = p_revision_id;
    END IF;
    PERFORM vocab._audit('vocab.revision.review', 'vocab_word_revision', p_revision_id,
                         jsonb_build_object('verdict', p_verdict, 'review_id', v_review));
    RETURN v_review;
END;
$$;

-- Submitted revisions waiting for a verdict, oldest first (bounded).
CREATE FUNCTION vocab.review_queue()
RETURNS TABLE (
    word_revision_id uuid, word_id uuid, slug text, locale text, revision integer,
    term text, pronunciation text, part_of_speech text, definition text, example text,
    gloss text, source_id uuid, source_rights_status text, has_audio boolean,
    created_by uuid, created_at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
#variable_conflict use_column
BEGIN
    PERFORM vocab._require_staff('editor', 'reviewer', 'publisher', 'admin');
    RETURN QUERY
    SELECT r.id, r.word_id, w.slug, r.locale, r.revision, r.term, r.pronunciation,
           r.part_of_speech, r.definition, r.example, r.gloss, r.source_id, s.rights_status,
           EXISTS (SELECT 1 FROM vocab.audio_assets a WHERE a.word_revision_id = r.id),
           r.created_by, r.created_at
    FROM vocab.word_revisions r
    JOIN vocab.words w ON w.id = r.word_id
    JOIN vocab.sources s ON s.id = r.source_id
    WHERE r.status = 'in_review'
    ORDER BY r.created_at, r.id
    LIMIT 200;
END;
$$;

-- Put a chosen word on a date that has not opened yet (or on today, only if
-- today has no word at all), replacing whatever the date had. Both locale
-- rows are written together.
CREATE FUNCTION vocab.schedule_word(p_date date, p_word_id uuid)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_written integer;
BEGIN
    PERFORM vocab._require_staff('publisher', 'admin');
    IF p_date IS NULL OR p_word_id IS NULL THEN
        RAISE EXCEPTION 'Date and word are required' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM vocab.words w WHERE w.id = p_word_id) THEN
        RAISE EXCEPTION 'Word not found' USING ERRCODE = 'P0002';
    END IF;
    PERFORM vocab._lock_schedule();
    -- The guard trigger refuses this delete once the date has opened.
    DELETE FROM vocab.daily_assignments a WHERE a.haiti_date = p_date;
    v_written := vocab._assign_word(p_date, p_word_id, 'staff');
    PERFORM vocab._audit('vocab.schedule.set', 'vocab_word', p_word_id,
                         jsonb_build_object('haiti_date', p_date, 'rows', v_written));
    RETURN v_written;
END;
$$;

-- Clear a future date (the next fill may then choose a word for it).
CREATE FUNCTION vocab.unschedule_date(p_date date)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_removed integer;
BEGIN
    PERFORM vocab._require_staff('publisher', 'admin');
    IF p_date IS NULL THEN
        RAISE EXCEPTION 'Date is required' USING ERRCODE = '22023';
    END IF;
    PERFORM vocab._lock_schedule();
    DELETE FROM vocab.daily_assignments a WHERE a.haiti_date = p_date;
    GET DIAGNOSTICS v_removed = ROW_COUNT;
    PERFORM vocab._audit('vocab.schedule.clear', 'vocab_schedule', NULL,
                         jsonb_build_object('haiti_date', p_date, 'rows', v_removed));
    RETURN v_removed;
END;
$$;

-- The calendar staff look at: what is recorded for each date, and whether the
-- date is locked (already opened in Haiti).
CREATE FUNCTION vocab.calendar(p_from date, p_days integer)
RETURNS TABLE (
    haiti_date date, locale text, word_id uuid, slug text, word_revision_id uuid,
    revision integer, term text, assigned_via text, assigned_by uuid,
    assigned_at timestamptz, is_locked boolean)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
#variable_conflict use_column
BEGIN
    PERFORM vocab._require_staff('editor', 'reviewer', 'publisher', 'admin');
    IF p_from IS NULL OR p_days IS NULL OR p_days < 1 OR p_days > 92 THEN
        RAISE EXCEPTION 'p_from is required and p_days must be between 1 and 92'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    SELECT a.haiti_date, a.locale, a.word_id, w.slug, a.word_revision_id, r.revision, r.term,
           a.assigned_via, a.assigned_by, a.assigned_at,
           a.haiti_date <= vocab.haiti_date(clock_timestamp())
    FROM vocab.daily_assignments a
    JOIN vocab.words w ON w.id = a.word_id
    JOIN vocab.word_revisions r ON r.id = a.word_revision_id
    WHERE a.haiti_date BETWEEN p_from AND p_from + p_days - 1
    ORDER BY a.haiti_date, a.locale;
END;
$$;

-- Staff-triggered run of the fill (the worker will call ensure_assignments itself).
CREATE FUNCTION vocab.staff_ensure_assignments(p_from date, p_days integer)
RETURNS TABLE (haiti_date date, locale text, word_id uuid, word_revision_id uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
#variable_conflict use_column
DECLARE v_created integer;
BEGIN
    PERFORM vocab._require_staff('publisher', 'admin');
    RETURN QUERY SELECT e.haiti_date, e.locale, e.word_id, e.word_revision_id
                 FROM vocab.ensure_assignments(p_from, p_days) e;
    GET DIAGNOSTICS v_created = ROW_COUNT;
    PERFORM vocab._audit('vocab.schedule.ensure', 'vocab_schedule', NULL,
                         jsonb_build_object('from', p_from, 'days', p_days, 'rows', v_created));
END;
$$;

-- Retire a word: it is never chosen again and its assignments on dates that
-- have NOT opened are removed (so the fill can choose another word). Dates
-- that already opened keep it for ever. Returns the number of rows removed.
CREATE FUNCTION vocab.retire_word(p_word_id uuid)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_removed integer;
BEGIN
    PERFORM vocab._require_staff('publisher', 'admin');
    PERFORM vocab._lock_schedule();
    UPDATE vocab.words w SET is_active = false WHERE w.id = p_word_id AND w.is_active;
    IF NOT FOUND AND NOT EXISTS (SELECT 1 FROM vocab.words w WHERE w.id = p_word_id) THEN
        RAISE EXCEPTION 'Word not found' USING ERRCODE = 'P0002';
    END IF;
    DELETE FROM vocab.daily_assignments a
     WHERE a.word_id = p_word_id AND a.haiti_date > vocab.haiti_date(clock_timestamp());
    GET DIAGNOSTICS v_removed = ROW_COUNT;
    PERFORM vocab._audit('vocab.word.retire', 'vocab_word', p_word_id,
                         jsonb_build_object('future_rows_removed', v_removed));
    RETURN v_removed;
END;
$$;

-- ============================================================================
-- Privileges
-- ============================================================================
REVOKE ALL ON ALL TABLES IN SCHEMA vocab FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA vocab FROM PUBLIC, anon, authenticated;

-- The student API: may enter the schema and call ONE function. It holds no
-- table privilege here, so it cannot list words, read the schedule, see a
-- future date, or reach any staff function.
GRANT USAGE ON SCHEMA vocab TO edu_api;
GRANT EXECUTE ON FUNCTION vocab.daily_word(text) TO edu_api;
