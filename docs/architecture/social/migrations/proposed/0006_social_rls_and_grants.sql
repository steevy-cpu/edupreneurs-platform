-- ============================================================================
-- PROPOSED — NOT APPLIED. Social-00 design artefact (see 0001 header).
-- ============================================================================
-- Edupreneurs 2.0 — social module: row-level security, grants, policies
--
-- Two layers, both needed:
--   GRANT   decides which TABLES and COLUMNS a role may touch at all;
--   POLICY  (row-level security, "RLS") decides which ROWS of those it sees.
--
-- Summary
--   edu_social         SELECT on a column subset of 12 tables, filtered by RLS;
--                      EXECUTE on the member functions. No INSERT/UPDATE/DELETE.
--   edu_social_mod     SELECT on what moderation needs, only while the verified
--                      actor holds an active social staff role; EXECUTE on the
--                      moderation functions. No INSERT/UPDATE/DELETE.
--   edu_social_worker  EXECUTE on social.run_retention() and nothing else.
--   edu_api, anon, authenticated, service_role, PUBLIC: nothing.

-- ----------------------------------------------------------------------------
-- Default deny
-- ----------------------------------------------------------------------------
DO $$
DECLARE t record;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'social' LOOP
        EXECUTE format('ALTER TABLE social.%I ENABLE ROW LEVEL SECURITY', t.tablename);
    END LOOP;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA social FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA social FROM PUBLIC, anon, authenticated, service_role;
-- PostgreSQL lets PUBLIC execute every new function by default, and that default
-- cannot be switched off per schema (see app change C10). So: revoke explicitly,
-- then grant one by one. A Social-01 test fails if any social function is
-- executable by PUBLIC, anon or authenticated.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA social FROM PUBLIC, anon, authenticated, service_role;

-- ============================================================================
-- edu_social — the student-facing role
-- ============================================================================
GRANT SELECT (submissions_open, guidelines_version) ON social.config TO edu_social;
-- Not granted: grade_band, pending_display_name, timestamps.
GRANT SELECT (user_id, account_kind, display_name, avatar_key) ON social.profiles TO edu_social;
GRANT SELECT (user_id, age_band, consent_status, status, guidelines_version, guidelines_accepted_at)
    ON social.enrollments TO edu_social;
GRANT SELECT ON social.safety_settings TO edu_social;
GRANT SELECT (id, user_id, community_id, kind, reason_code, starts_at, ends_at, lifted_at)
    ON social.sanctions TO edu_social;
GRANT SELECT (id, slug, kind, names, descriptions, grade_band, listing, join_mode, posting, status)
    ON social.communities TO edu_social;
GRANT SELECT (community_id, user_id, role, status, requested_at) ON social.memberships TO edu_social;
-- Not granted: body_sha256, screening_version, screening_flags, body_scrubbed_at.
GRANT SELECT (id, community_id, author_id, client_op_id, kind, locale, body, status, moderation_reason_code,
              comment_count, reaction_count, publish_seq, change_seq, submitted_at, published_at, status_changed_at)
    ON social.posts TO edu_social;
GRANT SELECT (id, post_id, community_id, parent_comment_id, author_id, client_op_id, locale, body, status,
              moderation_reason_code, reaction_count, publish_seq, change_seq, submitted_at, published_at,
              status_changed_at)
    ON social.comments TO edu_social;
GRANT SELECT (user_id, post_id, comment_id, kind) ON social.reactions TO edu_social;
GRANT SELECT ON social.blocks TO edu_social;
-- Not granted: note, content_snapshot, target_user_id, moderation_item_id.
GRANT SELECT (id, reporter_id, post_id, comment_id, profile_user_id, category, status, created_at)
    ON social.reports TO edu_social;
GRANT SELECT ON social.notification_events TO edu_social;
-- Deliberately NO grants on: staff_roles, adult_links, community_invites, moderation_items,
-- moderation_actions, escalations, evidence_holds, audit_events, rate_counters, visibility_clock.

CREATE POLICY config_read ON social.config FOR SELECT TO edu_social USING (true);

-- A profile is visible to its owner, and to people who share an active community
-- with them — unless one of the two blocked the other.
CREATE POLICY profiles_read ON social.profiles FOR SELECT TO edu_social
    USING (user_id = (SELECT social.current_actor_id())
           OR (social.shares_community_with(user_id) AND NOT social.blocked_with(user_id)));

CREATE POLICY enrollments_read_own ON social.enrollments FOR SELECT TO edu_social
    USING (user_id = (SELECT social.current_actor_id()));
CREATE POLICY settings_read_own ON social.safety_settings FOR SELECT TO edu_social
    USING (user_id = (SELECT social.current_actor_id()));
CREATE POLICY sanctions_read_own ON social.sanctions FOR SELECT TO edu_social
    USING (user_id = (SELECT social.current_actor_id()));
CREATE POLICY memberships_read_own ON social.memberships FOR SELECT TO edu_social
    USING (user_id = (SELECT social.current_actor_id()));

-- A community is visible if (a) I am an active member, or (b) I asked to join
-- it, or (c) it is listed and matches my grade band. Draft and archived
-- communities are visible to nobody on this role.
CREATE POLICY communities_read ON social.communities FOR SELECT TO edu_social
    USING (status IN ('open', 'frozen') AND (
        social.can_read_community(id)
        OR (social.actor_access(NULL) = 'ok' AND (
               EXISTS (SELECT 1 FROM social.memberships m
                       WHERE m.community_id = communities.id AND m.status = 'pending_approval')
            OR (listing = 'listed_to_eligible' AND EXISTS (
                   SELECT 1 FROM social.profiles p
                   WHERE p.user_id = (SELECT social.current_actor_id())
                     AND (p.account_kind <> 'learner' OR social.actor_grade_band() = communities.grade_band)))
        ))
    ));

-- Posts: my own in any state; other people's only when PUBLISHED, in a
-- community I can read, and with no block between us.
CREATE POLICY posts_read ON social.posts FOR SELECT TO edu_social
    USING (author_id = (SELECT social.current_actor_id())
           OR (status = 'published'
               AND social.can_read_community(community_id)
               AND (author_id IS NULL OR NOT social.blocked_with(author_id))));

-- Comments: the same, and additionally the post above them must be published
-- and visible to me (the sub-query is itself filtered by posts_read).
CREATE POLICY comments_read ON social.comments FOR SELECT TO edu_social
    USING (author_id = (SELECT social.current_actor_id())
           OR (status = 'published'
               AND social.can_read_community(community_id)
               AND (author_id IS NULL OR NOT social.blocked_with(author_id))
               AND EXISTS (SELECT 1 FROM social.posts p
                           WHERE p.id = comments.post_id AND p.status = 'published')));

-- Only MY reactions, MY blocks, MY reports, MY notifications are readable.
-- Nobody can list who reacted to a post or who blocked or reported them.
CREATE POLICY reactions_read_own ON social.reactions FOR SELECT TO edu_social
    USING (user_id = (SELECT social.current_actor_id()));
CREATE POLICY blocks_read_own ON social.blocks FOR SELECT TO edu_social
    USING (blocker_id = (SELECT social.current_actor_id()));
CREATE POLICY reports_read_own ON social.reports FOR SELECT TO edu_social
    USING (reporter_id = (SELECT social.current_actor_id()));
CREATE POLICY notifications_read_own ON social.notification_events FOR SELECT TO edu_social
    USING (recipient_id = (SELECT social.current_actor_id()));

GRANT EXECUTE ON FUNCTION
    social.current_actor_id(),
    social.actor_access(uuid),
    social.actor_grade_band(),
    social.can_read_community(uuid),
    social.blocked_with(uuid),
    social.shares_community_with(uuid),
    social.write_denial(uuid, text),
    social.submit_post(uuid, uuid, text, text, text, bytea, text, jsonb),
    social.submit_comment(uuid, uuid, uuid, text, text, bytea, text, jsonb),
    social.set_reaction(uuid, uuid, text),
    social.file_report(uuid, uuid, uuid, text, text),
    social.set_block(uuid, boolean),
    social.join_with_invite(bytea),
    social.decide_join_request(uuid, uuid, boolean),
    social.leave_community(uuid),
    social.delete_own_content(uuid, uuid),
    social.update_profile(text, text),
    social.accept_guidelines(text),
    social.update_own_settings(boolean, boolean, boolean, boolean),
    social.mark_notifications_read(bigint),
    social.visibility_changes(bigint, integer),
    social.my_private_profile(),
    social.community_members(uuid)
TO edu_social;

-- ============================================================================
-- edu_social_mod — moderation and administration endpoints
-- ============================================================================
-- Every policy below has the same condition: the VERIFIED ACTOR of this
-- transaction holds an active social staff role. The role alone is not enough.
GRANT SELECT ON social.config, social.profiles, social.safety_settings, social.communities,
    social.memberships, social.posts, social.comments, social.moderation_items,
    social.moderation_actions, social.sanctions, social.escalations, social.evidence_holds,
    social.staff_roles, social.adult_links
    TO edu_social_mod;
GRANT SELECT (user_id, age_band, consent_status, consent_method, status, created_at)
    ON social.enrollments TO edu_social_mod;
-- Moderators judge a report without knowing WHO filed it: reporter_id is not
-- granted. Revealing it is a separate, audited, safety-lead-only function
-- (social.mod_reveal_reporter, specified for Social-02).
GRANT SELECT (id, post_id, comment_id, profile_user_id, target_user_id, community_id, category, note,
              content_snapshot, status, moderation_item_id, created_at, resolved_at, scrubbed_at)
    ON social.reports TO edu_social_mod;
-- The code digest is not readable even by staff.
GRANT SELECT (id, community_id, max_uses, use_count, expires_at, revoked_at, created_by, created_at)
    ON social.community_invites TO edu_social_mod;
GRANT SELECT ON social.audit_events TO edu_social_mod;

CREATE POLICY mod_config ON social.config FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['moderator', 'safety_lead', 'social_admin']));
CREATE POLICY mod_profiles ON social.profiles FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['moderator', 'safety_lead', 'social_admin']));
CREATE POLICY mod_enrollments ON social.enrollments FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['moderator', 'safety_lead', 'social_admin']));
CREATE POLICY mod_settings ON social.safety_settings FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['moderator', 'safety_lead', 'social_admin']));
CREATE POLICY mod_communities ON social.communities FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['moderator', 'safety_lead', 'social_admin']));
CREATE POLICY mod_invites ON social.community_invites FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['safety_lead', 'social_admin']));
CREATE POLICY mod_memberships ON social.memberships FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['moderator', 'safety_lead', 'social_admin']));
CREATE POLICY mod_posts ON social.posts FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['moderator', 'safety_lead']));
CREATE POLICY mod_comments ON social.comments FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['moderator', 'safety_lead']));
CREATE POLICY mod_reports ON social.reports FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['moderator', 'safety_lead']));
CREATE POLICY mod_items ON social.moderation_items FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['moderator', 'safety_lead']));
CREATE POLICY mod_actions ON social.moderation_actions FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['moderator', 'safety_lead']));
CREATE POLICY mod_sanctions ON social.sanctions FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['moderator', 'safety_lead']));
-- Escalations, evidence holds, the audit trail and adult links: safety lead only.
CREATE POLICY mod_escalations ON social.escalations FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['safety_lead'])
           OR opened_by = (SELECT social.current_actor_id()));
CREATE POLICY mod_holds ON social.evidence_holds FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['safety_lead']));
CREATE POLICY mod_audit ON social.audit_events FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['safety_lead']));
CREATE POLICY mod_adult_links ON social.adult_links FOR SELECT TO edu_social_mod
    USING (social.actor_has_staff_role(ARRAY['safety_lead', 'social_admin']));
-- A staff member sees their own role rows; the safety lead and admin see all.
CREATE POLICY mod_staff_roles ON social.staff_roles FOR SELECT TO edu_social_mod
    USING (user_id = (SELECT social.current_actor_id())
           OR social.actor_has_staff_role(ARRAY['safety_lead', 'social_admin']));

GRANT EXECUTE ON FUNCTION
    social.current_actor_id(),
    social.actor_has_staff_role(text[]),
    social.mod_claim_next(integer),
    social.mod_decide(uuid, text, text, text),
    social.mod_escalate(uuid, text, text),
    social.mod_impose_sanction(uuid, text, uuid, text, integer, uuid, text),
    social.mod_lift_sanction(uuid, text),
    social.erase_user(uuid),
    social.decide_join_request(uuid, uuid, boolean),
    social.community_members(uuid)
TO edu_social_mod;

-- ============================================================================
-- edu_social_worker — the scheduled retention job
-- ============================================================================
GRANT EXECUTE ON FUNCTION social.run_retention() TO edu_social_worker;
