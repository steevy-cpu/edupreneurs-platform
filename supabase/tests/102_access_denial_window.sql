-- At most one persisted `staff.access` denial per actor per 60-second window.
BEGIN;
SELECT * FROM no_plan();

GRANT edu_api TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_staff TO postgres WITH INHERIT FALSE, SET TRUE;
GRANT edu_worker TO postgres WITH INHERIT FALSE, SET TRUE;
CREATE FUNCTION pg_temp.as_role(p_role text, p_actor uuid, p_sql text) RETURNS text
LANGUAGE plpgsql AS $fn$
DECLARE v_out text;
BEGIN
    PERFORM set_config('edu.actor_id', COALESCE(p_actor::text, ''), true);
    EXECUTE format('SET LOCAL ROLE %I', p_role);
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
CREATE FUNCTION pg_temp.denials(p_actor uuid) RETURNS integer LANGUAGE sql AS
$$ SELECT count(*)::int FROM app.audit_events
   WHERE actor_id = p_actor AND action = 'staff.access' AND outcome = 'denied' $$;

\set A '''a0000000-0000-4000-8000-000000000001'''
\set B '''a0000000-0000-4000-8000-000000000002'''
CREATE FUNCTION pg_temp.deny(p_role text, p_actor uuid) RETURNS text LANGUAGE sql AS
$$ SELECT pg_temp.as_role(p_role, p_actor,
       $q$SELECT ops.audit_access_denied('{"method":"GET","route":"/v1/staff/me"}')$q$) $$;

-- start from a known state inside this transaction (rolled back at the end)
DELETE FROM ops.access_denial_windows;
CREATE TEMP TABLE base AS SELECT pg_temp.denials(:A) AS a, pg_temp.denials(:B) AS b;

-- ---- structure and privileges ------------------------------------------------------
SELECT col_is_pk('ops', 'access_denial_windows', 'actor_id', 'one window row per actor');
SELECT is((SELECT relrowsecurity FROM pg_class WHERE oid = 'ops.access_denial_windows'::regclass), true,
    'row-level security is enabled on the window table');
SELECT is((SELECT count(*)::int FROM pg_policies WHERE schemaname = 'ops'), 0, 'no policy: nobody reads or writes it directly');
SELECT is((SELECT count(*)::int FROM information_schema.role_table_grants
           WHERE table_schema = 'ops' AND grantee NOT IN ('postgres')), 0,
    'no role other than the owner holds a privilege on ops tables');
SELECT is((SELECT count(*)::int FROM pg_constraint
           WHERE conrelid = 'ops.access_denial_windows'::regclass AND contype = 'f'), 0,
    'no foreign key: the row can never block account deletion');
SELECT is(pg_temp.as_role('edu_staff', :A::uuid, 'SELECT count(*) FROM ops.access_denial_windows'), 'ERROR:42501', 'edu_staff cannot read the window table');
SELECT is(pg_temp.as_role('edu_staff', :A::uuid, 'DELETE FROM ops.access_denial_windows RETURNING 1'), 'ERROR:42501', 'edu_staff cannot reset a window');
SELECT is(pg_temp.as_role('edu_staff', :A::uuid, $$UPDATE ops.access_denial_windows SET window_started_at = '-infinity' RETURNING 1$$), 'ERROR:42501', 'edu_staff cannot backdate a window');
SELECT is(pg_temp.deny('edu_api', :A::uuid), 'ERROR:42501', 'edu_api cannot record a refusal');
SELECT is(pg_temp.deny('edu_worker', :A::uuid), 'ERROR:42501', 'edu_worker cannot record a refusal');
SELECT is(pg_temp.as_role('edu_staff', :A::uuid, $$SELECT ops.erase_learner('a0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'edu_staff cannot call the erasure hook');
SELECT is(pg_temp.as_role('edu_api', :A::uuid, $$SELECT ops.erase_learner('a0000000-0000-4000-8000-000000000001')$$), 'ERROR:42501', 'edu_api cannot call the erasure hook');
SELECT is(pg_temp.deny('edu_staff', NULL), 'ERROR:42501', 'no actor: nothing to record');

-- ---- the bound ------------------------------------------------------------------------
SELECT isnt(pg_temp.deny('edu_staff', :A::uuid), NULL, 'the first refusal is written and returns the event id');
SELECT is(pg_temp.denials(:A) - (SELECT a FROM base), 1, 'one event after the first refusal');
SELECT is(pg_temp.deny('edu_staff', :A::uuid), NULL, 'a second refusal inside the window returns NULL');
SELECT is(pg_temp.deny('edu_staff', :A::uuid), NULL, 'a third one too');
SELECT is(pg_temp.as_role('edu_staff', :A::uuid, $$SELECT ops.audit_access_denied('{"note":"free text is not even validated when nothing is written"}')$$), NULL, 'a suppressed refusal stores none of its details');
SELECT is(pg_temp.denials(:A) - (SELECT a FROM base), 1, 'still exactly one event for A');
SELECT is((SELECT suppressed FROM ops.access_denial_windows WHERE actor_id = :A), 3, 'the three suppressed refusals are counted');

-- another account has its own window
SELECT isnt(pg_temp.deny('edu_staff', :B::uuid), NULL, 'B is not affected by the window of A');
SELECT is(pg_temp.denials(:B) - (SELECT b FROM base), 1, 'one event for B');
SELECT is((SELECT count(*)::int FROM ops.access_denial_windows), 2, 'one window row per refused account, however many refusals');

-- 100 more refusals: still one event, one row
SELECT is((SELECT count(*)::int FROM generate_series(1, 100) AS n
           WHERE pg_temp.deny('edu_staff', 'a0000000-0000-4000-8000-000000000001') IS NULL), 100,
    '100 further refusals are all suppressed');
SELECT is(pg_temp.denials(:A) - (SELECT a FROM base), 1, 'the audit log did not grow');

-- 59 seconds later: still inside; 61 seconds later: a new event that reports the suppressed count
UPDATE ops.access_denial_windows SET window_started_at = now() - interval '59 seconds' WHERE actor_id = :A;
SELECT is(pg_temp.deny('edu_staff', :A::uuid), NULL, 'after 59 s the window is still closed');
UPDATE ops.access_denial_windows SET window_started_at = now() - interval '61 seconds' WHERE actor_id = :A;
SELECT isnt(pg_temp.deny('edu_staff', :A::uuid), NULL, 'after 61 s the next refusal is written again');
SELECT is(pg_temp.denials(:A) - (SELECT a FROM base), 2, 'two events for A in total');
SELECT is((SELECT details FROM app.audit_events WHERE actor_id = :A AND action = 'staff.access'
           ORDER BY created_at DESC, (details ? 'suppressed_before') DESC LIMIT 1),
    '{"method":"GET","route":"/v1/staff/me","suppressed_before":104}'::jsonb,
    'the new event says how many refusals were not written in between');
SELECT is((SELECT suppressed FROM ops.access_denial_windows WHERE actor_id = :A), 0, 'the counter starts again');
UPDATE ops.access_denial_windows SET window_started_at = now() - interval '61 seconds' WHERE actor_id = :A;
SELECT isnt(pg_temp.deny('edu_staff', :A::uuid), NULL, 'a quiet window is followed by a plain event');
SELECT is((SELECT count(*)::int FROM app.audit_events WHERE actor_id = :A AND action = 'staff.access'
           AND details ? 'suppressed_before' AND created_at = now()), 1, 'suppressed_before appears only when something was suppressed');

-- a written event still obeys the audit detail rules
UPDATE ops.access_denial_windows SET window_started_at = now() - interval '61 seconds' WHERE actor_id = :A;
SELECT is(pg_temp.as_role('edu_staff', :A::uuid, $$SELECT ops.audit_access_denied('{"note":"free text"}')$$), 'ERROR:22023', 'details of a written refusal follow the audit rules');

-- ---- erasure hook -----------------------------------------------------------------------
SELECT is(ops.erase_learner(:A), '{"access_denial_windows": 1}'::jsonb, 'erase_learner removes the window row of that account');
SELECT is(ops.erase_learner(:A), '{"access_denial_windows": 0}'::jsonb, 'erase_learner is idempotent');
SELECT is((SELECT array_agg(actor_id) FROM ops.access_denial_windows), ARRAY[:B::uuid], 'other accounts are untouched');

SELECT * FROM finish();
ROLLBACK;
