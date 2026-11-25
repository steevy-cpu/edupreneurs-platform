-- The background job queue: who may use it, leasing, retry with backoff,
-- dead-lettering, idempotent enqueue.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_worker TO postgres WITH INHERIT FALSE, SET TRUE;
CREATE FUNCTION pg_temp.as_role(p_role text, p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    EXECUTE format('SET LOCAL ROLE %I', p_role);
    BEGIN
        EXECUTE p_sql INTO v_out;
    EXCEPTION WHEN OTHERS THEN
        v_out := 'ERROR:' || SQLSTATE;
    END;
    EXECUTE 'RESET ROLE';
    RETURN v_out;
END;
$fn$;
CREATE FUNCTION pg_temp.w(p_sql text) RETURNS text LANGUAGE sql AS $$ SELECT pg_temp.as_role('edu_worker', p_sql) $$;

-- an empty queue inside this transaction (rolled back at the end)
DELETE FROM app.background_jobs;
CREATE TEMP TABLE base AS SELECT count(*) AS audit FROM app.audit_events;

-- ---- privileges --------------------------------------------------------------------
SELECT is(pg_temp.as_role('edu_api', $$SELECT ops.enqueue_job('noop')$$), 'ERROR:42501', 'edu_api cannot enqueue');
SELECT is(pg_temp.as_role('edu_api', $$SELECT count(*) FROM ops.claim_jobs('w-api', ARRAY['noop'], 1, 30)$$), 'ERROR:42501', 'edu_api cannot claim');
SELECT is(pg_temp.as_role('edu_api', $$SELECT ops.complete_job(gen_random_uuid(), 'w-api')$$), 'ERROR:42501', 'edu_api cannot complete');
SELECT is(pg_temp.as_role('edu_api', $$SELECT ops.fail_job(gen_random_uuid(), 'w-api', 'X')$$), 'ERROR:42501', 'edu_api cannot fail a job');
SELECT is(pg_temp.as_role('edu_api', 'SELECT count(*) FROM app.background_jobs'), 'ERROR:42501', 'edu_api cannot read the job table');
SELECT is(pg_temp.as_role('edu_staff', $$SELECT count(*) FROM ops.claim_jobs('w-staff', ARRAY['noop'], 1, 30)$$), 'ERROR:42501', 'edu_staff cannot claim (only enqueue)');
SELECT is(pg_temp.as_role('edu_staff', $$SELECT ops.complete_job(gen_random_uuid(), 'w-staff')$$), 'ERROR:42501', 'edu_staff cannot complete');
SELECT isnt(left(pg_temp.as_role('edu_staff', $$SELECT ops.enqueue_job('noop', '{}', 't105-staff')$$), 5), 'ERROR', 'edu_staff may enqueue');
SELECT is(pg_temp.w('SELECT count(*) FROM app.background_jobs'), 'ERROR:42501', 'edu_worker cannot read the job table directly');
SELECT is(pg_temp.w($$UPDATE app.background_jobs SET status = 'completed' RETURNING 1$$), 'ERROR:42501', 'edu_worker cannot write the job table directly');
SELECT is(pg_temp.w($$SELECT ops.job_backoff(1)$$), 'ERROR:42501', 'internal helpers are not callable');
DELETE FROM app.background_jobs;

-- ---- input checks --------------------------------------------------------------------
SELECT is(pg_temp.w($$SELECT ops.enqueue_job('Bad Kind')$$), 'ERROR:22023', 'kind is validated');
SELECT is(pg_temp.w($$SELECT ops.enqueue_job('noop', '[1]')$$), 'ERROR:22023', 'payload must be an object');
SELECT is(pg_temp.w(format($$SELECT ops.enqueue_job('noop', %L)$$, jsonb_build_object('x', repeat('y', 9000)))), 'ERROR:22023', 'payload is bounded');
SELECT is(pg_temp.w($$SELECT ops.enqueue_job('noop', '{}', 'key with spaces')$$), 'ERROR:22023', 'idempotency key is validated');
SELECT is(pg_temp.w($$SELECT ops.enqueue_job('noop', '{}', NULL, NULL, 21)$$), 'ERROR:22023', 'max_attempts is bounded');
SELECT is(pg_temp.w($$SELECT count(*) FROM ops.claim_jobs('x', ARRAY['noop'], 1, 30)$$), 'ERROR:22023', 'worker id is validated');
SELECT is(pg_temp.w($$SELECT count(*) FROM ops.claim_jobs('w-1', ARRAY[]::text[], 1, 30)$$), 'ERROR:22023', 'kinds are required');
SELECT is(pg_temp.w($$SELECT count(*) FROM ops.claim_jobs('w-1', ARRAY['noop'], 101, 30)$$), 'ERROR:22023', 'limit is bounded');
SELECT is(pg_temp.w($$SELECT count(*) FROM ops.claim_jobs('w-1', ARRAY['noop'], 1, 0)$$), 'ERROR:22023', 'lease is bounded');
SELECT is((SELECT count(*)::int FROM app.background_jobs), 0, 'refused calls enqueued nothing');

-- ---- idempotent enqueue ---------------------------------------------------------------
CREATE TEMP TABLE j (label text PRIMARY KEY, id uuid);
INSERT INTO j VALUES ('a', pg_temp.w($$SELECT ops.enqueue_job('noop', '{"n":1}', 't105-key-a', NULL, 3)$$)::uuid);
SELECT is(pg_temp.w($$SELECT ops.enqueue_job('noop', '{"n":2}', 't105-key-a')$$)::uuid, (SELECT id FROM j WHERE label = 'a'), 'the same key returns the first job');
SELECT is(pg_temp.w($$SELECT ops.enqueue_job('other_kind', '{}', 't105-key-a')$$)::uuid, (SELECT id FROM j WHERE label = 'a'), 'even for another kind');
SELECT is((SELECT row(count(*), min(payload::text), min(max_attempts))::text FROM app.background_jobs), row(1, '{"n": 1}', 3)::text, 'one row, unchanged by the repeats');
INSERT INTO j VALUES ('b', pg_temp.w($$SELECT ops.enqueue_job('noop')$$)::uuid);
INSERT INTO j VALUES ('c', pg_temp.w($$SELECT ops.enqueue_job('noop')$$)::uuid);
SELECT is((SELECT count(*)::int FROM app.background_jobs), 3, 'jobs without a key are always new');
INSERT INTO j VALUES ('later', pg_temp.w($$SELECT ops.enqueue_job('noop', '{}', NULL, now() + interval '1 hour')$$)::uuid);
INSERT INTO j VALUES ('other', pg_temp.w($$SELECT ops.enqueue_job('other_kind')$$)::uuid);
UPDATE app.background_jobs SET run_after = now() - interval '3 seconds' WHERE id = (SELECT id FROM j WHERE label = 'a');
UPDATE app.background_jobs SET run_after = now() - interval '2 seconds' WHERE id = (SELECT id FROM j WHERE label = 'b');
UPDATE app.background_jobs SET run_after = now() - interval '1 second' WHERE id = (SELECT id FROM j WHERE label = 'c');

-- ---- claim ---------------------------------------------------------------------------------
SELECT is(pg_temp.w($$SELECT string_agg(job_id::text || ':' || attempt, ',' ORDER BY job_id) FROM ops.claim_jobs('w-1', ARRAY['noop'], 2, 30)$$),
    (SELECT string_agg(id::text || ':1', ',' ORDER BY id) FROM j WHERE label IN ('a', 'b')), 'w-1 gets the two oldest due jobs, attempt 1');
SELECT is((SELECT row(status, leased_by, attempts, lease_until = now() + interval '30 seconds')::text FROM app.background_jobs WHERE id = (SELECT id FROM j WHERE label = 'a')),
    row('leased', 'w-1', 1, true)::text, 'the lease is recorded');
SELECT is(pg_temp.w($$SELECT string_agg(job_id::text, ',') FROM ops.claim_jobs('w-2', ARRAY['noop'], 10, 30)$$), (SELECT id::text FROM j WHERE label = 'c'),
    'w-2 gets only what is left: not the leased jobs, not the future job, not another kind');
SELECT is(pg_temp.w($$SELECT count(*) FROM ops.claim_jobs('w-3', ARRAY['noop'], 10, 30)$$), '0', 'nothing left to claim');

-- ---- only the lease holder acts ----------------------------------------------------------
SELECT is(pg_temp.w(format($$SELECT ops.complete_job(%L, 'w-2')$$, (SELECT id FROM j WHERE label = 'a'))), 'false', 'another worker cannot complete my job');
SELECT is(pg_temp.w(format($$SELECT ops.fail_job(%L, 'w-2', 'X')$$, (SELECT id FROM j WHERE label = 'a'))), NULL, 'another worker cannot fail my job');
SELECT is(pg_temp.w(format($$SELECT ops.heartbeat_job(%L, 'w-2', 30)$$, (SELECT id FROM j WHERE label = 'a'))), 'false', 'another worker cannot renew my lease');
SELECT is(pg_temp.w(format($$SELECT ops.heartbeat_job(%L, 'w-1', 600)$$, (SELECT id FROM j WHERE label = 'a'))), 'true', 'the holder renews the lease');
SELECT is((SELECT lease_until = now() + interval '600 seconds' FROM app.background_jobs WHERE id = (SELECT id FROM j WHERE label = 'a')), true, 'the lease is extended');
SELECT is(pg_temp.w(format($$SELECT ops.complete_job(%L, 'w-1')$$, (SELECT id FROM j WHERE label = 'a'))), 'true', 'the holder completes the job');
SELECT is((SELECT row(status, leased_by, lease_until)::text FROM app.background_jobs WHERE id = (SELECT id FROM j WHERE label = 'a')), row('completed', NULL::text, NULL::timestamptz)::text, 'completed, lease cleared');
SELECT is(pg_temp.w(format($$SELECT ops.complete_job(%L, 'w-1')$$, (SELECT id FROM j WHERE label = 'a'))), 'false', 'a job is completed once');
SELECT is(pg_temp.w($$SELECT ops.enqueue_job('noop', '{}', 't105-key-a')$$)::uuid, (SELECT id FROM j WHERE label = 'a'), 'a completed job still answers for its idempotency key (no second run)');

-- ---- an expired lease is taken over; the old holder is fenced off -----------------------
UPDATE app.background_jobs SET lease_until = now() - interval '1 second' WHERE id = (SELECT id FROM j WHERE label = 'b');
SELECT is(pg_temp.w($$SELECT string_agg(job_id::text || ':' || attempt, ',') FROM ops.claim_jobs('w-2', ARRAY['noop'], 10, 30)$$), (SELECT id::text || ':2' FROM j WHERE label = 'b'),
    'the job of a silent worker is leased again: attempt 2');
SELECT is(pg_temp.w(format($$SELECT ops.complete_job(%L, 'w-1')$$, (SELECT id FROM j WHERE label = 'b'))), 'false', 'the first worker, back from the dead, cannot complete it');
SELECT is(pg_temp.w(format($$SELECT ops.heartbeat_job(%L, 'w-1', 30)$$, (SELECT id FROM j WHERE label = 'b'))), 'false', 'nor renew it');
SELECT is(pg_temp.w(format($$SELECT ops.complete_job(%L, 'w-2')$$, (SELECT id FROM j WHERE label = 'b'))), 'true', 'the second worker completes it');
SELECT is((SELECT attempts FROM app.background_jobs WHERE id = (SELECT id FROM j WHERE label = 'b')), 2, 'exactly one retry');

-- ---- failure, backoff, dead letter -------------------------------------------------------
INSERT INTO j VALUES ('f', pg_temp.w($$SELECT ops.enqueue_job('noop', '{"lesson_id":"b0000000-0000-4000-8000-000000000005"}', NULL, now() - interval '1 minute', 3)$$)::uuid);
SELECT is(pg_temp.w($$SELECT count(*) FROM ops.claim_jobs('w-1', ARRAY['noop'], 1, 30)$$), '1', 'attempt 1');
SELECT is(pg_temp.w(format($$SELECT ops.fail_job(%L, 'w-1', 'TimeoutError')$$, (SELECT id FROM j WHERE label = 'f'))), 'queued', 'a failed attempt goes back to the queue');
SELECT is((SELECT row(status, error_class, attempts, run_after - now(), leased_by)::text FROM app.background_jobs WHERE id = (SELECT id FROM j WHERE label = 'f')),
    row('queued', 'TimeoutError', 1, interval '5 seconds', NULL::text)::text, 'retry after 5 s, error class stored');
SELECT is(pg_temp.w($$SELECT count(*) FROM ops.claim_jobs('w-1', ARRAY['noop'], 1, 30)$$), '0', 'not before the backoff has passed');
UPDATE app.background_jobs SET run_after = now() WHERE id = (SELECT id FROM j WHERE label = 'f');
SELECT is(pg_temp.w($$SELECT count(*) FROM ops.claim_jobs('w-1', ARRAY['noop'], 1, 30)$$), '1', 'attempt 2');
SELECT is(pg_temp.w(format($$SELECT ops.fail_job(%L, 'w-1', 'a sentence, not a class name: Élève A')$$, (SELECT id FROM j WHERE label = 'f'))), 'queued', 'a malformed error class does not lose the failure');
SELECT is((SELECT row(error_class, run_after - now())::text FROM app.background_jobs WHERE id = (SELECT id FROM j WHERE label = 'f')),
    row('UnnamedError', interval '10 seconds')::text, 'free text is never stored as an error class; the backoff doubles');
UPDATE app.background_jobs SET run_after = now() WHERE id = (SELECT id FROM j WHERE label = 'f');
SELECT is(pg_temp.w($$SELECT max(attempt) FROM ops.claim_jobs('w-1', ARRAY['noop'], 1, 30)$$), '3', 'attempt 3 = max_attempts');
SELECT is(pg_temp.w(format($$SELECT ops.fail_job(%L, 'w-1', 'ValueError')$$, (SELECT id FROM j WHERE label = 'f'))), 'dead', 'no attempts left: dead');
SELECT is((SELECT row(status, error_class, attempts, leased_by)::text FROM app.background_jobs WHERE id = (SELECT id FROM j WHERE label = 'f')), row('dead', 'ValueError', 3, NULL::text)::text, 'dead-lettered');
UPDATE app.background_jobs SET run_after = now() - interval '1 hour' WHERE id = (SELECT id FROM j WHERE label = 'f');
SELECT is(pg_temp.w($$SELECT count(*) FROM ops.claim_jobs('w-1', ARRAY['noop'], 10, 30)$$), '0', 'a dead job is never handed out again');

SELECT is((SELECT array_agg(ops.job_backoff(n) ORDER BY n) FROM unnest(ARRAY[1, 2, 3, 4, 8, 9, 20, 500]) AS n),
    ARRAY['5 s', '10 s', '20 s', '40 s', '640 s', '900 s', '900 s', '900 s']::interval[], 'backoff: 5 s doubling, capped at 15 minutes');

-- a lease that runs out on the LAST attempt: dead, not retried for ever
INSERT INTO j VALUES ('g', pg_temp.w($$SELECT ops.enqueue_job('noop', '{}', NULL, now() - interval '1 minute', 1)$$)::uuid);
SELECT is(pg_temp.w($$SELECT count(*) FROM ops.claim_jobs('w-1', ARRAY['noop'], 1, 30)$$), '1', 'the only attempt');
UPDATE app.background_jobs SET lease_until = now() - interval '1 second' WHERE id = (SELECT id FROM j WHERE label = 'g');
SELECT is(pg_temp.w($$SELECT count(*) FROM ops.claim_jobs('w-2', ARRAY['noop'], 10, 30)$$), '0', 'not handed out again');
SELECT is((SELECT row(status, error_class, attempts)::text FROM app.background_jobs WHERE id = (SELECT id FROM j WHERE label = 'g')), row('dead', 'LeaseExpired', 1)::text, 'dead with LeaseExpired');

-- ---- audit: one event per dead job, class only ------------------------------------------
SELECT is((SELECT array_agg(e.details ->> 'error_class' ORDER BY e.details ->> 'error_class') FROM app.audit_events e WHERE e.created_at = now() AND e.action = 'job.dead'),
    ARRAY['LeaseExpired', 'ValueError'], 'each dead job wrote one job.dead event');
SELECT is((SELECT (count(*) - (SELECT audit FROM base))::int FROM app.audit_events), 2, 'nothing else was audited (retries are not events)');
SELECT is((SELECT count(*)::int FROM app.audit_events e WHERE e.created_at = now() AND e.action = 'job.dead'
           AND (e.details::text LIKE '%lesson_id%' OR e.details ? 'payload' OR e.target_kind <> 'background_job' OR e.outcome <> 'error')), 0,
    'no payload in the audit event');

SELECT * FROM finish();
ROLLBACK;
