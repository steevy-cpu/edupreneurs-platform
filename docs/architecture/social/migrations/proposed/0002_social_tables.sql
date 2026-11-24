-- ============================================================================
-- PROPOSED — NOT APPLIED. Social-00 design artefact (see 0001 header).
-- ============================================================================
-- Edupreneurs 2.0 — social module: 23 private tables (initial scope)
--
-- NOT in this file, on purpose: direct messages and media. Their draft tables
-- are in ../future/ and need their own safety review before adoption.
--
-- Conventions (same as the `app` schema):
--   * every table has a primary key and row-level security (enabled in 0006);
--   * no foreign key to auth.users cascades a delete;
--   * safety records keep plain uuid columns WITHOUT a foreign key where the
--     record must outlive the account it is about (same idea as app.audit_events).

-- ============================================================================
-- OPERATIONS: configuration and the visibility clock (2)
-- ============================================================================
-- One row. Limits live in data so the safety lead can tighten them without a deploy.
CREATE TABLE social.config (
    id boolean PRIMARY KEY DEFAULT true CHECK (id),
    -- Global kill switch. Defaults to CLOSED: nobody can submit until staff open it.
    submissions_open boolean NOT NULL DEFAULT false,
    guidelines_version text NOT NULL DEFAULT 'draft-1' CHECK (guidelines_version ~ '^[a-z0-9.-]{3,40}$'),
    max_posts_per_day smallint NOT NULL DEFAULT 5 CHECK (max_posts_per_day BETWEEN 1 AND 100),
    max_comments_per_day smallint NOT NULL DEFAULT 30 CHECK (max_comments_per_day BETWEEN 1 AND 500),
    max_reactions_per_day smallint NOT NULL DEFAULT 200 CHECK (max_reactions_per_day BETWEEN 1 AND 2000),
    max_reports_per_day smallint NOT NULL DEFAULT 20 CHECK (max_reports_per_day BETWEEN 1 AND 200),
    max_join_attempts_per_hour smallint NOT NULL DEFAULT 5 CHECK (max_join_attempts_per_hour BETWEEN 1 AND 50),
    max_pending_posts smallint NOT NULL DEFAULT 3 CHECK (max_pending_posts BETWEEN 1 AND 50),
    max_pending_comments smallint NOT NULL DEFAULT 10 CHECK (max_pending_comments BETWEEN 1 AND 100),
    max_memberships smallint NOT NULL DEFAULT 10 CHECK (max_memberships BETWEEN 1 AND 50),
    max_blocks smallint NOT NULL DEFAULT 200 CHECK (max_blocks BETWEEN 1 AND 1000),
    -- Distinct open reports that hide a published item until a moderator looks at it.
    auto_hide_report_threshold smallint NOT NULL DEFAULT 2 CHECK (auto_hide_report_threshold BETWEEN 1 AND 20),
    review_due_hours smallint NOT NULL DEFAULT 24 CHECK (review_due_hours BETWEEN 1 AND 168),
    severe_report_due_hours smallint NOT NULL DEFAULT 4 CHECK (severe_report_due_hours BETWEEN 1 AND 48),
    retain_rejected_days smallint NOT NULL DEFAULT 30 CHECK (retain_rejected_days BETWEEN 1 AND 365),
    retain_removed_days smallint NOT NULL DEFAULT 90 CHECK (retain_removed_days BETWEEN 1 AND 730),
    retain_reports_days smallint NOT NULL DEFAULT 365 CHECK (retain_reports_days BETWEEN 30 AND 1825),
    retain_actions_days smallint NOT NULL DEFAULT 730 CHECK (retain_actions_days BETWEEN 90 AND 3650),
    retain_notifications_days smallint NOT NULL DEFAULT 30 CHECK (retain_notifications_days BETWEEN 1 AND 180),
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO social.config DEFAULT VALUES;

-- One row. Every change of what members can SEE (publish, hide, remove, delete,
-- restore) takes the next number while holding this row's lock. Because the lock
-- is released only at commit, numbers become visible in order: a phone that asks
-- "what changed after 41?" can never miss number 42 because 43 committed first.
-- Same idea as app.account_sync_state, but one clock for the whole module.
CREATE TABLE social.visibility_clock (
    id boolean PRIMARY KEY DEFAULT true CHECK (id),
    current_seq bigint NOT NULL DEFAULT 0 CHECK (current_seq >= 0)
);
INSERT INTO social.visibility_clock DEFAULT VALUES;

-- ============================================================================
-- IDENTITY, ELIGIBILITY AND SAFETY SETTINGS (5)
-- ============================================================================
-- Who may moderate or administer. Separate from app.staff_roles: an editor of
-- lessons is not automatically trusted with children's conversations.
CREATE TABLE social.staff_roles (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    role text NOT NULL CHECK (role IN ('moderator', 'safety_lead', 'social_admin')),
    is_active boolean NOT NULL DEFAULT true,
    granted_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    granted_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    PRIMARY KEY (user_id, role),
    CHECK (granted_by IS NULL OR granted_by <> user_id)
);

-- The LIMITED PUBLIC PROFILE: the only personal data other members ever see.
-- No real name requirement, no photo upload, no bio, no school, no contact data.
-- display_name is user-written text, so it is moderated like a post:
-- a new name waits in pending_display_name until a moderator approves it.
CREATE TABLE social.profiles (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE RESTRICT,
    account_kind text NOT NULL CHECK (account_kind IN ('learner', 'teacher', 'staff')),
    -- Coarse band, set at enrolment by an authorised adult. NOT read from app.learner_profiles.
    grade_band text CHECK (grade_band IN ('7AF-9AF', 'NS1-NS4')),
    display_name text CHECK (display_name IS NULL OR char_length(display_name) BETWEEN 2 AND 40),
    pending_display_name text CHECK (pending_display_name IS NULL OR char_length(pending_display_name) BETWEEN 2 AND 40),
    -- One of the avatars shipped inside the app. Never an uploaded image.
    avatar_key text NOT NULL DEFAULT 'default' CHECK (avatar_key ~ '^[a-z0-9_-]{1,40}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((account_kind = 'learner') = (grade_band IS NOT NULL))
);

-- PRIVATE eligibility record. Never visible to other members.
-- We store an age BAND, not a date of birth (data minimisation).
CREATE TABLE social.enrollments (
    user_id uuid PRIMARY KEY REFERENCES social.profiles(user_id) ON DELETE CASCADE,
    age_band text NOT NULL DEFAULT 'unknown'
        CHECK (age_band IN ('unknown', 'under_13', '13_15', '16_17', '18_plus')),
    consent_status text NOT NULL DEFAULT 'pending'
        CHECK (consent_status IN ('pending', 'granted', 'withdrawn', 'not_required')),
    consent_method text
        CHECK (consent_method IS NULL OR consent_method IN ('school_agreement', 'guardian_paper', 'guardian_in_app')),
    consent_recorded_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    consent_recorded_at timestamptz,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'paused', 'closed')),
    guidelines_version text,
    guidelines_accepted_at timestamptz,
    enrolled_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    -- Nobody is active without a known age band and a consent decision.
    CHECK (status <> 'active' OR (age_band <> 'unknown' AND consent_status IN ('granted', 'not_required'))),
    -- Only adults can be "consent not required".
    CHECK (consent_status <> 'not_required' OR age_band = '18_plus'),
    CHECK (consent_status <> 'granted' OR (
        consent_method IS NOT NULL AND consent_recorded_by IS NOT NULL AND consent_recorded_at IS NOT NULL)),
    CHECK (enrolled_by <> user_id),
    CHECK (consent_recorded_by IS NULL OR consent_recorded_by <> user_id)
);

-- Which adult may manage which learner's social settings.
-- The adult has their own Auth account; we store no extra contact data here.
CREATE TABLE social.adult_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    adult_user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    learner_user_id uuid NOT NULL REFERENCES social.enrollments(user_id) ON DELETE CASCADE,
    relationship text NOT NULL CHECK (relationship IN ('parent_guardian', 'school_official')),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'revoked')),
    verified_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    verified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (adult_user_id, learner_user_id),
    CHECK (adult_user_id <> learner_user_id),
    CHECK (status <> 'verified' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)),
    -- An adult cannot verify their own link to a child.
    CHECK (verified_by IS NULL OR verified_by <> adult_user_id)
);

-- Per-learner switches. A linked adult or staff can lock them; the learner can
-- then only make them stricter, never looser.
CREATE TABLE social.safety_settings (
    user_id uuid PRIMARY KEY REFERENCES social.enrollments(user_id) ON DELETE CASCADE,
    can_post boolean NOT NULL DEFAULT true,
    can_comment boolean NOT NULL DEFAULT true,
    can_react boolean NOT NULL DEFAULT true,
    notifications_enabled boolean NOT NULL DEFAULT true,
    locked_by text NOT NULL DEFAULT 'none' CHECK (locked_by IN ('none', 'adult', 'staff')),
    updated_by uuid,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- COMMUNITIES (3)
-- ============================================================================
-- There are no public communities. A community is visible to its verified
-- members, and (if listed) by name to eligible learners of the same grade band.
CREATE TABLE social.communities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]{3,80}$'),
    kind text NOT NULL CHECK (kind IN ('class_group', 'subject_forum', 'announcements')),
    names jsonb NOT NULL CHECK (jsonb_typeof(names) = 'object' AND names ? 'fr'),
    descriptions jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(descriptions) = 'object'),
    -- Younger and older learners are never mixed in one community.
    grade_band text NOT NULL CHECK (grade_band IN ('7AF-9AF', 'NS1-NS4', 'staff_only')),
    listing text NOT NULL DEFAULT 'invite_only' CHECK (listing IN ('invite_only', 'listed_to_eligible')),
    join_mode text NOT NULL DEFAULT 'invite_then_approval'
        CHECK (join_mode IN ('staff_assigned', 'invite_then_approval')),
    -- Only one value is allowed today. Adding another mode (for example
    -- post-moderation for trusted groups) must be a deliberate, reviewed migration.
    moderation_mode text NOT NULL DEFAULT 'pre_moderated' CHECK (moderation_mode IN ('pre_moderated')),
    posting text NOT NULL DEFAULT 'members' CHECK (posting IN ('members', 'staff_only')),
    -- draft -> open <-> frozen -> archived.  frozen = read-only (per-community kill switch).
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'open', 'frozen', 'archived')),
    member_limit integer NOT NULL DEFAULT 60 CHECK (member_limit BETWEEN 2 AND 500),
    created_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Invite codes are stored only as a SHA-256 digest: a database leak does not
-- reveal usable codes. Codes always expire.
CREATE TABLE social.community_invites (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    community_id uuid NOT NULL REFERENCES social.communities(id) ON DELETE RESTRICT,
    code_sha256 bytea NOT NULL UNIQUE CHECK (octet_length(code_sha256) = 32),
    max_uses integer NOT NULL DEFAULT 60 CHECK (max_uses BETWEEN 1 AND 500),
    use_count integer NOT NULL DEFAULT 0 CHECK (use_count >= 0),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (use_count <= max_uses),
    CHECK (expires_at > created_at)
);

-- VERIFIED group membership: a row is 'active' only after a DIFFERENT, authorised
-- person (teacher of the group or staff) confirmed it.
CREATE TABLE social.memberships (
    community_id uuid NOT NULL REFERENCES social.communities(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL REFERENCES social.profiles(user_id) ON DELETE CASCADE,
    role text NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'teacher')),
    -- pending_approval -> active -> left | removed ;  pending_approval -> removed (declined)
    status text NOT NULL DEFAULT 'pending_approval'
        CHECK (status IN ('pending_approval', 'active', 'left', 'removed')),
    verification_method text
        CHECK (verification_method IS NULL OR verification_method IN ('staff_assignment', 'invite_code', 'school_roster')),
    invite_id uuid REFERENCES social.community_invites(id) ON DELETE SET NULL,
    verified_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    verified_at timestamptz,
    requested_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    PRIMARY KEY (community_id, user_id),
    CHECK (status <> 'active' OR (
        verified_by IS NOT NULL AND verified_at IS NOT NULL AND verification_method IS NOT NULL)),
    CHECK (verified_by IS NULL OR verified_by <> user_id)
);

-- ============================================================================
-- CONTENT (3) — text only
-- ============================================================================
-- Lifecycle (enforced by triggers in 0003, for EVERY writer):
--
--   pending_review ──approve──► published ◄──restore── hidden
--        │                        │  │                   ▲ │
--        │ reject                 │  └────auto-hide──────┘ │
--        ▼                        │ remove                 │ remove
--     rejected                    ▼                        ▼
--                              removed ◄───────────────────┘
--   any non-final state ──author deletes──► deleted
--
-- A row can only be INSERTED as pending_review, and can only become 'published'
-- if a moderation action by SOMEONE OTHER THAN THE AUTHOR approved exactly this
-- text (matched by digest). Nothing is ever visible to others before that.
--
-- There is no editing. A rejected post can be corrected and sent again as a NEW
-- post. That keeps "what was approved" and "what is shown" identical forever.
CREATE TABLE social.posts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    community_id uuid NOT NULL REFERENCES social.communities(id) ON DELETE RESTRICT,
    -- NULL after the author's account was erased.
    author_id uuid REFERENCES social.profiles(user_id) ON DELETE SET NULL,
    -- Generated by the phone when the learner taps "send". Makes retries safe.
    client_op_id uuid NOT NULL,
    kind text NOT NULL DEFAULT 'discussion' CHECK (kind IN ('discussion', 'question', 'announcement')),
    locale text NOT NULL CHECK (locale IN ('fr', 'ht')),
    -- Plain text. NULL once scrubbed (rejected / removed / deleted + retention).
    body text CHECK (body IS NULL OR char_length(body) BETWEEN 1 AND 2000),
    body_sha256 bytea NOT NULL CHECK (octet_length(body_sha256) = 32),
    status text NOT NULL DEFAULT 'pending_review'
        CHECK (status IN ('pending_review', 'published', 'hidden', 'rejected', 'removed', 'deleted')),
    -- Shown to the AUTHOR only, as a fixed code the app translates (never free text).
    moderation_reason_code text CHECK (moderation_reason_code IS NULL OR moderation_reason_code ~ '^[a-z_]{3,40}$'),
    -- Output of the local, rule-based screen run inside our own API. Staff-only columns.
    screening_version text NOT NULL CHECK (screening_version ~ '^[a-z0-9.-]{1,40}$'),
    screening_flags jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(screening_flags) = 'array'),
    comment_count integer NOT NULL DEFAULT 0 CHECK (comment_count >= 0),
    reaction_count integer NOT NULL DEFAULT 0 CHECK (reaction_count >= 0),
    publish_seq bigint UNIQUE CHECK (publish_seq IS NULL OR publish_seq > 0),
    change_seq bigint CHECK (change_seq IS NULL OR change_seq > 0),
    submitted_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    status_changed_at timestamptz NOT NULL DEFAULT now(),
    body_scrubbed_at timestamptz,
    UNIQUE (author_id, client_op_id),
    UNIQUE (id, community_id),
    CHECK (status NOT IN ('published', 'hidden') OR (
        publish_seq IS NOT NULL AND published_at IS NOT NULL AND body IS NOT NULL)),
    CHECK (status NOT IN ('pending_review', 'rejected') OR publish_seq IS NULL),
    CHECK (status <> 'pending_review' OR body IS NOT NULL)
);

-- Comments: one level of replies only (a reply to a reply is refused).
CREATE TABLE social.comments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id uuid NOT NULL,
    community_id uuid NOT NULL,
    parent_comment_id uuid,
    author_id uuid REFERENCES social.profiles(user_id) ON DELETE SET NULL,
    client_op_id uuid NOT NULL,
    locale text NOT NULL CHECK (locale IN ('fr', 'ht')),
    body text CHECK (body IS NULL OR char_length(body) BETWEEN 1 AND 1000),
    body_sha256 bytea NOT NULL CHECK (octet_length(body_sha256) = 32),
    status text NOT NULL DEFAULT 'pending_review'
        CHECK (status IN ('pending_review', 'published', 'hidden', 'rejected', 'removed', 'deleted')),
    moderation_reason_code text CHECK (moderation_reason_code IS NULL OR moderation_reason_code ~ '^[a-z_]{3,40}$'),
    screening_version text NOT NULL CHECK (screening_version ~ '^[a-z0-9.-]{1,40}$'),
    screening_flags jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(screening_flags) = 'array'),
    reaction_count integer NOT NULL DEFAULT 0 CHECK (reaction_count >= 0),
    publish_seq bigint UNIQUE CHECK (publish_seq IS NULL OR publish_seq > 0),
    change_seq bigint CHECK (change_seq IS NULL OR change_seq > 0),
    submitted_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    status_changed_at timestamptz NOT NULL DEFAULT now(),
    body_scrubbed_at timestamptz,
    UNIQUE (author_id, client_op_id),
    UNIQUE (id, post_id),
    -- A comment always belongs to the same community as its post...
    FOREIGN KEY (post_id, community_id) REFERENCES social.posts(id, community_id) ON DELETE RESTRICT,
    -- ...and a reply always belongs to the same post as its parent.
    FOREIGN KEY (parent_comment_id, post_id) REFERENCES social.comments(id, post_id) ON DELETE RESTRICT,
    CHECK (parent_comment_id IS NULL OR parent_comment_id <> id),
    CHECK (status NOT IN ('published', 'hidden') OR (
        publish_seq IS NOT NULL AND published_at IS NOT NULL AND body IS NOT NULL)),
    CHECK (status NOT IN ('pending_review', 'rejected') OR publish_seq IS NULL),
    CHECK (status <> 'pending_review' OR body IS NOT NULL)
);

-- A fixed set of POSITIVE reactions. No free text, no downvote, and nobody can
-- see WHO reacted (only a total): less social pressure, nothing to moderate.
CREATE TABLE social.reactions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES social.profiles(user_id) ON DELETE CASCADE,
    post_id uuid REFERENCES social.posts(id) ON DELETE CASCADE,
    comment_id uuid REFERENCES social.comments(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('helpful', 'thanks', 'encourage')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(post_id, comment_id) = 1),
    UNIQUE (user_id, post_id),
    UNIQUE (user_id, comment_id)
);

-- ============================================================================
-- SAFETY: blocks, reports, moderation, sanctions, escalation (7)
-- ============================================================================
CREATE TABLE social.blocks (
    blocker_id uuid NOT NULL REFERENCES social.profiles(user_id) ON DELETE CASCADE,
    blocked_id uuid NOT NULL REFERENCES social.profiles(user_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (blocker_id, blocked_id),
    CHECK (blocker_id <> blocked_id)
);

-- The moderation QUEUE: one row per thing a human must look at.
CREATE TABLE social.moderation_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_kind text NOT NULL CHECK (subject_kind IN ('post', 'comment', 'profile_name')),
    post_id uuid REFERENCES social.posts(id) ON DELETE RESTRICT,
    comment_id uuid REFERENCES social.comments(id) ON DELETE RESTRICT,
    profile_user_id uuid, -- no FK: the item must survive account erasure
    community_id uuid REFERENCES social.communities(id) ON DELETE RESTRICT,
    reason text NOT NULL CHECK (reason IN ('pre_publication', 'reported')),
    -- 0 = possible child-safety issue ... 3 = routine
    priority smallint NOT NULL DEFAULT 2 CHECK (priority BETWEEN 0 AND 3),
    -- open -> claimed -> resolved ;  claimed -> open (lease expired) ;  claimed -> escalated -> resolved
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'claimed', 'escalated', 'resolved')),
    claimed_by uuid,
    lease_until timestamptz,
    resolution text CHECK (resolution IS NULL OR resolution IN (
        'approved', 'rejected', 'dismissed', 'removed', 'withdrawn', 'stale')),
    opened_at timestamptz NOT NULL DEFAULT now(),
    due_at timestamptz NOT NULL,
    resolved_at timestamptz,
    CHECK (num_nonnulls(post_id, comment_id, profile_user_id) = 1),
    CHECK ((subject_kind = 'post') = (post_id IS NOT NULL)),
    CHECK ((subject_kind = 'comment') = (comment_id IS NOT NULL)),
    CHECK (status <> 'claimed' OR (claimed_by IS NOT NULL AND lease_until IS NOT NULL)),
    CHECK ((status = 'resolved') = (resolved_at IS NOT NULL AND resolution IS NOT NULL))
);

CREATE TABLE social.reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- NULL after the reporter's account was erased. Never shown to the reported user.
    reporter_id uuid REFERENCES social.profiles(user_id) ON DELETE SET NULL,
    post_id uuid REFERENCES social.posts(id) ON DELETE RESTRICT,
    comment_id uuid REFERENCES social.comments(id) ON DELETE RESTRICT,
    profile_user_id uuid, -- reported profile; no FK (see header)
    target_user_id uuid,  -- author of the reported content at report time; no FK
    community_id uuid REFERENCES social.communities(id) ON DELETE RESTRICT,
    category text NOT NULL CHECK (category IN (
        'bullying_harassment', 'sexual_content', 'child_safety', 'violence_threat', 'self_harm',
        'hate', 'personal_info', 'spam_scam', 'impersonation', 'other')),
    note text CHECK (note IS NULL OR char_length(note) BETWEEN 1 AND 500),
    -- Copy of the reported text at report time: evidence even if the author deletes it.
    content_snapshot text CHECK (content_snapshot IS NULL OR char_length(content_snapshot) <= 2000),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'actioned', 'dismissed')),
    moderation_item_id uuid REFERENCES social.moderation_items(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    scrubbed_at timestamptz,
    CHECK (num_nonnulls(post_id, comment_id, profile_user_id) = 1),
    UNIQUE (reporter_id, post_id),
    UNIQUE (reporter_id, comment_id),
    UNIQUE (reporter_id, profile_user_id)
);

-- APPEND-ONLY record of every moderation decision (trigger in 0003).
-- It holds a digest of the content, never the content itself.
CREATE TABLE social.moderation_actions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id uuid REFERENCES social.moderation_items(id) ON DELETE RESTRICT,
    actor_id uuid, -- no FK; NULL only for automatic actions
    actor_role text NOT NULL CHECK (actor_role IN ('moderator', 'safety_lead', 'social_admin', 'teacher', 'system')),
    action text NOT NULL CHECK (action IN (
        'approve', 'reject', 'dismiss', 'restore', 'remove', 'auto_hide',
        'approve_name', 'reject_name', 'remove_name',
        'warn', 'mute', 'suspend', 'ban', 'lift_sanction', 'escalate', 'erase_account')),
    post_id uuid,
    comment_id uuid,
    target_user_id uuid,
    community_id uuid,
    reason_code text CHECK (reason_code IS NULL OR reason_code ~ '^[a-z_]{3,40}$'),
    internal_note text CHECK (internal_note IS NULL OR char_length(internal_note) <= 1000),
    content_sha256 bytea CHECK (content_sha256 IS NULL OR octet_length(content_sha256) = 32),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (actor_role = 'system' OR actor_id IS NOT NULL)
);

-- warning    = recorded notice, no restriction
-- mute       = can read, cannot post / comment / react
-- suspension = no access to the social module, always time-limited
-- ban        = no access until lifted on appeal; safety lead only
CREATE TABLE social.sanctions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES social.profiles(user_id) ON DELETE CASCADE,
    community_id uuid REFERENCES social.communities(id) ON DELETE RESTRICT, -- NULL = everywhere
    kind text NOT NULL CHECK (kind IN ('warning', 'mute', 'suspension', 'ban')),
    reason_code text NOT NULL CHECK (reason_code ~ '^[a-z_]{3,40}$'),
    starts_at timestamptz NOT NULL DEFAULT now(),
    ends_at timestamptz,
    imposed_by uuid NOT NULL,
    action_id uuid REFERENCES social.moderation_actions(id) ON DELETE RESTRICT,
    lifted_at timestamptz,
    lifted_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (kind = 'ban' OR ends_at IS NOT NULL),
    CHECK (ends_at IS NULL OR ends_at >= starts_at),
    CHECK ((lifted_at IS NULL) = (lifted_by IS NULL)),
    CHECK (imposed_by <> user_id)
);

CREATE TABLE social.escalations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id uuid NOT NULL REFERENCES social.moderation_items(id) ON DELETE RESTRICT,
    level text NOT NULL CHECK (level IN ('safety_lead', 'guardian_or_school', 'external_authority')),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'closed')),
    summary text NOT NULL CHECK (char_length(summary) BETWEEN 1 AND 1000),
    opened_by uuid NOT NULL,
    opened_at timestamptz NOT NULL DEFAULT now(),
    due_at timestamptz NOT NULL,
    closed_by uuid,
    closed_at timestamptz,
    outcome_code text CHECK (outcome_code IS NULL OR outcome_code ~ '^[a-z_]{3,40}$'),
    external_reference text CHECK (external_reference IS NULL OR char_length(external_reference) <= 200),
    CHECK ((status = 'closed') = (closed_at IS NOT NULL AND closed_by IS NOT NULL AND outcome_code IS NOT NULL))
);

-- While a hold is active, retention and deletion do NOT scrub the held text.
CREATE TABLE social.evidence_holds (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id uuid REFERENCES social.posts(id) ON DELETE RESTRICT,
    comment_id uuid REFERENCES social.comments(id) ON DELETE RESTRICT,
    report_id uuid REFERENCES social.reports(id) ON DELETE RESTRICT,
    escalation_id uuid REFERENCES social.escalations(id) ON DELETE RESTRICT,
    reason_code text NOT NULL CHECK (reason_code ~ '^[a-z_]{3,40}$'),
    placed_by uuid NOT NULL,
    placed_at timestamptz NOT NULL DEFAULT now(),
    released_by uuid,
    released_at timestamptz,
    CHECK (num_nonnulls(post_id, comment_id, report_id) = 1),
    CHECK ((released_at IS NULL) = (released_by IS NULL))
);

-- ============================================================================
-- OPERATIONS: notifications, audit, rate counters (3)
-- ============================================================================
-- Pull-based notification EVENTS. A row carries ids only, never text: the app
-- fetches the content through the normal authorised endpoints, so a notification
-- can never show something that has since been removed or that the reader may no longer see.
CREATE TABLE social.notification_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipient_id uuid NOT NULL REFERENCES social.profiles(user_id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN (
        'post_approved', 'post_rejected', 'comment_approved', 'comment_rejected', 'content_removed',
        'comment_on_post', 'reply_to_comment', 'membership_approved', 'membership_declined',
        'name_approved', 'name_rejected', 'sanction_notice', 'announcement')),
    post_id uuid,
    comment_id uuid,
    community_id uuid,
    -- "3 new comments on your post" is ONE row with actor_count = 3.
    actor_count integer NOT NULL DEFAULT 1 CHECK (actor_count > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    read_at timestamptz,
    expires_at timestamptz NOT NULL
);

-- APPEND-ONLY (trigger in 0003). Mirrors app.audit_events; kept separate so the
-- social roles need nothing in the `app` schema.
CREATE TABLE social.audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid, -- deliberately no FK
    actor_kind text NOT NULL CHECK (actor_kind IN ('user', 'adult', 'teacher', 'staff', 'worker', 'system')),
    action text NOT NULL CHECK (char_length(action) BETWEEN 3 AND 100),
    target_kind text,
    target_id uuid,
    outcome text NOT NULL CHECK (outcome IN ('allowed', 'denied', 'error')),
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Fixed-window counters, e.g. ("post_day", today) -> 4. Stored in Postgres so
-- limits hold across API processes without adding Redis.
CREATE TABLE social.rate_counters (
    user_id uuid NOT NULL REFERENCES social.profiles(user_id) ON DELETE CASCADE,
    bucket text NOT NULL CHECK (bucket ~ '^[a-z_]{3,40}$'),
    window_start timestamptz NOT NULL,
    hits integer NOT NULL DEFAULT 0 CHECK (hits >= 0),
    PRIMARY KEY (user_id, bucket, window_start)
);

-- ============================================================================
-- INDEXES (in addition to PK / UNIQUE indexes)
-- ============================================================================
-- Feed: newest published posts of one community, keyset-paginated on publish_seq.
CREATE INDEX idx_posts_feed ON social.posts (community_id, publish_seq DESC) WHERE status = 'published';
-- "What changed since N" for the phone's cache.
CREATE INDEX idx_posts_changes ON social.posts (community_id, change_seq) WHERE change_seq IS NOT NULL;
-- "My submissions" and the pending-count / daily caps.
CREATE INDEX idx_posts_author ON social.posts (author_id, submitted_at DESC) WHERE author_id IS NOT NULL;
-- Retention sweep.
CREATE INDEX idx_posts_scrub ON social.posts (status, status_changed_at)
    WHERE body IS NOT NULL AND status IN ('rejected', 'removed', 'deleted');

CREATE INDEX idx_comments_thread ON social.comments (post_id, publish_seq) WHERE status = 'published';
CREATE INDEX idx_comments_changes ON social.comments (community_id, change_seq) WHERE change_seq IS NOT NULL;
CREATE INDEX idx_comments_author ON social.comments (author_id, submitted_at DESC) WHERE author_id IS NOT NULL;
CREATE INDEX idx_comments_parent ON social.comments (parent_comment_id) WHERE parent_comment_id IS NOT NULL;
CREATE INDEX idx_comments_scrub ON social.comments (status, status_changed_at)
    WHERE body IS NOT NULL AND status IN ('rejected', 'removed', 'deleted');

CREATE INDEX idx_memberships_user ON social.memberships (user_id) WHERE status = 'active';
CREATE INDEX idx_memberships_pending ON social.memberships (community_id, requested_at) WHERE status = 'pending_approval';
CREATE INDEX idx_invites_community ON social.community_invites (community_id);
CREATE INDEX idx_adult_links_learner ON social.adult_links (learner_user_id);
CREATE INDEX idx_reactions_post ON social.reactions (post_id) WHERE post_id IS NOT NULL;
CREATE INDEX idx_reactions_comment ON social.reactions (comment_id) WHERE comment_id IS NOT NULL;
CREATE INDEX idx_blocks_blocked ON social.blocks (blocked_id);

-- The moderator's "next item": most urgent first, oldest first.
CREATE INDEX idx_mod_items_queue ON social.moderation_items (priority, opened_at) WHERE status IN ('open', 'claimed');
-- At most one unresolved item per subject and reason.
CREATE UNIQUE INDEX uq_mod_items_open_post ON social.moderation_items (post_id, reason)
    WHERE status <> 'resolved' AND post_id IS NOT NULL;
CREATE UNIQUE INDEX uq_mod_items_open_comment ON social.moderation_items (comment_id, reason)
    WHERE status <> 'resolved' AND comment_id IS NOT NULL;
CREATE UNIQUE INDEX uq_mod_items_open_profile ON social.moderation_items (profile_user_id, reason)
    WHERE status <> 'resolved' AND profile_user_id IS NOT NULL;
CREATE INDEX idx_mod_items_community ON social.moderation_items (community_id);

CREATE INDEX idx_reports_item ON social.reports (moderation_item_id);
CREATE INDEX idx_reports_post ON social.reports (post_id) WHERE post_id IS NOT NULL;
CREATE INDEX idx_reports_comment ON social.reports (comment_id) WHERE comment_id IS NOT NULL;
CREATE INDEX idx_reports_target ON social.reports (target_user_id, created_at DESC);
CREATE INDEX idx_reports_scrub ON social.reports (resolved_at) WHERE scrubbed_at IS NULL AND resolved_at IS NOT NULL;
CREATE INDEX idx_reports_community ON social.reports (community_id);

CREATE INDEX idx_mod_actions_item ON social.moderation_actions (item_id);
CREATE INDEX idx_mod_actions_post ON social.moderation_actions (post_id) WHERE post_id IS NOT NULL;
CREATE INDEX idx_mod_actions_comment ON social.moderation_actions (comment_id) WHERE comment_id IS NOT NULL;
CREATE INDEX idx_mod_actions_target ON social.moderation_actions (target_user_id, created_at DESC);
CREATE INDEX idx_mod_actions_created ON social.moderation_actions (created_at);

CREATE INDEX idx_sanctions_active ON social.sanctions (user_id) WHERE lifted_at IS NULL;
CREATE INDEX idx_sanctions_community ON social.sanctions (community_id) WHERE community_id IS NOT NULL;
CREATE INDEX idx_sanctions_action ON social.sanctions (action_id);
CREATE INDEX idx_escalations_open ON social.escalations (due_at) WHERE status <> 'closed';
CREATE INDEX idx_escalations_item ON social.escalations (item_id);
CREATE INDEX idx_holds_post ON social.evidence_holds (post_id) WHERE released_at IS NULL AND post_id IS NOT NULL;
CREATE INDEX idx_holds_comment ON social.evidence_holds (comment_id) WHERE released_at IS NULL AND comment_id IS NOT NULL;
CREATE INDEX idx_holds_report ON social.evidence_holds (report_id) WHERE released_at IS NULL AND report_id IS NOT NULL;
CREATE INDEX idx_holds_escalation ON social.evidence_holds (escalation_id);

CREATE INDEX idx_notifications_inbox ON social.notification_events (recipient_id, id DESC);
CREATE INDEX idx_notifications_expiry ON social.notification_events (expires_at);
CREATE INDEX idx_social_audit_target ON social.audit_events (target_kind, target_id, created_at DESC);
CREATE INDEX idx_social_audit_created ON social.audit_events (created_at);
CREATE INDEX idx_rate_counters_window ON social.rate_counters (window_start);

-- Foreign keys to auth.users / staff columns (so a future account-deletion
-- procedure does not have to scan whole tables; same reasoning as app change C12).
CREATE INDEX idx_social_staff_granted_by ON social.staff_roles (granted_by) WHERE granted_by IS NOT NULL;
CREATE INDEX idx_enrollments_enrolled_by ON social.enrollments (enrolled_by);
CREATE INDEX idx_enrollments_consent_by ON social.enrollments (consent_recorded_by) WHERE consent_recorded_by IS NOT NULL;
CREATE INDEX idx_adult_links_verified_by ON social.adult_links (verified_by) WHERE verified_by IS NOT NULL;
CREATE INDEX idx_communities_created_by ON social.communities (created_by);
CREATE INDEX idx_invites_created_by ON social.community_invites (created_by);
CREATE INDEX idx_memberships_verified_by ON social.memberships (verified_by) WHERE verified_by IS NOT NULL;
CREATE INDEX idx_memberships_invite ON social.memberships (invite_id) WHERE invite_id IS NOT NULL;
