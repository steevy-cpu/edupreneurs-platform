-- Delivery: quiet hours in America/Port-au-Prince (midnight, daylight saving),
-- opt-out, leases, retry with bounded backoff, terminal failure.
-- Every clock value is explicit (the internal _at functions) and every event is
-- enqueued with an explicit deliver_after, so the test does not depend on the
-- hour, the day or the year it runs in. All instants are in 2019-2020: PAST
-- dates, whose time-zone rules are history and cannot be changed by a later
-- tzdata release (Haiti: UTC-5, daylight saving 2019-03-10 to 2019-11-03).
BEGIN;
SELECT * FROM no_plan();

-- Start from an empty outbox so counts are exact. Inside the test transaction;
-- rolled back at the end: nothing is really deleted.
TRUNCATE notify.delivery_attempts, notify.deliveries, notify.outbox, notify.preferences;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''

-- =============================================================================
-- 1. The quiet-hours window (platform default 21:00-06:00 Haiti time)
-- =============================================================================
-- Winter: Haiti is UTC-5 (EST).
SELECT is(notify.window_end('2019-01-15 01:59:59+00', '21:00', '06:00'), NULL, '20:59:59 local: not quiet');
SELECT is(notify.window_end('2019-01-15 02:00:00+00', '21:00', '06:00'), '2019-01-15 11:00:00+00'::timestamptz, '21:00:00 local: quiet until 06:00 next morning');
SELECT is(notify.window_end('2019-01-15 04:59:00+00', '21:00', '06:00'), '2019-01-15 11:00:00+00'::timestamptz, '23:59 local (before Haiti midnight): same morning end');
SELECT is(notify.window_end('2019-01-15 05:01:00+00', '21:00', '06:00'), '2019-01-15 11:00:00+00'::timestamptz, '00:01 local (after Haiti midnight): same morning end');
SELECT is(notify.window_end('2019-01-15 10:59:59+00', '21:00', '06:00'), '2019-01-15 11:00:00+00'::timestamptz, '05:59:59 local: still quiet');
SELECT is(notify.window_end('2019-01-15 11:00:00+00', '21:00', '06:00'), NULL, '06:00:00 local: quiet hours are over');
SELECT is(notify.window_end('2019-01-15 00:30:00+00', '21:00', '06:00'), NULL, '00:30 UTC is 19:30 in Haiti, not midnight: the UTC date is never used');

-- Daylight saving started in Haiti on 2019-03-10 (02:00 -> 03:00): UTC-4 afterwards.
SELECT is(notify.window_end('2019-03-09 01:30:00+00', '21:00', '06:00'), NULL, 'before the change, 01:30 UTC is 20:30 local: not quiet');
SELECT is(notify.window_end('2019-03-11 01:30:00+00', '21:00', '06:00'), '2019-03-11 10:00:00+00'::timestamptz, 'after the change, 01:30 UTC is 21:30 local: quiet, until 06:00 = 10:00 UTC');
SELECT is(notify.window_end('2019-03-10 03:00:00+00', '21:00', '06:00'), '2019-03-10 10:00:00+00'::timestamptz, 'the night of the spring change is 8 hours long: 22:00 EST -> 06:00 EDT');
SELECT is(notify.window_end('2019-03-10 10:30:00+00', '21:00', '06:00'), NULL, '10:30 UTC on the first summer day is 06:30 local: not quiet (it was 05:30 the day before)');
SELECT is(notify.window_end('2019-03-09 10:30:00+00', '21:00', '06:00'), '2019-03-09 11:00:00+00'::timestamptz, '... the day before, 10:30 UTC was 05:30 local: quiet');

-- Daylight saving ended in Haiti on 2019-11-03 (02:00 -> 01:00): UTC-5 afterwards.
SELECT is(notify.window_end('2019-11-03 03:59:00+00', '21:00', '06:00'), '2019-11-03 11:00:00+00'::timestamptz, 'the night of the autumn change is 10 hours long: 23:59 EDT -> 06:00 EST');
SELECT is(notify.window_end('2019-11-03 05:30:00+00', '21:00', '06:00'), '2019-11-03 11:00:00+00'::timestamptz, 'first 01:30 (EDT) of the repeated hour: quiet');
SELECT is(notify.window_end('2019-11-03 06:30:00+00', '21:00', '06:00'), '2019-11-03 11:00:00+00'::timestamptz, 'second 01:30 (EST) of the repeated hour: quiet, same end');
SELECT is(notify.window_end('2019-11-03 10:30:00+00', '21:00', '06:00'), '2019-11-03 11:00:00+00'::timestamptz, '10:30 UTC is 05:30 local after the change: still quiet');
SELECT is(notify.window_end('2019-11-02 10:30:00+00', '21:00', '06:00'), NULL, '... the day before, 10:30 UTC was 06:30 local: not quiet');

-- Other window shapes.
SELECT is(notify.window_end('2019-01-15 18:30:00+00', '13:00', '14:00'), '2019-01-15 19:00:00+00'::timestamptz, 'a window that does not wrap midnight');
SELECT is(notify.window_end('2019-01-15 19:00:00+00', '13:00', '14:00'), NULL, '... ends exclusive');
SELECT is(notify.window_end('2019-01-15 18:30:00+00', '13:00', '13:00'), NULL, 'an empty window is never quiet');
SELECT is(notify.window_end('2019-01-15 18:30:00+00', NULL, NULL), NULL, 'no window is never quiet');

-- The learner's own window is IN ADDITION to the platform's.
INSERT INTO notify.preferences (learner_id, push_enabled, quiet_start, quiet_end) VALUES (:B, true, '05:00', '08:00');
SELECT is(notify.quiet_until('2019-01-15 17:00:00+00', :A), '2019-01-15 17:00:00+00'::timestamptz, 'noon, no preferences: allowed now');
SELECT is(notify.quiet_until('2019-01-15 03:00:00+00', :A), '2019-01-15 11:00:00+00'::timestamptz, 'night, no preferences: platform window applies');
SELECT is(notify.quiet_until('2019-01-15 03:00:00+00', :B), '2019-01-15 13:00:00+00'::timestamptz, 'night, own window 05:00-08:00 chained after the platform window: 08:00 local');
SELECT is(notify.quiet_until('2019-01-15 12:30:00+00', :B), '2019-01-15 13:00:00+00'::timestamptz, '07:30 local: outside the platform window but inside the learner''s');
SELECT is(notify.quiet_until('2019-01-15 13:00:00+00', :B), '2019-01-15 13:00:00+00'::timestamptz, '08:00 local: allowed');
UPDATE notify.preferences SET quiet_start = '06:00', quiet_end = '21:00' WHERE learner_id = :B;
SELECT ok(notify.quiet_until('2019-01-15 17:00:00+00', :B) > '2019-01-15 17:00:00+00'::timestamptz,
    'windows that together cover the whole day: always "later", and the function still returns');
DELETE FROM notify.preferences;

-- =============================================================================
-- 2. Claiming
-- =============================================================================
CREATE FUNCTION pg_temp.claim(p_now timestamptz, p_limit integer DEFAULT 20) RETURNS integer
LANGUAGE sql AS $fn$ SELECT count(*)::integer FROM notify._claim_due_at('push', p_limit, 60, p_now) $fn$;
CREATE FUNCTION pg_temp.d(p_outbox uuid) RETURNS text
LANGUAGE sql AS $fn$
    SELECT state || '/' || attempt_count || '/' || COALESCE(last_error_code, '-') || '/' ||
           COALESCE(to_char(next_attempt_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'), '-')
    FROM notify.deliveries WHERE outbox_id = p_outbox $fn$;
CREATE FUNCTION pg_temp.report(p_outbox uuid, p_outcome text, p_error text, p_now timestamptz) RETURNS text
LANGUAGE sql AS $fn$
    SELECT notify._record_attempt_at(p_outbox, 'push', (SELECT lease_token FROM notify.deliveries WHERE outbox_id = p_outbox), p_outcome, p_error, p_now) $fn$;

SELECT throws_ok($$SELECT * FROM notify._claim_due_at('email', 1, 60, now())$$, '22023', NULL, 'unknown channel refused');
SELECT throws_ok($$SELECT * FROM notify._claim_due_at('push', 0, 60, now())$$, '22023', NULL, 'limit must be positive');
SELECT throws_ok($$SELECT * FROM notify._claim_due_at('push', 101, 60, now())$$, '22023', NULL, 'limit is bounded');
SELECT throws_ok($$SELECT * FROM notify._claim_due_at('push', 1, 4, now())$$, '22023', NULL, 'lease is bounded below');
SELECT throws_ok($$SELECT * FROM notify._claim_due_at('push', 1, 901, now())$$, '22023', NULL, 'lease is bounded above');
SELECT is((SELECT count(*)::int FROM notify.claim_due('push')), 0, 'claim_due on an empty queue returns nothing');

-- ---- push is OFF until the learner turns it on ---------------------------------------
SELECT notify.enqueue(:A, 'sync_reminder', '{}', 'no-prefs', ARRAY['push','in_app'], '2019-01-01 00:00:00+00') AS e1 \gset
SELECT is(pg_temp.claim('2019-01-15 17:00:00+00'), 0, 'no preferences row: nothing is handed to the worker');
SELECT is(pg_temp.d(:'e1'), 'suppressed/0/push_not_enabled/-', '... the push is suppressed, no attempt spent');
SELECT is((SELECT state FROM notify.outbox WHERE id = :'e1'), 'settled', '... and the event is settled (still in the in-app list)');

INSERT INTO notify.preferences (learner_id, push_enabled) VALUES (:A, false);
SELECT notify.enqueue(:A, 'sync_reminder', '{}', 'push-off', ARRAY['push'], '2019-01-01 00:00:00+00') AS e2 \gset
SELECT is(pg_temp.claim('2019-01-15 17:00:00+00'), 0, 'push_enabled = false: nothing is handed to the worker');
SELECT is(pg_temp.d(:'e2'), 'suppressed/0/push_not_enabled/-', '... suppressed');
SELECT is(pg_temp.claim('2019-01-15 17:00:00+00'), 0, 'a suppressed delivery is never picked up again');

-- ---- quiet hours put a push off without spending an attempt ---------------------------
UPDATE notify.preferences SET push_enabled = true WHERE learner_id = :A;
SELECT notify.enqueue(:A, 'daily_word_available', '{"word_id":"f0000000-0000-4000-8000-000000000001"}', 'w1', ARRAY['push','in_app'], '2019-01-01 00:00:00+00') AS e3 \gset
SELECT is(pg_temp.claim('2019-01-15 03:00:00+00'), 0, '22:00 Haiti time: nothing is handed to the worker');
SELECT is(pg_temp.d(:'e3'), 'pending/0/-/2019-01-15 11:00:00', '... put off until 06:00 Haiti time, attempt count still 0');
SELECT is(pg_temp.claim('2019-01-15 10:59:59+00'), 0, '05:59:59: still nothing');
SELECT is((SELECT attempt_no || '|' || kind || '|' || refs::text || '|' || (recipient_id = :A)::text
           FROM notify._claim_due_at('push', 20, 60, '2019-01-15 11:00:00+00')),
    '1|daily_word_available|{"word_id": "f0000000-0000-4000-8000-000000000001"}|true',
    '06:00:00: claimed, attempt 1, carrying kind + ids only');
SELECT is(pg_temp.d(:'e3'), 'leased/1/-/2019-01-15 11:01:00', '... leased for 60 seconds');
SELECT is(pg_temp.claim('2019-01-15 11:00:30+00'), 0, 'a leased delivery is not handed out twice');

-- ---- retry with bounded exponential backoff, then terminal failure ---------------------
UPDATE notify.policy SET backoff_cap_seconds = 200;   -- base 60, cap 200, max 5 attempts
SELECT is(notify._record_attempt_at(:'e3', 'push', gen_random_uuid(), 'delivered', NULL, '2019-01-15 11:00:10+00'), 'stale', 'a report with the wrong lease token is refused');
SELECT is(pg_temp.d(:'e3'), 'leased/1/-/2019-01-15 11:01:00', '... and changes nothing');
SELECT throws_ok($$SELECT notify._record_attempt_at(gen_random_uuid(), 'push', gen_random_uuid(), 'exploded', NULL, now())$$, '22023', NULL, 'unknown outcome refused');
SELECT throws_ok($$SELECT notify._record_attempt_at(gen_random_uuid(), 'push', gen_random_uuid(), 'retry', 'Le serveur a dit non', now())$$, '22023', NULL, 'free-text error refused: codes only');
SELECT throws_ok($$SELECT notify._record_attempt_at(gen_random_uuid(), 'push', gen_random_uuid(), 'retry', NULL, now())$$, '22023', NULL, 'a retry needs an error code');

SELECT is(pg_temp.report(:'e3', 'retry', 'transient', '2019-01-15 11:00:10+00'), 'pending', 'attempt 1 fails: retry');
SELECT is(pg_temp.d(:'e3'), 'pending/1/transient/2019-01-15 11:01:10', '... after 60 s');
SELECT is(pg_temp.claim('2019-01-15 11:01:09+00'), 0, 'not before the backoff has passed');
SELECT is(pg_temp.claim('2019-01-15 11:01:10+00'), 1, 'attempt 2');
SELECT is(pg_temp.report(:'e3', 'retry', 'timeout', '2019-01-15 11:01:10+00'), 'pending', 'attempt 2 fails: retry');
SELECT is(pg_temp.d(:'e3'), 'pending/2/timeout/2019-01-15 11:03:10', '... after 120 s (doubled)');
SELECT is(pg_temp.claim('2019-01-15 11:03:10+00'), 1, 'attempt 3');
SELECT is(pg_temp.report(:'e3', 'retry', 'provider_unavailable', '2019-01-15 11:03:10+00'), 'pending', 'attempt 3 fails: retry');
SELECT is(pg_temp.d(:'e3'), 'pending/3/provider_unavailable/2019-01-15 11:06:30', '... after 200 s (240 capped to 200)');
SELECT is(pg_temp.claim('2019-01-15 11:06:30+00'), 1, 'attempt 4');
SELECT is(pg_temp.report(:'e3', 'retry', 'transient', '2019-01-15 11:06:30+00'), 'pending', 'attempt 4 fails: retry');
SELECT is(pg_temp.d(:'e3'), 'pending/4/transient/2019-01-15 11:09:50', '... after 200 s (capped)');
SELECT is((SELECT state FROM notify.outbox WHERE id = :'e3'), 'pending', 'the event stays pending while retries remain');
SELECT is(pg_temp.claim('2019-01-15 11:09:50+00'), 1, 'attempt 5 (the last allowed)');
SELECT is(pg_temp.report(:'e3', 'retry', 'transient', '2019-01-15 11:09:50+00'), 'failed', 'attempt 5 fails: terminal');
SELECT is(pg_temp.d(:'e3'), 'failed/5/max_attempts/-', '... failed for good, nothing scheduled');
SELECT is((SELECT state FROM notify.outbox WHERE id = :'e3'), 'settled', '... and the event is settled');
SELECT is(pg_temp.claim('2020-01-15 17:00:00+00'), 0, 'a failed delivery is never retried');
SELECT is((SELECT string_agg(attempt_no || ':' || outcome || ':' || error_code, ',' ORDER BY attempt_no)
           FROM notify.delivery_attempts WHERE outbox_id = :'e3'),
    '1:retry:transient,2:retry:timeout,3:retry:provider_unavailable,4:retry:transient,5:failed:transient',
    'the attempt log has one row per attempt');
SELECT is(notify._record_attempt_at(:'e3', 'push', gen_random_uuid(), 'delivered', NULL, '2019-01-15 11:10:00+00'), 'stale', 'nothing can be reported on a finished delivery');
UPDATE notify.policy SET backoff_cap_seconds = 3600;

-- ---- an immediate permanent failure ----------------------------------------------------
SELECT notify.enqueue(:A, 'sync_reminder', '{}', 'perm', ARRAY['push'], '2019-01-01 00:00:00+00') AS e4 \gset
SELECT is(pg_temp.claim('2019-01-16 17:00:00+00'), 1, 'claimed');
SELECT is(pg_temp.report(:'e4', 'failed', 'rejected', '2019-01-16 17:00:01+00'), 'failed', 'the adapter says "do not retry"');
SELECT is(pg_temp.d(:'e4'), 'failed/1/rejected/-', '... terminal after one attempt');

-- ---- success ---------------------------------------------------------------------------
SELECT notify.enqueue(:A, 'sync_reminder', '{}', 'good', ARRAY['push'], '2019-01-01 00:00:00+00') AS e5 \gset
SELECT is(pg_temp.claim('2019-01-17 17:00:00+00'), 1, 'claimed');
SELECT is(pg_temp.report(:'e5', 'delivered', NULL, '2019-01-17 17:00:01+00'), 'delivered', 'delivered');
SELECT is(pg_temp.d(:'e5'), 'delivered/1/-/-', '... terminal');
SELECT is((SELECT state FROM notify.outbox WHERE id = :'e5'), 'settled', '... event settled');

-- ---- a worker that dies: the lease runs out and the delivery is retried ----------------
SELECT notify.enqueue(:A, 'sync_reminder', '{}', 'lost', ARRAY['push'], '2019-01-01 00:00:00+00') AS e6 \gset
SELECT lease_token AS t6 FROM notify._claim_due_at('push', 20, 60, '2019-01-18 17:00:00+00') \gset
SELECT is(pg_temp.claim('2019-01-18 17:00:59+00'), 0, 'while the lease holds nobody else gets it');
SELECT is(pg_temp.claim('2019-01-18 17:01:00+00'), 1, 'when the lease runs out it is claimed again');
SELECT is(pg_temp.d(:'e6'), 'leased/2/-/2019-01-18 17:02:00', '... as attempt 2');
SELECT is((SELECT outcome || ':' || error_code FROM notify.delivery_attempts WHERE outbox_id = :'e6' AND attempt_no = 1), 'lease_lost:lease_expired', '... and the lost attempt is logged');
SELECT is(notify._record_attempt_at(:'e6', 'push', :'t6', 'delivered', NULL, '2019-01-18 17:01:05+00'), 'stale', 'the dead worker''s late report is refused (stale token)');
SELECT is(pg_temp.report(:'e6', 'delivered', NULL, '2019-01-18 17:01:06+00'), 'delivered', 'the second worker delivers: exactly one success is recorded');
SELECT is((SELECT count(*)::int FROM notify.delivery_attempts WHERE outbox_id = :'e6' AND outcome = 'delivered'), 1, '... one');
-- A lease lost on the last allowed attempt is terminal.
SELECT notify.enqueue(:A, 'sync_reminder', '{}', 'lost-last', ARRAY['push'], '2019-01-01 00:00:00+00') AS e7 \gset
UPDATE notify.policy SET max_attempts = 1;
SELECT is(pg_temp.claim('2019-01-19 17:00:00+00'), 1, 'claimed (the only attempt allowed)');
SELECT is(pg_temp.claim('2019-01-19 17:01:00+00'), 0, 'lease lost on the last attempt: not handed out again');
SELECT is(pg_temp.d(:'e7'), 'failed/1/lease_expired/-', '... terminal');
UPDATE notify.policy SET max_attempts = 5;

-- ---- opt-out by category, read at delivery time -----------------------------------------
SELECT notify.enqueue(:A, 'daily_word_available', '{}', 'muted-1', ARRAY['push'], '2019-01-01 00:00:00+00') AS e8 \gset
SELECT notify.enqueue(:A, 'entitlement_expiring', '{}', 'muted-2', ARRAY['push'], '2019-01-01 00:00:00+00') AS e9 \gset
UPDATE notify.preferences SET muted_categories = ARRAY['learning'] WHERE learner_id = :A;   -- AFTER enqueue
SELECT is(pg_temp.claim('2019-01-20 17:00:00+00'), 1, 'only the category that is not muted is handed out');
SELECT is(pg_temp.d(:'e8'), 'suppressed/0/category_muted/-', 'the muted category is suppressed');
SELECT is(split_part(pg_temp.d(:'e9'), '/', 1), 'leased', 'the other category is delivered');
SELECT is(pg_temp.report(:'e9', 'delivered', NULL, '2019-01-20 17:00:01+00'), 'delivered', 'done');
UPDATE notify.preferences SET muted_categories = '{}' WHERE learner_id = :A;

-- ---- the learner's own quiet hours ------------------------------------------------------
UPDATE notify.preferences SET quiet_start = '12:00', quiet_end = '14:00' WHERE learner_id = :A;
SELECT notify.enqueue(:A, 'sync_reminder', '{}', 'siesta', ARRAY['push'], '2019-01-01 00:00:00+00') AS e10 \gset
SELECT is(pg_temp.claim('2019-01-21 17:30:00+00'), 0, '12:30 Haiti time inside the learner''s own window: nothing');
SELECT is(pg_temp.d(:'e10'), 'pending/0/-/2019-01-21 19:00:00', '... put off until 14:00 Haiti time');
SELECT is(pg_temp.claim('2019-01-21 19:00:00+00'), 1, '14:00: claimed');
SELECT is(pg_temp.report(:'e10', 'delivered', NULL, '2019-01-21 19:00:01+00'), 'delivered', 'done');
UPDATE notify.preferences SET quiet_start = NULL, quiet_end = NULL WHERE learner_id = :A;

-- ---- expiry, retired kinds, limit -------------------------------------------------------
SELECT notify.enqueue(:A, 'sync_reminder', '{}', 'stale', ARRAY['push'], '2019-01-01 00:00:00+00', '2019-01-02 00:00:00+00') AS e11 \gset
SELECT is(pg_temp.claim('2019-01-22 17:00:00+00'), 0, 'an expired event is not pushed');
SELECT is(pg_temp.d(:'e11'), 'expired/0/-/-', '... marked expired');

SELECT notify.enqueue(:A, 'sync_reminder', '{}', 'retired', ARRAY['push'], '2019-01-01 00:00:00+00') AS e12 \gset
UPDATE notify.kinds SET is_active = false WHERE kind = 'sync_reminder';
SELECT is(pg_temp.claim('2019-01-23 17:00:00+00'), 0, 'a kind switched off after enqueue is not pushed');
SELECT is(pg_temp.d(:'e12'), 'suppressed/0/kind_inactive/-', '... suppressed');
UPDATE notify.kinds SET is_active = true WHERE kind = 'sync_reminder';

SELECT notify.enqueue(:A, 'sync_reminder', '{}', 'batch-' || n, ARRAY['push'], '2019-01-01 00:00:00+00') FROM generate_series(1, 3) n;
SELECT is(pg_temp.claim('2019-01-24 17:00:00+00', 2), 2, 'the limit bounds a claim');
SELECT is(pg_temp.claim('2019-01-24 17:00:00+00', 2), 1, '... the rest comes with the next claim');

-- ---- invariants over everything this test produced ---------------------------------------
SELECT is((SELECT count(*)::int FROM notify.deliveries WHERE attempt_count > (SELECT max_attempts FROM notify.policy)), 0,
    'no delivery was ever attempted more often than the policy allows');
SELECT is((SELECT count(*)::int FROM notify.outbox o WHERE (o.state = 'pending') <>
            EXISTS (SELECT 1 FROM notify.deliveries d WHERE d.outbox_id = o.id AND d.state IN ('pending','leased'))), 0,
    'an event is pending exactly while one of its deliveries is unfinished');
SELECT is((SELECT (notify.erase_learner(:A) ->> 'delivery_attempts')::int > 0), true, 'erase_learner also removes the attempt log');
SELECT is((SELECT count(*)::int FROM notify.delivery_attempts) + (SELECT count(*)::int FROM notify.deliveries), 0, '... nothing is left');

SELECT * FROM finish();
ROLLBACK;
