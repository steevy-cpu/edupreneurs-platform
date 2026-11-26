-- ============================================================================
-- FUTURE — NOT PART OF THE INITIAL SCHEMA. NOT APPLIED. NOT APPROVED.
-- ============================================================================
-- Direct and small-group messaging. Kept in a separate file because private
-- messages between minors (and between adults and minors) carry the highest
-- safety risk of any social feature. Do not adopt before:
--   * the questions in 10-risks-and-open-decisions.md (D-07, D-08) are answered;
--   * a legal review covers private communications of minors;
--   * the moderation team can review reported conversations within the SLA.
--
-- Design constraints already decided (06-moderation-workflow-and-threat-model.md):
--   * no "open" messaging: both people must share an active community, and the
--     conversation must be permitted by BOTH learners' safety settings;
--   * an adult (teacher/staff) can never start a one-to-one conversation with a
--     learner; teacher <-> class communication stays in the class community;
--   * text only; messages are reportable; a report shares the reported message
--     and its surrounding context with moderators;
--   * no end-to-end encryption claim: reported content must be reviewable;
--   * no always-on connection: delivery is by polling the conversation screen.

CREATE TABLE social.conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL CHECK (kind IN ('direct', 'group')),
    -- A group conversation always hangs off a community; its members must be members of that community.
    community_id uuid REFERENCES social.communities(id) ON DELETE RESTRICT,
    status text NOT NULL DEFAULT 'pending_acceptance'
        CHECK (status IN ('pending_acceptance', 'open', 'frozen', 'closed')),
    created_by uuid REFERENCES social.profiles(user_id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_message_seq bigint NOT NULL DEFAULT 0 CHECK (last_message_seq >= 0),
    CHECK (kind = 'direct' OR community_id IS NOT NULL)
);

CREATE TABLE social.conversation_participants (
    conversation_id uuid NOT NULL REFERENCES social.conversations(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL REFERENCES social.profiles(user_id) ON DELETE CASCADE,
    -- invited -> accepted | declined ; accepted -> left | removed
    status text NOT NULL DEFAULT 'invited' CHECK (status IN ('invited', 'accepted', 'declined', 'left', 'removed')),
    last_read_seq bigint NOT NULL DEFAULT 0 CHECK (last_read_seq >= 0),
    joined_at timestamptz,
    PRIMARY KEY (conversation_id, user_id)
);

CREATE TABLE social.messages (
    conversation_id uuid NOT NULL REFERENCES social.conversations(id) ON DELETE RESTRICT,
    -- Per-conversation counter allocated under the conversation's row lock
    -- (the same commit-ordering trick as social.visibility_clock).
    seq bigint NOT NULL CHECK (seq > 0),
    id uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    sender_id uuid REFERENCES social.profiles(user_id) ON DELETE SET NULL,
    client_op_id uuid NOT NULL,
    body text CHECK (body IS NULL OR char_length(body) BETWEEN 1 AND 1000),
    body_sha256 bytea NOT NULL CHECK (octet_length(body_sha256) = 32),
    status text NOT NULL DEFAULT 'delivered' CHECK (status IN ('held', 'delivered', 'removed', 'deleted')),
    screening_version text NOT NULL,
    screening_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (conversation_id, seq),
    UNIQUE (sender_id, client_op_id)
);

CREATE INDEX idx_participants_user ON social.conversation_participants (user_id) WHERE status = 'accepted';

-- OPEN QUESTION (D-08): messages cannot be human-approved one by one without
-- destroying the feature, so "held" would rely on the automated screen. That is
-- a weaker guarantee than the pre-moderation of posts, and the reason this file
-- is not part of the initial schema.
