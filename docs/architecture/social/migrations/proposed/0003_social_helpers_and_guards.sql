-- ============================================================================
-- PROPOSED — NOT APPLIED. Social-00 design artefact (see 0001 header).
-- ============================================================================
-- Edupreneurs 2.0 — social module: helper functions and integrity triggers
--
-- Triggers are used for the rules that must hold for EVERY writer — the API, a
-- future worker, or a person in a SQL console — exactly as the `app` schema does
-- for lesson publication.
--
-- All functions: empty search_path, no dynamic SQL, schema-qualified names.

-- ----------------------------------------------------------------------------
-- Read helpers (used by row-level-security policies and by the write functions)
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.actor_has_staff_role(p_roles text[])
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT EXISTS (
        SELECT 1 FROM social.staff_roles s
        WHERE s.user_id = social.current_actor_id() AND s.is_active AND s.role = ANY (p_roles)
    )
$$;

-- The caller's standing, optionally for one community:
--   'ok' | 'not_enrolled' | 'not_active' | 'suspended' | 'not_member'
-- Checked on every request, so a suspension takes effect immediately even though
-- the access token itself stays valid for up to an hour.
CREATE FUNCTION social.actor_access(p_community_id uuid DEFAULT NULL)
RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.current_actor_id();
    v_status text;
BEGIN
    IF v_actor IS NULL THEN
        RETURN 'not_enrolled';
    END IF;
    SELECT e.status INTO v_status FROM social.enrollments e WHERE e.user_id = v_actor;
    IF NOT FOUND THEN
        RETURN 'not_enrolled';
    END IF;
    IF v_status <> 'active' THEN
        RETURN 'not_active';
    END IF;
    IF EXISTS (
        SELECT 1 FROM social.sanctions s
        WHERE s.user_id = v_actor
          AND s.kind IN ('suspension', 'ban')
          AND s.lifted_at IS NULL
          AND s.starts_at <= now()
          AND (s.ends_at IS NULL OR s.ends_at > now())
          AND (s.community_id IS NULL OR s.community_id = p_community_id)
    ) THEN
        RETURN 'suspended';
    END IF;
    IF p_community_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM social.memberships m
        WHERE m.community_id = p_community_id AND m.user_id = v_actor AND m.status = 'active'
    ) THEN
        RETURN 'not_member';
    END IF;
    RETURN 'ok';
END $$;

CREATE FUNCTION social.can_read_community(p_community_id uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT social.actor_access(p_community_id) = 'ok'
       AND EXISTS (
           SELECT 1 FROM social.communities c
           WHERE c.id = p_community_id AND c.status IN ('open', 'frozen'))
$$;

-- Is there a block in EITHER direction between the caller and this user?
CREATE FUNCTION social.blocked_with(p_other uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT EXISTS (
        SELECT 1 FROM social.blocks b
        WHERE (b.blocker_id = social.current_actor_id() AND b.blocked_id = p_other)
           OR (b.blocker_id = p_other AND b.blocked_id = social.current_actor_id())
    )
$$;

-- Profiles are visible only to people who share an active community.
CREATE FUNCTION social.shares_community_with(p_other uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM social.memberships mine
        JOIN social.memberships theirs ON theirs.community_id = mine.community_id
        JOIN social.communities c ON c.id = mine.community_id
        WHERE mine.user_id = social.current_actor_id() AND mine.status = 'active'
          AND theirs.user_id = p_other AND theirs.status = 'active'
          AND c.status IN ('open', 'frozen')
    )
$$;

-- The caller's own grade band (a column the API role cannot read directly).
CREATE FUNCTION social.actor_grade_band()
RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT p.grade_band FROM social.profiles p WHERE p.user_id = social.current_actor_id()
$$;

-- Why the caller may NOT write here, as an API error code; NULL when allowed.
-- p_capability: 'post' | 'comment' | 'react'
CREATE FUNCTION social.write_denial(p_community_id uuid, p_capability text)
RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.current_actor_id();
    v_access text := social.actor_access(p_community_id);
    v_cfg social.config%ROWTYPE;
    v_community record;
    v_settings record;
    v_guidelines text;
BEGIN
    IF v_access <> 'ok' THEN
        RETURN CASE v_access
            WHEN 'not_enrolled' THEN 'social_not_enrolled'
            WHEN 'not_active' THEN 'social_not_active'
            WHEN 'suspended' THEN 'social_suspended'
            ELSE 'not_a_member'
        END;
    END IF;
    SELECT * INTO v_cfg FROM social.config;
    IF NOT v_cfg.submissions_open THEN
        RETURN 'submissions_closed';
    END IF;
    SELECT c.status, c.posting INTO v_community FROM social.communities c WHERE c.id = p_community_id;
    IF NOT FOUND OR v_community.status <> 'open' THEN
        RETURN 'community_read_only';
    END IF;
    SELECT e.guidelines_version INTO v_guidelines FROM social.enrollments e WHERE e.user_id = v_actor;
    IF v_guidelines IS DISTINCT FROM v_cfg.guidelines_version THEN
        RETURN 'guidelines_not_accepted';
    END IF;
    IF EXISTS (
        SELECT 1 FROM social.sanctions s
        WHERE s.user_id = v_actor AND s.kind = 'mute' AND s.lifted_at IS NULL
          AND s.starts_at <= now() AND s.ends_at > now()
          AND (s.community_id IS NULL OR s.community_id = p_community_id)
    ) THEN
        RETURN 'social_muted';
    END IF;
    SELECT s.can_post, s.can_comment, s.can_react INTO v_settings
    FROM social.safety_settings s WHERE s.user_id = v_actor;
    IF FOUND AND (
           (p_capability = 'post' AND NOT v_settings.can_post)
        OR (p_capability = 'comment' AND NOT v_settings.can_comment)
        OR (p_capability = 'react' AND NOT v_settings.can_react)
    ) THEN
        RETURN 'capability_disabled';
    END IF;
    IF p_capability = 'post' AND v_community.posting = 'staff_only' AND NOT EXISTS (
        SELECT 1 FROM social.memberships m
        WHERE m.community_id = p_community_id AND m.user_id = v_actor
          AND m.status = 'active' AND m.role = 'teacher'
    ) THEN
        RETURN 'posting_restricted';
    END IF;
    RETURN NULL;
END $$;

-- ----------------------------------------------------------------------------
-- Internal helpers. NOT granted to any API role: they are only called from the
-- SECURITY DEFINER functions in 0004 / 0005, which run with the owner's rights.
-- ----------------------------------------------------------------------------
-- Takes the visibility clock's row lock until the end of the transaction.
CREATE FUNCTION social.next_visibility_seq()
RETURNS bigint
LANGUAGE sql VOLATILE
SET search_path = ''
AS $$
    UPDATE social.visibility_clock SET current_seq = current_seq + 1 RETURNING current_seq
$$;

-- Counts one hit in a fixed window and says whether the caller is still within
-- the limit. The API COMMITS a refused request too, so refused attempts count.
CREATE FUNCTION social.bump_rate(p_user uuid, p_bucket text, p_window_seconds integer, p_limit integer)
RETURNS boolean
LANGUAGE plpgsql VOLATILE
SET search_path = ''
AS $$
DECLARE
    v_start timestamptz := to_timestamp(
        floor(extract(epoch FROM now()) / p_window_seconds) * p_window_seconds);
    v_hits integer;
BEGIN
    INSERT INTO social.rate_counters AS rc (user_id, bucket, window_start, hits)
    VALUES (p_user, p_bucket, v_start, 1)
    ON CONFLICT (user_id, bucket, window_start) DO UPDATE SET hits = rc.hits + 1
    RETURNING rc.hits INTO v_hits;
    RETURN v_hits <= p_limit;
END $$;

CREATE FUNCTION social.seconds_to_window_end(p_window_seconds integer)
RETURNS integer
LANGUAGE sql STABLE
SET search_path = ''
AS $$
    SELECT (p_window_seconds - (floor(extract(epoch FROM now()))::bigint % p_window_seconds))::integer
$$;

CREATE FUNCTION social.write_audit(
    p_actor_kind text, p_action text, p_target_kind text, p_target_id uuid,
    p_outcome text, p_details jsonb DEFAULT '{}'::jsonb)
RETURNS void
LANGUAGE sql VOLATILE
SET search_path = ''
AS $$
    INSERT INTO social.audit_events (actor_id, actor_kind, action, target_kind, target_id, outcome, details)
    VALUES (social.current_actor_id(), p_actor_kind, p_action, p_target_kind, p_target_id, p_outcome, p_details)
$$;

-- Adds a notification event, respecting the recipient's own switch. "New
-- comment on your post" events are merged into one unread row per post.
CREATE FUNCTION social.notify(
    p_recipient uuid, p_kind text, p_post_id uuid, p_comment_id uuid, p_community_id uuid)
RETURNS void
LANGUAGE plpgsql VOLATILE
SET search_path = ''
AS $$
DECLARE
    v_days integer;
BEGIN
    IF p_recipient IS NULL OR NOT EXISTS (SELECT 1 FROM social.profiles p WHERE p.user_id = p_recipient) THEN
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1 FROM social.safety_settings s
        WHERE s.user_id = p_recipient AND NOT s.notifications_enabled
    ) AND p_kind NOT IN ('sanction_notice', 'content_removed') THEN
        RETURN;
    END IF;
    IF p_kind = 'comment_on_post' THEN
        UPDATE social.notification_events n
        SET actor_count = n.actor_count + 1, created_at = now()
        WHERE n.recipient_id = p_recipient AND n.kind = p_kind
          AND n.post_id = p_post_id AND n.read_at IS NULL;
        IF FOUND THEN
            RETURN;
        END IF;
    END IF;
    SELECT c.retain_notifications_days INTO v_days FROM social.config c;
    INSERT INTO social.notification_events (recipient_id, kind, post_id, comment_id, community_id, expires_at)
    VALUES (p_recipient, p_kind, p_post_id, p_comment_id, p_community_id, now() + make_interval(days => v_days));
END $$;

-- ----------------------------------------------------------------------------
-- Guard: content can only be born as "waiting for review"
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.content_insert_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    IF NEW.status <> 'pending_review' OR NEW.publish_seq IS NOT NULL OR NEW.change_seq IS NOT NULL
       OR NEW.published_at IS NOT NULL OR NEW.author_id IS NULL THEN
        RAISE EXCEPTION 'social content must be inserted as pending_review by a known author'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;

-- ----------------------------------------------------------------------------
-- Guard: the content lifecycle, immutability of approved text, and the
-- "approved by someone else" rule. Shared by posts and comments.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.content_update_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    v_approved boolean;
BEGIN
    IF NEW.id <> OLD.id OR NEW.community_id <> OLD.community_id
       OR NEW.client_op_id <> OLD.client_op_id OR NEW.submitted_at <> OLD.submitted_at
       OR NEW.body_sha256 <> OLD.body_sha256 THEN
        RAISE EXCEPTION 'identity columns of social content are immutable' USING ERRCODE = '23514';
    END IF;
    -- Nested on purpose: PL/pgSQL plans a whole condition at once, and the posts
    -- table has no post_id column for it to resolve.
    IF TG_TABLE_NAME = 'comments' THEN
        IF NEW.post_id <> OLD.post_id OR NEW.parent_comment_id IS DISTINCT FROM OLD.parent_comment_id THEN
            RAISE EXCEPTION 'a comment cannot be moved' USING ERRCODE = '23514';
        END IF;
    END IF;
    -- The author can only ever change to NULL (account erasure).
    IF NEW.author_id IS DISTINCT FROM OLD.author_id AND NEW.author_id IS NOT NULL THEN
        RAISE EXCEPTION 'the author of social content cannot be changed' USING ERRCODE = '23514';
    END IF;
    IF OLD.publish_seq IS NOT NULL AND NEW.publish_seq IS DISTINCT FROM OLD.publish_seq THEN
        RAISE EXCEPTION 'publish_seq is immutable once assigned' USING ERRCODE = '23514';
    END IF;
    -- The text never changes. It can only be erased, and only in a final state.
    IF NEW.body IS DISTINCT FROM OLD.body THEN
        IF NEW.body IS NOT NULL OR NEW.status NOT IN ('rejected', 'removed', 'deleted') THEN
            RAISE EXCEPTION 'the text of social content is immutable' USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.status <> OLD.status THEN
        IF NOT (
               (OLD.status = 'pending_review' AND NEW.status IN ('published', 'rejected', 'deleted'))
            OR (OLD.status = 'published' AND NEW.status IN ('hidden', 'removed', 'deleted'))
            OR (OLD.status = 'hidden' AND NEW.status IN ('published', 'removed', 'deleted'))
        ) THEN
            RAISE EXCEPTION 'illegal social content transition % -> %', OLD.status, NEW.status
                USING ERRCODE = '23514';
        END IF;

        IF NEW.status = 'published' THEN
            -- THE CORE SAFETY INVARIANT: an approval (or a restore after a report was
            -- dismissed) of exactly this text, by someone who is not its author.
            IF TG_TABLE_NAME = 'posts' THEN
                SELECT EXISTS (
                    SELECT 1 FROM social.moderation_actions a
                    WHERE a.post_id = NEW.id
                      AND a.action = CASE WHEN OLD.status = 'hidden' THEN 'restore' ELSE 'approve' END
                      AND a.content_sha256 = NEW.body_sha256
                      AND a.actor_id IS NOT NULL
                      AND a.actor_id IS DISTINCT FROM NEW.author_id
                ) INTO v_approved;
            ELSE
                SELECT EXISTS (
                    SELECT 1 FROM social.moderation_actions a
                    WHERE a.comment_id = NEW.id
                      AND a.action = CASE WHEN OLD.status = 'hidden' THEN 'restore' ELSE 'approve' END
                      AND a.content_sha256 = NEW.body_sha256
                      AND a.actor_id IS NOT NULL
                      AND a.actor_id IS DISTINCT FROM NEW.author_id
                ) INTO v_approved;
            END IF;
            IF NOT v_approved THEN
                RAISE EXCEPTION 'social content cannot be published without an independent approval'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        NEW.status_changed_at := now();
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER posts_insert_guard BEFORE INSERT ON social.posts
    FOR EACH ROW EXECUTE FUNCTION social.content_insert_guard();
CREATE TRIGGER posts_update_guard BEFORE UPDATE ON social.posts
    FOR EACH ROW EXECUTE FUNCTION social.content_update_guard();
CREATE TRIGGER comments_insert_guard BEFORE INSERT ON social.comments
    FOR EACH ROW EXECUTE FUNCTION social.content_insert_guard();
CREATE TRIGGER comments_update_guard BEFORE UPDATE ON social.comments
    FOR EACH ROW EXECUTE FUNCTION social.content_update_guard();

-- ----------------------------------------------------------------------------
-- Guard: replies are one level deep
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.comment_depth_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    IF NEW.parent_comment_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM social.comments c
        WHERE c.id = NEW.parent_comment_id AND c.parent_comment_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'a reply cannot itself be replied to' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER comments_depth_guard BEFORE INSERT ON social.comments
    FOR EACH ROW EXECUTE FUNCTION social.comment_depth_guard();

-- ----------------------------------------------------------------------------
-- Guard: an ACTIVE membership needs an active enrolment, the right grade band,
-- and a free seat. A teacher role needs a teacher or staff account.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.membership_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    v_profile record;
    v_community record;
BEGIN
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status = 'active' AND NEW.role = OLD.role THEN
        RETURN NEW;
    END IF;
    SELECT p.account_kind, p.grade_band, e.status AS enrollment_status INTO v_profile
    FROM social.profiles p
    LEFT JOIN social.enrollments e ON e.user_id = p.user_id
    WHERE p.user_id = NEW.user_id;
    IF v_profile.enrollment_status IS DISTINCT FROM 'active' THEN
        RAISE EXCEPTION 'only an actively enrolled participant can be an active member'
            USING ERRCODE = '23514';
    END IF;
    SELECT c.grade_band, c.member_limit, c.status INTO v_community
    FROM social.communities c WHERE c.id = NEW.community_id FOR UPDATE;
    IF v_community.status = 'archived' THEN
        RAISE EXCEPTION 'an archived community accepts no members' USING ERRCODE = '23514';
    END IF;
    IF NEW.role = 'teacher' AND v_profile.account_kind = 'learner' THEN
        RAISE EXCEPTION 'a learner account cannot hold the teacher role' USING ERRCODE = '23514';
    END IF;
    IF v_profile.account_kind = 'learner' AND v_profile.grade_band IS DISTINCT FROM v_community.grade_band THEN
        RAISE EXCEPTION 'learner grade band does not match the community' USING ERRCODE = '23514';
    END IF;
    IF (SELECT count(*) FROM social.memberships m
        WHERE m.community_id = NEW.community_id AND m.status = 'active'
          AND m.user_id <> NEW.user_id) >= v_community.member_limit THEN
        RAISE EXCEPTION 'the community is full' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER memberships_guard BEFORE INSERT OR UPDATE ON social.memberships
    FOR EACH ROW EXECUTE FUNCTION social.membership_guard();

-- ----------------------------------------------------------------------------
-- Guard: moderation actions and audit events are append-only. Rows can be
-- deleted only after the configured retention period (by the retention job).
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.append_only_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    v_days integer;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '23514';
    END IF;
    SELECT c.retain_actions_days INTO v_days FROM social.config c;
    IF OLD.created_at > now() - make_interval(days => v_days) THEN
        RAISE EXCEPTION '% rows cannot be deleted before the retention period ends', TG_TABLE_NAME
            USING ERRCODE = '23514';
    END IF;
    RETURN OLD;
END $$;

CREATE TRIGGER moderation_actions_append_only BEFORE UPDATE OR DELETE ON social.moderation_actions
    FOR EACH ROW EXECUTE FUNCTION social.append_only_guard();
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON social.audit_events
    FOR EACH ROW EXECUTE FUNCTION social.append_only_guard();
