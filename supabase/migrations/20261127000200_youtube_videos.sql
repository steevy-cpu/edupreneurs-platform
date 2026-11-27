-- YouTube-01: teacher-approved YouTube videos attached to lessons (metadata only).
--
-- What is stored: the 11-character video id and a SMALL, bounded copy of public
-- metadata returned by the YouTube Data API `videos.list` (title, channel, duration,
-- status flags), with the time it was fetched. No audiovisual content, no thumbnail
-- image, no search results, and nothing about any learner.
--
-- Rules enforced in the database:
--   1. A learner (the `edu_api` role) can see a lesson-video link ONLY when ALL hold:
--        * the link is approved by a reviewer who is not the person who proposed it;
--        * the video is active (not disabled or withdrawn by staff);
--        * the last metadata check found it public or unlisted, processed, embeddable,
--          not age-restricted and not blocked in Haiti;
--        * that check is not older than its expiry (at most 30 days: see the policy
--          report on stored API data);
--        * the lesson itself is visible.
--      Anything else is simply absent, so the lesson renders without the video.
--   2. If the channel, the Made-for-Kids designation, the age rating or the
--      embeddability of a video changes, every approved link to it goes back to
--      `needs_review`: a teacher must look again.
--   3. The student API role has no write privilege on these tables.
--
-- Rollback: additive only. `DROP TABLE app.lesson_video_links, app.videos CASCADE`
-- and dropping the two trigger functions restores the previous schema.

CREATE TABLE app.videos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL DEFAULT 'youtube' CHECK (provider = 'youtube'),
    -- Exactly the YouTube id alphabet and length. Anything else (a URL, a script,
    -- whitespace, a playlist id) cannot be stored.
    provider_video_id text NOT NULL UNIQUE CHECK (provider_video_id ~ '^[A-Za-z0-9_-]{11}$'),
    title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    channel_id text NOT NULL CHECK (channel_id ~ '^UC[A-Za-z0-9_-]{22}$'),
    channel_title text NOT NULL CHECK (char_length(channel_title) BETWEEN 1 AND 120),
    duration_seconds integer NOT NULL CHECK (duration_seconds BETWEEN 1 AND 14400),
    -- Language spoken in the video, when the channel declared it (BCP-47, e.g. fr, ht, en).
    audio_language text CHECK (audio_language IS NULL OR audio_language ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$'),
    -- status.madeForKids as returned by the API. Not a reason to hide a video; the
    -- client must not add engagement features around it (see the mobile handoff).
    made_for_kids boolean NOT NULL,
    age_restricted boolean NOT NULL,
    embeddable boolean NOT NULL,
    privacy_status text NOT NULL CHECK (privacy_status IN ('public','unlisted','private')),
    upload_status text NOT NULL CHECK (upload_status IN ('processed','uploaded','failed','rejected','deleted')),
    blocked_in_ht boolean NOT NULL,
    -- Last time the provider was asked about this video, and when that answer stops
    -- being usable. A video whose check has expired is hidden until it is refreshed.
    metadata_fetched_at timestamptz NOT NULL,
    metadata_expires_at timestamptz NOT NULL,
    -- 'removed' = the provider no longer returns the video (deleted, private, terminated).
    availability text NOT NULL CHECK (availability IN ('available','removed')),
    -- Staff control, independent of the provider.
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled','withdrawn')),
    status_reason text CHECK (status_reason IS NULL OR char_length(status_reason) BETWEEN 1 AND 500),
    legacy_ref text UNIQUE CHECK (legacy_ref IS NULL OR char_length(legacy_ref) BETWEEN 1 AND 120),
    created_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT videos_metadata_window CHECK (
        metadata_expires_at > metadata_fetched_at
        AND metadata_expires_at <= metadata_fetched_at + interval '30 days'
    ),
    CONSTRAINT videos_disabled_has_reason CHECK (status = 'active' OR status_reason IS NOT NULL)
);

CREATE TABLE app.lesson_video_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lesson_id uuid NOT NULL REFERENCES app.lessons(id) ON DELETE RESTRICT,
    video_id uuid NOT NULL REFERENCES app.videos(id) ON DELETE RESTRICT,
    -- Lesson languages this video is shown with (a French video may suit both).
    locales text[] NOT NULL CHECK (cardinality(locales) BETWEEN 1 AND 2 AND locales <@ ARRAY['fr','ht']::text[]),
    position smallint NOT NULL CHECK (position BETWEEN 1 AND 20),
    purpose text NOT NULL DEFAULT 'explanation' CHECK (purpose IN ('explanation','example','exercise_help','enrichment')),
    start_seconds integer NOT NULL DEFAULT 0 CHECK (start_seconds >= 0),
    review_status text NOT NULL DEFAULT 'proposed'
        CHECK (review_status IN ('proposed','approved','needs_review','rejected','withdrawn')),
    -- Where the proposal came from. Automatic suggestions are only ever proposals.
    source text NOT NULL CHECK (source IN ('teacher','staff_search','legacy_import','ai_suggestion')),
    proposed_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    reviewed_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    reviewed_at timestamptz,
    review_note text CHECK (review_note IS NULL OR char_length(review_note) BETWEEN 1 AND 1000),
    legacy_ref text CHECK (legacy_ref IS NULL OR char_length(legacy_ref) BETWEEN 1 AND 120),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (lesson_id, video_id),
    UNIQUE (lesson_id, position),
    CONSTRAINT links_approval_is_by_someone_else CHECK (
        review_status <> 'approved'
        OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_by <> proposed_by)
    )
);
CREATE INDEX idx_lesson_video_links_video ON app.lesson_video_links(video_id);

-- An approval must come from an active reviewer, and only for a video that is
-- currently presentable; the start offset must fall inside the video.
CREATE FUNCTION app.video_link_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    v app.videos%ROWTYPE;
BEGIN
    SELECT * INTO v FROM app.videos WHERE id = NEW.video_id;
    IF NEW.start_seconds >= v.duration_seconds THEN
        RAISE EXCEPTION 'start_seconds must be inside the video' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.review_status = 'approved'
       AND (TG_OP = 'INSERT' OR OLD.review_status IS DISTINCT FROM 'approved'
            OR OLD.reviewed_by IS DISTINCT FROM NEW.reviewed_by) THEN
        IF NOT EXISTS (
            SELECT 1 FROM app.staff_roles sr
            WHERE sr.user_id = NEW.reviewed_by AND sr.role IN ('reviewer','admin') AND sr.is_active
        ) THEN
            RAISE EXCEPTION 'only an active reviewer can approve a lesson video'
                USING ERRCODE = 'check_violation';
        END IF;
        IF NOT (v.status = 'active' AND v.availability = 'available' AND v.embeddable
                AND NOT v.age_restricted AND NOT v.blocked_in_ht
                AND v.privacy_status IN ('public','unlisted') AND v.upload_status = 'processed'
                AND v.metadata_expires_at > now()) THEN
            RAISE EXCEPTION 'this video cannot be approved: it is not currently presentable (status, availability, embedding, age rating, region or expired metadata)'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER lesson_video_links_guard
    BEFORE INSERT OR UPDATE ON app.lesson_video_links
    FOR EACH ROW EXECUTE FUNCTION app.video_link_guard();

-- A material change to a video sends every approved link back to a teacher.
CREATE FUNCTION app.video_material_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    IF NEW.channel_id IS DISTINCT FROM OLD.channel_id
       OR NEW.made_for_kids IS DISTINCT FROM OLD.made_for_kids
       OR NEW.age_restricted IS DISTINCT FROM OLD.age_restricted
       OR NEW.embeddable IS DISTINCT FROM OLD.embeddable
       OR abs(NEW.duration_seconds - OLD.duration_seconds) > 5 THEN
        UPDATE app.lesson_video_links
        SET review_status = 'needs_review',
            review_note = left('Video metadata changed on ' || to_char(now(), 'YYYY-MM-DD')
                               || '; please review again.', 1000)
        WHERE video_id = NEW.id AND review_status = 'approved';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER videos_material_change
    AFTER UPDATE ON app.videos
    FOR EACH ROW EXECUTE FUNCTION app.video_material_change();

ALTER TABLE app.videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.lesson_video_links ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.videos, app.lesson_video_links FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION app.video_link_guard(), app.video_material_change() FROM PUBLIC, anon, authenticated;

-- The student API role reads only what a learner may see: no reviewer identities,
-- notes, staff reasons or legacy references.
GRANT SELECT (id, provider, provider_video_id, title, channel_id, channel_title, duration_seconds,
              audio_language, made_for_kids, metadata_fetched_at)
    ON app.videos TO edu_api;
GRANT SELECT (id, lesson_id, video_id, locales, position, purpose, start_seconds)
    ON app.lesson_video_links TO edu_api;

CREATE POLICY videos_read_presentable ON app.videos FOR SELECT TO edu_api
    USING (status = 'active' AND availability = 'available' AND embeddable
           AND NOT age_restricted AND NOT blocked_in_ht
           AND privacy_status IN ('public','unlisted') AND upload_status = 'processed'
           AND metadata_expires_at > now());
CREATE POLICY lesson_video_links_read_approved ON app.lesson_video_links FOR SELECT TO edu_api
    USING (review_status = 'approved'
           AND EXISTS (SELECT 1 FROM app.videos v WHERE v.id = lesson_video_links.video_id)
           AND EXISTS (SELECT 1 FROM app.lessons l WHERE l.id = lesson_video_links.lesson_id));
