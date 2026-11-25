-- Mon Edupreneur 2.0 — Word of the Day: private schema `vocab` (tables + integrity guards)
--
-- Overnight mission 2026-11-24, lane VOCAB. Nothing is created in schema `app`
-- and no existing migration is edited (plan §3). The functions that read and
-- write these tables are in the next migration (20261124040200).
--
-- MODEL
--   sources            where a word's text / recording comes from, and its rights status
--   words              the stable identity of a word (a concept, not a spelling)
--   word_revisions     one independent revision per locale ('fr' / 'ht'):
--                      draft -> in_review -> approved | rejected
--   reviews            append-only verdicts; the reviewer is never the author
--   audio_assets       METADATA of an optional recording (no storage service, no TTS)
--   daily_assignments  (haiti_date, locale) -> word_revision_id. THE SCHEDULE OF RECORD.
--
-- "Today" is always the America/Port-au-Prince calendar date computed from the
-- SERVER clock. A device clock is never an input anywhere in this schema.
--
-- WHY TRIGGERS, WHY SECURITY DEFINER, CONCURRENCY: same reasoning as
-- 20261121000200_integrity_guards.sql. The rules must hold for every writer
-- (staff API, worker, a person in a SQL console); a guard must see every row
-- regardless of row-level security; guards that check "what has been reviewed"
-- lock the parent revision first so two transactions cannot both pass.

CREATE SCHEMA vocab;
REVOKE ALL ON SCHEMA vocab FROM PUBLIC;
REVOKE ALL ON SCHEMA vocab FROM anon, authenticated;
COMMENT ON SCHEMA vocab IS
    'Private Word-of-the-Day data. Reached only through FastAPI; never expose this schema in the Supabase Data API.';

-- ============================================================================
-- Product-day helpers (pure; the only place the time zone name is written)
-- ============================================================================
-- STABLE, not IMMUTABLE: the answer depends on the server's time-zone database.
CREATE FUNCTION vocab.haiti_date(p_now timestamptz DEFAULT now())
RETURNS date
LANGUAGE sql STABLE
SET search_path = ''
AS $$ SELECT (p_now AT TIME ZONE 'America/Port-au-Prince')::date $$;

-- The instant a Haiti calendar date begins. Haiti's clock changes happen at
-- 02:00 local time, so local midnight always exists exactly once.
CREATE FUNCTION vocab.haiti_day_start(p_date date)
RETURNS timestamptz
LANGUAGE sql STABLE
SET search_path = ''
AS $$ SELECT p_date::timestamp AT TIME ZONE 'America/Port-au-Prince' $$;

-- ============================================================================
-- TABLES (6)
-- ============================================================================
CREATE TABLE vocab.sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_title text NOT NULL CHECK (char_length(source_title) BETWEEN 1 AND 240),
    source_uri text CHECK (source_uri IS NULL OR char_length(source_uri) BETWEEN 1 AND 500),
    licence text NOT NULL CHECK (char_length(licence) BETWEEN 1 AND 120),
    rights_status text NOT NULL DEFAULT 'unverified'
        CHECK (rights_status IN ('unverified','cleared','restricted','blocked')),
    rights_notes text CHECK (rights_notes IS NULL OR char_length(rights_notes) <= 1000),
    rights_decided_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    rights_decided_at timestamptz,
    created_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE vocab.words (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]{2,80}$'),
    -- A retired word is never picked for a NEW date. Dates it already served keep it.
    is_active boolean NOT NULL DEFAULT true,
    retired_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    retired_at timestamptz,
    created_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((is_active AND retired_at IS NULL AND retired_by IS NULL)
        OR (NOT is_active AND retired_at IS NOT NULL))
);

-- French and Haitian Creole are INDEPENDENT revisions of the same word.
-- Every text column is bounded, single-line (no control characters), and the
-- whole learner-visible payload has a hard byte budget so the daily response
-- stays small on a slow, metered connection (see word_revisions_payload_budget).
CREATE TABLE vocab.word_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    word_id uuid NOT NULL REFERENCES vocab.words(id) ON DELETE RESTRICT,
    locale text NOT NULL CHECK (locale IN ('fr','ht')),
    revision integer NOT NULL CHECK (revision > 0),
    term text NOT NULL
        CHECK (char_length(term) BETWEEN 1 AND 60 AND term = btrim(term) AND term !~ '[[:cntrl:]]'),
    -- Phonetic / pronunciation help as TEXT (e.g. a respelling). Not audio.
    pronunciation text
        CHECK (pronunciation IS NULL OR (char_length(pronunciation) BETWEEN 1 AND 80 AND pronunciation !~ '[[:cntrl:]]')),
    -- Language-neutral code; the app shows the label in the learner's language.
    part_of_speech text NOT NULL CHECK (part_of_speech IN (
        'noun','verb','adjective','adverb','pronoun','preposition',
        'conjunction','interjection','determiner','expression')),
    definition text NOT NULL
        CHECK (char_length(definition) BETWEEN 1 AND 300 AND definition !~ '[[:cntrl:]]'),
    example text NOT NULL
        CHECK (char_length(example) BETWEEN 1 AND 240 AND example !~ '[[:cntrl:]]'),
    -- Optional short gloss in the OTHER language (Creole for 'fr', French for 'ht').
    gloss text
        CHECK (gloss IS NULL OR (char_length(gloss) BETWEEN 1 AND 80 AND gloss !~ '[[:cntrl:]]')),
    source_id uuid NOT NULL REFERENCES vocab.sources(id) ON DELETE RESTRICT,
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','in_review','approved','rejected')),
    created_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    approved_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (word_id, locale, revision),
    UNIQUE (id, word_id, locale),
    CHECK (
        (status = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
        OR (status <> 'approved' AND approved_by IS NULL AND approved_at IS NULL)
    ),
    -- Size of the five texts exactly as they appear inside a JSON document
    -- (quotes and escapes included; an absent optional field counts as `null`).
    CONSTRAINT word_revisions_payload_budget CHECK (
        octet_length(to_jsonb(term)::text)
        + COALESCE(octet_length(to_jsonb(pronunciation)::text), 4)
        + octet_length(to_jsonb(definition)::text)
        + octet_length(to_jsonb(example)::text)
        + COALESCE(octet_length(to_jsonb(gloss)::text), 4) <= 800
    )
);

CREATE TABLE vocab.reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    word_revision_id uuid NOT NULL REFERENCES vocab.word_revisions(id) ON DELETE RESTRICT,
    reviewer_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    verdict text NOT NULL CHECK (verdict IN ('approved','rejected')),
    notes text CHECK (notes IS NULL OR char_length(notes) <= 1000),
    reviewed_at timestamptz NOT NULL DEFAULT now()
);

-- Metadata only. The bytes live (one day) in object storage under object_key;
-- nothing in this mission uploads, synthesises or plays audio.
-- HARD CAP 102 400 bytes (100 KiB): a single spoken word in a speech codec is
-- a few tens of kilobytes; anything larger is refused at the database.
CREATE TABLE vocab.audio_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    word_revision_id uuid NOT NULL UNIQUE REFERENCES vocab.word_revisions(id) ON DELETE RESTRICT,
    object_key text NOT NULL UNIQUE CHECK (object_key ~ '^[a-z0-9][a-z0-9/_.-]{2,119}$'),
    byte_size integer NOT NULL CHECK (byte_size BETWEEN 1 AND 102400),
    sha256 bytea NOT NULL CHECK (octet_length(sha256) = 32),
    mime_type text NOT NULL CHECK (mime_type IN ('audio/mpeg','audio/mp4','audio/aac','audio/ogg')),
    duration_ms integer NOT NULL CHECK (duration_ms BETWEEN 1 AND 15000),
    -- The rights record of the RECORDING (voice, performer), separate from the text's.
    source_id uuid NOT NULL REFERENCES vocab.sources(id) ON DELETE RESTRICT,
    created_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- The schedule of record. One row per (Haiti date, locale); every row of a
-- date points at the SAME word, and a French row always exists (French is the
-- fallback when a Creole translation is missing) — see check_daily_assignment_day.
-- The composite foreign key pins the revision's word and locale.
CREATE TABLE vocab.daily_assignments (
    haiti_date date NOT NULL,
    locale text NOT NULL CHECK (locale IN ('fr','ht')),
    word_id uuid NOT NULL,
    word_revision_id uuid NOT NULL,
    -- 'auto' = filled by vocab.ensure_assignments; 'staff' = chosen by a person.
    assigned_via text NOT NULL CHECK (assigned_via IN ('auto','staff')),
    assigned_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (haiti_date, locale),
    FOREIGN KEY (word_revision_id, word_id, locale)
        REFERENCES vocab.word_revisions(id, word_id, locale) ON DELETE RESTRICT,
    CHECK (assigned_via = 'auto' OR assigned_by IS NOT NULL)
);

-- ============================================================================
-- INDEXES (in addition to the PK / UNIQUE indexes above; every FK is covered)
-- ============================================================================
CREATE INDEX idx_vocab_revs_approved ON vocab.word_revisions(word_id, locale, revision DESC)
    WHERE status = 'approved';
CREATE INDEX idx_vocab_revs_queue ON vocab.word_revisions(created_at) WHERE status = 'in_review';
CREATE INDEX idx_vocab_revs_source ON vocab.word_revisions(source_id);
CREATE INDEX idx_vocab_revs_created_by ON vocab.word_revisions(created_by);
CREATE INDEX idx_vocab_revs_approved_by ON vocab.word_revisions(approved_by) WHERE approved_by IS NOT NULL;
CREATE INDEX idx_vocab_reviews_revision ON vocab.reviews(word_revision_id, reviewed_at DESC);
CREATE INDEX idx_vocab_reviews_reviewer ON vocab.reviews(reviewer_id);
CREATE INDEX idx_vocab_audio_source ON vocab.audio_assets(source_id);
CREATE INDEX idx_vocab_audio_created_by ON vocab.audio_assets(created_by);
CREATE INDEX idx_vocab_assignments_word ON vocab.daily_assignments(word_id, haiti_date DESC);
CREATE INDEX idx_vocab_assignments_revision ON vocab.daily_assignments(word_revision_id);
CREATE INDEX idx_vocab_assignments_by ON vocab.daily_assignments(assigned_by) WHERE assigned_by IS NOT NULL;
CREATE INDEX idx_vocab_words_created_by ON vocab.words(created_by);
CREATE INDEX idx_vocab_words_retired_by ON vocab.words(retired_by) WHERE retired_by IS NOT NULL;
CREATE INDEX idx_vocab_sources_created_by ON vocab.sources(created_by);
CREATE INDEX idx_vocab_sources_decided_by ON vocab.sources(rights_decided_by) WHERE rights_decided_by IS NOT NULL;

-- ============================================================================
-- Row-level security: default deny. There is NO policy at all in this schema;
-- the student API reads through vocab.daily_word() only (next migration).
-- ============================================================================
ALTER TABLE vocab.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE vocab.words ENABLE ROW LEVEL SECURITY;
ALTER TABLE vocab.word_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE vocab.reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE vocab.audio_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE vocab.daily_assignments ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- GUARDS: sources
-- ============================================================================
-- A source starts 'unverified'. Its rights status may change later (rights can
-- be granted or withdrawn) and the decision is stamped by the server; the
-- identity of a source that submitted material cites cannot be rewritten.
CREATE FUNCTION vocab.guard_source()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.rights_status <> 'unverified' OR NEW.rights_decided_by IS NOT NULL
           OR NEW.rights_decided_at IS NOT NULL THEN
            RAISE EXCEPTION 'Sources must be created with unverified rights';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'Source identity and authorship cannot be changed';
    END IF;
    IF (NEW.source_title IS DISTINCT FROM OLD.source_title
        OR NEW.source_uri IS DISTINCT FROM OLD.source_uri
        OR NEW.licence IS DISTINCT FROM OLD.licence)
       AND (EXISTS (SELECT 1 FROM vocab.word_revisions r
                    WHERE r.source_id = OLD.id AND r.status <> 'draft')
         OR EXISTS (SELECT 1 FROM vocab.audio_assets a
                    JOIN vocab.word_revisions r ON r.id = a.word_revision_id
                    WHERE a.source_id = OLD.id AND r.status <> 'draft')) THEN
        RAISE EXCEPTION 'Source identity used in submitted material is immutable';
    END IF;
    IF NEW.rights_status IS DISTINCT FROM OLD.rights_status THEN
        -- Who and when are the server's facts, not the caller's.
        NEW.rights_decided_by := app.current_actor_id();
        NEW.rights_decided_at := now();
    ELSE
        NEW.rights_decided_by := OLD.rights_decided_by;
        NEW.rights_decided_at := OLD.rights_decided_at;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_source
BEFORE INSERT OR UPDATE ON vocab.sources
FOR EACH ROW EXECUTE FUNCTION vocab.guard_source();

-- ============================================================================
-- GUARDS: words
-- ============================================================================
CREATE FUNCTION vocab.guard_word()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NOT NEW.is_active OR NEW.retired_at IS NOT NULL OR NEW.retired_by IS NOT NULL THEN
            RAISE EXCEPTION 'Words must be created active';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.slug IS DISTINCT FROM OLD.slug
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'Word identity and authorship cannot be changed';
    END IF;
    IF NEW.is_active AND NOT OLD.is_active THEN
        NEW.retired_by := NULL;
        NEW.retired_at := NULL;
    ELSIF NOT NEW.is_active AND OLD.is_active THEN
        NEW.retired_by := app.current_actor_id();
        NEW.retired_at := now();
    ELSE
        NEW.retired_by := OLD.retired_by;
        NEW.retired_at := OLD.retired_at;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_word
BEFORE INSERT OR UPDATE ON vocab.words
FOR EACH ROW EXECUTE FUNCTION vocab.guard_word();

-- ============================================================================
-- GUARDS: word revisions
-- ============================================================================
-- New rows must be drafts: a revision cannot be INSERTed already approved.
CREATE FUNCTION vocab.guard_word_revision_insert()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF NEW.status <> 'draft' OR NEW.approved_by IS NOT NULL OR NEW.approved_at IS NOT NULL THEN
        RAISE EXCEPTION 'Word revisions must be created as unapproved drafts';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER guard_word_revision_insert
BEFORE INSERT ON vocab.word_revisions
FOR EACH ROW EXECUTE FUNCTION vocab.guard_word_revision_insert();

-- The whole life cycle:
--   draft      -> draft (edit)  | in_review (submit, content untouched)
--   in_review  -> approved | rejected   (decided by the LATEST review; content frozen)
--   approved, rejected -> nothing, ever. A correction is a NEW revision.
-- Only drafts can be deleted.
CREATE FUNCTION vocab.protect_word_revision()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_content_changed boolean;
    v_latest_verdict text;
    v_latest_reviewer uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'Only draft word revisions can be deleted';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status IN ('approved','rejected') THEN
        RAISE EXCEPTION 'Approved and rejected word revisions are immutable; create a new revision';
    END IF;
    -- Authorship is fixed at creation. Otherwise an author could reassign the
    -- draft to someone else and then "independently" review it.
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.word_id IS DISTINCT FROM OLD.word_id
       OR NEW.locale IS DISTINCT FROM OLD.locale OR NEW.revision IS DISTINCT FROM OLD.revision
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'Word revision identity and authorship cannot be changed';
    END IF;
    v_content_changed :=
        NEW.term IS DISTINCT FROM OLD.term OR NEW.pronunciation IS DISTINCT FROM OLD.pronunciation
        OR NEW.part_of_speech IS DISTINCT FROM OLD.part_of_speech
        OR NEW.definition IS DISTINCT FROM OLD.definition OR NEW.example IS DISTINCT FROM OLD.example
        OR NEW.gloss IS DISTINCT FROM OLD.gloss OR NEW.source_id IS DISTINCT FROM OLD.source_id;

    IF OLD.status = 'draft' THEN
        IF NEW.status = 'draft' THEN
            RETURN NEW;
        END IF;
        IF NEW.status <> 'in_review' THEN
            RAISE EXCEPTION 'Invalid word revision transition';
        END IF;
        IF v_content_changed THEN
            RAISE EXCEPTION 'Submit a draft without changing it in the same step';
        END IF;
        RETURN NEW;
    END IF;

    -- OLD.status = 'in_review': the exact snapshot a reviewer reads is frozen.
    IF v_content_changed THEN
        RAISE EXCEPTION 'Submitted content cannot be modified; create a new revision';
    END IF;
    IF NEW.status = 'in_review' THEN
        RETURN NEW;
    END IF;
    IF NEW.status = 'draft' THEN
        RAISE EXCEPTION 'Invalid word revision transition';
    END IF;

    -- The LATEST review decides (role checked separately: a reviewer holding
    -- two role rows must not produce two rows here).
    SELECT r.verdict, r.reviewer_id INTO v_latest_verdict, v_latest_reviewer
    FROM vocab.reviews r
    WHERE r.word_revision_id = OLD.id
    ORDER BY r.reviewed_at DESC, r.id DESC
    LIMIT 1;

    IF NEW.status = 'rejected' THEN
        IF v_latest_verdict IS DISTINCT FROM 'rejected' THEN
            RAISE EXCEPTION 'Rejection requires the latest review to be a rejection';
        END IF;
        RETURN NEW;
    END IF;

    -- NEW.status = 'approved'
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

    -- Rights gate. FOR SHARE: a concurrent withdrawal of rights waits for us
    -- (or we see it), so "approved with uncleared rights" cannot be committed.
    IF NOT EXISTS (
        SELECT 1 FROM vocab.sources s
        WHERE s.id = OLD.source_id AND s.rights_status = 'cleared'
        FOR SHARE
    ) THEN
        RAISE EXCEPTION 'Approval requires a rights-cleared source record';
    END IF;
    IF EXISTS (
        SELECT 1 FROM vocab.audio_assets a
        JOIN vocab.sources s ON s.id = a.source_id
        WHERE a.word_revision_id = OLD.id AND s.rights_status <> 'cleared'
    ) THEN
        RAISE EXCEPTION 'Approval requires the recording''s rights to be cleared';
    END IF;

    -- The approval time is the server's, not the caller's.
    NEW.approved_at := now();
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_word_revision
BEFORE UPDATE OR DELETE ON vocab.word_revisions
FOR EACH ROW EXECUTE FUNCTION vocab.protect_word_revision();

-- ============================================================================
-- GUARDS: reviews
-- ============================================================================
CREATE FUNCTION vocab.validate_review()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_created_by uuid; v_status text;
BEGIN
    -- Locks the revision so reviews, content edits and approval are serialised.
    SELECT r.created_by, r.status INTO v_created_by, v_status
    FROM vocab.word_revisions r WHERE r.id = NEW.word_revision_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Word revision does not exist';
    END IF;
    IF v_status <> 'in_review' THEN
        RAISE EXCEPTION 'Only a submitted word revision can be reviewed';
    END IF;
    IF v_created_by = NEW.reviewer_id THEN
        RAISE EXCEPTION 'Author cannot review own word';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM app.staff_roles sr
        WHERE sr.user_id = NEW.reviewer_id AND sr.is_active
          AND sr.role IN ('reviewer','admin')
    ) THEN
        RAISE EXCEPTION 'Reviewer role required';
    END IF;
    -- Approval looks at the LATEST review, so the review time must be the
    -- server's clock (a future-dated review could stay "latest" forever).
    NEW.reviewed_at := clock_timestamp();
    RETURN NEW;
END;
$$;
CREATE TRIGGER validate_review
BEFORE INSERT ON vocab.reviews
FOR EACH ROW EXECUTE FUNCTION vocab.validate_review();

CREATE FUNCTION vocab.prevent_append_only_change()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    RAISE EXCEPTION 'Append-only records cannot be updated or deleted';
END;
$$;
CREATE TRIGGER no_edit_reviews BEFORE UPDATE OR DELETE ON vocab.reviews
    FOR EACH ROW EXECUTE FUNCTION vocab.prevent_append_only_change();

-- ============================================================================
-- GUARDS: audio metadata
-- ============================================================================
-- A recording is part of the snapshot a reviewer approves: it can only be
-- attached, changed or removed while the revision is still a draft.
CREATE FUNCTION vocab.protect_audio_asset()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_parent_id uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.word_revision_id <> OLD.word_revision_id THEN
        RAISE EXCEPTION 'A recording cannot move to another word revision';
    END IF;
    v_parent_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.word_revision_id
                        ELSE NEW.word_revision_id END;
    -- Serialise against a concurrent submit / review of the parent.
    PERFORM 1 FROM vocab.word_revisions r WHERE r.id = v_parent_id FOR SHARE;
    IF EXISTS (SELECT 1 FROM vocab.word_revisions r
               WHERE r.id = v_parent_id AND r.status <> 'draft') THEN
        RAISE EXCEPTION 'Recordings of submitted, approved or rejected words are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER protect_audio_asset
BEFORE INSERT OR UPDATE OR DELETE ON vocab.audio_assets
FOR EACH ROW EXECUTE FUNCTION vocab.protect_audio_asset();

-- ============================================================================
-- GUARDS: the daily schedule
-- ============================================================================
-- * A date that has OPENED in Haiti (today or earlier) is frozen: its rows can
--   never be updated or deleted, by anyone.
-- * A date in the past can never receive a row (history is not back-filled).
-- * Today can receive a row only if it has none yet (a late fill of a day that
--   had no word; nothing a learner already saw is replaced).
-- * Future dates can be scheduled and rescheduled, at most 366 days ahead.
-- * Only an APPROVED revision of an ACTIVE word with CLEARED rights is assignable.
-- The clock is clock_timestamp() (the real instant of the write), not now()
-- (transaction start), so a transaction left open across midnight cannot
-- rewrite the day that opened meanwhile. Residual window: docs lane note.
CREATE FUNCTION vocab.guard_daily_assignment()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_today date := vocab.haiti_date(clock_timestamp());
BEGIN
    IF TG_OP IN ('UPDATE','DELETE') AND OLD.haiti_date <= v_today THEN
        RAISE EXCEPTION 'The word of a day that has already opened cannot be changed';
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
CREATE TRIGGER guard_daily_assignment
BEFORE INSERT OR UPDATE OR DELETE ON vocab.daily_assignments
FOR EACH ROW EXECUTE FUNCTION vocab.guard_daily_assignment();

-- Checked at COMMIT (deferred), so one transaction may replace both locale rows
-- of a future date: every row of a date is the same word, and French exists.
CREATE FUNCTION vocab.check_daily_assignment_day()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_date date;
    v_rows integer;
    v_words integer;
    v_has_fr boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN v_date := OLD.haiti_date; ELSE v_date := NEW.haiti_date; END IF;
    SELECT count(*), count(DISTINCT a.word_id), COALESCE(bool_or(a.locale = 'fr'), false)
      INTO v_rows, v_words, v_has_fr
    FROM vocab.daily_assignments a WHERE a.haiti_date = v_date;
    IF v_rows > 0 AND (v_words <> 1 OR NOT v_has_fr) THEN
        RAISE EXCEPTION 'A day needs one word for all its locales, including French';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER check_daily_assignment_day
AFTER INSERT OR UPDATE OR DELETE ON vocab.daily_assignments
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION vocab.check_daily_assignment_day();

-- ============================================================================
-- Privileges. PostgreSQL grants EXECUTE on new functions to PUBLIC by default
-- and that default cannot be revoked per schema, so every migration that
-- creates functions ends with an explicit REVOKE (same rule as schema `app`).
-- ============================================================================
REVOKE ALL ON ALL TABLES IN SCHEMA vocab FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA vocab FROM PUBLIC, anon, authenticated;
