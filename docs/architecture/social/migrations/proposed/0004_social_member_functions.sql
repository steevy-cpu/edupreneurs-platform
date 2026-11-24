-- ============================================================================
-- PROPOSED — NOT APPLIED. Social-00 design artefact (see 0001 header).
-- ============================================================================
-- Edupreneurs 2.0 — social module: the member write boundary
--
-- The student-facing role (edu_social) has NO INSERT / UPDATE / DELETE privilege
-- on any social table. These functions are the only way in, and each one does
-- everything that must be true together in one transaction.
--
-- Shared rules:
--   * The caller is ALWAYS social.current_actor_id(). No function takes a
--     "user id of the caller" parameter.
--   * Expected refusals ("you are muted", "too many posts today") are RETURNED
--     as {"result": "<code>"} and the transaction COMMITS, so rate counters and
--     audit rows survive. Only programming errors RAISE.
--   * Each call first locks the caller's own enrolment row. One learner's social
--     writes therefore run one at a time, which makes retries and double-taps safe.
--   * Lock order, to avoid deadlocks: caller's enrolment -> comment -> post ->
--     moderation item -> visibility clock.
--
-- Residual trust (same as app.sync_apply_operation): the functions trust the API
-- for the actor id, the text digest and the local screening result.

CREATE FUNCTION social.lock_actor()
RETURNS uuid
LANGUAGE plpgsql VOLATILE
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.current_actor_id();
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    PERFORM 1 FROM social.enrollments e WHERE e.user_id = v_actor FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    RETURN v_actor;
END $$;

-- ----------------------------------------------------------------------------
-- Posts
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.submit_post(
    p_client_op_id uuid,
    p_community_id uuid,
    p_kind text,
    p_locale text,
    p_body text,
    p_body_sha256 bytea,
    p_screening_version text,
    p_screening_flags jsonb
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.lock_actor();
    v_cfg social.config%ROWTYPE;
    v_existing record;
    v_denial text;
    v_post_id uuid;
BEGIN
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('result', 'social_not_enrolled');
    END IF;

    -- 1. Safe retry: the same client_op_id with the same text returns the first answer.
    SELECT p.id, p.status, p.body_sha256, p.community_id INTO v_existing
    FROM social.posts p WHERE p.author_id = v_actor AND p.client_op_id = p_client_op_id;
    IF FOUND THEN
        IF v_existing.body_sha256 = p_body_sha256 AND v_existing.community_id = p_community_id THEN
            RETURN jsonb_build_object('result', 'ok', 'replayed', true,
                                      'post_id', v_existing.id, 'status', v_existing.status);
        END IF;
        RETURN jsonb_build_object('result', 'idempotency_conflict');
    END IF;

    -- 2. May this person write here, right now?
    v_denial := social.write_denial(p_community_id, 'post');
    IF v_denial IS NOT NULL THEN
        RETURN jsonb_build_object('result', v_denial);
    END IF;
    IF p_kind = 'announcement' AND NOT EXISTS (
        SELECT 1 FROM social.memberships m
        WHERE m.community_id = p_community_id AND m.user_id = v_actor
          AND m.status = 'active' AND m.role = 'teacher'
    ) THEN
        RETURN jsonb_build_object('result', 'posting_restricted');
    END IF;

    -- 3. Limits that keep the review queue small enough for a small team.
    SELECT * INTO v_cfg FROM social.config;
    IF (SELECT count(*) FROM social.posts p
        WHERE p.author_id = v_actor AND p.status = 'pending_review') >= v_cfg.max_pending_posts THEN
        RETURN jsonb_build_object('result', 'pending_limit_reached');
    END IF;
    IF NOT social.bump_rate(v_actor, 'post_day', 86400, v_cfg.max_posts_per_day) THEN
        RETURN jsonb_build_object('result', 'rate_limited',
                                  'retry_after_s', social.seconds_to_window_end(86400));
    END IF;

    -- 4. Store it as "waiting for review" and put it in the moderators' queue.
    INSERT INTO social.posts (community_id, author_id, client_op_id, kind, locale, body, body_sha256,
                              screening_version, screening_flags)
    VALUES (p_community_id, v_actor, p_client_op_id, p_kind, p_locale, p_body, p_body_sha256,
            p_screening_version, p_screening_flags)
    RETURNING id INTO v_post_id;

    INSERT INTO social.moderation_items (subject_kind, post_id, community_id, reason, priority, due_at)
    VALUES ('post', v_post_id, p_community_id, 'pre_publication',
            CASE WHEN jsonb_array_length(p_screening_flags) > 0 THEN 1 ELSE 2 END,
            now() + make_interval(hours => v_cfg.review_due_hours));

    RETURN jsonb_build_object('result', 'ok', 'replayed', false,
                              'post_id', v_post_id, 'status', 'pending_review');
END $$;

-- ----------------------------------------------------------------------------
-- Comments
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.submit_comment(
    p_client_op_id uuid,
    p_post_id uuid,
    p_parent_comment_id uuid,
    p_locale text,
    p_body text,
    p_body_sha256 bytea,
    p_screening_version text,
    p_screening_flags jsonb
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.lock_actor();
    v_cfg social.config%ROWTYPE;
    v_existing record;
    v_post record;
    v_denial text;
    v_comment_id uuid;
BEGIN
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('result', 'social_not_enrolled');
    END IF;

    SELECT c.id, c.status, c.body_sha256, c.post_id INTO v_existing
    FROM social.comments c WHERE c.author_id = v_actor AND c.client_op_id = p_client_op_id;
    IF FOUND THEN
        IF v_existing.body_sha256 = p_body_sha256 AND v_existing.post_id = p_post_id THEN
            RETURN jsonb_build_object('result', 'ok', 'replayed', true,
                                      'comment_id', v_existing.id, 'status', v_existing.status);
        END IF;
        RETURN jsonb_build_object('result', 'idempotency_conflict');
    END IF;

    -- The post must be something this person can see right now. Unknown, removed,
    -- other-community and blocked-author posts all give the SAME answer.
    SELECT p.community_id, p.author_id, p.status INTO v_post FROM social.posts p WHERE p.id = p_post_id;
    IF NOT FOUND OR v_post.status <> 'published' THEN
        RETURN jsonb_build_object('result', 'content_not_found');
    END IF;
    v_denial := social.write_denial(v_post.community_id, 'comment');
    IF v_denial = 'not_a_member' THEN
        RETURN jsonb_build_object('result', 'content_not_found');
    ELSIF v_denial IS NOT NULL THEN
        RETURN jsonb_build_object('result', v_denial);
    END IF;
    IF v_post.author_id IS NOT NULL AND social.blocked_with(v_post.author_id) THEN
        RETURN jsonb_build_object('result', 'content_not_found');
    END IF;
    IF p_parent_comment_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM social.comments c
        WHERE c.id = p_parent_comment_id AND c.post_id = p_post_id
          AND c.status = 'published' AND c.parent_comment_id IS NULL
          AND (c.author_id IS NULL OR NOT social.blocked_with(c.author_id))
    ) THEN
        RETURN jsonb_build_object('result', 'content_not_found');
    END IF;

    SELECT * INTO v_cfg FROM social.config;
    IF (SELECT count(*) FROM social.comments c
        WHERE c.author_id = v_actor AND c.status = 'pending_review') >= v_cfg.max_pending_comments THEN
        RETURN jsonb_build_object('result', 'pending_limit_reached');
    END IF;
    IF NOT social.bump_rate(v_actor, 'comment_day', 86400, v_cfg.max_comments_per_day) THEN
        RETURN jsonb_build_object('result', 'rate_limited',
                                  'retry_after_s', social.seconds_to_window_end(86400));
    END IF;

    INSERT INTO social.comments (post_id, community_id, parent_comment_id, author_id, client_op_id,
                                 locale, body, body_sha256, screening_version, screening_flags)
    VALUES (p_post_id, v_post.community_id, p_parent_comment_id, v_actor, p_client_op_id,
            p_locale, p_body, p_body_sha256, p_screening_version, p_screening_flags)
    RETURNING id INTO v_comment_id;

    INSERT INTO social.moderation_items (subject_kind, comment_id, community_id, reason, priority, due_at)
    VALUES ('comment', v_comment_id, v_post.community_id, 'pre_publication',
            CASE WHEN jsonb_array_length(p_screening_flags) > 0 THEN 1 ELSE 2 END,
            now() + make_interval(hours => v_cfg.review_due_hours));

    RETURN jsonb_build_object('result', 'ok', 'replayed', false,
                              'comment_id', v_comment_id, 'status', 'pending_review');
END $$;

-- ----------------------------------------------------------------------------
-- Reactions. p_kind NULL removes the caller's reaction. Naturally idempotent:
-- sending the same request twice leaves the same state.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.set_reaction(p_post_id uuid, p_comment_id uuid, p_kind text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid;
    v_cfg social.config%ROWTYPE;
    v_subject record;
    v_denial text;
    v_existing text;
    v_has boolean;
BEGIN
    IF num_nonnulls(p_post_id, p_comment_id) <> 1 THEN
        RAISE EXCEPTION 'exactly one of post id / comment id is required' USING ERRCODE = '22023';
    END IF;
    v_actor := social.lock_actor();
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('result', 'social_not_enrolled');
    END IF;

    IF p_post_id IS NOT NULL THEN
        SELECT p.community_id, p.author_id, p.status INTO v_subject
        FROM social.posts p WHERE p.id = p_post_id;
    ELSE
        -- A comment under a post that is no longer published is not reachable either.
        SELECT c.community_id, c.author_id,
               CASE WHEN p.status = 'published' THEN c.status ELSE 'hidden' END AS status
        INTO v_subject
        FROM social.comments c JOIN social.posts p ON p.id = c.post_id
        WHERE c.id = p_comment_id;
    END IF;
    IF NOT FOUND OR v_subject.status <> 'published' THEN
        RETURN jsonb_build_object('result', 'content_not_found');
    END IF;
    v_denial := social.write_denial(v_subject.community_id, 'react');
    IF v_denial = 'not_a_member' THEN
        RETURN jsonb_build_object('result', 'content_not_found');
    ELSIF v_denial IS NOT NULL THEN
        RETURN jsonb_build_object('result', v_denial);
    END IF;
    IF v_subject.author_id IS NOT NULL AND social.blocked_with(v_subject.author_id) THEN
        RETURN jsonb_build_object('result', 'content_not_found');
    END IF;
    IF v_subject.author_id = v_actor THEN
        RETURN jsonb_build_object('result', 'not_allowed');
    END IF;

    SELECT r.kind INTO v_existing FROM social.reactions r
    WHERE r.user_id = v_actor AND (r.post_id = p_post_id OR r.comment_id = p_comment_id);
    v_has := FOUND;

    IF p_kind IS NULL THEN
        IF v_has THEN
            DELETE FROM social.reactions r
            WHERE r.user_id = v_actor AND (r.post_id = p_post_id OR r.comment_id = p_comment_id);
            IF p_post_id IS NOT NULL THEN
                UPDATE social.posts SET reaction_count = GREATEST(reaction_count - 1, 0) WHERE id = p_post_id;
            ELSE
                UPDATE social.comments SET reaction_count = GREATEST(reaction_count - 1, 0) WHERE id = p_comment_id;
            END IF;
        END IF;
        RETURN jsonb_build_object('result', 'ok', 'my_reaction', NULL);
    END IF;

    IF v_has THEN
        IF v_existing <> p_kind THEN
            UPDATE social.reactions r SET kind = p_kind
            WHERE r.user_id = v_actor AND (r.post_id = p_post_id OR r.comment_id = p_comment_id);
        END IF;
        RETURN jsonb_build_object('result', 'ok', 'my_reaction', p_kind);
    END IF;

    SELECT * INTO v_cfg FROM social.config;
    IF NOT social.bump_rate(v_actor, 'reaction_day', 86400, v_cfg.max_reactions_per_day) THEN
        RETURN jsonb_build_object('result', 'rate_limited',
                                  'retry_after_s', social.seconds_to_window_end(86400));
    END IF;
    INSERT INTO social.reactions (user_id, post_id, comment_id, kind)
    VALUES (v_actor, p_post_id, p_comment_id, p_kind);
    IF p_post_id IS NOT NULL THEN
        UPDATE social.posts SET reaction_count = reaction_count + 1 WHERE id = p_post_id;
    ELSE
        UPDATE social.comments SET reaction_count = reaction_count + 1 WHERE id = p_comment_id;
    END IF;
    RETURN jsonb_build_object('result', 'ok', 'my_reaction', p_kind);
END $$;

-- ----------------------------------------------------------------------------
-- Reports. A report (a) is recorded with a copy of the text, (b) opens or
-- raises the priority of a moderation item, and (c) HIDES the content at once
-- when the category is severe or enough different members reported it.
-- The reporter is never told whether the content was hidden.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.file_report(
    p_post_id uuid,
    p_comment_id uuid,
    p_profile_user_id uuid,
    p_category text,
    p_note text
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid;
    v_cfg social.config%ROWTYPE;
    v_kind text;
    v_found boolean;
    v_access text;
    v_community uuid;
    v_target uuid;
    v_status text;
    v_snapshot text;
    v_parent_post uuid;
    v_report_id uuid;
    v_item_id uuid;
    v_severe boolean := p_category IN ('child_safety', 'sexual_content', 'self_harm', 'violence_threat');
    v_priority smallint;
    v_due timestamptz;
    v_seq bigint;
BEGIN
    IF num_nonnulls(p_post_id, p_comment_id, p_profile_user_id) <> 1 THEN
        RAISE EXCEPTION 'exactly one report subject is required' USING ERRCODE = '22023';
    END IF;
    v_actor := social.lock_actor();
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('result', 'social_not_enrolled');
    END IF;

    -- Safe retry: one report per reporter and subject.
    SELECT r.id INTO v_report_id FROM social.reports r
    WHERE r.reporter_id = v_actor
      AND (r.post_id = p_post_id OR r.comment_id = p_comment_id OR r.profile_user_id = p_profile_user_id);
    IF FOUND THEN
        RETURN jsonb_build_object('result', 'ok', 'replayed', true, 'report_id', v_report_id);
    END IF;

    IF p_post_id IS NOT NULL THEN
        v_kind := 'post';
        SELECT p.community_id, p.author_id, p.status, p.body
        INTO v_community, v_target, v_status, v_snapshot
        FROM social.posts p WHERE p.id = p_post_id FOR UPDATE;
        v_found := FOUND;
    ELSIF p_comment_id IS NOT NULL THEN
        v_kind := 'comment';
        SELECT c.community_id, c.author_id, c.status, c.body, c.post_id
        INTO v_community, v_target, v_status, v_snapshot, v_parent_post
        FROM social.comments c WHERE c.id = p_comment_id FOR UPDATE;
        v_found := FOUND;
    ELSE
        v_kind := 'profile_name';
        SELECT p.user_id, p.display_name INTO v_target, v_snapshot
        FROM social.profiles p WHERE p.user_id = p_profile_user_id FOR UPDATE;
        v_found := FOUND AND social.shares_community_with(p_profile_user_id);
        v_status := 'published';
    END IF;

    v_access := social.actor_access(v_community);
    IF v_access = 'suspended' THEN
        RETURN jsonb_build_object('result', 'social_suspended');
    END IF;
    IF NOT v_found OR v_access <> 'ok' OR v_status IN ('pending_review', 'rejected') THEN
        RETURN jsonb_build_object('result', 'content_not_found');
    END IF;
    IF v_target = v_actor THEN
        RETURN jsonb_build_object('result', 'not_allowed');
    END IF;
    -- Already taken down (the phone showed a cached copy): acknowledge, nothing to do.
    IF v_status IN ('removed', 'deleted') THEN
        RETURN jsonb_build_object('result', 'ok', 'replayed', false, 'report_id', NULL, 'already_handled', true);
    END IF;

    SELECT * INTO v_cfg FROM social.config;
    IF NOT social.bump_rate(v_actor, 'report_day', 86400, v_cfg.max_reports_per_day) THEN
        RETURN jsonb_build_object('result', 'rate_limited',
                                  'retry_after_s', social.seconds_to_window_end(86400));
    END IF;

    v_priority := CASE WHEN v_severe THEN 0 ELSE 1 END;
    v_due := now() + make_interval(hours => CASE WHEN v_severe THEN v_cfg.severe_report_due_hours
                                                 ELSE v_cfg.review_due_hours END);

    SELECT i.id INTO v_item_id FROM social.moderation_items i
    WHERE i.reason = 'reported' AND i.status <> 'resolved'
      AND (i.post_id = p_post_id OR i.comment_id = p_comment_id OR i.profile_user_id = p_profile_user_id)
    FOR UPDATE;
    IF FOUND THEN
        UPDATE social.moderation_items i
        SET priority = LEAST(i.priority, v_priority), due_at = LEAST(i.due_at, v_due)
        WHERE i.id = v_item_id;
    ELSE
        INSERT INTO social.moderation_items (subject_kind, post_id, comment_id, profile_user_id,
                                             community_id, reason, priority, due_at)
        VALUES (v_kind, p_post_id, p_comment_id, p_profile_user_id, v_community, 'reported', v_priority, v_due)
        RETURNING id INTO v_item_id;
    END IF;

    INSERT INTO social.reports (reporter_id, post_id, comment_id, profile_user_id, target_user_id,
                                community_id, category, note, content_snapshot, moderation_item_id)
    VALUES (v_actor, p_post_id, p_comment_id, p_profile_user_id, v_target,
            v_community, p_category, p_note, v_snapshot, v_item_id)
    RETURNING id INTO v_report_id;

    -- Hide first, review second.
    IF v_kind IN ('post', 'comment') AND v_status = 'published' AND (
        v_severe OR (
            SELECT count(*) FROM social.reports r
            WHERE r.status = 'open' AND (r.post_id = p_post_id OR r.comment_id = p_comment_id)
        ) >= v_cfg.auto_hide_report_threshold
    ) THEN
        v_seq := social.next_visibility_seq();
        IF v_kind = 'post' THEN
            UPDATE social.posts SET status = 'hidden', change_seq = v_seq WHERE id = p_post_id;
        ELSE
            UPDATE social.comments SET status = 'hidden', change_seq = v_seq WHERE id = p_comment_id;
            UPDATE social.posts SET comment_count = GREATEST(comment_count - 1, 0) WHERE id = v_parent_post;
        END IF;
        INSERT INTO social.moderation_actions (item_id, actor_id, actor_role, action, post_id, comment_id,
                                               target_user_id, community_id, reason_code)
        VALUES (v_item_id, NULL, 'system', 'auto_hide', p_post_id, p_comment_id, v_target, v_community,
                CASE WHEN v_severe THEN 'severe_report' ELSE 'report_threshold' END);
    END IF;

    RETURN jsonb_build_object('result', 'ok', 'replayed', false, 'report_id', v_report_id);
END $$;

-- ----------------------------------------------------------------------------
-- Blocks. Blocking hides each person's content from the other. Teachers and
-- staff cannot be blocked (they can be REPORTED), so safety notices still arrive.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.set_block(p_user_id uuid, p_blocked boolean)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.lock_actor();
    v_kind text;
BEGIN
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('result', 'social_not_enrolled');
    END IF;
    IF p_user_id = v_actor THEN
        RETURN jsonb_build_object('result', 'not_allowed');
    END IF;
    IF NOT p_blocked THEN
        DELETE FROM social.blocks b WHERE b.blocker_id = v_actor AND b.blocked_id = p_user_id;
        RETURN jsonb_build_object('result', 'ok', 'blocked', false);
    END IF;
    IF EXISTS (SELECT 1 FROM social.blocks b WHERE b.blocker_id = v_actor AND b.blocked_id = p_user_id) THEN
        RETURN jsonb_build_object('result', 'ok', 'blocked', true);
    END IF;
    SELECT p.account_kind INTO v_kind FROM social.profiles p WHERE p.user_id = p_user_id;
    IF NOT FOUND OR NOT social.shares_community_with(p_user_id) THEN
        RETURN jsonb_build_object('result', 'user_not_found');
    END IF;
    IF v_kind <> 'learner' THEN
        RETURN jsonb_build_object('result', 'cannot_block_staff');
    END IF;
    IF (SELECT count(*) FROM social.blocks b WHERE b.blocker_id = v_actor)
       >= (SELECT c.max_blocks FROM social.config c) THEN
        RETURN jsonb_build_object('result', 'limit_reached');
    END IF;
    INSERT INTO social.blocks (blocker_id, blocked_id) VALUES (v_actor, p_user_id)
    ON CONFLICT DO NOTHING;
    RETURN jsonb_build_object('result', 'ok', 'blocked', true);
END $$;

-- ----------------------------------------------------------------------------
-- Joining. A valid code only creates a REQUEST; a teacher of the group or staff
-- must approve it (verified membership). Every failure looks the same, and
-- attempts are counted even when they fail, so codes cannot be guessed.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.join_with_invite(p_code_sha256 bytea)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.lock_actor();
    v_cfg social.config%ROWTYPE;
    v_access text;
    v_invite record;
    v_profile record;
    v_status text;
BEGIN
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('result', 'social_not_enrolled');
    END IF;
    v_access := social.actor_access(NULL);
    IF v_access <> 'ok' THEN
        RETURN jsonb_build_object('result',
            CASE v_access WHEN 'suspended' THEN 'social_suspended' ELSE 'social_not_active' END);
    END IF;
    SELECT * INTO v_cfg FROM social.config;
    IF NOT social.bump_rate(v_actor, 'join_hour', 3600, v_cfg.max_join_attempts_per_hour) THEN
        RETURN jsonb_build_object('result', 'rate_limited',
                                  'retry_after_s', social.seconds_to_window_end(3600));
    END IF;

    SELECT i.id, i.community_id, c.grade_band INTO v_invite
    FROM social.community_invites i JOIN social.communities c ON c.id = i.community_id
    WHERE i.code_sha256 = p_code_sha256
      AND i.revoked_at IS NULL AND i.expires_at > now() AND i.use_count < i.max_uses
      AND c.status = 'open' AND c.join_mode = 'invite_then_approval'
    FOR UPDATE OF i;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'invite_invalid');
    END IF;
    SELECT p.account_kind, p.grade_band INTO v_profile FROM social.profiles p WHERE p.user_id = v_actor;
    IF v_profile.account_kind = 'learner' AND v_profile.grade_band IS DISTINCT FROM v_invite.grade_band THEN
        RETURN jsonb_build_object('result', 'invite_invalid');
    END IF;

    SELECT m.status INTO v_status FROM social.memberships m
    WHERE m.community_id = v_invite.community_id AND m.user_id = v_actor FOR UPDATE;
    IF FOUND THEN
        IF v_status IN ('active', 'pending_approval') THEN
            RETURN jsonb_build_object('result', 'ok', 'replayed', true,
                                      'community_id', v_invite.community_id, 'status', v_status);
        ELSIF v_status = 'removed' THEN
            -- Someone removed from a group cannot let themselves back in.
            RETURN jsonb_build_object('result', 'invite_invalid');
        END IF;
        UPDATE social.memberships m
        SET status = 'pending_approval', invite_id = v_invite.id, requested_at = now(), ended_at = NULL,
            verified_by = NULL, verified_at = NULL, verification_method = NULL
        WHERE m.community_id = v_invite.community_id AND m.user_id = v_actor;
    ELSE
        IF (SELECT count(*) FROM social.memberships m
            WHERE m.user_id = v_actor AND m.status IN ('active', 'pending_approval')) >= v_cfg.max_memberships THEN
            RETURN jsonb_build_object('result', 'limit_reached');
        END IF;
        INSERT INTO social.memberships (community_id, user_id, invite_id)
        VALUES (v_invite.community_id, v_actor, v_invite.id);
    END IF;
    UPDATE social.community_invites i SET use_count = i.use_count + 1 WHERE i.id = v_invite.id;
    RETURN jsonb_build_object('result', 'ok', 'replayed', false,
                              'community_id', v_invite.community_id, 'status', 'pending_approval');
END $$;

-- Approve or decline a join request. Allowed for: an active TEACHER of that
-- community, or social staff. Never for the requester themselves.
CREATE FUNCTION social.decide_join_request(p_community_id uuid, p_user_id uuid, p_approve boolean)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.current_actor_id();
    v_is_staff boolean;
    v_status text;
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    v_is_staff := social.actor_has_staff_role(ARRAY['social_admin', 'moderator', 'safety_lead']);
    IF p_user_id = v_actor OR NOT (
        v_is_staff OR (
            social.actor_access(p_community_id) = 'ok' AND EXISTS (
                SELECT 1 FROM social.memberships m
                WHERE m.community_id = p_community_id AND m.user_id = v_actor
                  AND m.status = 'active' AND m.role = 'teacher'))
    ) THEN
        PERFORM social.write_audit('user', 'membership.decide', 'community', p_community_id, 'denied');
        RETURN jsonb_build_object('result', 'forbidden');
    END IF;

    SELECT m.status INTO v_status FROM social.memberships m
    WHERE m.community_id = p_community_id AND m.user_id = p_user_id FOR UPDATE;
    IF NOT FOUND OR v_status <> 'pending_approval' THEN
        RETURN jsonb_build_object('result', 'invalid_state');
    END IF;

    IF p_approve THEN
        UPDATE social.memberships m
        SET status = 'active', verified_by = v_actor, verified_at = now(),
            verification_method = COALESCE(m.verification_method, 'invite_code')
        WHERE m.community_id = p_community_id AND m.user_id = p_user_id;
        PERFORM social.notify(p_user_id, 'membership_approved', NULL, NULL, p_community_id);
    ELSE
        UPDATE social.memberships m SET status = 'removed', ended_at = now()
        WHERE m.community_id = p_community_id AND m.user_id = p_user_id;
        PERFORM social.notify(p_user_id, 'membership_declined', NULL, NULL, p_community_id);
    END IF;
    PERFORM social.write_audit(CASE WHEN v_is_staff THEN 'staff' ELSE 'teacher' END, 'membership.decide',
        'community', p_community_id, 'allowed',
        jsonb_build_object('member', p_user_id, 'approved', p_approve));
    RETURN jsonb_build_object('result', 'ok', 'status', CASE WHEN p_approve THEN 'active' ELSE 'removed' END);
END $$;

CREATE FUNCTION social.leave_community(p_community_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.lock_actor();
BEGIN
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('result', 'social_not_enrolled');
    END IF;
    UPDATE social.memberships m SET status = 'left', ended_at = now()
    WHERE m.community_id = p_community_id AND m.user_id = v_actor
      AND m.status IN ('active', 'pending_approval');
    RETURN jsonb_build_object('result', 'ok');
END $$;

-- ----------------------------------------------------------------------------
-- Deleting your own post or comment. It disappears for everyone at once. The
-- text is erased immediately UNLESS a report or an evidence hold is open, in
-- which case moderators keep it until that is resolved (then retention erases it).
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.delete_own_content(p_post_id uuid, p_comment_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid;
    v_status text;
    v_parent_post uuid;
    v_held boolean;
    v_seq bigint;
BEGIN
    IF num_nonnulls(p_post_id, p_comment_id) <> 1 THEN
        RAISE EXCEPTION 'exactly one of post id / comment id is required' USING ERRCODE = '22023';
    END IF;
    v_actor := social.lock_actor();
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('result', 'social_not_enrolled');
    END IF;

    IF p_post_id IS NOT NULL THEN
        SELECT p.status INTO v_status FROM social.posts p
        WHERE p.id = p_post_id AND p.author_id = v_actor FOR UPDATE;
    ELSE
        SELECT c.status, c.post_id INTO v_status, v_parent_post FROM social.comments c
        WHERE c.id = p_comment_id AND c.author_id = v_actor FOR UPDATE;
    END IF;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'content_not_found');
    END IF;
    IF v_status IN ('deleted', 'rejected', 'removed') THEN
        RETURN jsonb_build_object('result', 'ok', 'status', v_status);
    END IF;

    v_held := EXISTS (
        SELECT 1 FROM social.reports r
        WHERE r.status = 'open' AND (r.post_id = p_post_id OR r.comment_id = p_comment_id)
    ) OR EXISTS (
        SELECT 1 FROM social.evidence_holds h
        WHERE h.released_at IS NULL AND (h.post_id = p_post_id OR h.comment_id = p_comment_id)
    );
    IF v_status IN ('published', 'hidden') THEN
        v_seq := social.next_visibility_seq();
    END IF;

    IF p_post_id IS NOT NULL THEN
        UPDATE social.posts p
        SET status = 'deleted', change_seq = COALESCE(v_seq, p.change_seq),
            body = CASE WHEN v_held THEN p.body ELSE NULL END,
            body_scrubbed_at = CASE WHEN v_held THEN NULL ELSE now() END
        WHERE p.id = p_post_id;
    ELSE
        UPDATE social.comments c
        SET status = 'deleted', change_seq = COALESCE(v_seq, c.change_seq),
            body = CASE WHEN v_held THEN c.body ELSE NULL END,
            body_scrubbed_at = CASE WHEN v_held THEN NULL ELSE now() END
        WHERE c.id = p_comment_id;
        IF v_status = 'published' THEN
            UPDATE social.posts SET comment_count = GREATEST(comment_count - 1, 0) WHERE id = v_parent_post;
        END IF;
    END IF;

    -- Nothing left for a moderator to approve.
    UPDATE social.moderation_items i
    SET status = 'resolved', resolution = 'withdrawn', resolved_at = now(), claimed_by = NULL, lease_until = NULL
    WHERE i.reason = 'pre_publication' AND i.status <> 'resolved'
      AND (i.post_id = p_post_id OR i.comment_id = p_comment_id);

    RETURN jsonb_build_object('result', 'ok', 'status', 'deleted');
END $$;

-- ----------------------------------------------------------------------------
-- Profile, guidelines, settings, notifications
-- ----------------------------------------------------------------------------
-- A new display name is NOT shown to anyone until a moderator approves it.
CREATE FUNCTION social.update_profile(p_display_name text, p_avatar_key text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.lock_actor();
    v_cfg social.config%ROWTYPE;
    v_current text;
BEGIN
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('result', 'social_not_enrolled');
    END IF;
    IF social.actor_access(NULL) <> 'ok' THEN
        RETURN jsonb_build_object('result', 'social_not_active');
    END IF;
    IF p_avatar_key IS NOT NULL THEN
        UPDATE social.profiles p SET avatar_key = p_avatar_key, updated_at = now() WHERE p.user_id = v_actor;
    END IF;
    IF p_display_name IS NOT NULL THEN
        SELECT p.display_name INTO v_current FROM social.profiles p WHERE p.user_id = v_actor;
        IF v_current IS DISTINCT FROM p_display_name THEN
            SELECT * INTO v_cfg FROM social.config;
            IF NOT social.bump_rate(v_actor, 'name_day', 86400, 3) THEN
                RETURN jsonb_build_object('result', 'rate_limited',
                                          'retry_after_s', social.seconds_to_window_end(86400));
            END IF;
            UPDATE social.profiles p SET pending_display_name = p_display_name, updated_at = now()
            WHERE p.user_id = v_actor;
            IF NOT EXISTS (
                SELECT 1 FROM social.moderation_items i
                WHERE i.profile_user_id = v_actor AND i.reason = 'pre_publication' AND i.status <> 'resolved'
            ) THEN
                INSERT INTO social.moderation_items (subject_kind, profile_user_id, reason, priority, due_at)
                VALUES ('profile_name', v_actor, 'pre_publication', 2,
                        now() + make_interval(hours => v_cfg.review_due_hours));
            END IF;
            RETURN jsonb_build_object('result', 'ok', 'display_name_status', 'pending_review');
        END IF;
    END IF;
    RETURN jsonb_build_object('result', 'ok', 'display_name_status', 'unchanged');
END $$;

CREATE FUNCTION social.accept_guidelines(p_version text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.lock_actor();
BEGIN
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('result', 'social_not_enrolled');
    END IF;
    IF p_version IS DISTINCT FROM (SELECT c.guidelines_version FROM social.config c) THEN
        RETURN jsonb_build_object('result', 'guidelines_outdated');
    END IF;
    UPDATE social.enrollments e
    SET guidelines_version = p_version, guidelines_accepted_at = now(), updated_at = now()
    WHERE e.user_id = v_actor;
    RETURN jsonb_build_object('result', 'ok');
END $$;

-- NULL = leave unchanged. When an adult or staff locked the settings, the
-- learner may only switch capabilities OFF.
CREATE FUNCTION social.update_own_settings(
    p_can_post boolean, p_can_comment boolean, p_can_react boolean, p_notifications_enabled boolean)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.lock_actor();
    v_row social.safety_settings%ROWTYPE;
BEGIN
    IF v_actor IS NULL THEN
        RETURN jsonb_build_object('result', 'social_not_enrolled');
    END IF;
    INSERT INTO social.safety_settings (user_id) VALUES (v_actor) ON CONFLICT (user_id) DO NOTHING;
    SELECT * INTO v_row FROM social.safety_settings s WHERE s.user_id = v_actor FOR UPDATE;
    IF v_row.locked_by <> 'none' AND (
           (COALESCE(p_can_post, false) AND NOT v_row.can_post)
        OR (COALESCE(p_can_comment, false) AND NOT v_row.can_comment)
        OR (COALESCE(p_can_react, false) AND NOT v_row.can_react)
    ) THEN
        RETURN jsonb_build_object('result', 'settings_locked');
    END IF;
    UPDATE social.safety_settings s
    SET can_post = COALESCE(p_can_post, s.can_post),
        can_comment = COALESCE(p_can_comment, s.can_comment),
        can_react = COALESCE(p_can_react, s.can_react),
        notifications_enabled = COALESCE(p_notifications_enabled, s.notifications_enabled),
        updated_by = v_actor, updated_at = now()
    WHERE s.user_id = v_actor;
    RETURN jsonb_build_object('result', 'ok');
END $$;

CREATE FUNCTION social.mark_notifications_read(p_up_to_id bigint)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.current_actor_id();
    v_count integer;
BEGIN
    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'No verified actor in this transaction' USING ERRCODE = '42501';
    END IF;
    UPDATE social.notification_events n SET read_at = now()
    WHERE n.recipient_id = v_actor AND n.id <= p_up_to_id AND n.read_at IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN jsonb_build_object('result', 'ok', 'marked', v_count);
END $$;

-- ----------------------------------------------------------------------------
-- "What changed since N?" for the phone's cache: ids and a visible/not-visible
-- flag only, for the caller's own communities. This is how a removed post
-- disappears from a phone that had cached it. (Row-level security alone cannot
-- answer this: a removed row is, correctly, invisible to members.)
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.visibility_changes(p_since bigint, p_limit integer)
RETURNS TABLE (subject_kind text, id uuid, post_id uuid, community_id uuid, change_seq bigint, visible boolean)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT x.subject_kind, x.id, x.post_id, x.community_id, x.change_seq, x.visible
    FROM (
        SELECT 'post'::text AS subject_kind, p.id, p.id AS post_id, p.community_id, p.change_seq,
               p.status = 'published' AS visible
        FROM social.posts p
        WHERE p.change_seq > p_since
          AND p.community_id IN (
              SELECT m.community_id FROM social.memberships m
              WHERE m.user_id = social.current_actor_id() AND m.status = 'active')
        UNION ALL
        SELECT 'comment'::text, c.id, c.post_id, c.community_id, c.change_seq,
               c.status = 'published'
        FROM social.comments c
        WHERE c.change_seq > p_since
          AND c.community_id IN (
              SELECT m.community_id FROM social.memberships m
              WHERE m.user_id = social.current_actor_id() AND m.status = 'active')
    ) x
    WHERE social.actor_access(NULL) = 'ok'
    ORDER BY x.change_seq
    LIMIT LEAST(GREATEST(p_limit, 1), 200)
$$;

-- ----------------------------------------------------------------------------
-- Two narrow read functions for data that table grants deliberately do not expose
-- ----------------------------------------------------------------------------
-- The caller's own not-yet-approved display name and grade band. (The API role
-- has no SELECT on these columns, so it cannot read anyone else's by mistake.)
CREATE FUNCTION social.my_private_profile()
RETURNS TABLE (grade_band text, pending_display_name text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT p.grade_band, p.pending_display_name
    FROM social.profiles p WHERE p.user_id = social.current_actor_id()
$$;

-- The member list and join requests of one community — for its teacher(s) and
-- for social staff only. Ordinary members get no member directory at all.
CREATE FUNCTION social.community_members(p_community_id uuid)
RETURNS TABLE (user_id uuid, display_name text, avatar_key text, role text, status text, requested_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT m.user_id, p.display_name, p.avatar_key, m.role, m.status, m.requested_at
    FROM social.memberships m JOIN social.profiles p ON p.user_id = m.user_id
    WHERE m.community_id = p_community_id
      AND m.status IN ('active', 'pending_approval')
      AND (
          social.actor_has_staff_role(ARRAY['social_admin', 'moderator', 'safety_lead'])
          OR (social.actor_access(p_community_id) = 'ok' AND EXISTS (
                  SELECT 1 FROM social.memberships t
                  WHERE t.community_id = p_community_id AND t.user_id = social.current_actor_id()
                    AND t.status = 'active' AND t.role = 'teacher'))
      )
    ORDER BY m.status DESC, m.requested_at
$$;
