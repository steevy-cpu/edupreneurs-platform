-- ============================================================================
-- PROPOSED — NOT APPLIED. Social-00 design artefact (see 0001 header).
-- ============================================================================
-- Edupreneurs 2.0 — social module: moderation, sanctions, retention, erasure
--
-- These functions are executable only by edu_social_mod (moderation endpoints);
-- run_retention() only by edu_social_worker (the scheduled job). Each moderation
-- function ALSO checks, inside the database, that the verified actor holds an
-- active social staff role — so a
-- bug that routes a student request to the moderation pool still changes nothing.
--
-- Rules that hold everywhere:
--   * nobody moderates their own content or sanctions themselves;
--   * every decision writes an append-only moderation_actions row;
--   * the approval row is written BEFORE the content is published, because the
--     publication trigger (0003) refuses to publish without it.

CREATE FUNCTION social.require_staff(p_roles text[])
RETURNS uuid
LANGUAGE plpgsql STABLE
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.current_actor_id();
BEGIN
    IF v_actor IS NULL OR NOT social.actor_has_staff_role(p_roles) THEN
        RAISE EXCEPTION 'social staff role required' USING ERRCODE = '42501';
    END IF;
    RETURN v_actor;
END $$;

CREATE FUNCTION social.actor_staff_label()
RETURNS text
LANGUAGE sql STABLE
SET search_path = ''
AS $$
    SELECT CASE
        WHEN social.actor_has_staff_role(ARRAY['safety_lead']) THEN 'safety_lead'
        WHEN social.actor_has_staff_role(ARRAY['moderator']) THEN 'moderator'
        ELSE 'social_admin'
    END
$$;

-- ----------------------------------------------------------------------------
-- Take the next item from the queue: most urgent first, then oldest.
-- A claim is a short lease; if the moderator closes the tab, the item returns
-- to the queue by itself when the lease runs out. Returns NULL when empty.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.mod_claim_next(p_lease_minutes integer DEFAULT 15)
RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.require_staff(ARRAY['moderator', 'safety_lead']);
    v_item_id uuid;
BEGIN
    SELECT i.id INTO v_item_id
    FROM social.moderation_items i
    LEFT JOIN social.posts p ON p.id = i.post_id
    LEFT JOIN social.comments c ON c.id = i.comment_id
    WHERE (i.status = 'open' OR (i.status = 'claimed' AND i.lease_until < now()))
      -- never offer a moderator their own content
      AND COALESCE(p.author_id, c.author_id, i.profile_user_id) IS DISTINCT FROM v_actor
    ORDER BY i.priority, i.opened_at
    LIMIT 1
    FOR UPDATE OF i SKIP LOCKED;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    UPDATE social.moderation_items i
    SET status = 'claimed', claimed_by = v_actor,
        lease_until = now() + make_interval(mins => LEAST(GREATEST(p_lease_minutes, 1), 60))
    WHERE i.id = v_item_id;
    RETURN v_item_id;
END $$;

-- ----------------------------------------------------------------------------
-- Decide a claimed item.
--   reason 'pre_publication' : p_decision = 'approve' | 'reject'
--   reason 'reported'        : p_decision = 'dismiss' (content stays / comes back) | 'remove'
-- 'reject' and 'remove' need a reason code; the author sees that code, translated.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.mod_decide(p_item_id uuid, p_decision text, p_reason_code text, p_note text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.require_staff(ARRAY['moderator', 'safety_lead']);
    v_role text := social.actor_staff_label();
    v_item social.moderation_items%ROWTYPE;
    v_author uuid;
    v_status text;
    v_digest bytea;
    v_parent_post uuid;
    v_parent_comment uuid;
    v_post_author uuid;
    v_reply_to uuid;
    v_pending_name text;
    v_resolution text;
    v_seq bigint;
BEGIN
    -- Read without a lock first, lock the SUBJECT, then lock the item
    -- (lock order: comment -> post -> item; see 0004 header).
    SELECT * INTO v_item FROM social.moderation_items i WHERE i.id = p_item_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'item_not_found');
    END IF;
    IF v_item.subject_kind = 'post' THEN
        SELECT p.author_id, p.status, p.body_sha256 INTO v_author, v_status, v_digest
        FROM social.posts p WHERE p.id = v_item.post_id FOR UPDATE;
    ELSIF v_item.subject_kind = 'comment' THEN
        SELECT c.author_id, c.status, c.body_sha256, c.post_id, c.parent_comment_id
        INTO v_author, v_status, v_digest, v_parent_post, v_parent_comment
        FROM social.comments c WHERE c.id = v_item.comment_id FOR UPDATE;
    ELSE
        SELECT p.user_id, p.pending_display_name INTO v_author, v_pending_name
        FROM social.profiles p WHERE p.user_id = v_item.profile_user_id FOR UPDATE;
    END IF;
    SELECT * INTO v_item FROM social.moderation_items i WHERE i.id = p_item_id FOR UPDATE;

    IF v_item.status <> 'claimed' OR v_item.claimed_by IS DISTINCT FROM v_actor OR v_item.lease_until < now() THEN
        RETURN jsonb_build_object('result', 'item_not_claimed');
    END IF;
    IF v_author = v_actor THEN
        RETURN jsonb_build_object('result', 'self_moderation_forbidden');
    END IF;
    IF NOT (
           (v_item.reason = 'pre_publication' AND p_decision IN ('approve', 'reject'))
        OR (v_item.reason = 'reported' AND p_decision IN ('dismiss', 'remove'))
    ) THEN
        RAISE EXCEPTION 'decision % is not valid for a % item', p_decision, v_item.reason
            USING ERRCODE = '22023';
    END IF;
    IF p_decision IN ('reject', 'remove') AND p_reason_code IS NULL THEN
        RAISE EXCEPTION 'a reason code is required to reject or remove' USING ERRCODE = '22023';
    END IF;

    -- ---------------- posts and comments ----------------
    IF v_item.subject_kind IN ('post', 'comment') THEN
        IF p_decision = 'approve' THEN
            IF v_status <> 'pending_review' THEN
                v_resolution := 'stale'; -- e.g. the author deleted it meanwhile
            ELSE
                INSERT INTO social.moderation_actions (item_id, actor_id, actor_role, action, post_id, comment_id,
                    target_user_id, community_id, internal_note, content_sha256)
                VALUES (p_item_id, v_actor, v_role, 'approve', v_item.post_id, v_item.comment_id,
                    v_author, v_item.community_id, p_note, v_digest);
                v_seq := social.next_visibility_seq();
                IF v_item.subject_kind = 'post' THEN
                    UPDATE social.posts
                    SET status = 'published', publish_seq = v_seq, change_seq = v_seq, published_at = now()
                    WHERE id = v_item.post_id;
                    PERFORM social.notify(v_author, 'post_approved', v_item.post_id, NULL, v_item.community_id);
                ELSE
                    UPDATE social.comments
                    SET status = 'published', publish_seq = v_seq, change_seq = v_seq, published_at = now()
                    WHERE id = v_item.comment_id;
                    UPDATE social.posts SET comment_count = comment_count + 1 WHERE id = v_parent_post
                    RETURNING author_id INTO v_post_author;
                    PERFORM social.notify(v_author, 'comment_approved', v_parent_post, v_item.comment_id, v_item.community_id);
                    -- Tell the post's author, and the author of the comment replied to —
                    -- unless it is the same person or there is a block between them.
                    IF v_post_author IS DISTINCT FROM v_author AND NOT EXISTS (
                        SELECT 1 FROM social.blocks b
                        WHERE (b.blocker_id = v_post_author AND b.blocked_id = v_author)
                           OR (b.blocker_id = v_author AND b.blocked_id = v_post_author)
                    ) THEN
                        PERFORM social.notify(v_post_author, 'comment_on_post', v_parent_post, NULL, v_item.community_id);
                    END IF;
                    IF v_parent_comment IS NOT NULL THEN
                        SELECT c.author_id INTO v_reply_to FROM social.comments c WHERE c.id = v_parent_comment;
                        IF v_reply_to IS DISTINCT FROM v_author AND v_reply_to IS DISTINCT FROM v_post_author
                           AND NOT EXISTS (
                            SELECT 1 FROM social.blocks b
                            WHERE (b.blocker_id = v_reply_to AND b.blocked_id = v_author)
                               OR (b.blocker_id = v_author AND b.blocked_id = v_reply_to)
                        ) THEN
                            PERFORM social.notify(v_reply_to, 'reply_to_comment', v_parent_post, v_item.comment_id, v_item.community_id);
                        END IF;
                    END IF;
                END IF;
                v_resolution := 'approved';
            END IF;

        ELSIF p_decision = 'reject' THEN
            IF v_status <> 'pending_review' THEN
                v_resolution := 'stale';
            ELSE
                IF v_item.subject_kind = 'post' THEN
                    UPDATE social.posts SET status = 'rejected', moderation_reason_code = p_reason_code
                    WHERE id = v_item.post_id;
                    PERFORM social.notify(v_author, 'post_rejected', v_item.post_id, NULL, v_item.community_id);
                ELSE
                    UPDATE social.comments SET status = 'rejected', moderation_reason_code = p_reason_code
                    WHERE id = v_item.comment_id;
                    PERFORM social.notify(v_author, 'comment_rejected', v_parent_post, v_item.comment_id, v_item.community_id);
                END IF;
                v_resolution := 'rejected';
            END IF;

        ELSIF p_decision = 'dismiss' THEN
            -- The report was unfounded. If the content was hidden, bring it back.
            IF v_status = 'hidden' THEN
                INSERT INTO social.moderation_actions (item_id, actor_id, actor_role, action, post_id, comment_id,
                    target_user_id, community_id, internal_note, content_sha256)
                VALUES (p_item_id, v_actor, v_role, 'restore', v_item.post_id, v_item.comment_id,
                    v_author, v_item.community_id, p_note, v_digest);
                v_seq := social.next_visibility_seq();
                IF v_item.subject_kind = 'post' THEN
                    UPDATE social.posts SET status = 'published', change_seq = v_seq WHERE id = v_item.post_id;
                ELSE
                    UPDATE social.comments SET status = 'published', change_seq = v_seq WHERE id = v_item.comment_id;
                    UPDATE social.posts SET comment_count = comment_count + 1 WHERE id = v_parent_post;
                END IF;
            END IF;
            v_resolution := 'dismissed';

        ELSE -- remove
            IF v_status IN ('published', 'hidden') THEN
                v_seq := social.next_visibility_seq();
                IF v_item.subject_kind = 'post' THEN
                    UPDATE social.posts
                    SET status = 'removed', change_seq = v_seq, moderation_reason_code = p_reason_code
                    WHERE id = v_item.post_id;
                ELSE
                    UPDATE social.comments
                    SET status = 'removed', change_seq = v_seq, moderation_reason_code = p_reason_code
                    WHERE id = v_item.comment_id;
                    IF v_status = 'published' THEN
                        UPDATE social.posts SET comment_count = GREATEST(comment_count - 1, 0) WHERE id = v_parent_post;
                    END IF;
                END IF;
                PERFORM social.notify(v_author, 'content_removed',
                    COALESCE(v_item.post_id, v_parent_post), v_item.comment_id, v_item.community_id);
            END IF;
            -- 'deleted' by the author meanwhile: still recorded as removed, for the reporter's sake.
            v_resolution := 'removed';
        END IF;

    -- ---------------- display names ----------------
    ELSE
        IF p_decision = 'approve' THEN
            IF v_pending_name IS NULL THEN
                v_resolution := 'stale';
            ELSE
                UPDATE social.profiles SET display_name = pending_display_name, pending_display_name = NULL, updated_at = now()
                WHERE user_id = v_item.profile_user_id;
                PERFORM social.notify(v_author, 'name_approved', NULL, NULL, NULL);
                v_resolution := 'approved';
            END IF;
        ELSIF p_decision = 'reject' THEN
            UPDATE social.profiles SET pending_display_name = NULL, updated_at = now()
            WHERE user_id = v_item.profile_user_id;
            PERFORM social.notify(v_author, 'name_rejected', NULL, NULL, NULL);
            v_resolution := 'rejected';
        ELSIF p_decision = 'remove' THEN
            -- The app shows a neutral placeholder for a NULL name.
            UPDATE social.profiles SET display_name = NULL, pending_display_name = NULL, updated_at = now()
            WHERE user_id = v_item.profile_user_id;
            PERFORM social.notify(v_author, 'name_rejected', NULL, NULL, NULL);
            v_resolution := 'removed';
        ELSE
            v_resolution := 'dismissed';
        END IF;
    END IF;

    -- The decision record ('approve' / 'restore' rows for content were written above).
    -- Nothing is recorded as a decision when the item had gone stale.
    IF v_resolution <> 'stale'
       AND NOT (v_item.subject_kind IN ('post', 'comment') AND v_resolution = 'approved') THEN
        INSERT INTO social.moderation_actions (item_id, actor_id, actor_role, action, post_id, comment_id,
            target_user_id, community_id, reason_code, internal_note, content_sha256)
        VALUES (p_item_id, v_actor, v_role,
            CASE
                WHEN v_item.subject_kind = 'profile_name' AND p_decision = 'approve' THEN 'approve_name'
                WHEN v_item.subject_kind = 'profile_name' AND p_decision = 'reject' THEN 'reject_name'
                WHEN v_item.subject_kind = 'profile_name' AND p_decision = 'remove' THEN 'remove_name'
                ELSE p_decision
            END,
            v_item.post_id, v_item.comment_id, v_author, v_item.community_id, p_reason_code, p_note, v_digest);
    END IF;

    UPDATE social.moderation_items i
    SET status = 'resolved', resolution = v_resolution, resolved_at = now()
    WHERE i.id = p_item_id;

    IF v_item.reason = 'reported' THEN
        UPDATE social.reports r
        SET status = CASE WHEN v_resolution = 'removed' THEN 'actioned' ELSE 'dismissed' END,
            resolved_at = now()
        WHERE r.moderation_item_id = p_item_id AND r.status = 'open';
    END IF;

    PERFORM social.write_audit('staff', 'moderation.decide', 'moderation_item', p_item_id, 'allowed',
        jsonb_build_object('decision', p_decision, 'resolution', v_resolution));
    RETURN jsonb_build_object('result', 'ok', 'resolution', v_resolution);
END $$;

-- ----------------------------------------------------------------------------
-- Escalate a claimed item to the safety lead (or beyond). The item leaves the
-- normal queue, the evidence is put on hold, and a deadline is set.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.mod_escalate(p_item_id uuid, p_level text, p_summary text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.require_staff(ARRAY['moderator', 'safety_lead']);
    v_item social.moderation_items%ROWTYPE;
    v_escalation_id uuid;
BEGIN
    SELECT * INTO v_item FROM social.moderation_items i WHERE i.id = p_item_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'item_not_found');
    END IF;
    IF v_item.status = 'resolved' OR (v_item.status = 'claimed' AND v_item.claimed_by IS DISTINCT FROM v_actor) THEN
        RETURN jsonb_build_object('result', 'item_not_claimed');
    END IF;
    IF p_level <> 'safety_lead' AND NOT social.actor_has_staff_role(ARRAY['safety_lead']) THEN
        -- Contacting a family, a school or an authority is the safety lead's decision.
        RETURN jsonb_build_object('result', 'forbidden');
    END IF;

    INSERT INTO social.escalations (item_id, level, summary, opened_by, due_at)
    VALUES (p_item_id, p_level, p_summary, v_actor,
            now() + make_interval(hours => (SELECT c.severe_report_due_hours FROM social.config c)))
    RETURNING id INTO v_escalation_id;

    IF v_item.post_id IS NOT NULL OR v_item.comment_id IS NOT NULL THEN
        INSERT INTO social.evidence_holds (post_id, comment_id, escalation_id, reason_code, placed_by)
        VALUES (v_item.post_id, v_item.comment_id, v_escalation_id, 'escalation', v_actor);
    END IF;
    INSERT INTO social.evidence_holds (report_id, escalation_id, reason_code, placed_by)
    SELECT r.id, v_escalation_id, 'escalation', v_actor
    FROM social.reports r WHERE r.moderation_item_id = p_item_id;

    UPDATE social.moderation_items i
    SET status = 'escalated', priority = 0, claimed_by = NULL, lease_until = NULL
    WHERE i.id = p_item_id;

    INSERT INTO social.moderation_actions (item_id, actor_id, actor_role, action, post_id, comment_id,
        target_user_id, community_id, reason_code)
    VALUES (p_item_id, v_actor, social.actor_staff_label(), 'escalate', v_item.post_id, v_item.comment_id,
        v_item.profile_user_id, v_item.community_id, p_level);
    PERFORM social.write_audit('staff', 'moderation.escalate', 'moderation_item', p_item_id, 'allowed',
        jsonb_build_object('level', p_level, 'escalation', v_escalation_id));
    RETURN jsonb_build_object('result', 'ok', 'escalation_id', v_escalation_id);
END $$;

-- ----------------------------------------------------------------------------
-- Sanctions. Moderators: warning, mute, suspension up to 7 days.
-- Safety lead only: longer suspensions, bans, and anything against a teacher or staff account.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.mod_impose_sanction(
    p_user_id uuid,
    p_kind text,
    p_community_id uuid,
    p_reason_code text,
    p_hours integer,
    p_item_id uuid,
    p_note text
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.require_staff(ARRAY['moderator', 'safety_lead']);
    v_is_lead boolean := social.actor_has_staff_role(ARRAY['safety_lead']);
    v_target_kind text;
    v_action_id uuid;
    v_sanction_id uuid;
    v_ends timestamptz;
BEGIN
    IF p_user_id = v_actor THEN
        RETURN jsonb_build_object('result', 'forbidden');
    END IF;
    SELECT p.account_kind INTO v_target_kind FROM social.profiles p WHERE p.user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'user_not_found');
    END IF;
    IF NOT v_is_lead AND (
           p_kind = 'ban'
        OR v_target_kind <> 'learner'
        OR (p_kind = 'suspension' AND COALESCE(p_hours, 0) > 168)
    ) THEN
        PERFORM social.write_audit('staff', 'sanction.impose', 'user', p_user_id, 'denied',
            jsonb_build_object('kind', p_kind));
        RETURN jsonb_build_object('result', 'forbidden');
    END IF;
    IF p_kind IN ('mute', 'suspension') AND COALESCE(p_hours, 0) < 1 THEN
        RAISE EXCEPTION 'a mute or suspension needs a duration in hours' USING ERRCODE = '22023';
    END IF;
    v_ends := CASE p_kind
        WHEN 'ban' THEN NULL
        WHEN 'warning' THEN now()
        ELSE now() + make_interval(hours => p_hours)
    END;

    INSERT INTO social.moderation_actions (item_id, actor_id, actor_role, action, target_user_id,
        community_id, reason_code, internal_note)
    VALUES (p_item_id, v_actor, social.actor_staff_label(),
        CASE p_kind WHEN 'warning' THEN 'warn' WHEN 'suspension' THEN 'suspend' ELSE p_kind END,
        p_user_id, p_community_id, p_reason_code, p_note)
    RETURNING id INTO v_action_id;

    INSERT INTO social.sanctions (user_id, community_id, kind, reason_code, ends_at, imposed_by, action_id)
    VALUES (p_user_id, p_community_id, p_kind, p_reason_code, v_ends, v_actor, v_action_id)
    RETURNING id INTO v_sanction_id;

    PERFORM social.notify(p_user_id, 'sanction_notice', NULL, NULL, p_community_id);
    PERFORM social.write_audit('staff', 'sanction.impose', 'user', p_user_id, 'allowed',
        jsonb_build_object('kind', p_kind, 'sanction', v_sanction_id));
    RETURN jsonb_build_object('result', 'ok', 'sanction_id', v_sanction_id, 'ends_at', v_ends);
END $$;

-- Lifting a ban (an appeal) is a safety-lead decision, and never by the person who imposed it alone:
-- the lead who lifts must differ from the target. Other sanctions: any moderator.
CREATE FUNCTION social.mod_lift_sanction(p_sanction_id uuid, p_reason_code text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.require_staff(ARRAY['moderator', 'safety_lead']);
    v_sanction social.sanctions%ROWTYPE;
BEGIN
    SELECT * INTO v_sanction FROM social.sanctions s WHERE s.id = p_sanction_id FOR UPDATE;
    IF NOT FOUND OR v_sanction.lifted_at IS NOT NULL THEN
        RETURN jsonb_build_object('result', 'invalid_state');
    END IF;
    IF v_sanction.user_id = v_actor
       OR (v_sanction.kind = 'ban' AND NOT social.actor_has_staff_role(ARRAY['safety_lead'])) THEN
        RETURN jsonb_build_object('result', 'forbidden');
    END IF;
    UPDATE social.sanctions s SET lifted_at = now(), lifted_by = v_actor WHERE s.id = p_sanction_id;
    INSERT INTO social.moderation_actions (actor_id, actor_role, action, target_user_id, community_id, reason_code)
    VALUES (v_actor, social.actor_staff_label(), 'lift_sanction', v_sanction.user_id,
            v_sanction.community_id, p_reason_code);
    PERFORM social.write_audit('staff', 'sanction.lift', 'user', v_sanction.user_id, 'allowed',
        jsonb_build_object('sanction', p_sanction_id));
    RETURN jsonb_build_object('result', 'ok');
END $$;

-- ----------------------------------------------------------------------------
-- Account erasure (the social half of a future account-deletion procedure).
-- Erases the person's text and personal rows; keeps safety records, which hold
-- ids and digests but no text. Refuses while an evidence hold is active.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.erase_user(p_user_id uuid)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor uuid := social.require_staff(ARRAY['safety_lead', 'social_admin']);
    v_seq bigint;
    v_posts integer;
    v_comments integer;
BEGIN
    PERFORM 1 FROM social.profiles p WHERE p.user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'user_not_found');
    END IF;
    IF EXISTS (
        SELECT 1 FROM social.evidence_holds h
        LEFT JOIN social.posts p ON p.id = h.post_id
        LEFT JOIN social.comments c ON c.id = h.comment_id
        LEFT JOIN social.reports r ON r.id = h.report_id
        WHERE h.released_at IS NULL
          AND (p.author_id = p_user_id OR c.author_id = p_user_id OR r.target_user_id = p_user_id)
    ) THEN
        RETURN jsonb_build_object('result', 'blocked_by_evidence_hold');
    END IF;

    v_seq := social.next_visibility_seq();

    -- Published comments stop counting on their posts.
    UPDATE social.posts p
    SET comment_count = GREATEST(p.comment_count - x.n, 0)
    FROM (SELECT c.post_id, count(*)::integer AS n FROM social.comments c
          WHERE c.author_id = p_user_id AND c.status = 'published' GROUP BY c.post_id) x
    WHERE p.id = x.post_id;

    -- Their reactions stop counting too (the rows go away with the profile).
    UPDATE social.posts p SET reaction_count = GREATEST(p.reaction_count - 1, 0)
    FROM social.reactions r WHERE r.user_id = p_user_id AND r.post_id = p.id;
    UPDATE social.comments c SET reaction_count = GREATEST(c.reaction_count - 1, 0)
    FROM social.reactions r WHERE r.user_id = p_user_id AND r.comment_id = c.id;

    -- Erase the text. Live content becomes 'deleted'; finished content keeps its state.
    UPDATE social.comments c
    SET status = CASE WHEN c.status IN ('pending_review', 'published', 'hidden') THEN 'deleted' ELSE c.status END,
        change_seq = CASE WHEN c.status IN ('published', 'hidden') THEN v_seq ELSE c.change_seq END,
        body = NULL, body_scrubbed_at = now()
    WHERE c.author_id = p_user_id AND c.body IS NOT NULL;
    GET DIAGNOSTICS v_comments = ROW_COUNT;

    UPDATE social.posts p
    SET status = CASE WHEN p.status IN ('pending_review', 'published', 'hidden') THEN 'deleted' ELSE p.status END,
        change_seq = CASE WHEN p.status IN ('published', 'hidden') THEN v_seq ELSE p.change_seq END,
        body = NULL, body_scrubbed_at = now()
    WHERE p.author_id = p_user_id AND p.body IS NOT NULL;
    GET DIAGNOSTICS v_posts = ROW_COUNT;

    UPDATE social.moderation_items i
    SET status = 'resolved', resolution = 'withdrawn', resolved_at = now(), claimed_by = NULL, lease_until = NULL
    WHERE i.status <> 'resolved' AND i.reason = 'pre_publication' AND (
           i.profile_user_id = p_user_id
        OR i.post_id IN (SELECT p.id FROM social.posts p WHERE p.author_id = p_user_id)
        OR i.comment_id IN (SELECT c.id FROM social.comments c WHERE c.author_id = p_user_id));

    UPDATE social.reports r SET note = NULL WHERE r.reporter_id = p_user_id;
    DELETE FROM social.adult_links l WHERE l.adult_user_id = p_user_id;

    -- Removing the profile cascades to: enrolment, settings, memberships, reactions,
    -- blocks, sanctions, notifications, rate counters, links as a learner.
    -- posts.author_id, comments.author_id and reports.reporter_id become NULL.
    DELETE FROM social.profiles p WHERE p.user_id = p_user_id;

    INSERT INTO social.moderation_actions (actor_id, actor_role, action, target_user_id)
    VALUES (v_actor, social.actor_staff_label(), 'erase_account', p_user_id);
    PERFORM social.write_audit('staff', 'account.erase', 'user', p_user_id, 'allowed',
        jsonb_build_object('posts', v_posts, 'comments', v_comments));
    RETURN jsonb_build_object('result', 'ok', 'posts_erased', v_posts, 'comments_erased', v_comments);
END $$;

-- ----------------------------------------------------------------------------
-- Retention job. Run daily by the worker role. Erases text that has outlived
-- its purpose and deletes expired rows. Anything under an active evidence hold
-- is skipped. Idempotent: running it twice changes nothing the second time.
-- ----------------------------------------------------------------------------
CREATE FUNCTION social.run_retention()
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_cfg social.config%ROWTYPE;
    v_posts integer;
    v_comments integer;
    v_reports integer;
    v_notifications integer;
    v_actions integer;
    v_audit integer;
BEGIN
    SELECT * INTO v_cfg FROM social.config;

    UPDATE social.posts p SET body = NULL, body_scrubbed_at = now()
    WHERE p.body IS NOT NULL
      AND (   (p.status = 'rejected' AND p.status_changed_at < now() - make_interval(days => v_cfg.retain_rejected_days))
           OR (p.status = 'removed' AND p.status_changed_at < now() - make_interval(days => v_cfg.retain_removed_days))
           OR (p.status = 'deleted' AND NOT EXISTS (
                   SELECT 1 FROM social.reports r WHERE r.post_id = p.id AND r.status = 'open')))
      AND NOT EXISTS (SELECT 1 FROM social.evidence_holds h WHERE h.post_id = p.id AND h.released_at IS NULL);
    GET DIAGNOSTICS v_posts = ROW_COUNT;

    UPDATE social.comments c SET body = NULL, body_scrubbed_at = now()
    WHERE c.body IS NOT NULL
      AND (   (c.status = 'rejected' AND c.status_changed_at < now() - make_interval(days => v_cfg.retain_rejected_days))
           OR (c.status = 'removed' AND c.status_changed_at < now() - make_interval(days => v_cfg.retain_removed_days))
           OR (c.status = 'deleted' AND NOT EXISTS (
                   SELECT 1 FROM social.reports r WHERE r.comment_id = c.id AND r.status = 'open')))
      AND NOT EXISTS (SELECT 1 FROM social.evidence_holds h WHERE h.comment_id = c.id AND h.released_at IS NULL);
    GET DIAGNOSTICS v_comments = ROW_COUNT;

    UPDATE social.reports r SET note = NULL, content_snapshot = NULL, scrubbed_at = now()
    WHERE r.scrubbed_at IS NULL AND r.resolved_at < now() - make_interval(days => v_cfg.retain_reports_days)
      AND NOT EXISTS (SELECT 1 FROM social.evidence_holds h WHERE h.report_id = r.id AND h.released_at IS NULL);
    GET DIAGNOSTICS v_reports = ROW_COUNT;

    DELETE FROM social.notification_events n WHERE n.expires_at < now();
    GET DIAGNOSTICS v_notifications = ROW_COUNT;
    DELETE FROM social.rate_counters rc WHERE rc.window_start < now() - interval '2 days';

    -- The append-only trigger allows these deletes only past the retention period.
    DELETE FROM social.moderation_actions a
    WHERE a.created_at < now() - make_interval(days => v_cfg.retain_actions_days)
      AND NOT EXISTS (SELECT 1 FROM social.sanctions s WHERE s.action_id = a.id);
    GET DIAGNOSTICS v_actions = ROW_COUNT;
    DELETE FROM social.audit_events e
    WHERE e.created_at < now() - make_interval(days => v_cfg.retain_actions_days);
    GET DIAGNOSTICS v_audit = ROW_COUNT;

    RETURN jsonb_build_object('posts_scrubbed', v_posts, 'comments_scrubbed', v_comments,
        'reports_scrubbed', v_reports, 'notifications_deleted', v_notifications,
        'actions_deleted', v_actions, 'audit_deleted', v_audit);
END $$;
