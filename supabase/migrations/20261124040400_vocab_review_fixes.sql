-- Mon Edupreneur 2.0 — Word of the Day: fixes from the independent review of a3c48a3
--
-- F1 (MEDIUM). The "day opened before commit" check is a DEFERRABLE constraint
--    trigger. A session could run SET CONSTRAINTS ALL IMMEDIATE right after a
--    schedule change (the check passes early), keep the transaction open over
--    Haiti midnight and commit: learners would have seen today's word change.
--    Fix: an UPDATE/DELETE of an assignment takes an exclusive, transaction-level
--    advisory lock on its date; the learner read takes the shared side for the
--    date it serves and serves NOTHING while it cannot get it. So no reader can
--    see the old word of an opened day and later a different one.
--    The lock is taken only once the change has been ACCEPTED (future, not
--    frozen day), so a refused attempt on today never disturbs today's read.
--    RESIDUAL (availability, not integrity): a raw database session that holds
--    such a transaction open over midnight, or that takes the same advisory
--    key by hand (advisory locks are open to every login), makes that day
--    answer "no word" until the session ends. Bounding the session lifetime of
--    the login roles belongs to their provisioning.
--    The learner read must run READ COMMITTED (the API default): its snapshot
--    is taken after the shared lock is obtained.
-- F2 (LOW). TRUNCATE fires no row trigger: statement triggers now refuse it on
--    the schedule, the revisions and the reviews.
-- F3. vocab._clock(): the guards' clock, overridable ONLY by a session whose
--    database login is the owner (postgres) — the same party that could disable
--    the triggers. API, staff and worker logins always get the real clock.

CREATE FUNCTION vocab._day_key(p_date date)
RETURNS bigint
LANGUAGE sql IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$ SELECT hashtextextended('vocab.day:' || to_char(p_date, 'YYYY-MM-DD'), 0) $$;

CREATE FUNCTION vocab._clock()
RETURNS timestamptz
LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE v_override text;
BEGIN
    IF session_user = 'postgres' THEN
        v_override := current_setting('vocab.test_clock', true);
        IF v_override IS NOT NULL AND v_override <> '' THEN
            RETURN v_override::timestamptz;
        END IF;
    END IF;
    RETURN clock_timestamp();
END;
$$;

CREATE OR REPLACE FUNCTION vocab.guard_daily_assignment()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_clock timestamptz := vocab._clock();
    v_today date := vocab.haiti_date(v_clock);
BEGIN
    IF TG_OP IN ('UPDATE','DELETE') THEN
        -- Refused first, WITHOUT the lock: an attempt on an opened or frozen day
        -- must never make the learner read of that day answer "no word".
        IF OLD.haiti_date <= v_today THEN
            RAISE EXCEPTION 'The word of a day that has already opened cannot be changed';
        END IF;
        IF vocab.is_day_locked(OLD.haiti_date, v_clock) THEN
            RAISE EXCEPTION 'The schedule of a day is frozen shortly before it opens';
        END IF;
        -- Held until this transaction ends (it cannot be released early). The
        -- learner read takes the shared side for the day it serves (see
        -- vocab.daily_word_at).
        PERFORM pg_advisory_xact_lock(vocab._day_key(OLD.haiti_date));
        -- The wait for the lock may have been long: decide again on the clock
        -- read AFTER the lock was obtained.
        v_clock := vocab._clock();
        v_today := vocab.haiti_date(v_clock);
        IF OLD.haiti_date <= v_today THEN
            RAISE EXCEPTION 'The word of a day that has already opened cannot be changed';
        END IF;
        IF vocab.is_day_locked(OLD.haiti_date, v_clock) THEN
            RAISE EXCEPTION 'The schedule of a day is frozen shortly before it opens';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND (NEW.haiti_date IS DISTINCT FROM OLD.haiti_date
                             OR NEW.locale IS DISTINCT FROM OLD.locale) THEN
        RAISE EXCEPTION 'An assignment cannot move to another date or locale';
    END IF;
    IF NEW.haiti_date < v_today THEN
        RAISE EXCEPTION 'A past day cannot be assigned';
    END IF;
    IF NEW.haiti_date > v_today + 366 THEN
        RAISE EXCEPTION 'A day more than 366 days ahead cannot be assigned';
    END IF;
    IF TG_OP = 'INSERT' AND NEW.locale <> 'fr'
       AND vocab.is_day_locked(NEW.haiti_date, v_clock)
       AND NOT EXISTS (
           SELECT 1 FROM vocab.daily_assignments a
           WHERE a.haiti_date = NEW.haiti_date AND a.locale = 'fr'
             AND a.assigned_at >= transaction_timestamp()
       ) THEN
        RAISE EXCEPTION 'A translation cannot be added to a day that has opened or is about to open';
    END IF;
    -- FOR SHARE on the word: a concurrent retirement waits for this write.
    IF NOT EXISTS (
        SELECT 1 FROM vocab.words w
        WHERE w.id = NEW.word_id AND w.is_active
        FOR SHARE
    ) THEN
        RAISE EXCEPTION 'Only an active word can be assigned';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM vocab.word_revisions r
        JOIN vocab.sources s ON s.id = r.source_id
        WHERE r.id = NEW.word_revision_id AND r.status = 'approved'
          AND s.rights_status = 'cleared'
        FOR SHARE OF s
    ) THEN
        RAISE EXCEPTION 'Only an approved, rights-cleared word revision can be assigned';
    END IF;
    NEW.assigned_at := clock_timestamp();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION vocab.check_daily_assignment_day()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_date date;
    v_rows integer;
    v_words integer;
    v_has_fr boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN v_date := OLD.haiti_date; ELSE v_date := NEW.haiti_date; END IF;
    IF TG_OP IN ('UPDATE','DELETE') AND vocab._clock() >= vocab.haiti_day_start(OLD.haiti_date) THEN
        RAISE EXCEPTION 'The day opened before this schedule change was committed';
    END IF;
    SELECT count(*), count(DISTINCT a.word_id), COALESCE(bool_or(a.locale = 'fr'), false)
      INTO v_rows, v_words, v_has_fr
    FROM vocab.daily_assignments a WHERE a.haiti_date = v_date;
    IF v_rows > 0 AND (v_words <> 1 OR NOT v_has_fr) THEN
        RAISE EXCEPTION 'A day needs one word for all its locales, including French';
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION vocab.daily_word_at(p_locale text, p_now timestamptz)
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
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
#variable_conflict use_column
DECLARE
    v_date date;
BEGIN
    IF p_locale IS NULL OR p_locale NOT IN ('fr','ht') OR p_now IS NULL THEN
        RAISE EXCEPTION 'Unsupported locale' USING ERRCODE = '22023';
    END IF;
    v_date := vocab.haiti_date(p_now);
    -- A transaction that changed this date's rows before the date was locked and
    -- is STILL OPEN holds the exclusive side of this lock. Serving the old row
    -- now and the new one after its commit would change an opened day's word,
    -- so in that case nothing is served until that transaction has ended.
    IF NOT pg_try_advisory_xact_lock_shared(vocab._day_key(v_date)) THEN
        RETURN;
    END IF;
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

CREATE OR REPLACE FUNCTION vocab.daily_word(p_locale text)
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
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF app.current_actor_id() IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY SELECT * FROM vocab.daily_word_at(p_locale, now());
END;
$$;

CREATE FUNCTION vocab.refuse_truncate()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    RAISE EXCEPTION 'This table cannot be truncated';
END;
$$;
CREATE TRIGGER no_truncate BEFORE TRUNCATE ON vocab.daily_assignments
    FOR EACH STATEMENT EXECUTE FUNCTION vocab.refuse_truncate();
CREATE TRIGGER no_truncate BEFORE TRUNCATE ON vocab.word_revisions
    FOR EACH STATEMENT EXECUTE FUNCTION vocab.refuse_truncate();
CREATE TRIGGER no_truncate BEFORE TRUNCATE ON vocab.reviews
    FOR EACH STATEMENT EXECUTE FUNCTION vocab.refuse_truncate();

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA vocab FROM PUBLIC, anon, authenticated;
