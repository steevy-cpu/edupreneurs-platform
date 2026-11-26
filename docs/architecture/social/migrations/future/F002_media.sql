-- ============================================================================
-- FUTURE — NOT PART OF THE INITIAL SCHEMA. NOT APPLIED. NOT APPROVED.
-- ============================================================================
-- Optional compressed images on posts. Kept separate because images change the
-- risk profile completely (faces of minors, location clues, illegal imagery)
-- and the cost profile (storage, bandwidth). Video is out of scope entirely.
-- Do not adopt before the decisions D-09 and D-10 in
-- 10-risks-and-open-decisions.md are made and the store/legal review is done.
--
-- Design constraints already decided:
--   * images only; one image per post at first; never in comments or profiles;
--   * the phone compresses BEFORE upload (longest side <= 1280 px, target
--     <= 150 KB, metadata such as GPS position stripped on the device AND again on the server);
--   * upload goes to private object storage through a short-lived signed URL;
--     nothing is ever served from a public bucket;
--   * an image is part of the post's review: the post cannot be approved until
--     its image is 'clean', and a human sees the image before approving;
--   * no image is sent to a third-party scanning or AI service until the privacy
--     and permission review (D-06) explicitly approves that vendor and purpose;
--   * the feed never auto-downloads images on mobile data: the app shows a
--     placeholder with the size, and the learner taps to load.

CREATE TABLE social.media_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid REFERENCES social.profiles(user_id) ON DELETE SET NULL,
    kind text NOT NULL CHECK (kind IN ('image')),
    -- uploading -> uploaded -> clean | rejected ;  any -> purged
    status text NOT NULL DEFAULT 'uploading'
        CHECK (status IN ('uploading', 'uploaded', 'clean', 'rejected', 'purged')),
    object_key text CHECK (object_key IS NULL OR char_length(object_key) <= 300),
    content_type text NOT NULL CHECK (content_type IN ('image/jpeg', 'image/webp')),
    byte_size integer NOT NULL CHECK (byte_size BETWEEN 1 AND 307200),
    width smallint NOT NULL CHECK (width BETWEEN 1 AND 1280),
    height smallint NOT NULL CHECK (height BETWEEN 1 AND 1280),
    sha256 bytea NOT NULL CHECK (octet_length(sha256) = 32),
    thumb_object_key text,
    created_at timestamptz NOT NULL DEFAULT now(),
    purged_at timestamptz
);

CREATE TABLE social.post_media (
    post_id uuid NOT NULL REFERENCES social.posts(id) ON DELETE RESTRICT,
    media_id uuid NOT NULL UNIQUE REFERENCES social.media_assets(id) ON DELETE RESTRICT,
    position smallint NOT NULL DEFAULT 1 CHECK (position = 1),
    alt_text text CHECK (alt_text IS NULL OR char_length(alt_text) <= 200),
    PRIMARY KEY (post_id, position)
);

CREATE INDEX idx_media_owner ON social.media_assets (owner_id, created_at DESC);
CREATE INDEX idx_media_cleanup ON social.media_assets (status, created_at) WHERE status IN ('uploading', 'rejected');
