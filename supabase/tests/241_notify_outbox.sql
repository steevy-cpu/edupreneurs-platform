-- The outbox: who can create a notification, dedupe, "ids only", isolation, erasure.
BEGIN;
SELECT * FROM no_plan();
-- Same helper as 020_rls_isolation.sql: run one statement AS THE STUDENT API ROLE
-- with the given actor. Returns the first column as text, or 'ERROR:<sqlstate>'.
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

-- Start from an empty outbox so counts are exact. Inside the test transaction;
-- rolled back at the end: nothing is really deleted.
TRUNCATE notify.delivery_attempts, notify.deliveries, notify.outbox, notify.preferences;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
\set EDITOR '''a0000000-0000-4000-8000-000000000003'''
-- An id with no learner profile (the seeded staff accounts may get one on first sign-in).
\set NOBODY '''a0000000-0000-4000-8000-0000000000ff'''
\set WORD '''{"word_id":"f0000000-0000-4000-8000-000000000001"}'''

-- ---- a client request cannot create, claim, report or erase ---------------------
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}','k1')$$), 'ERROR:42501', 'student API cannot enqueue for itself');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000002','sync_reminder','{}','k1')$$), 'ERROR:42501', 'student API cannot enqueue for another learner');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM notify.claim_due('push')$$), 'ERROR:42501', 'student API cannot claim deliveries');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM notify._claim_due_at('push', 1, 60, now())$$), 'ERROR:42501', 'student API cannot call the internal claim');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify.record_attempt(gen_random_uuid(),'push',gen_random_uuid(),'delivered')$$), 'ERROR:42501', 'student API cannot report a delivery');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify._record_attempt_at(gen_random_uuid(),'push',gen_random_uuid(),'delivered',NULL,now())$$), 'ERROR:42501', 'student API cannot call the internal report');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify.erase_learner('a0000000-0000-4000-8000-000000000002')$$), 'ERROR:42501', 'student API cannot erase a learner');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify._settle(gen_random_uuid())$$), 'ERROR:42501', 'student API cannot call _settle');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify.quiet_until(now(), 'a0000000-0000-4000-8000-000000000002')$$), 'ERROR:42501', 'student API cannot probe another learner''s quiet hours');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO notify.outbox (recipient_id, kind, dedupe_hash) VALUES ('a0000000-0000-4000-8000-000000000001','sync_reminder', sha256('x')) RETURNING 1$$), 'ERROR:42501', 'student API cannot insert an outbox row');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO notify.preferences (learner_id, push_enabled) VALUES ('a0000000-0000-4000-8000-000000000001', true) RETURNING 1$$), 'ERROR:42501', 'student API cannot insert preferences directly');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM notify.deliveries'), 'ERROR:42501', 'student API cannot read delivery state');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM notify.delivery_attempts'), 'ERROR:42501', 'student API cannot read the attempt log');
SELECT is(pg_temp.as_api(:A::uuid, $$UPDATE notify.policy SET quiet_start = '00:00' RETURNING 1$$), 'ERROR:42501', 'student API cannot change platform quiet hours');
SELECT is(pg_temp.as_api(:A::uuid, $$INSERT INTO notify.kinds (kind, category) VALUES ('marketing_blast','learning') RETURNING 1$$), 'ERROR:42501', 'student API cannot add a kind');

-- ---- enqueue (as the owner: the producer seam) and dedupe -------------------------
SELECT isnt(notify.enqueue(:A, 'daily_word_available', :WORD, 'word:2026-11-24'), NULL, 'server code enqueues for A');
SELECT is(notify.enqueue(:A, 'daily_word_available', :WORD, 'word:2026-11-24'),
          (SELECT id FROM notify.outbox WHERE recipient_id = :A AND kind = 'daily_word_available'),
          'the same event enqueued again returns the same id');
SELECT is((SELECT count(*)::int FROM notify.outbox WHERE recipient_id = :A), 1, '... and creates no second row');
SELECT isnt(notify.enqueue(:A, 'sync_reminder', '{}', 'word:2026-11-24'), NULL, 'same key, another kind: a different event');
SELECT isnt(notify.enqueue(:B, 'daily_word_available', :WORD, 'word:2026-11-24'), NULL, 'same key, another learner: a different event');
SELECT isnt(notify.enqueue(:A, 'daily_word_available', :WORD, 'word:2026-11-25'), NULL, 'another key: a different event');
SELECT is((SELECT count(*)::int FROM notify.outbox), 4, 'four distinct events exist');
SELECT is((SELECT count(*)::int FROM notify.outbox WHERE state <> 'settled'), 0, 'in-app only events need no worker: settled at once');
SELECT is((SELECT count(*)::int FROM notify.deliveries), 0, 'in-app only events create no delivery row');
SELECT isnt(notify.enqueue(:B, 'entitlement_expiring', '{"grant_id":"f0000000-0000-4000-8000-000000000009"}', 'grant-9', ARRAY['push','in_app','push']), NULL, 'an event may ask for push as well');
SELECT is((SELECT channels FROM notify.outbox WHERE kind = 'entitlement_expiring'), ARRAY['in_app','push'], 'channels are de-duplicated and ordered');
SELECT is((SELECT state || '/' || attempt_count FROM notify.deliveries), 'pending/0', 'the push delivery waits for a worker');
SELECT is((SELECT state FROM notify.outbox WHERE kind = 'entitlement_expiring'), 'pending', 'the event is pending while its push is');
SELECT is((SELECT count(*)::int FROM notify.outbox WHERE dedupe_hash = sha256(convert_to('word:2026-11-24', 'UTF8'))), 3,
    'the dedupe key is stored only as its SHA-256 digest');

-- ---- bounded inputs -------------------------------------------------------------
SELECT throws_ok($$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','marketing_blast','{}','k')$$, '22023', NULL, 'unknown kind refused');
UPDATE notify.kinds SET is_active = false WHERE kind = 'sync_reminder';
SELECT throws_ok($$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}','k-inactive')$$, '22023', NULL, 'inactive kind refused');
UPDATE notify.kinds SET is_active = true WHERE kind = 'sync_reminder';
SELECT throws_ok($$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}','')$$, '22023', NULL, 'empty dedupe key refused');
SELECT throws_ok($$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}',repeat('k',201))$$, '22023', NULL, 'over-long dedupe key refused');
SELECT throws_ok($$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}','k', ARRAY['sms'])$$, '22023', NULL, 'unknown channel refused');
SELECT throws_ok($$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}','k', ARRAY[]::text[])$$, '22023', NULL, 'no channel refused');
SELECT throws_ok($$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}','k', ARRAY['in_app'], now() + interval '91 days')$$, '22023', NULL, 'deliver_after beyond 90 days refused');
SELECT throws_ok($$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{}','k', ARRAY['in_app'], now(), now() - interval '1 second')$$, '22023', NULL, 'expiry before delivery refused');
SELECT throws_ok($$SELECT notify.enqueue(NULL,'sync_reminder','{}','k')$$, '22004', NULL, 'recipient is required');
SELECT throws_ok($$SELECT notify.enqueue('a0000000-0000-4000-8000-0000000000ff','sync_reminder','{}','k')$$, '23503', NULL, 'recipient must be a learner with a profile');

-- ---- no free text can be stored ----------------------------------------------------
SELECT throws_ok($$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{"word_id":"Bonjour, viens voir!"}','t1')$$, '22023', NULL, 'enqueue refuses text in a reference value');
SELECT throws_ok($$SELECT notify.enqueue('a0000000-0000-4000-8000-000000000001','sync_reminder','{"title":"f0000000-0000-4000-8000-000000000001"}','t2')$$, '22023', NULL, 'enqueue refuses a key that is not on the allow-list');
-- ... and the table itself refuses, even for the owner writing around the function:
SELECT throws_ok($$INSERT INTO notify.outbox (recipient_id, kind, refs, dedupe_hash) VALUES ('a0000000-0000-4000-8000-000000000001','sync_reminder','{"word_id":"Bonjour"}', sha256('c1'))$$, '23514', NULL, 'constraint: a reference value must be a UUID');
SELECT throws_ok($$INSERT INTO notify.outbox (recipient_id, kind, refs, dedupe_hash) VALUES ('a0000000-0000-4000-8000-000000000001','sync_reminder','{"body":"f0000000-0000-4000-8000-000000000001"}', sha256('c2'))$$, '23514', NULL, 'constraint: unknown reference key');
SELECT throws_ok($$INSERT INTO notify.outbox (recipient_id, kind, refs, dedupe_hash) VALUES ('a0000000-0000-4000-8000-000000000001','sync_reminder','{"word_id":{"text":"hello"}}', sha256('c3'))$$, '23514', NULL, 'constraint: nested object refused');
SELECT throws_ok($$INSERT INTO notify.outbox (recipient_id, kind, refs, dedupe_hash) VALUES ('a0000000-0000-4000-8000-000000000001','sync_reminder','["f0000000-0000-4000-8000-000000000001"]', sha256('c4'))$$, '23514', NULL, 'constraint: an array is not a refs object');
SELECT throws_ok($$INSERT INTO notify.outbox (recipient_id, kind, refs, dedupe_hash) VALUES ('a0000000-0000-4000-8000-000000000001','sync_reminder','"hello"', sha256('c5'))$$, '23514', NULL, 'constraint: a bare string is not a refs object');
SELECT throws_ok($$INSERT INTO notify.outbox (recipient_id, kind, refs, dedupe_hash) VALUES ('a0000000-0000-4000-8000-000000000001','sync_reminder','{"word_id":"F0000000-0000-4000-8000-00000000000A"}', sha256('c6'))$$, '23514', NULL, 'constraint: only canonical lower-case UUIDs');
SELECT throws_ok($$INSERT INTO notify.outbox (recipient_id, kind, refs, dedupe_hash) VALUES ('a0000000-0000-4000-8000-000000000001','sync_reminder','{"word_id":123}', sha256('c7'))$$, '23514', NULL, 'constraint: numbers refused');
SELECT throws_ok($$INSERT INTO notify.outbox (recipient_id, kind, refs, dedupe_hash) VALUES ('a0000000-0000-4000-8000-000000000001','sync_reminder',
    '{"word_id":"f0000000-0000-4000-8000-000000000001","lesson_id":"f0000000-0000-4000-8000-000000000001","unit_id":"f0000000-0000-4000-8000-000000000001","course_id":"f0000000-0000-4000-8000-000000000001","grant_id":"f0000000-0000-4000-8000-000000000001"}', sha256('c8'))$$, '23514', NULL, 'constraint: at most four references');
SELECT throws_ok($$INSERT INTO notify.outbox (recipient_id, kind, dedupe_hash) VALUES ('a0000000-0000-4000-8000-000000000001','Viens apprendre', sha256('c9'))$$, '23503', NULL, 'constraint: kind must be on the allow-list');
SELECT throws_ok($$INSERT INTO notify.outbox (recipient_id, kind, channels, dedupe_hash) VALUES ('a0000000-0000-4000-8000-000000000001','sync_reminder', ARRAY['Bonjour'], sha256('c10'))$$, '23514', NULL, 'constraint: channels is an allow-list');
SELECT throws_ok($$INSERT INTO notify.outbox (recipient_id, kind, dedupe_hash) VALUES ('a0000000-0000-4000-8000-000000000001','sync_reminder', convert_to('a readable dedupe key', 'UTF8'))$$, '23514', NULL, 'constraint: the dedupe column only takes a 32-byte digest');
SELECT throws_ok($$UPDATE notify.deliveries SET last_error_code = 'Bonjour'$$, '23514', NULL, 'constraint: error codes are an allow-list');
-- ---- preferences: only my own, only through the function ---------------------------
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify.set_preferences(true, ARRAY['learning','learning'], '22:00', '05:00')$$), '', 'A sets own preferences');
SELECT is((SELECT push_enabled::text || '|' || muted_categories::text || '|' || quiet_start::text || '|' || quiet_end::text
           FROM notify.preferences WHERE learner_id = :A), 'true|{learning}|22:00:00|05:00:00', '... stored for A, categories de-duplicated');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify.set_preferences(false, '{}', NULL, NULL)$$), '', 'A replaces own preferences');
SELECT is((SELECT count(*)::int FROM notify.preferences), 1, '... still one row (upsert)');
SELECT is((SELECT push_enabled::text || '|' || muted_categories::text || '|' || COALESCE(quiet_start::text, 'none')
           FROM notify.preferences WHERE learner_id = :A), 'false|{}|none', '... replaced');
SELECT is(pg_temp.as_api(:B::uuid, $$SELECT notify.set_preferences(true, ARRAY['reminders'], NULL, NULL)$$), '', 'B sets own preferences');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT string_agg(learner_id::text, $$,$$) FROM notify.preferences'), 'a0000000-0000-4000-8000-000000000001', 'A reads only own preferences');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM notify.preferences WHERE learner_id = 'a0000000-0000-4000-8000-000000000002'$$), '0', 'A cannot read B preferences by id');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM notify.preferences'), '0', 'no actor: no preferences');
SELECT is(pg_temp.as_api(NULL, $$SELECT notify.set_preferences(true, '{}', NULL, NULL)$$), 'ERROR:42501', 'no actor: cannot set preferences');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify.set_preferences(true, ARRAY['marketing'], NULL, NULL)$$), 'ERROR:22023', 'unknown category refused');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify.set_preferences(true, '{}', '21:00', '21:00')$$), 'ERROR:22023', 'an empty quiet window refused');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify.set_preferences(true, '{}', '21:00', NULL)$$), 'ERROR:22023', 'half a quiet window refused');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT notify.set_preferences(NULL, '{}', NULL, NULL)$$), 'ERROR:22004', 'push_enabled is required');
SELECT is(pg_temp.as_api(:NOBODY::uuid, $$SELECT notify.set_preferences(true, '{}', NULL, NULL)$$), 'ERROR:23503', 'an account without a learner profile cannot hold preferences');
SELECT is(pg_temp.as_api(:A::uuid, $$UPDATE notify.preferences SET push_enabled = true RETURNING 1$$), 'ERROR:42501', 'A cannot update preferences around the function');
SELECT is(pg_temp.as_api(:A::uuid, $$DELETE FROM notify.preferences RETURNING 1$$), 'ERROR:42501', 'A cannot delete preferences');
SELECT throws_ok($$UPDATE notify.preferences SET muted_categories = ARRAY['Bonjour']$$, '23514', NULL, 'constraint: muted categories are an allow-list');

-- ---- isolation of the in-app list ---------------------------------------------------
-- State now: A has 3 in-app events, B has 2 (one of them also push).
-- Add rows that must NOT be listed: not due yet, push-only, expired.
SELECT isnt(notify.enqueue(:A, 'sync_reminder', '{}', 'later', ARRAY['in_app'], now() + interval '1 hour'), NULL, 'an event for later');
SELECT isnt(notify.enqueue(:A, 'sync_reminder', '{}', 'push-only', ARRAY['push']), NULL, 'a push-only event');
INSERT INTO notify.outbox (recipient_id, kind, deliver_after, expires_at, dedupe_hash, state)
VALUES (:A, 'sync_reminder', now() - interval '2 hours', now() - interval '1 hour', sha256('expired'), 'settled');

SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE recipient_id <> app.current_actor_id()) FROM notify.outbox'), '3/0', 'A lists only own, due, unexpired in-app events');
SELECT is(pg_temp.as_api(:B::uuid, 'SELECT count(*) || $$/$$ || count(*) FILTER (WHERE recipient_id <> app.current_actor_id()) FROM notify.outbox'), '2/0', 'B lists only own events');
SELECT is(pg_temp.as_api(:A::uuid, $$SELECT count(*) FROM notify.outbox WHERE recipient_id = 'a0000000-0000-4000-8000-000000000002'$$), '0', 'A cannot read B events by id');
SELECT is(pg_temp.as_api(NULL, 'SELECT count(*) FROM notify.outbox'), '0', 'no actor: no events');
SELECT is(pg_temp.as_api(:EDITOR::uuid, 'SELECT count(*) FROM notify.outbox'), '0', 'a staff user sees no learner events through the student API');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM notify.outbox WHERE dedupe_hash IS NOT NULL'), 'ERROR:42501', 'A cannot read the dedupe digest column');
SELECT is(pg_temp.as_api(:A::uuid, $$UPDATE notify.outbox SET kind = 'sync_reminder' RETURNING 1$$), 'ERROR:42501', 'A cannot update events');
SELECT is(pg_temp.as_api(:A::uuid, 'DELETE FROM notify.outbox RETURNING 1'), 'ERROR:42501', 'A cannot delete events');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM notify.kinds'), '3', 'the kind allow-list is readable');
SELECT is(pg_temp.as_api(:A::uuid, 'SELECT count(*) FROM notify.policy'), '1', 'the platform policy is readable');

-- ---- erasure hook -----------------------------------------------------------------
SELECT is(notify.erase_learner(:A),
    '{"schema":"notify","outbox":6,"deliveries":1,"delivery_attempts":0,"preferences":1}'::jsonb,
    'erase_learner removes everything about A and reports counts');
SELECT is((SELECT count(*)::int FROM notify.outbox WHERE recipient_id = :A)
        + (SELECT count(*)::int FROM notify.preferences WHERE learner_id = :A), 0, 'nothing about A is left');
SELECT is((SELECT count(*)::int FROM notify.outbox WHERE recipient_id = :B) || '/' ||
          (SELECT count(*)::int FROM notify.preferences WHERE learner_id = :B) || '/' ||
          (SELECT count(*)::int FROM notify.deliveries), '2/1/1', 'B is untouched');
SELECT is(notify.erase_learner(:A) ->> 'outbox', '0', 'erasing again is a no-op');
SELECT throws_ok('SELECT notify.erase_learner(NULL)', '22004', NULL, 'erase_learner needs a user id');
-- With the notify rows gone, nothing in notify blocks the account orchestrator
-- from removing the profile (other schemas still may).
SELECT is((SELECT count(*)::int FROM pg_constraint c
           WHERE c.contype = 'f' AND c.connamespace = 'notify'::regnamespace
             AND c.confrelid = 'app.learner_profiles'::regclass), 2,
    'two notify foreign keys point at learner_profiles (outbox, preferences); both are cleared by the hook');

SELECT * FROM finish();
ROLLBACK;
