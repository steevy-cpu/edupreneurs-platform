-- YouTube-01: a learner sees a lesson video only when it is approved by a second person,
-- active, available, embeddable, not age-restricted, not blocked in Haiti and freshly
-- checked. Synthetic fixtures only; everything is rolled back.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
CREATE FUNCTION pg_temp.as_api(p_actor uuid, p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    PERFORM set_config('edu.actor_id', COALESCE(p_actor::text, ''), true);
    EXECUTE 'SET LOCAL ROLE edu_api';
    BEGIN
        EXECUTE p_sql INTO v_out;
    EXCEPTION WHEN OTHERS THEN
        v_out := 'ERROR:' || SQLSTATE;
    END;
    EXECUTE 'RESET ROLE';
    PERFORM set_config('edu.actor_id', '', true);
    RETURN v_out;
END;
$fn$;

-- seed: student A …0001, editor …0003 (editor role), reviewer …0004 (reviewer role), lesson …0005
CREATE FUNCTION pg_temp.video(p_n int, p_vid text) RETURNS uuid LANGUAGE sql AS $$
    INSERT INTO app.videos (id, provider_video_id, title, channel_id, channel_title, duration_seconds,
                            made_for_kids, age_restricted, embeddable, privacy_status, upload_status,
                            blocked_in_ht, metadata_fetched_at, metadata_expires_at, availability, created_by)
    VALUES (('a1000000-0000-4000-8000-0000000000' || lpad(p_n::text, 2, '0'))::uuid, p_vid,
            'Synthetic video ' || p_n, 'UC' || repeat('A', 22), 'Synthetic channel', 300,
            false, false, true, 'public', 'processed', false, now() - interval '1 day', now() + interval '6 days',
            'available', 'a0000000-0000-4000-8000-000000000003')
    RETURNING id
$$;
CREATE FUNCTION pg_temp.link(p_video uuid, p_pos int) RETURNS uuid LANGUAGE sql AS $$
    INSERT INTO app.lesson_video_links (lesson_id, video_id, locales, position, source, proposed_by)
    VALUES ('b0000000-0000-4000-8000-000000000005', p_video, ARRAY['fr','ht'], p_pos, 'teacher',
            'a0000000-0000-4000-8000-000000000003')
    RETURNING id
$$;
CREATE FUNCTION pg_temp.approve(p_link uuid) RETURNS void LANGUAGE sql AS $$
    UPDATE app.lesson_video_links SET review_status = 'approved',
        reviewed_by = 'a0000000-0000-4000-8000-000000000004', reviewed_at = now()
    WHERE id = p_link
$$;
CREATE FUNCTION pg_temp.visible() RETURNS text LANGUAGE sql AS $$
    SELECT pg_temp.as_api('a0000000-0000-4000-8000-000000000001',
        'SELECT coalesce(string_agg(v.provider_video_id, '','' ORDER BY k.position), '''')
         FROM app.lesson_video_links k JOIN app.videos v ON v.id = k.video_id')
$$;

-- ---- strict identifiers --------------------------------------------------------------
SELECT throws_ok($$SELECT pg_temp.video(90, 'short')$$, '23514', NULL, 'a video id shorter than 11 characters is refused');
SELECT throws_ok($$SELECT pg_temp.video(90, 'abcdefghijkl')$$, '23514', NULL, 'a video id longer than 11 characters is refused');
SELECT throws_ok($$SELECT pg_temp.video(90, '<script>a1b')$$, '23514', NULL, 'markup is not a video id');
SELECT throws_ok($$SELECT pg_temp.video(90, 'abc def ghi')$$, '23514', NULL, 'whitespace is not part of a video id');
SELECT throws_ok($$SELECT pg_temp.video(90, 'https://you')$$, '23514', NULL, 'a URL is not a video id');
SELECT throws_ok($$INSERT INTO app.videos (provider_video_id, title, channel_id, channel_title, duration_seconds, made_for_kids,
    age_restricted, embeddable, privacy_status, upload_status, blocked_in_ht, metadata_fetched_at, metadata_expires_at,
    availability, created_by) VALUES ('bbbbbbbbbb0', 't', 'not-a-channel', 'c', 60, false, false, true, 'public',
    'processed', false, now(), now() + interval '1 day', 'available', 'a0000000-0000-4000-8000-000000000003')$$,
    '23514', NULL, 'a malformed channel id is refused');
SELECT throws_ok($$INSERT INTO app.videos (provider_video_id, title, channel_id, channel_title, duration_seconds, made_for_kids,
    age_restricted, embeddable, privacy_status, upload_status, blocked_in_ht, metadata_fetched_at, metadata_expires_at,
    availability, created_by) VALUES ('bbbbbbbbbb1', 't', 'UC' || repeat('A',22), 'c', 60, false, false, true, 'public',
    'processed', false, now(), now() + interval '31 days', 'available', 'a0000000-0000-4000-8000-000000000003')$$,
    '23514', NULL, 'stored metadata cannot be declared valid for more than 30 days');
SELECT throws_ok($$INSERT INTO app.videos (provider_video_id, title, channel_id, channel_title, duration_seconds, made_for_kids,
    age_restricted, embeddable, privacy_status, upload_status, blocked_in_ht, metadata_fetched_at, metadata_expires_at,
    availability, created_by) VALUES ('bbbbbbbbbb2', repeat('x', 201), 'UC' || repeat('A',22), 'c', 60, false, false, true,
    'public', 'processed', false, now(), now() + interval '1 day', 'available', 'a0000000-0000-4000-8000-000000000003')$$,
    '23514', NULL, 'titles are bounded');

-- ---- approval rules --------------------------------------------------------------------
SELECT lives_ok($$SELECT pg_temp.link(pg_temp.video(1, 'okVideo0001'), 1)$$, 'a teacher proposes a video');
SELECT is(pg_temp.visible(), '', 'a proposed (unreviewed) video is invisible');
SELECT throws_ok($$UPDATE app.lesson_video_links SET review_status = 'approved', reviewed_by = proposed_by, reviewed_at = now()$$,
    '23514', NULL, 'the proposer cannot approve their own video');
SELECT throws_ok($$UPDATE app.lesson_video_links SET review_status = 'approved', reviewed_by = 'a0000000-0000-4000-8000-000000000002', reviewed_at = now()$$,
    '23514', NULL, 'a non-reviewer cannot approve');
SELECT lives_ok($$SELECT pg_temp.approve(id) FROM app.lesson_video_links$$, 'an active reviewer approves');
SELECT is(pg_temp.visible(), 'okVideo0001', 'the approved, presentable video is visible');
SELECT throws_ok($$SELECT pg_temp.link('a1000000-0000-4000-8000-000000000001', 2)$$, '23505', NULL, 'the same video cannot be attached twice to a lesson');
SELECT throws_ok($$UPDATE app.lesson_video_links SET start_seconds = 300$$, '23514', NULL, 'the start offset must be inside the video');

-- ---- every non-presentable state hides the video -------------------------------------------
CREATE FUNCTION pg_temp.hidden_when(p_set text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE v text;
BEGIN
    EXECUTE 'UPDATE app.videos SET ' || p_set || ' WHERE provider_video_id = ''okVideo0001''';
    v := pg_temp.visible();
    RETURN v;
END $$;
SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$status = 'disabled', status_reason = 'staff decision'$$), '', 'disabled by staff: hidden');
ROLLBACK TO SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$status = 'withdrawn', status_reason = 'rights'$$), '', 'withdrawn: hidden');
ROLLBACK TO SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$availability = 'removed'$$), '', 'deleted or private on YouTube: hidden');
ROLLBACK TO SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$privacy_status = 'private'$$), '', 'private: hidden');
ROLLBACK TO SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$upload_status = 'rejected'$$), '', 'rejected upload: hidden');
ROLLBACK TO SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$blocked_in_ht = true$$), '', 'blocked in Haiti: hidden');
ROLLBACK TO SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$metadata_fetched_at = now() - interval '31 days', metadata_expires_at = now() - interval '1 day'$$), '',
    'expired metadata: hidden until refreshed');
ROLLBACK TO SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$embeddable = false$$), '', 'no longer embeddable: hidden');
SELECT is((SELECT review_status FROM app.lesson_video_links), 'needs_review', '... and sent back to a teacher');
ROLLBACK TO SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$age_restricted = true$$), '', 'age-restricted: hidden and sent back to review');
ROLLBACK TO SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$channel_id = 'UC' || repeat('B', 22)$$), '', 'the video moved to another channel: hidden until re-reviewed');
ROLLBACK TO SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$made_for_kids = true$$), '', 'the Made-for-Kids designation changed: re-review');
ROLLBACK TO SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$title = 'A corrected title'$$), 'okVideo0001', 'a title change alone keeps the approval');
ROLLBACK TO SAVEPOINT s;
SELECT is(pg_temp.hidden_when($$metadata_fetched_at = now(), metadata_expires_at = now() + interval '30 days'$$), 'okVideo0001',
    'a refresh keeps the video visible');
ROLLBACK TO SAVEPOINT s;
UPDATE app.lessons SET is_active = false WHERE id = 'b0000000-0000-4000-8000-000000000005';
SELECT is(pg_temp.visible(), '', 'the video of an inactive lesson is hidden');
ROLLBACK TO SAVEPOINT s;

-- Made for Kids videos may be shown (the client adds no engagement features).
INSERT INTO app.videos (provider_video_id, title, channel_id, channel_title, duration_seconds, made_for_kids, age_restricted,
    embeddable, privacy_status, upload_status, blocked_in_ht, metadata_fetched_at, metadata_expires_at, availability, created_by)
VALUES ('kidsVideo01', 'MFK', 'UC' || repeat('C', 22), 'Kids channel', 120, true, false, true, 'public', 'processed', false,
    now(), now() + interval '7 days', 'available', 'a0000000-0000-4000-8000-000000000003');
SELECT pg_temp.approve(pg_temp.link((SELECT id FROM app.videos WHERE provider_video_id = 'kidsVideo01'), 2));
SELECT is(pg_temp.visible(), 'okVideo0001,kidsVideo01', 'a Made-for-Kids video can be approved and shown');

-- A video that is not presentable cannot be approved at all.
INSERT INTO app.videos (provider_video_id, title, channel_id, channel_title, duration_seconds, made_for_kids, age_restricted,
    embeddable, privacy_status, upload_status, blocked_in_ht, metadata_fetched_at, metadata_expires_at, availability, created_by)
VALUES ('noEmbed0001', 'x', 'UC' || repeat('D', 22), 'c', 120, false, false, false, 'public', 'processed', false,
    now(), now() + interval '7 days', 'available', 'a0000000-0000-4000-8000-000000000003');
SELECT throws_ok($$SELECT pg_temp.approve(pg_temp.link((SELECT id FROM app.videos WHERE provider_video_id = 'noEmbed0001'), 3))$$,
    '23514', NULL, 'a non-embeddable video cannot be approved');

-- ---- what the API role can read ---------------------------------------------------------------
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', 'SELECT reviewed_by::text FROM app.lesson_video_links LIMIT 1'),
    'ERROR:42501', 'reviewer identity is not readable');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', 'SELECT review_note FROM app.lesson_video_links LIMIT 1'),
    'ERROR:42501', 'review notes are not readable');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', 'SELECT status_reason FROM app.videos LIMIT 1'),
    'ERROR:42501', 'staff reasons are not readable');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001', 'SELECT * FROM app.videos LIMIT 1'),
    'ERROR:42501', 'SELECT * on videos is refused');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001',
    $$INSERT INTO app.videos (provider_video_id) VALUES ('zzzzzzzzzz1') RETURNING 1$$), 'ERROR:42501', 'a learner cannot add a video');
SELECT is(pg_temp.as_api('a0000000-0000-4000-8000-000000000001',
    $$UPDATE app.lesson_video_links SET position = 9 RETURNING 1$$), 'ERROR:42501', 'a learner cannot change a link');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM app.lesson_video_links'), '2',
    'video links are lesson content, not learner data: identical for every account');

SELECT * FROM finish();
ROLLBACK;
